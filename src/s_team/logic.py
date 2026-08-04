"""Team documents and their consent-based organizational hierarchy.

Every team remains an independently shared topic.  A subteam is an
Team holding a role in its parent: the parent carries an ordinary role
offered to a Team actor, and the child carries an
``team_role_holding`` naming which role in which parent.  Consequently,
accepting a parent never grants access to its children, and a hierarchy is
visible only once the seat has been taken on both sides.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from sovereign import ApplicationRegistration, ProtocolNode, Session, SessionResult


TEAM_APPLICATION_ID = "team"
TEAM_APP_NAME = "S-Team"
FLOW_APPLICATION_ID = "flow"
FLOW_FACADE_API_VERSION = 1
FLOW_DECISION_RESULT_CONTRACT_ID = "s-flow.decision-result"
FLOW_DECISION_RESULT_CONTRACT_VERSION = 1


class TeamLogic:
    GOVERNANCE_RECORD_TYPES = frozenset({
        "team_trustee_state",
        "team_member_opening",
        "team_member_application",
        "team_member_resolution",
        "team_trustee_election",
        "team_trustee_candidacy",
        "team_trustee_action",
        "team_trustee_reality",
        "team_external_member_resolution",
    })
    POOL_RECORD_TYPES = frozenset({
        "team_pool_invitation",
        "team_pool_application",
        "team_pool_resolution",
    })
    TRUSTS = frozenset({"identity", "trust"})
    TRUSTEE_CAUSES = frozenset({
        "genesis", "election", "resignation", "resolution",
    })
    ACTION_KINDS = frozenset({
        "member_opening", "member_resolution", "trustee_resignation",
        "election_implementation", "domain_action",
    })
    GOVERNANCE_FIELDS = {
        "team_trustee_state": (
            frozenset({
                "type", "trust", "holder_actor_uuid", "previous_state_uuid",
                "cause", "acted_by", "acted_at", "authority_basis_uuid",
                "signals", "consideration", "expectation",
            }),
            frozenset({"process_uuid", "process_result_hash"}),
        ),
        "team_member_opening": (
            frozenset({
                "type", "member_role_uuid", "previous_opening_uuid", "state",
                "opened_by", "opened_at", "authority_basis_uuid",
            }),
            frozenset({"closed_at"}),
        ),
        "team_member_application": (
            frozenset({
                "type", "opening_uuid", "previous_application_uuid",
                "actor_uuid", "submitted_at", "state",
            }),
            frozenset({"withdrawn_at"}),
        ),
        "team_member_resolution": (
            frozenset({
                "type", "opening_uuid", "application_uuid", "actor_uuid",
                "outcome", "resolved_by", "resolved_at",
                "authority_basis_uuid", "signals", "consideration", "expectation",
            }),
            frozenset(),
        ),
        "team_trustee_election": (
            frozenset({
                "type", "trust", "process_uuid", "process_definition_id",
                "process_definition_version", "electorate_actor_uuids",
                "triggered_by", "triggered_at", "target_state_uuid",
                "facilitator_trust", "facilitator_actor_uuid",
                "facilitator_authority_basis_uuid",
            }),
            frozenset(),
        ),
        "team_trustee_candidacy": (
            frozenset({
                "type", "trust", "actor_uuid", "vacant_state_uuid",
                "previous_candidacy_uuid", "submitted_at", "state",
            }),
            frozenset({"withdrawn_at"}),
        ),
        "team_trustee_action": (
            frozenset({
                "type", "trust", "action_kind", "subject_uuid", "acted_by",
                "acted_at", "authority_basis_uuid", "signals", "consideration",
                "expectation", "payload",
            }),
            frozenset(),
        ),
        "team_trustee_reality": (
            frozenset({
                "type", "action_uuid", "observed_by", "observed_at", "reality",
                "authority_basis_uuid",
            }),
            frozenset(),
        ),
        "team_external_member_resolution": (
            frozenset({
                "type", "pool_uuid", "pool_invitation_uuid",
                "pool_application_uuid", "opening_uuid", "actor_uuid",
                "outcome", "resolved_by", "resolved_at",
                "authority_basis_uuid", "application_evidence_hash",
                "signals", "consideration", "expectation",
            }),
            frozenset(),
        ),
    }
    POOL_FIELDS = {
        "team_pool_invitation": (
            frozenset({
                "type", "team_uuid", "team_title", "opening_uuid",
                "published_by", "published_at", "expires_at",
                "authority_basis_uuid",
            }),
            frozenset(),
        ),
        "team_pool_application": (
            frozenset({
                "type", "invitation_uuid", "team_uuid", "opening_uuid",
                "actor_uuid", "submitted_at", "state",
                "previous_application_uuid",
            }),
            frozenset({"withdrawn_at"}),
        ),
        "team_pool_resolution": (
            frozenset({
                "type", "invitation_uuid", "application_uuid",
                "team_uuid", "opening_uuid", "actor_uuid", "outcome",
                "resolved_by", "resolved_at", "authority_basis_uuid",
                "signals", "consideration", "expectation",
            }),
            frozenset({"team_invitation_token"}),
        ),
    }

    def __init__(self, session: Session, config: dict | None = None,
                 collaboration=None, facades=None):
        self.session = session
        self.config = config or {}
        self.collaboration = collaboration
        self.facades = facades
        # Reading Session.identity snapshots the whole protocol tree, and
        # building one payload asked for it hundreds of times - once per
        # role, per holder, per member list - which cost over a second per
        # build. Reads memoise inside a scope; nothing outside one does, so
        # a mutation can never see a stale entry.
        self._memo: dict | None = None
        self.session.identity
        with self.session.lock:
            self.session.application_metadata(TEAM_APPLICATION_ID)

    @contextmanager
    def _reading(self):
        """Memoise repeated lookups for the length of one read.

        Only reads open a scope, and a read performs no mutation, so nothing
        cached here can go stale while it is in use. Nested scopes share the
        outermost one, since a payload builds the organization inside itself.
        """
        outer = self._memo
        if outer is None:
            self._memo = {}
        try:
            yield
        finally:
            if outer is None:
                self._memo = None

    def _cached(self, key, build):
        if self._memo is None:
            return build()
        if key not in self._memo:
            self._memo[key] = build()
        return self._memo[key]

    @property
    def _identity_uuid(self) -> str:
        return self._cached(("identity",), lambda: self.session.identity.uuid)

    def application_registration(self) -> ApplicationRegistration:
        return ApplicationRegistration(
            TEAM_APPLICATION_ID,
            frozenset({"team", "team_pool"}),
            self.shared_topics,
            self.accept_team_topic_invitation,
            assignment_scoped=True,
            mount_invitation=True,
            on_peer_update=self.reconcile_governance_updates,
        )

    def shared_topics(self) -> list[ProtocolNode]:
        return [*self.teams(), *self.pools()]

    def teams(self) -> list[ProtocolNode]:
        container = self._find_team_container()
        if not container:
            return []
        found = [
            child for child in container.live_children()
            if child.data.get("type") == "team"
        ]
        return sorted(found, key=lambda node: (
            str(node.data.get("title", "")), node.created_at,
        ))

    def pools(self) -> list[ProtocolNode]:
        container = self._find_team_container()
        if not container:
            return []
        return sorted(
            [
                child for child in container.live_children()
                if child.data.get("type") == "team_pool"
            ],
            key=lambda node: (
                str(node.data.get("team_title") or ""), node.created_at,
            ),
        )

    def pool_for_team(self, team: ProtocolNode) -> ProtocolNode | None:
        matches = [
            pool for pool in self.pools()
            if pool.data.get("team_uuid") == team.uuid
        ]
        return matches[0] if len(matches) == 1 else None

    def _create_pool(self, team: ProtocolNode) -> SessionResult:
        return self.session.create_child(
            self._team_container().uuid,
            {
                "type": "team_pool",
                "team_uuid": team.uuid,
                "team_title": str(team.data.get("title") or "Untitled team"),
                "title": f"{team.data.get('title') or 'Untitled team'} Pool",
                "created_by": self._identity_uuid,
                "created_at": self._now(),
            },
            {},
        )

    # A name is the whole of how a role or a team is referred to: a
    # badge, an offer, a seat in a parent, a line in the organization tree.
    # Two of them called the same thing are two different things that read
    # as one. Refusing the write would throw away what somebody typed, so
    # the name is kept and numbered instead.
    _NUMBERED = re.compile(r"\s*\(\d+\)$")

    @classmethod
    def _distinct_name(cls, name: str, taken) -> str:
        existing = {
            str(entry or "").strip().casefold()
            for entry in taken
        }
        if name.casefold() not in existing:
            return name
        # A second "Lead (2)" becomes "Lead (3)", not "Lead (2) (2)".
        base = cls._NUMBERED.sub("", name) or name
        index = 2
        while f"{base} ({index})".casefold() in existing:
            index += 1
        return f"{base} ({index})"

    def _sibling_names(
        self, node: ProtocolNode, node_type: str, field: str,
    ) -> list[str]:
        """What the things beside this one are already called.

        A team is a topic root rather than a child of its neighbours,
        so its family is the team list rather than a parent's children.
        """
        if node_type == "team":
            family = self.teams()
        else:
            parent = self.session.protocol.index.get(node.parent_uuid)
            family = self._ordered(parent, node_type) if parent else []
        return [
            sibling.data.get(field) for sibling in family
            if sibling.uuid != node.uuid
        ]

    def _team_titles(self) -> list[str]:
        return [node.data.get("title") for node in self.teams()]

    def sections(self, team: ProtocolNode) -> list[ProtocolNode]:
        return self._ordered(team, "team_section")

    def clauses(self, section: ProtocolNode) -> list[ProtocolNode]:
        return self._ordered(section, "team_clause")

    # A subteam is not a link any more: it is a Team holding a
    # role in its parent, the same shape as a person holding one. The parent
    # side is an ordinary role with an offer to a Team actor; the child
    # side is a team_role_holding naming which role in which parent.
    #
    # The child keeps its own record rather than only the parent holding one,
    # because somebody who has joined the child but not the parent still has
    # to know a parent exists - that is what tells them the team is
    # read-only until they join it.

    def parent_holdings(self, team: ProtocolNode) -> list[ProtocolNode]:
        """This team's roles in other teams, in declared order."""
        return self._ordered(team, "team_role_holding")

    def is_organization(self, team: ProtocolNode) -> bool:
        """Whether this Team is a root body rather than a subteam.

        Organization is contextual vocabulary, not stored state or another
        Actor kind. An unmounted or no-longer-accepted parent claim is not a
        live holding, so it does not turn a root body into a subteam.
        """
        return not any(
            self._holding_is_live(team, holding)
            for holding in self.parent_holdings(team)
        )

    def child_teams(
        self, team: ProtocolNode,
    ) -> list[tuple[str, ProtocolNode]]:
        """(child team uuid, the role it was offered) for each subunit."""
        found = []
        for role in self.roles(team):
            for offer in self.role_offers(role):
                if offer.data.get("actor_kind") == "team":
                    child_uuid = str(offer.data.get("actor_uuid") or "").strip()
                    if child_uuid:
                        found.append((child_uuid, role))
        return found

    def _team_holds_role(
        self, role: ProtocolNode, actor_uuid: str,
    ) -> bool:
        """Whether a Team actor's holding of this role is live.

        Offer plus accepted answer, exactly as for a person. Deliberately not
        checking that the answer is against the current version: that would
        mean every edit to a parent freezes every subteam until somebody
        re-accepts on each one's behalf, on top of each person re-accepting
        their own roles. Left for step 3b to decide with the ANY-path guard.
        """
        if not self._offer_for(role, actor_uuid):
            return False
        answer = next(
            (
                child for child in role.live_children()
                if (
                    child.data.get("type") == "team_role_decision"
                    and child.data.get("actor_uuid") == actor_uuid
                )
            ),
            None,
        )
        return bool(
            answer
            and answer.data.get("decision") == "accepted"
            and not self._is_expired(answer.data.get("expires_at"))
        )

    def _holding_is_live(
        self, holder: ProtocolNode, holding: ProtocolNode,
    ) -> bool:
        """Whether `holder` really occupies the seat this holding names.

        The holder is passed rather than looked up, because this also runs
        against an invited subtree that is not in the local index yet - which
        is the whole point of checking it before mounting.
        """
        parent = self._node(
            str(holding.data.get("parent_team_uuid") or "").strip(),
            "team",
        )
        role = self._node(
            str(holding.data.get("role_uuid") or "").strip(), "team_role",
        )
        # The role has to be one of that parent's own: a holding naming
        # somebody else's role says nothing about this relationship.
        owner = self._local_team_topic(role.uuid) if role else None
        if not parent or not role or not owner or owner.uuid != parent.uuid:
            return False
        return self._team_holds_role(role, holder.uuid)

    @staticmethod
    def _ordered(parent: ProtocolNode, node_type: str) -> list[ProtocolNode]:
        return sorted(
            [
                child for child in parent.live_children()
                if child.data.get("type") == node_type
            ],
            key=lambda node: (float(node.data.get("order", 0)), node.created_at),
        )

    def create_team(self, title: str) -> SessionResult:
        normalized = str(title or "").strip()
        if not normalized:
            return SessionResult("error", reason="team title is required")
        normalized = self._distinct_name(normalized, self._team_titles())
        result = self.session.create_child(
            self._team_container().uuid,
            {"type": "team", "title": normalized},
            {},
        )
        if result.status == "ok":
            member = self._create_default_member(result.value)
            identity = self._create_trusteeship(result.value, "identity")
            trust = self._create_trusteeship(result.value, "trust")
            pool = self._create_pool(result.value)
            self._remember_team(result.value.uuid)
            return SessionResult(
                "ok",
                value=result.value.uuid,
                effects=[
                    *result.effects, *member.effects, *identity.effects,
                    *trust.effects, *pool.effects,
                ],
            )
        return result

    def create_subteam(
        self, parent_team_uuid: str, title: str,
    ) -> SessionResult:
        """Make a seat in the parent and fill it with a new team."""
        parent = self._node(parent_team_uuid, "team")
        if not parent:
            return SessionResult("error", reason="parent team not found")
        normalized = str(title or "").strip()
        if not normalized:
            return SessionResult("error", reason="team title is required")
        role = self.create_role(parent.uuid, normalized)
        if role.status != "ok":
            return role
        seated = self.create_seated_team(role.value, normalized)
        if seated.status != "ok":
            self.session.delete(role.value)
            return seated
        seated.effects = [*role.effects, *seated.effects]
        return seated

    def create_seated_team(
        self, role_uuid: str, title: str,
    ) -> SessionResult:
        """Fill a role with a new team.

        This is how structure is made: a seat exists, and a team is
        created to take it. The creator holds the new team's Identity,
        which is what lets them answer for it straight away.
        """
        role = self._node(role_uuid, "team_role")
        parent = self._local_team_topic(role.uuid) if role else None
        if not role or not parent:
            return SessionResult("error", reason="role not found")
        prerequisites = self._check_parent_chain(parent)
        if prerequisites.status != "ok":
            return prerequisites
        if not self.holds_identity(parent):
            return SessionResult(
                "error", reason="only the Identity holder can offer a role",
            )
        normalized = str(title or "").strip()
        if not normalized:
            return SessionResult("error", reason="team title is required")
        normalized = self._distinct_name(normalized, self._team_titles())

        created = self.session.create_child(
            self._team_container().uuid,
            {"type": "team", "title": normalized},
            {},
        )
        if created.status != "ok":
            return created
        child = created.value
        member = self._create_default_member(child)
        identity = self._create_trusteeship(child, "identity")
        trust = self._create_trusteeship(child, "trust")
        pool = self._create_pool(child)
        offered = self.offer_role(role.uuid, child.uuid)
        if offered.status != "ok":
            self.session.delete(child.uuid)
            return offered
        seated = self.seat_team(role.uuid, child.uuid)
        if seated.status != "ok":
            self.session.delete(child.uuid)
            return seated
        self._remember_team(child.uuid)
        return SessionResult(
            "ok",
            value=child.uuid,
            effects=[
                *created.effects, *identity.effects, *member.effects,
                *trust.effects, *pool.effects,
                *offered.effects, *seated.effects,
            ],
        )

    # What a copy carries. Everything a team holds beyond this is
    # somebody's record of taking part in it - Identity, offers, answers, the
    # seats it holds elsewhere - and copying the text is not copying who
    # agreed to it.
    CLONED_TYPES = frozenset({
        "team_section", "team_clause",
        "team_role", "team_accountability", "team_domain",
    })

    def clone_team(
        self, team_uuid: str, title: str | None = None,
    ) -> SessionResult:
        """Copy a team's text and structure, with nobody in it.

        Fresh uuids throughout, because acceptance is uuid-keyed: a copy that
        shared role uuids with its original would let an answer given there
        count here. Nothing is stripped afterwards - the records of taking
        part are simply never copied - so the copy lands at zero actors,
        which is what a template is (2.8). No Identity and no default
        Member either: taking Identity is how somebody starts using it.

        Not gated on holding a role in the source. Copying reads that
        team and writes only a new one of this session's own, so an
        team you can see read-only is one you can fork into a template.
        """
        source = self._node(team_uuid, "team")
        if not source:
            return SessionResult("error", reason="team not found")
        normalized = self._distinct_name(
            str(title or "").strip() or (
                f"{source.data.get('title') or 'Untitled team'} (template)"
            ),
            self._team_titles(),
        )
        # The copy is a new body with the same agreement, so it takes a new
        # team name and keeps the agreement's - which is the whole reason the
        # two are separate fields. A template's text arrives named.
        data = {"type": "team", "title": normalized}
        if agreement_title := source.data.get("agreement_title"):
            data["agreement_title"] = agreement_title
        created = self.session.create_child(
            self._team_container().uuid, data, {},
        )
        if created.status != "ok":
            return created
        copied = self._copy_content(source, created.value.uuid)
        if copied.status != "ok":
            self.session.delete(created.value.uuid)
            return copied
        self._remember_team(created.value.uuid)
        return SessionResult(
            "ok",
            value=created.value.uuid,
            effects=[*created.effects, *copied.effects],
        )

    def _copy_content(
        self, source: ProtocolNode, target_uuid: str,
    ) -> SessionResult:
        """Recreate a node's copyable children under a new parent."""
        effects = []
        for child in source.live_children():
            if child.data.get("type") not in self.CLONED_TYPES:
                continue
            # Order rides along in the data, so the children can be walked in
            # any order and still come out arranged as they were.
            created = self.session.create_child(
                target_uuid, dict(child.data), dict(child.weights),
            )
            if created.status != "ok":
                return created
            copied = self._copy_content(child, created.value.uuid)
            if copied.status != "ok":
                return copied
            effects.extend([*created.effects, *copied.effects])
        return SessionResult("ok", effects=effects)

    def select_team(self, team_uuid: str) -> SessionResult:
        team = self._node(team_uuid, "team")
        if not team:
            return SessionResult("error", reason="team not found")
        self._remember_team(team.uuid)
        return SessionResult("ok", value=team.uuid)

    def create_section(self, team_uuid: str, title: str) -> SessionResult:
        team = self._node(team_uuid, "team")
        if not team:
            return SessionResult("error", reason="team not found")
        allowed = self._interaction_guard(team)
        if allowed.status != "ok":
            return allowed
        normalized = str(title or "").strip()
        if not normalized:
            return SessionResult("error", reason="section title is required")
        result = self.session.create_child(
            team.uuid,
            {
                "type": "team_section",
                "title": normalized,
                "order": self.session.next_child_order(
                    team.uuid, "team_section",
                ),
            },
            {},
        )
        if result.status == "ok":
            return SessionResult(
                "ok", value=result.value.uuid, effects=result.effects,
            )
        return result

    def create_clause(self, section_uuid: str, text: str) -> SessionResult:
        section = self._node(section_uuid, "team_section")
        if not section:
            return SessionResult("error", reason="section not found")
        allowed = self._interaction_guard_for_node(section.uuid)
        if allowed.status != "ok":
            return allowed
        normalized = str(text or "").strip()
        if not normalized:
            return SessionResult("error", reason="clause text is required")
        result = self.session.create_child(
            section.uuid,
            {
                "type": "team_clause",
                "text": normalized,
                "order": self.session.next_child_order(
                    section.uuid, "team_clause",
                ),
            },
            {},
        )
        if result.status == "ok":
            return SessionResult(
                "ok", value=result.value.uuid, effects=result.effects,
            )
        return result

    def update_clause(self, clause_uuid: str, text: str) -> SessionResult:
        clause = self._node(clause_uuid, "team_clause")
        if not clause:
            return SessionResult("error", reason="clause not found")
        allowed = self._interaction_guard_for_node(clause.uuid)
        if allowed.status != "ok":
            return allowed
        normalized = str(text or "").strip()
        if not normalized:
            return SessionResult("error", reason="clause text is required")
        data = dict(clause.data)
        data["text"] = normalized
        return self.session.modify(clause.uuid, data, clause.weights)

    def rename_team(self, team_uuid: str, title: str) -> SessionResult:
        # The seat in the parent keeps its own name. It is what the parent
        # expects of this body, which is not the same thing as what the
        # body calls itself.
        return self._retitle(
            team_uuid, "team", "title", title, distinct=True,
        )

    def rename_agreement(self, team_uuid: str, title: str) -> SessionResult:
        """Name the agreement, which is not the name of the team.

        A team is a body of people; its agreement is the text they hold to.
        One name was doing both jobs, so a team called "Finance" had an
        agreement called "Finance" - and renaming the body silently retitled
        the document everybody had accepted. They are stored as two fields on
        the same node because sections already hang off the team directly and
        there is no separate agreement node to carry one.

        It is left unset rather than defaulted: an agreement nobody has named
        is a real state, and seeding every team with the word "Agreement" as
        a name would only make the label unreadable as a name. The page shows
        a prompt in its place. Both fields sit in team_reference_hash, so
        renaming either re-opens acceptances - which is right for the title
        of the thing that was accepted.
        """
        return self._retitle(
            team_uuid, "team", "agreement_title", title,
        )

    def rename_section(self, section_uuid: str, title: str) -> SessionResult:
        return self._retitle(section_uuid, "team_section", "title", title)

    def _retitle(self, node_uuid: str, node_type: str, field: str,
                 value: str, distinct: bool = False) -> SessionResult:
        node = self._node(node_uuid, node_type)
        if not node:
            return SessionResult("error", reason=f"{node_type} not found")
        allowed = self._interaction_guard_for_node(node.uuid)
        if allowed.status != "ok":
            return allowed
        normalized = str(value or "").strip()
        if not normalized:
            return SessionResult("error", reason=f"{field} is required")
        if distinct:
            normalized = self._distinct_name(
                normalized, self._sibling_names(node, node_type, field),
            )
        data = dict(node.data)
        data[field] = normalized
        return self.session.modify(node.uuid, data, node.weights)

    def delete_team(self, team_uuid: str) -> SessionResult:
        # A team is a topic, so deleting it also stops sharing it -
        # otherwise peers keep syncing a document this side no longer has.
        # There is no "last team" to protect: unlike a board, nothing
        # here creates one on demand, and a host with none is a valid state.
        team = self._node(team_uuid, "team")
        if not team:
            return SessionResult("error", reason="team not found")
        allowed = self._interaction_guard(team)
        if allowed.status != "ok":
            return allowed
        effects = []
        # The child topics are independent teams, so deleting a parent
        # promotes them rather than cascading through the organization:
        # their side of the seat goes, and they become roots.
        for child_uuid, _role in self.child_teams(team):
            child = self._node(child_uuid, "team")
            if not child:
                continue
            for holding in self.parent_holdings(child):
                if holding.data.get("parent_team_uuid") != team.uuid:
                    continue
                dropped = self.session.delete(holding.uuid)
                if dropped.status == "ok":
                    effects.extend(dropped.effects)
        # And the answers given on this team's behalf elsewhere go with
        # it, so no parent is left showing a seat filled by something that is
        # gone from here. Its own side of each seat needs no separate delete:
        # the holdings are inside the subtree about to go.
        for holding in self.parent_holdings(team):
            effects.extend(self._release_seat(team, holding))
        pool = self.pool_for_team(team)
        if pool:
            pool_release = self.session.end_topic_sharing(pool.uuid)
            pool_deleted = self.session.delete(pool.uuid)
            effects.extend(pool_release.effects)
            if pool_deleted.status == "ok":
                effects.extend(pool_deleted.effects)
        release = self.session.end_topic_sharing(team.uuid)
        result = self.session.delete(team.uuid)
        if result.status != "ok":
            return result
        result.effects = [*effects, *release.effects, *result.effects]
        remaining = [item for item in self.teams() if item.uuid != team.uuid]
        self._remember_team(remaining[0].uuid if remaining else "")
        return result

    def delete_section(self, section_uuid: str) -> SessionResult:
        # Deleting a section takes its clauses with it. That is safe here
        # only because the request is local and explicit; adopting a peer's
        # section deletion is a separate decision this application still
        # leaves to the generic reconciliation path.
        section = self._node(section_uuid, "team_section")
        if not section:
            return SessionResult("error", reason="section not found")
        allowed = self._interaction_guard_for_node(section.uuid)
        if allowed.status != "ok":
            return allowed
        return self.session.delete(section.uuid)

    def delete_clause(self, clause_uuid: str) -> SessionResult:
        clause = self._node(clause_uuid, "team_clause")
        if not clause:
            return SessionResult("error", reason="clause not found")
        allowed = self._interaction_guard_for_node(clause.uuid)
        if allowed.status != "ok":
            return allowed
        return self.session.delete(clause.uuid)

    def move_section(self, section_uuid: str, index: int) -> SessionResult:
        if not self._node(section_uuid, "team_section"):
            return SessionResult("error", reason="section not found")
        allowed = self._interaction_guard_for_node(section_uuid)
        if allowed.status != "ok":
            return allowed
        return self.session.move_child_to_index(section_uuid, index)

    def move_clause(self, clause_uuid: str, index: int) -> SessionResult:
        if not self._node(clause_uuid, "team_clause"):
            return SessionResult("error", reason="clause not found")
        allowed = self._interaction_guard_for_node(clause_uuid)
        if allowed.status != "ok":
            return allowed
        return self.session.move_child_to_index(clause_uuid, index)

    def identity_holder(self, team: ProtocolNode) -> str:
        """The settled incumbent, including while successors are contested."""
        return str(
            self.trustee_projection(team, "identity").get(
                "holder_actor_uuid",
            ) or ""
        ).strip()

    def trust_holder(self, team: ProtocolNode) -> str:
        return str(
            self.trustee_projection(team, "trust").get(
                "holder_actor_uuid",
            ) or ""
        ).strip()

    def holds_identity(self, team: ProtocolNode) -> bool:
        return bool(
            (holder := self.identity_holder(team))
            and holder == self._identity_uuid
        )

    def holds_trust(self, team: ProtocolNode) -> bool:
        return bool(
            (holder := self.trust_holder(team))
            and holder == self._identity_uuid
        )

    def _holds_identity_of(self, team_uuid: str) -> bool:
        """Same question about a team named only by uuid, which may be
        one this session has not joined and so cannot answer for."""
        team = self._node(team_uuid, "team")
        return bool(team and self.holds_identity(team))

    def take_identity(self, team_uuid: str) -> SessionResult:
        """Instantiate an empty template; occupied trusteeships are elected."""
        team = self._node(team_uuid, "team")
        if not team:
            return SessionResult("error", reason="team not found")
        allowed = self._interaction_guard(team)
        if allowed.status != "ok":
            return allowed
        if any(self.governance_records(team, "team_trustee_state")):
            return SessionResult(
                "error",
                reason="Identity changes require a facilitated decision",
            )
        member = self._create_default_member(team)
        identity = self._create_trusteeship(team, "identity")
        trust = self._create_trusteeship(team, "trust")
        pool = self._create_pool(team)
        return SessionResult(
            "ok",
            value=identity.value,
            effects=[
                *member.effects, *identity.effects, *trust.effects,
                *pool.effects,
            ],
        )

    def offer_identity(
        self, team_uuid: str, actor_uuid: str,
    ) -> SessionResult:
        """Direct handover is not part of the append-only authority model."""
        team = self._node(team_uuid, "team")
        if not team:
            return SessionResult("error", reason="team not found")
        allowed = self._interaction_guard(team)
        if allowed.status != "ok":
            return allowed
        return SessionResult(
            "error", reason="Identity changes require a facilitated decision",
        )

    def resign_identity(self, team_uuid: str) -> SessionResult:
        """Append an explicit vacancy after the current Identity state."""
        return self.resign_trusteeship(team_uuid, "identity")

    def resign_trusteeship(
        self, team_uuid: str, trust: str,
        signals: str = "", consideration: str = "", expectation: str = "",
    ) -> SessionResult:
        team = self._node(team_uuid, "team")
        if not team:
            return SessionResult("error", reason="team not found")
        if trust not in self.TRUSTS:
            return SessionResult("error", reason="unknown trusteeship")
        holder = (
            self.identity_holder(team) if trust == "identity"
            else self.trust_holder(team)
        )
        if holder != self._identity_uuid:
            return SessionResult(
                "error",
                reason=f"only the {trust.title()} holder can step out of it",
            )
        current = self.trustee_projection(team, trust)
        current_uuid = current.get("current_state_uuid") or ""
        return self.append_governance_record(team.uuid, {
            "type": "team_trustee_state",
            "trust": trust,
            "holder_actor_uuid": "",
            "previous_state_uuid": current_uuid,
            "cause": "resignation",
            "acted_by": self._identity_uuid,
            "acted_at": self._now(),
            "authority_basis_uuid": current_uuid,
            "signals": str(signals or "").strip(),
            "consideration": str(consideration or "").strip(),
            "expectation": str(expectation or "").strip(),
        })

    def _create_default_member(
        self, team: ProtocolNode,
    ) -> SessionResult:
        """Every team starts with one role, taken by its creator.

        Without it a new team has nobody in it, and taking part would
        mean first inventing the role to take. The name and purpose are
        ordinary editable content - this is a starting point, not a fixture.
        """
        role = self.member_role(team)
        effects = []
        if role is None:
            created = self.session.create_child(
                team.uuid,
                {
                    "type": "team_role",
                    "name": "Member",
                    "purpose": "Belong to this team",
                    "system_key": "member",
                    "order": 0.0,
                },
                {},
            )
            if created.status != "ok":
                return created
            role = created.value
            effects.extend(created.effects)
        offered = self.session.create_child(
            role.uuid,
            {
                "type": "team_role_offer",
                "actor_uuid": self._identity_uuid,
                "actor_kind": "individual",
                "offered_by": self._identity_uuid,
                "offered_at": self._now(),
                "system_genesis": True,
            },
            {},
        )
        decided = self._record_role_decision(
            team, role, "accepted", None,
        )
        return SessionResult(
            "ok",
            value=role.uuid,
            effects=[*effects, *offered.effects, *decided.effects],
        )

    def _create_trusteeship(
        self, team: ProtocolNode, trust: str,
        actor_uuid: str | None = None,
    ) -> SessionResult:
        actor = actor_uuid or self._identity_uuid
        return self.session.create_child(
            team.uuid,
            {
                "type": "team_trustee_state",
                "trust": trust,
                "holder_actor_uuid": actor,
                "previous_state_uuid": "",
                "cause": "genesis",
                "acted_by": actor,
                "acted_at": self._now(),
                "authority_basis_uuid": "",
                "signals": "",
                "consideration": "",
                "expectation": "",
            },
            {},
        )

    def identity_payload(self, team: ProtocolNode) -> dict:
        return self.trusteeship_payload(team, "identity")

    def trust_payload(self, team: ProtocolNode) -> dict:
        return self.trusteeship_payload(team, "trust")

    def trusteeship_payload(self, team: ProtocolNode, trust: str) -> dict:
        """Render one append-only trusteeship and any successor contest."""
        blank = {
            "trust": trust,
            "node_uuid": "",
            "holder_actor_uuid": "",
            "holder_name": "",
            "is_self": False,
            "held_since": None,
            "claims": [],
            "candidates": [],
            "can_enter_candidacy": False,
            "can_act": False,
        }
        projection = self.trustee_projection(team, trust)
        current_uuid = projection.get("current_state_uuid") or ""
        current = self._governance_node(
            team, current_uuid, "team_trustee_state",
        )
        people = self._topic_members(team.uuid)
        members = {member["uuid"]: member for member in people}
        holder = str(projection.get("holder_actor_uuid") or "").strip()
        claims = [
            {"state_uuid": contender_uuid}
            for contender_uuid in projection.get("contenders") or []
        ]
        candidates = self.active_trustee_candidates_payload(team, trust)
        own_candidate = next(
            (candidate for candidate in candidates if candidate["is_self"]),
            None,
        )
        return {
            **blank,
            "trust": trust,
            "node_uuid": current_uuid,
            "state": projection.get("state") or "unconfigured",
            "holder_actor_uuid": holder,
            "holder_name": (
                (members.get(holder) or {}).get("name")
                or ("Someone you have not met" if holder else "")
            ),
            "is_self": holder == self._identity_uuid,
            "held_since": current.data.get("acted_at") if current else None,
            "claims": claims,
            "candidates": candidates,
            "can_enter_candidacy": bool(
                projection.get("state") == "vacant"
                and self._is_current_member(team, self._identity_uuid)
                and own_candidate is None
            ),
            "can_act": bool(self._authority_basis_for_actor(
                team, trust, self._identity_uuid,
            )),
        }

    # Roles are document content: a role is part of what people agree to,
    # not administration layered on top of it. Accountabilities and domains
    # are the same shape - text plus order, owned by a role - so they share
    # one set of write paths. They are separate node types rather than a
    # list inside the role's data because REACTABLE is per node: two people
    # editing different accountabilities have to diverge separately, exactly
    # as two clauses do. A list would collapse both edits into one
    # undiffable conflict.
    ROLE_ITEM_TYPES = {
        "accountability": "team_accountability",
        "domain": "team_domain",
    }

    def roles(self, team: ProtocolNode) -> list[ProtocolNode]:
        return self._ordered(team, "team_role")

    MEMBER_ROLE_SYSTEM_KEY = "member"

    def member_role(self, team: ProtocolNode) -> ProtocolNode | None:
        """Return the uniquely marked constitutional Member role."""
        marked = [
            role for role in self.roles(team)
            if role.data.get("system_key") == self.MEMBER_ROLE_SYSTEM_KEY
        ]
        return marked[0] if len(marked) == 1 else None

    def governance_records(
        self, team: ProtocolNode, node_type: str | None = None,
    ) -> list[ProtocolNode]:
        return sorted(
            [
                child for child in team.live_children()
                if child.data.get("type") in self.GOVERNANCE_RECORD_TYPES
                and (node_type is None or child.data.get("type") == node_type)
            ],
            key=lambda node: (node.created_at, node.uuid),
        )

    def governance_schema_error(self, node: ProtocolNode) -> str | None:
        node_type = node.data.get("type")
        contract = self.GOVERNANCE_FIELDS.get(node_type)
        if contract is None:
            return "not a governance record"
        if node.children:
            return "governance records cannot contain children"
        required, optional = contract
        fields = set(node.data)
        missing = sorted(required - fields)
        extra = sorted(fields - required - optional)
        if missing:
            return "missing governance fields: " + ", ".join(missing)
        if extra:
            return "unsupported governance fields: " + ", ".join(extra)

        data = node.data
        scalar_exceptions = {
            "electorate_actor_uuids", "payload", "process_definition_version",
        }
        for field in required - {"type"} - scalar_exceptions:
            if not isinstance(data.get(field), str):
                return f"{field} must be a string"
        for field in optional:
            if field in data and not isinstance(data[field], str):
                return f"{field} must be a string"
        if node_type in {"team_trustee_state", "team_trustee_election",
                         "team_trustee_candidacy", "team_trustee_action"}:
            if data.get("trust") not in self.TRUSTS:
                return "trust must be identity or trust"
        if node_type == "team_trustee_state":
            if data.get("cause") not in self.TRUSTEE_CAUSES:
                return "unsupported trustee-state cause"
            if data.get("cause") == "genesis" and (
                data.get("previous_state_uuid") or data.get("authority_basis_uuid")
            ):
                return "genesis cannot name previous state or authority basis"
            if data.get("cause") != "genesis" and not data.get("previous_state_uuid"):
                return "non-genesis trustee state requires previous_state_uuid"
            if data.get("cause") in {"election", "resolution"} and (
                not data.get("process_uuid") or not data.get("process_result_hash")
            ):
                return "election state requires process evidence"
        elif node_type == "team_member_opening":
            if data.get("state") not in {"open", "closed"}:
                return "opening state must be open or closed"
            if data.get("state") == "open" and data.get("previous_opening_uuid"):
                return "initial opening cannot name a predecessor"
            if data.get("state") == "closed" and (
                not data.get("closed_at") or not data.get("previous_opening_uuid")
            ):
                return "closed opening requires closed_at and a predecessor"
        elif node_type == "team_member_application":
            if data.get("state") not in {"submitted", "withdrawn"}:
                return "application state must be submitted or withdrawn"
            if data.get("state") == "submitted" and data.get("previous_application_uuid"):
                return "initial application cannot name a predecessor"
            if data.get("state") == "withdrawn" and (
                not data.get("withdrawn_at")
                or not data.get("previous_application_uuid")
            ):
                return "withdrawn application requires withdrawn_at and a predecessor"
        elif node_type == "team_member_resolution":
            if data.get("outcome") not in {"accepted", "rejected"}:
                return "resolution outcome must be accepted or rejected"
        elif node_type == "team_trustee_election":
            electorate = data.get("electorate_actor_uuids")
            if not isinstance(electorate, list) or not all(
                isinstance(actor, str) and actor for actor in electorate
            ):
                return "electorate_actor_uuids must be a list of actor UUIDs"
            if not electorate or len(electorate) != len(set(electorate)):
                return "electorate_actor_uuids must be non-empty and unique"
            version = data.get("process_definition_version")
            if isinstance(version, bool) or not isinstance(version, (str, int)):
                return "process_definition_version must be a string or integer"
            expected_facilitator = (
                "trust" if data.get("trust") == "identity" else "identity"
            )
            if data.get("facilitator_trust") != expected_facilitator:
                return "the counterpart trusteeship must facilitate the election"
        elif node_type == "team_trustee_candidacy":
            if data.get("state") not in {"active", "withdrawn"}:
                return "candidacy state must be active or withdrawn"
            if data.get("state") == "active" and data.get("previous_candidacy_uuid"):
                return "initial candidacy cannot name a predecessor"
            if data.get("state") == "withdrawn" and (
                not data.get("withdrawn_at")
                or not data.get("previous_candidacy_uuid")
            ):
                return "withdrawn candidacy requires withdrawn_at and a predecessor"
        elif node_type == "team_trustee_action":
            if data.get("action_kind") not in self.ACTION_KINDS:
                return "unsupported trustee action kind"
            if not isinstance(data.get("payload"), dict):
                return "trustee action payload must be an object"
        elif node_type == "team_external_member_resolution":
            if data.get("outcome") != "accepted":
                return "external Team resolution must be accepted"
        return None

    def pool_schema_error(self, node: ProtocolNode) -> str | None:
        node_type = node.data.get("type")
        contract = self.POOL_FIELDS.get(node_type)
        if contract is None:
            return "not a Pool record"
        if node.children:
            return "Pool records cannot contain children"
        required, optional = contract
        fields = set(node.data)
        missing = sorted(required - fields)
        extra = sorted(fields - required - optional)
        if missing:
            return "missing Pool fields: " + ", ".join(missing)
        if extra:
            return "unsupported Pool fields: " + ", ".join(extra)
        data = node.data
        for field in required - {"type"}:
            if not isinstance(data.get(field), str):
                return f"{field} must be a string"
        if "withdrawn_at" in data and not isinstance(data["withdrawn_at"], str):
            return "withdrawn_at must be a string"
        if "team_invitation_token" in data and not isinstance(
            data["team_invitation_token"], dict,
        ):
            return "team_invitation_token must be an object"
        if node_type == "team_pool_application":
            if data.get("state") not in {"submitted", "withdrawn"}:
                return "Pool application state must be submitted or withdrawn"
            if data.get("state") == "submitted" and data.get(
                "previous_application_uuid",
            ):
                return "initial Pool application cannot name a predecessor"
            if data.get("state") == "withdrawn" and (
                not data.get("previous_application_uuid")
                or not data.get("withdrawn_at")
            ):
                return "withdrawn Pool application requires its predecessor"
        elif node_type == "team_pool_resolution":
            if data.get("outcome") not in {"accepted", "rejected"}:
                return "Pool resolution outcome must be accepted or rejected"
            token = data.get("team_invitation_token")
            if data.get("outcome") == "accepted" and not token:
                return "accepted Pool resolution requires Team coordinates"
            if data.get("outcome") == "rejected" and token is not None:
                return "rejected Pool resolution cannot expose Team coordinates"
        return None

    def trustee_projection(self, team: ProtocolNode, trust: str) -> dict:
        states = [
            state for state in self.governance_records(team, "team_trustee_state")
            if state.data.get("trust") == trust
            and self.governance_schema_error(state) is None
        ]
        by_previous: dict[str, list[ProtocolNode]] = {}
        for state in states:
            by_previous.setdefault(
                str(state.data.get("previous_state_uuid") or ""), [],
            ).append(state)
        roots = by_previous.get("", [])
        blank = {
            "trust": trust, "state": "unconfigured", "current_state_uuid": "",
            "holder_actor_uuid": "", "contenders": [],
        }
        if not roots:
            return blank
        if len(roots) > 1:
            return {
                **blank, "state": "contested",
                "contenders": [state.uuid for state in roots],
            }
        current = roots[0]
        seen = {current.uuid}
        while True:
            successors = [
                state for state in by_previous.get(current.uuid, [])
                if state.uuid not in seen
            ]
            if not successors:
                holder = str(current.data.get("holder_actor_uuid") or "")
                return {
                    **blank,
                    "state": "held" if holder else "vacant",
                    "current_state_uuid": current.uuid,
                    "holder_actor_uuid": holder,
                }
            if len(successors) > 1:
                holder = str(current.data.get("holder_actor_uuid") or "")
                return {
                    **blank,
                    "state": "contested",
                    "current_state_uuid": current.uuid,
                    "holder_actor_uuid": holder,
                    "contenders": [state.uuid for state in successors],
                }
            current = successors[0]
            seen.add(current.uuid)

    def _record_chain_projection(
        self, team: ProtocolNode, node_type: str, root_uuid: str,
        predecessor_field: str,
    ) -> dict:
        records = self.governance_records(team, node_type)
        by_uuid = {record.uuid: record for record in records}
        root = by_uuid.get(root_uuid)
        blank = {
            "root_uuid": root_uuid,
            "current_uuid": "",
            "state": "missing",
            "contenders": [],
        }
        if root is None or root.data.get(predecessor_field):
            return blank
        by_previous: dict[str, list[ProtocolNode]] = {}
        for record in records:
            previous = str(record.data.get(predecessor_field) or "")
            if previous:
                by_previous.setdefault(previous, []).append(record)
        current = root
        seen = {root.uuid}
        while True:
            successors = [
                record for record in by_previous.get(current.uuid, [])
                if record.uuid not in seen
            ]
            if not successors:
                return {
                    **blank,
                    "current_uuid": current.uuid,
                    "state": str(current.data.get("state") or ""),
                }
            if len(successors) > 1:
                return {
                    **blank,
                    "current_uuid": current.uuid,
                    "state": "contested",
                    "effective_state": str(current.data.get("state") or ""),
                    "contenders": [record.uuid for record in successors],
                }
            current = successors[0]
            seen.add(current.uuid)

    def member_opening_projection(
        self, team: ProtocolNode, opening_uuid: str,
    ) -> dict:
        return self._record_chain_projection(
            team, "team_member_opening", opening_uuid,
            "previous_opening_uuid",
        )

    def member_application_projection(
        self, team: ProtocolNode, application_uuid: str,
    ) -> dict:
        return self._record_chain_projection(
            team, "team_member_application", application_uuid,
            "previous_application_uuid",
        )

    def trustee_candidacy_projection(
        self, team: ProtocolNode, candidacy_uuid: str,
    ) -> dict:
        return self._record_chain_projection(
            team, "team_trustee_candidacy", candidacy_uuid,
            "previous_candidacy_uuid",
        )

    def trustee_candidacy_roots(
        self, team: ProtocolNode, trust: str | None = None,
    ) -> list[ProtocolNode]:
        return [
            record
            for record in self.governance_records(
                team, "team_trustee_candidacy",
            )
            if not record.data.get("previous_candidacy_uuid")
            and (trust is None or record.data.get("trust") == trust)
        ]

    def active_trustee_candidates(
        self, team: ProtocolNode, trust: str,
    ) -> list[ProtocolNode]:
        projection = self.trustee_projection(team, trust)
        vacancy_uuid = str(projection.get("current_state_uuid") or "")
        if projection.get("state") != "vacant":
            return []
        return [
            candidacy
            for candidacy in self.trustee_candidacy_roots(team, trust)
            if candidacy.data.get("vacant_state_uuid") == vacancy_uuid
            and self.trustee_candidacy_projection(
                team, candidacy.uuid,
            ).get("state") == "active"
            and self._is_current_member(
                team, str(candidacy.data.get("actor_uuid") or ""),
            )
        ]

    def active_trustee_candidates_payload(
        self, team: ProtocolNode, trust: str,
    ) -> list[dict]:
        people = self._known_people()
        payload = []
        for candidacy in self.active_trustee_candidates(team, trust):
            actor_uuid = str(candidacy.data.get("actor_uuid") or "")
            person = people.get(actor_uuid) or {}
            payload.append({
                "uuid": candidacy.uuid,
                "actor_uuid": actor_uuid,
                "name": person.get("name") or person.get("address") or "Member",
                "picture": person.get("picture") or "",
                "is_self": actor_uuid == self._identity_uuid,
                "submitted_at": candidacy.data.get("submitted_at"),
                "can_withdraw": actor_uuid == self._identity_uuid,
            })
        return payload

    def member_opening_roots(self, team: ProtocolNode) -> list[ProtocolNode]:
        return [
            record
            for record in self.governance_records(team, "team_member_opening")
            if not record.data.get("previous_opening_uuid")
        ]

    def member_application_roots(
        self, team: ProtocolNode, opening_uuid: str | None = None,
    ) -> list[ProtocolNode]:
        return [
            record
            for record in self.governance_records(
                team, "team_member_application",
            )
            if not record.data.get("previous_application_uuid")
            and (
                opening_uuid is None
                or record.data.get("opening_uuid") == opening_uuid
            )
        ]

    def member_resolution_projection(
        self, team: ProtocolNode, application_uuid: str,
    ) -> dict:
        resolutions = [
            record
            for record in self.governance_records(
                team, "team_member_resolution",
            )
            if record.data.get("application_uuid") == application_uuid
        ]
        if not resolutions:
            return {"state": "pending", "records": []}
        outcomes = {record.data.get("outcome") for record in resolutions}
        return {
            "state": (
                next(iter(outcomes)) if len(outcomes) == 1 else "contested"
            ),
            "records": [record.uuid for record in resolutions],
        }

    def member_standing(self, team: ProtocolNode, actor_uuid: str) -> str:
        for application in self.member_application_roots(team):
            if application.data.get("actor_uuid") != actor_uuid:
                continue
            resolution = self.member_resolution_projection(
                team, application.uuid,
            )
            if resolution["state"] == "accepted":
                return "accepted"
            if resolution["state"] == "contested":
                return "contested"
        external = [
            record for record in self.governance_records(
                team, "team_external_member_resolution",
            )
            if record.data.get("actor_uuid") == actor_uuid
            and record.data.get("outcome") == "accepted"
        ]
        if external:
            return "accepted"
        return "observer"

    def membership_payload(self, team: ProtocolNode) -> dict:
        people = self._known_people()

        def actor_payload(actor_uuid: str) -> dict:
            person = people.get(actor_uuid) or {}
            return {
                "uuid": actor_uuid,
                "name": person.get("name") or person.get("address") or "Observer",
                "picture": person.get("picture") or "",
                "is_self": actor_uuid == self._identity_uuid,
            }

        openings = []
        for opening in self.member_opening_roots(team):
            projection = self.member_opening_projection(team, opening.uuid)
            applications = []
            for application in self.member_application_roots(
                team, opening.uuid,
            ):
                actor_uuid = str(application.data.get("actor_uuid") or "")
                application_state = self.member_application_projection(
                    team, application.uuid,
                )
                applications.append({
                    "uuid": application.uuid,
                    "actor": actor_payload(actor_uuid),
                    "state": application_state["state"],
                    "current_uuid": application_state["current_uuid"],
                    "resolution": self.member_resolution_projection(
                        team, application.uuid,
                    ),
                    "submitted_at": application.data.get("submitted_at"),
                })
            for resolution in self.governance_records(
                team, "team_external_member_resolution",
            ):
                if resolution.data.get("opening_uuid") != opening.uuid:
                    continue
                actor_uuid = str(resolution.data.get("actor_uuid") or "")
                applications.append({
                    "uuid": resolution.data.get("pool_application_uuid"),
                    "actor": actor_payload(actor_uuid),
                    "state": "submitted",
                    "current_uuid": resolution.data.get(
                        "pool_application_uuid",
                    ),
                    "resolution": {
                        "state": "accepted",
                        "records": [resolution.uuid],
                    },
                    "submitted_at": None,
                    "source": "pool",
                })
            openings.append({
                "uuid": opening.uuid,
                "state": projection["state"],
                "current_uuid": projection["current_uuid"],
                "contenders": projection["contenders"],
                "opened_at": opening.data.get("opened_at"),
                "applications": applications,
            })
        return {
            "openings": openings,
            "can_resolve": bool(self._authority_basis_for_actor(
                team, "identity", self._identity_uuid,
            )),
            "is_member": self._is_current_member(team, self._identity_uuid),
        }

    def verify_flow_decision_result(
        self,
        process_uuid: str,
        expected_result_hash: str | None = None,
        expected_definition_id: str = "integrative-election",
        expected_definition_version: str | None = None,
    ) -> dict:
        """Verify S-Flow's public result without reading its protocol nodes."""
        flow, flow_error = self._flow_facade()
        if flow is None or not callable(getattr(flow, "decision_result", None)):
            return self._flow_result_failure(
                "unavailable",
                flow_error or "S-Flow decision results are not available",
            )
        result = flow.decision_result(process_uuid)
        if not isinstance(result, dict):
            return self._flow_result_failure(
                "invalid", "S-Flow returned no decision result",
            )
        required = {
            "contract_id", "contract_version", "process_uuid",
            "definition_id", "definition_version", "lifecycle",
            "current_stage", "last_completed_stage",
            "terminal_outcome", "selected_candidate_uuid",
            "participant_snapshot", "facilitator_uuid", "result_hash",
        }
        if set(result) != required:
            return self._flow_result_failure(
                "invalid", "the decision result contract is incomplete",
                result,
            )
        if (
            result.get("contract_id") != FLOW_DECISION_RESULT_CONTRACT_ID
            or result.get("contract_version")
            != FLOW_DECISION_RESULT_CONTRACT_VERSION
        ):
            return self._flow_result_failure(
                "invalid", "the decision result contract version is unsupported",
                result,
            )
        string_fields = (
            "process_uuid", "definition_id", "definition_version",
            "lifecycle", "result_hash",
        )
        if any(
            not isinstance(result.get(field), str) or not result[field]
            for field in string_fields
        ):
            return self._flow_result_failure(
                "invalid", "the decision result has invalid required fields",
                result,
            )
        if any(
            not isinstance(result.get(field), str)
            for field in ("current_stage", "last_completed_stage")
        ):
            return self._flow_result_failure(
                "invalid", "the decision result has invalid progress fields",
                result,
            )
        if result["process_uuid"] != process_uuid:
            return self._flow_result_failure(
                "invalid", "the decision result names another process",
                result,
            )
        if (
            expected_definition_id
            and result["definition_id"] != expected_definition_id
        ):
            return self._flow_result_failure(
                "invalid", "the process does not use the expected definition",
                result,
            )
        if (
            expected_definition_version is not None
            and result["definition_version"] != expected_definition_version
        ):
            return self._flow_result_failure(
                "invalid", "the process definition version changed",
                result,
            )
        participants = result.get("participant_snapshot")
        if not isinstance(participants, list) or any(
            not isinstance(item, dict)
            or set(item) != {"identity_uuid", "role", "required"}
            or not isinstance(item.get("identity_uuid"), str)
            or not item.get("identity_uuid")
            or not isinstance(item.get("role"), str)
            or not item.get("role")
            or not isinstance(item.get("required"), bool)
            for item in participants
        ):
            return self._flow_result_failure(
                "invalid", "the participant snapshot is invalid",
                result,
            )
        facilitator = result.get("facilitator_uuid")
        if not isinstance(facilitator, str) or not facilitator:
            return self._flow_result_failure(
                "incomplete", "the process has no single facilitator",
                result,
            )
        try:
            computed_hash = self._canonical_flow_result_hash(result)
        except (TypeError, ValueError):
            return self._flow_result_failure(
                "invalid", "the decision result cannot be canonically hashed",
                result,
            )
        if result["result_hash"] != computed_hash:
            return self._flow_result_failure(
                "invalid", "the decision result hash is invalid",
                result,
                computed_hash,
            )
        if expected_result_hash and result["result_hash"] != expected_result_hash:
            return self._flow_result_failure(
                "changed", "the decision result changed",
                result,
                computed_hash,
            )
        outcome = result.get("terminal_outcome")
        candidate = result.get("selected_candidate_uuid")
        if result["lifecycle"] != "completed" or not isinstance(outcome, str):
            return self._flow_result_failure(
                "incomplete", "the decision process is not complete",
                result,
                computed_hash,
            )
        if result["definition_id"] == "integrative-election":
            if outcome not in {"elected", "void"}:
                return self._flow_result_failure(
                    "invalid", "the election has an invalid terminal outcome",
                    result,
                    computed_hash,
                )
            if outcome == "elected" and (
                not isinstance(candidate, str) or not candidate
            ):
                return self._flow_result_failure(
                    "incomplete", "the election selected no candidate",
                    result,
                    computed_hash,
                )
            if outcome == "void" and candidate is not None:
                return self._flow_result_failure(
                    "invalid", "a void election cannot select a candidate",
                    result,
                    computed_hash,
                )
        return {
            "valid": True,
            "status": "valid",
            "reason": "",
            "result": copy.deepcopy(result),
            "computed_hash": computed_hash,
        }

    def _flow_facade(self):
        if self.facades is None:
            return None, "S-Flow is not active"
        try:
            flow = self.facades.find(
                FLOW_APPLICATION_ID, FLOW_FACADE_API_VERSION,
            )
        except ValueError as exc:
            return None, str(exc)
        return (
            (flow, "") if flow is not None
            else (None, "S-Flow is not active")
        )

    def current_member_uuids(self, team: ProtocolNode) -> list[str]:
        candidates = {
            str(application.data.get("actor_uuid") or "")
            for application in self.member_application_roots(team)
        }
        candidates.update(
            str(record.data.get("actor_uuid") or "")
            for record in self.governance_records(
                team, "team_external_member_resolution",
            )
        )
        member = self.member_role(team)
        if member is not None:
            candidates.update(
                str(offer.data.get("actor_uuid") or "")
                for offer in self._all_role_offers(member)
                if offer.data.get("system_genesis")
            )
        return sorted(
            actor_uuid
            for actor_uuid in candidates
            if actor_uuid and self._is_current_member(team, actor_uuid)
        )

    def trustee_election_records(
        self, team: ProtocolNode, trust: str | None = None,
    ) -> list[ProtocolNode]:
        return [
            election
            for election in self.governance_records(
                team, "team_trustee_election",
            )
            if trust is None or election.data.get("trust") == trust
        ]

    def _validated_election_result(
        self, team: ProtocolNode, election: ProtocolNode,
        expected_result_hash: str | None = None,
    ) -> dict:
        verification = self.verify_flow_decision_result(
            str(election.data.get("process_uuid") or ""),
            expected_result_hash,
            str(election.data.get("process_definition_id") or ""),
            str(election.data.get("process_definition_version") or ""),
        )
        result = verification.get("result")
        if not isinstance(result, dict):
            return verification
        required_participants = {
            item.get("identity_uuid")
            for item in result.get("participant_snapshot") or []
            if item.get("role") == "requiredParticipant"
            and item.get("required") is True
        }
        electorate = set(election.data.get("electorate_actor_uuids") or [])
        if required_participants != electorate:
            return self._flow_result_failure(
                "invalid", "the Flow participant snapshot differs from the electorate",
                result, verification.get("computed_hash") or "",
            )
        if result.get("facilitator_uuid") != election.data.get(
            "facilitator_actor_uuid",
        ):
            return self._flow_result_failure(
                "invalid", "the Flow facilitator differs from the election record",
                result, verification.get("computed_hash") or "",
            )
        return verification

    def _election_target_predecessor_is_valid(
        self,
        team: ProtocolNode,
        election: ProtocolNode,
        previous: ProtocolNode,
    ) -> bool:
        """Prevent replay after another decision while allowing resignation."""
        target_uuid = str(election.data.get("target_state_uuid") or "")
        if previous.uuid == target_uuid:
            return True
        cursor = previous
        seen = set()
        while cursor.uuid not in seen:
            seen.add(cursor.uuid)
            if (
                cursor.data.get("trust") != election.data.get("trust")
                or cursor.data.get("cause") != "resignation"
            ):
                return False
            parent_uuid = str(cursor.data.get("previous_state_uuid") or "")
            if parent_uuid == target_uuid:
                return True
            parent = self._governance_node(
                team, parent_uuid, "team_trustee_state",
            )
            if parent is None:
                return False
            cursor = parent
        return False

    def _authority_basis_for_actor(
        self, team: ProtocolNode, trust: str, actor_uuid: str,
    ) -> str:
        projection = self.trustee_projection(team, trust)
        if projection.get("holder_actor_uuid") == actor_uuid:
            return str(projection.get("current_state_uuid") or "")
        if projection.get("state") != "vacant":
            return ""
        for candidacy in self.active_trustee_candidates(team, trust):
            if candidacy.data.get("actor_uuid") == actor_uuid:
                return candidacy.uuid
        return ""

    def enter_trustee_candidacy(
        self, team_uuid: str, trust: str,
    ) -> SessionResult:
        team = self._node(team_uuid, "team")
        normalized_trust = str(trust or "").strip().lower()
        if not team:
            return SessionResult("error", reason="team not found")
        if normalized_trust not in self.TRUSTS:
            return SessionResult("error", reason="unknown trusteeship")
        if not self._is_current_member(team, self._identity_uuid):
            return SessionResult(
                "error", reason="only a current Member may become a candidate",
            )
        vacancy = self.trustee_projection(team, normalized_trust)
        if vacancy.get("state") != "vacant":
            return SessionResult(
                "error", reason="the trusteeship is not vacant",
            )
        if any(
            candidate.data.get("actor_uuid") == self._identity_uuid
            for candidate in self.active_trustee_candidates(
                team, normalized_trust,
            )
        ):
            return SessionResult("error", reason="you are already a candidate")
        return self.append_governance_record(team.uuid, {
            "type": "team_trustee_candidacy",
            "trust": normalized_trust,
            "actor_uuid": self._identity_uuid,
            "vacant_state_uuid": str(vacancy["current_state_uuid"]),
            "previous_candidacy_uuid": "",
            "submitted_at": self._now(),
            "state": "active",
        })

    def withdraw_trustee_candidacy(
        self, team_uuid: str, candidacy_uuid: str,
    ) -> SessionResult:
        team = self._node(team_uuid, "team")
        candidacy = self._governance_node(
            team, candidacy_uuid, "team_trustee_candidacy",
        ) if team else None
        if (
            not team or not candidacy
            or candidacy.data.get("previous_candidacy_uuid")
            or candidacy.data.get("actor_uuid") != self._identity_uuid
        ):
            return SessionResult("error", reason="trustee candidacy not found")
        projection = self.trustee_candidacy_projection(
            team, candidacy.uuid,
        )
        if projection.get("state") != "active":
            return SessionResult("error", reason="candidacy is not active")
        return self.append_governance_record(team.uuid, {
            "type": "team_trustee_candidacy",
            "trust": candidacy.data["trust"],
            "actor_uuid": self._identity_uuid,
            "vacant_state_uuid": candidacy.data["vacant_state_uuid"],
            "previous_candidacy_uuid": str(projection["current_uuid"]),
            "submitted_at": candidacy.data["submitted_at"],
            "state": "withdrawn",
            "withdrawn_at": self._now(),
        })

    def start_trustee_election(
        self, team_uuid: str, trust: str,
        facilitator_actor_uuid: str = "",
    ) -> SessionResult:
        team = self._node(team_uuid, "team")
        normalized_trust = str(trust or "").strip().lower()
        if not team:
            return SessionResult("error", reason="team not found")
        if normalized_trust not in self.TRUSTS:
            return SessionResult("error", reason="unknown trusteeship")
        if not self._is_current_member(team, self._identity_uuid):
            return SessionResult(
                "error", reason="only a current Member may start an election",
            )
        electorate = self.current_member_uuids(team)
        if not electorate:
            return SessionResult("error", reason="the Team has no current Members")
        target = self.trustee_projection(team, normalized_trust)
        facilitator_trust = (
            "trust" if normalized_trust == "identity" else "identity"
        )
        facilitator = self.trustee_projection(team, facilitator_trust)
        requested_facilitator = str(facilitator_actor_uuid or "").strip()
        settled_facilitator = str(facilitator.get("holder_actor_uuid") or "")
        facilitator_basis_uuid = str(
            facilitator.get("current_state_uuid") or ""
        ) if settled_facilitator else ""
        if settled_facilitator:
            facilitator_actor_uuid = settled_facilitator
            if requested_facilitator and requested_facilitator != settled_facilitator:
                return SessionResult(
                    "error",
                    reason=f"{facilitator_trust.title()} is held by another Actor",
                )
        else:
            candidates = self.active_trustee_candidates(
                team, facilitator_trust,
            )
            candidate_actors = [
                str(candidate.data.get("actor_uuid") or "")
                for candidate in candidates
            ]
            if requested_facilitator:
                facilitator_actor_uuid = requested_facilitator
            elif self._identity_uuid in candidate_actors:
                facilitator_actor_uuid = self._identity_uuid
            elif len(candidate_actors) == 1:
                facilitator_actor_uuid = candidate_actors[0]
            else:
                facilitator_actor_uuid = ""
            facilitator_basis_uuid = self._authority_basis_for_actor(
                team, facilitator_trust, facilitator_actor_uuid,
            )
        if not target.get("current_state_uuid"):
            return SessionResult(
                "error", reason="the target trusteeship is not configured",
            )
        if not facilitator_actor_uuid or not facilitator_basis_uuid:
            return SessionResult(
                "error",
                reason=(
                    f"{facilitator_trust.title()} has no facilitator; "
                    "choose an active candidate"
                ),
            )
        flow, flow_error = self._flow_facade()
        if flow is None or not callable(
            getattr(flow, "create_integrative_election", None),
        ):
            return SessionResult(
                "error",
                reason=flow_error or "S-Flow cannot create elections",
            )
        title = (
            f"Elect {normalized_trust.title()} for "
            f"{team.data.get('title') or 'Team'}"
        )
        created = flow.create_integrative_election(
            title,
            electorate,
            facilitator_actor_uuid,
            electorate,
            "0.2.0",
        )
        if created.status != "ok":
            return created
        process_uuid = str(created.value or "")
        result = flow.decision_result(process_uuid)
        if not isinstance(result, dict):
            if callable(getattr(flow, "delete_process", None)):
                flow.delete_process(process_uuid)
            return SessionResult(
                "error", reason="S-Flow did not expose the created election",
            )
        recorded = self.append_governance_record(team.uuid, {
            "type": "team_trustee_election",
            "trust": normalized_trust,
            "target_state_uuid": str(target["current_state_uuid"]),
            "process_uuid": process_uuid,
            "process_definition_id": str(result.get("definition_id") or ""),
            "process_definition_version": str(
                result.get("definition_version") or ""
            ),
            "electorate_actor_uuids": electorate,
            "facilitator_trust": facilitator_trust,
            "facilitator_actor_uuid": facilitator_actor_uuid,
            "facilitator_authority_basis_uuid": facilitator_basis_uuid,
            "triggered_by": self._identity_uuid,
            "triggered_at": self._now(),
        })
        if recorded.status != "ok":
            if callable(getattr(flow, "delete_process", None)):
                flow.delete_process(process_uuid)
            return recorded
        recorded.effects = [*created.effects, *recorded.effects]
        return recorded

    def implement_trustee_election(
        self, team_uuid: str, election_uuid: str,
        signals: str = "", consideration: str = "", expectation: str = "",
    ) -> SessionResult:
        team = self._node(team_uuid, "team")
        election = self._governance_node(
            team, election_uuid, "team_trustee_election",
        ) if team else None
        if not team or not election:
            return SessionResult("error", reason="trustee election not found")
        existing = [
            state
            for state in self.governance_records(team, "team_trustee_state")
            if state.data.get("cause") == "election"
            and state.data.get("process_uuid") == election.data.get("process_uuid")
        ]
        if existing:
            return SessionResult(
                "error", reason="this election has already been implemented",
            )
        verified = self._validated_election_result(team, election)
        if not verified.get("valid"):
            return SessionResult("error", reason=verified.get("reason") or "invalid election result")
        result = verified["result"]
        if result.get("terminal_outcome") != "elected":
            return SessionResult(
                "error", reason="the election did not select a trustee",
            )
        facilitator_trust = str(election.data["facilitator_trust"])
        basis_uuid = self._authority_basis_for_actor(
            team, facilitator_trust, self._identity_uuid,
        )
        if not basis_uuid:
            return SessionResult(
                "error",
                reason=(
                    f"only {facilitator_trust.title()} or an authorised "
                    "acting candidate may implement this decision"
                ),
            )
        target = self.trustee_projection(team, str(election.data["trust"]))
        if target.get("state") == "contested":
            return SessionResult(
                "error", reason="the target trusteeship is already contested",
            )
        return self.append_governance_record(team.uuid, {
            "type": "team_trustee_state",
            "trust": str(election.data["trust"]),
            "holder_actor_uuid": str(result["selected_candidate_uuid"]),
            "previous_state_uuid": str(target.get("current_state_uuid") or ""),
            "cause": "election",
            "acted_by": self._identity_uuid,
            "acted_at": self._now(),
            "authority_basis_uuid": basis_uuid,
            "signals": str(signals or "").strip(),
            "consideration": str(consideration or "").strip(),
            "expectation": str(expectation or "").strip(),
            "process_uuid": str(election.data["process_uuid"]),
            "process_result_hash": str(result["result_hash"]),
        })

    def trustee_elections_payload(self, team: ProtocolNode) -> list[dict]:
        people = self._known_people()
        payload = []
        for election in self.trustee_election_records(team):
            checked = self._validated_election_result(team, election)
            result = checked.get("result") or {}
            facilitator_trust = str(election.data.get("facilitator_trust") or "")
            basis_uuid = self._authority_basis_for_actor(
                team, facilitator_trust, self._identity_uuid,
            )
            implemented = [
                state for state in self.governance_records(
                    team, "team_trustee_state",
                )
                if state.data.get("cause") == "election"
                and state.data.get("process_uuid")
                == election.data.get("process_uuid")
            ]
            candidate_uuid = str(result.get("selected_candidate_uuid") or "")
            candidate = people.get(candidate_uuid) or {}
            payload.append({
                "uuid": election.uuid,
                "trust": election.data.get("trust"),
                "process_uuid": election.data.get("process_uuid"),
                "definition_id": election.data.get("process_definition_id"),
                "definition_version": election.data.get("process_definition_version"),
                "electorate_actor_uuids": list(
                    election.data.get("electorate_actor_uuids") or []
                ),
                "facilitator_trust": facilitator_trust,
                "facilitator_actor_uuid": election.data.get("facilitator_actor_uuid"),
                "lifecycle": result.get("lifecycle") or "unavailable",
                "current_stage": result.get("current_stage") or "",
                "last_completed_stage": result.get("last_completed_stage") or "",
                "outcome": result.get("terminal_outcome"),
                "selected_candidate_uuid": candidate_uuid,
                "selected_candidate_name": candidate.get("name") or "",
                "result_status": checked.get("status"),
                "result_reason": checked.get("reason"),
                "result_hash": result.get("result_hash") or "",
                "implemented": bool(implemented),
                "implementation_uuids": [state.uuid for state in implemented],
                "can_implement": bool(
                    checked.get("valid")
                    and result.get("terminal_outcome") == "elected"
                    and basis_uuid
                    and not implemented
                ),
                "triggered_at": election.data.get("triggered_at"),
            })
        return payload

    @staticmethod
    def _canonical_flow_result_hash(result: dict) -> str:
        unsigned = {
            key: copy.deepcopy(value)
            for key, value in result.items()
            if key != "result_hash"
        }
        encoded = json.dumps(
            unsigned,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"

    @staticmethod
    def _flow_result_failure(
        status: str,
        reason: str,
        result: dict | None = None,
        computed_hash: str = "",
    ) -> dict:
        return {
            "valid": False,
            "status": status,
            "reason": reason,
            "result": copy.deepcopy(result),
            "computed_hash": computed_hash,
        }

    def _is_current_member(self, team: ProtocolNode, actor_uuid: str) -> bool:
        if self.member_standing(team, actor_uuid) == "accepted":
            return True
        role = self.member_role(team)
        if role is None or not self._offer_for(role, actor_uuid):
            return False
        offer = self._offer_for(role, actor_uuid)
        if not offer.data.get("system_genesis"):
            return False
        decision = self._role_decision_for(role, actor_uuid)
        return bool(
            decision
            and decision.data.get("decision") == "accepted"
            and not self._is_expired(decision.data.get("expires_at"))
        )

    def _signed_actor_status(
        self, node: ProtocolNode, actor_uuid: str,
    ) -> tuple[str, str]:
        identity_key = self.session.identity_key_for_actor(actor_uuid)
        if not identity_key:
            return ("deferred", "the named Actor's signing identity is not known")
        if identity_key != node.revision_origin:
            return ("unauthorized", "the verified signer is not the named Actor")
        return ("authorized", "")

    def _governance_node(
        self, team: ProtocolNode, node_uuid: str, node_type: str,
    ) -> ProtocolNode | None:
        node = self._node(node_uuid, node_type)
        if not node:
            return None
        owner = self._local_team_topic(node.uuid)
        return node if owner and owner.uuid == team.uuid else None

    def _trust_authority(
        self, team: ProtocolNode, trust: str, actor_uuid: str, basis_uuid: str,
    ) -> tuple[str, str]:
        projection = self.trustee_projection(team, trust)
        current_uuid = projection.get("current_state_uuid") or ""
        if not current_uuid:
            return ("deferred", f"{trust.title()} trusteeship is not configured")
        state = self._governance_node(
            team, basis_uuid, "team_trustee_state",
        )
        if state:
            if state.uuid != current_uuid:
                return ("unauthorized", "the trusteeship authority basis is stale")
            if projection.get("holder_actor_uuid") != actor_uuid:
                return ("unauthorized", f"the Actor does not hold {trust.title()}")
            return ("authorized", "")
        candidacy = self._governance_node(
            team, basis_uuid, "team_trustee_candidacy",
        )
        if candidacy is None:
            return ("deferred", "the authority basis is not available")
        if (
            projection.get("state") != "vacant"
            or candidacy.data.get("vacant_state_uuid") != current_uuid
        ):
            return ("unauthorized", "the acting-authority vacancy is no longer current")
        if (
            candidacy.data.get("trust") != trust
            or candidacy.data.get("actor_uuid") != actor_uuid
            or candidacy.data.get("previous_candidacy_uuid")
            or self.trustee_candidacy_projection(
                team, candidacy.uuid,
            ).get("state") != "active"
        ):
            return ("unauthorized", "the candidacy does not grant this authority")
        if not self._is_current_member(team, actor_uuid):
            return ("unauthorized", "the acting candidate is not a current Member")
        return ("authorized", "")

    def assess_governance_record(
        self, team: ProtocolNode, node: ProtocolNode,
        verification: str | None = None,
    ) -> dict:
        verification = verification or self.session.revision_verification(node)
        if verification == "unknown":
            return {"status": "deferred", "reason": "the signing key is not known"}
        if verification != "valid":
            return {"status": "invalid", "reason": "authorship signature is invalid"}
        schema_error = self.governance_schema_error(node)
        if schema_error:
            return {"status": "invalid", "reason": schema_error}
        if node.parent_uuid != team.uuid:
            return {
                "status": "invalid",
                "reason": "Governance records must be direct children of their Team.",
            }
        data = node.data
        node_type = data["type"]
        actor_field = {
            "team_trustee_state": "acted_by",
            "team_member_opening": "opened_by",
            "team_member_application": "actor_uuid",
            "team_member_resolution": "resolved_by",
            "team_trustee_election": "triggered_by",
            "team_trustee_candidacy": "actor_uuid",
            "team_trustee_action": "acted_by",
            "team_trustee_reality": "observed_by",
            "team_external_member_resolution": "resolved_by",
        }[node_type]
        actor_uuid = data.get(actor_field) or ""
        status, reason = self._signed_actor_status(node, actor_uuid)
        if status != "authorized":
            return {"status": status, "reason": reason}

        if node_type == "team_trustee_state":
            trust = data["trust"]
            existing = self.governance_records(team, "team_trustee_state")
            same_trust = [state for state in existing if state.data.get("trust") == trust]
            if data["cause"] == "genesis":
                if same_trust:
                    return {"status": "unauthorized", "reason": "trusteeship genesis already exists"}
                if data["holder_actor_uuid"] != actor_uuid:
                    return {"status": "unauthorized", "reason": "genesis must be authored by its holder"}
            else:
                previous = self._governance_node(
                    team, data["previous_state_uuid"], "team_trustee_state",
                )
                if previous is None or previous.data.get("trust") != trust:
                    return {"status": "deferred", "reason": "previous trustee state is not available"}
                projection = self.trustee_projection(team, trust)
                if previous.uuid != projection.get("current_state_uuid"):
                    competing = any(
                        state.data.get("previous_state_uuid") == previous.uuid
                        for state in same_trust
                    )
                    if not competing:
                        return {"status": "unauthorized", "reason": "previous trustee state is stale"}
                if data["cause"] == "resignation":
                    if data["authority_basis_uuid"] != previous.uuid:
                        return {"status": "unauthorized", "reason": "resignation basis must be the previous state"}
                    if previous.data.get("holder_actor_uuid") != actor_uuid:
                        return {"status": "unauthorized", "reason": "only the incumbent may resign"}
                    if data["holder_actor_uuid"]:
                        return {"status": "invalid", "reason": "resignation must leave the trusteeship vacant"}
                else:
                    if data["cause"] == "election":
                        elections = [
                            election
                            for election in self.trustee_election_records(
                                team, trust,
                            )
                            if election.data.get("process_uuid")
                            == data.get("process_uuid")
                        ]
                        if not elections:
                            return {"status": "deferred", "reason": "the trustee election record is not available"}
                        if len(elections) != 1:
                            return {"status": "invalid", "reason": "the process is named by competing election records"}
                        election = elections[0]
                        if not self._election_target_predecessor_is_valid(
                            team, election, previous,
                        ):
                            return {"status": "unauthorized", "reason": "the election targets an obsolete trusteeship state"}
                        checked = self._validated_election_result(
                            team,
                            election,
                            str(data.get("process_result_hash") or ""),
                        )
                        if not checked.get("valid"):
                            deferred = checked.get("status") in {
                                "unavailable", "incomplete",
                            }
                            return {
                                "status": "deferred" if deferred else "invalid",
                                "reason": checked.get("reason") or "the election result is invalid",
                            }
                        result = checked["result"]
                        if (
                            result.get("terminal_outcome") != "elected"
                            or result.get("selected_candidate_uuid")
                            != data.get("holder_actor_uuid")
                        ):
                            return {"status": "invalid", "reason": "the trustee state does not implement the election result"}
                    facilitator = "trust" if trust == "identity" else "identity"
                    status, reason = self._trust_authority(
                        team, facilitator, actor_uuid, data["authority_basis_uuid"],
                    )
                    if status != "authorized":
                        return {"status": status, "reason": reason}
        elif node_type == "team_member_opening":
            member = self.member_role(team)
            if member is None or data["member_role_uuid"] != member.uuid:
                return {"status": "invalid", "reason": "opening does not name the system Member role"}
            if data["state"] == "closed":
                previous = self._governance_node(
                    team, data["previous_opening_uuid"],
                    "team_member_opening",
                )
                if previous is None:
                    return {"status": "deferred", "reason": "previous Member opening is not available"}
                if (
                    previous.data.get("state") != "open"
                    or previous.data.get("member_role_uuid") != member.uuid
                ):
                    return {"status": "invalid", "reason": "opening closure does not match an open Member opening"}
            status, reason = self._trust_authority(
                team, "identity", actor_uuid, data["authority_basis_uuid"],
            )
            if status != "authorized":
                return {"status": status, "reason": reason}
        elif node_type == "team_member_application":
            opening = self._governance_node(
                team, data["opening_uuid"], "team_member_opening",
            )
            if opening is None:
                return {"status": "deferred", "reason": "Member opening is not available"}
            if data["state"] == "submitted":
                projection = self.member_opening_projection(
                    team, opening.uuid,
                )
                if projection.get("state") != "open":
                    return {"status": "unauthorized", "reason": "Member opening is closed or contested"}
            else:
                previous = self._governance_node(
                    team, data["previous_application_uuid"],
                    "team_member_application",
                )
                if previous is None:
                    return {"status": "deferred", "reason": "previous application is not available"}
                if (
                    previous.data.get("actor_uuid") != actor_uuid
                    or previous.data.get("opening_uuid") != opening.uuid
                    or previous.data.get("state") != "submitted"
                ):
                    return {"status": "invalid", "reason": "withdrawal does not match the submitted application"}
                if self.member_resolution_projection(
                    team, previous.uuid,
                )["state"] != "pending":
                    return {"status": "unauthorized", "reason": "a resolved application cannot be withdrawn"}
        elif node_type == "team_member_resolution":
            opening = self._governance_node(
                team, data["opening_uuid"], "team_member_opening",
            )
            application = self._governance_node(
                team, data["application_uuid"], "team_member_application",
            )
            if opening is None or application is None:
                return {"status": "deferred", "reason": "application prerequisites are not available"}
            if (
                application.data.get("opening_uuid") != opening.uuid
                or application.data.get("actor_uuid") != data["actor_uuid"]
            ):
                return {"status": "invalid", "reason": "resolution does not match its application"}
            application_state = self.member_application_projection(
                team, application.uuid,
            )["state"]
            if application_state != "submitted":
                return {"status": "unauthorized", "reason": "only a pending application can be resolved"}
            status, reason = self._trust_authority(
                team, "identity", actor_uuid, data["authority_basis_uuid"],
            )
            if status != "authorized":
                return {"status": status, "reason": reason}
        elif node_type == "team_external_member_resolution":
            opening = self._governance_node(
                team, data["opening_uuid"], "team_member_opening",
            )
            if opening is None or opening.data.get("previous_opening_uuid"):
                return {"status": "deferred", "reason": "Member opening is not available"}
            if not all((
                data.get("pool_uuid"), data.get("pool_invitation_uuid"),
                data.get("pool_application_uuid"), data.get("actor_uuid"),
                data.get("application_evidence_hash"),
            )):
                return {"status": "invalid", "reason": "external application evidence is incomplete"}
            status, reason = self._trust_authority(
                team, "identity", actor_uuid, data["authority_basis_uuid"],
            )
            if status != "authorized":
                return {"status": status, "reason": reason}
        elif node_type == "team_trustee_election":
            if not self._is_current_member(team, actor_uuid):
                return {"status": "unauthorized", "reason": "only a current Member may trigger an election"}
            if data.get("process_definition_id") != "integrative-election":
                return {"status": "invalid", "reason": "trustee elections require Integrative Election"}
            target = self._governance_node(
                team, data["target_state_uuid"], "team_trustee_state",
            )
            if target is None:
                return {"status": "deferred", "reason": "the election trusteeship snapshots are not available"}
            target_projection = self.trustee_projection(team, data["trust"])
            if (
                target.data.get("trust") != data["trust"]
                or target_projection.get("current_state_uuid") != target.uuid
            ):
                return {"status": "unauthorized", "reason": "the target trusteeship snapshot is stale"}
            status, reason = self._trust_authority(
                team,
                data["facilitator_trust"],
                data["facilitator_actor_uuid"],
                data["facilitator_authority_basis_uuid"],
            )
            if status != "authorized":
                return {"status": status, "reason": reason}
            if actor_uuid not in data["electorate_actor_uuids"]:
                return {"status": "invalid", "reason": "the triggering Member is absent from the electorate"}
            if set(data["electorate_actor_uuids"]) != set(
                self.current_member_uuids(team),
            ):
                return {"status": "unauthorized", "reason": "the electorate does not snapshot current Members"}
        elif node_type == "team_trustee_candidacy":
            vacancy = self._governance_node(
                team, data["vacant_state_uuid"], "team_trustee_state",
            )
            projection = self.trustee_projection(team, data["trust"])
            if vacancy is None:
                return {"status": "deferred", "reason": "vacant trustee state is not available"}
            if (
                projection.get("state") != "vacant"
                or projection.get("current_state_uuid") != vacancy.uuid
                or vacancy.data.get("trust") != data["trust"]
            ):
                return {"status": "unauthorized", "reason": "trusteeship is not currently vacant"}
            if data["state"] == "withdrawn":
                previous = self._governance_node(
                    team,
                    data["previous_candidacy_uuid"],
                    "team_trustee_candidacy",
                )
                if previous is None:
                    return {"status": "deferred", "reason": "previous candidacy is not available"}
                root = next((
                    candidate
                    for candidate in self.trustee_candidacy_roots(
                        team, data["trust"],
                    )
                    if candidate.uuid == previous.uuid
                    or self.trustee_candidacy_projection(
                        team, candidate.uuid,
                    ).get("current_uuid") == previous.uuid
                ), None)
                if (
                    root is None
                    or root.data.get("actor_uuid") != actor_uuid
                    or root.data.get("vacant_state_uuid")
                    != data["vacant_state_uuid"]
                    or self.trustee_candidacy_projection(
                        team, root.uuid,
                    ).get("current_uuid") != previous.uuid
                    or previous.data.get("state") != "active"
                ):
                    return {"status": "invalid", "reason": "withdrawal does not match the active candidacy"}
            elif any(
                candidate.data.get("actor_uuid") == actor_uuid
                and candidate.data.get("vacant_state_uuid") == vacancy.uuid
                and self.trustee_candidacy_projection(
                    team, candidate.uuid,
                ).get("state") == "active"
                for candidate in self.trustee_candidacy_roots(
                    team, data["trust"],
                )
            ):
                return {"status": "unauthorized", "reason": "the Actor is already a candidate"}
            if not self._is_current_member(team, actor_uuid):
                return {"status": "unauthorized", "reason": "only a current Member may become a candidate"}
        elif node_type == "team_trustee_action":
            status, reason = self._trust_authority(
                team, data["trust"], actor_uuid, data["authority_basis_uuid"],
            )
            if status != "authorized":
                return {"status": status, "reason": reason}
        elif node_type == "team_trustee_reality":
            action = self._governance_node(
                team, data["action_uuid"], "team_trustee_action",
            )
            if action is None:
                return {"status": "deferred", "reason": "observed trustee action is not available"}
            facilitator = "trust" if action.data.get("trust") == "identity" else "identity"
            status, reason = self._trust_authority(
                team, facilitator, actor_uuid, data["authority_basis_uuid"],
            )
            if status != "authorized":
                return {"status": status, "reason": reason}
        return {"status": "authorized", "reason": ""}

    def append_governance_record(
        self, team_uuid: str, data: dict,
    ) -> SessionResult:
        team = self._node(team_uuid, "team")
        if not team:
            return SessionResult("error", reason="team not found")
        allowed = self._interaction_guard(team)
        if allowed.status != "ok":
            return allowed
        candidate = ProtocolNode(
            copy.deepcopy(data), parent_uuid=team.uuid,
            revision_origin=self.session.identity.data["identity_key"],
        )
        assessment = self.assess_governance_record(
            team, candidate, verification="valid",
        )
        if assessment["status"] != "authorized":
            return SessionResult("error", reason=assessment["reason"])
        return self.session.create_child(team.uuid, data, {})

    def open_member_opening(self, team_uuid: str) -> SessionResult:
        team = self._node(team_uuid, "team")
        if not team:
            return SessionResult("error", reason="team not found")
        member = self.member_role(team)
        if member is None:
            return SessionResult("error", reason="Member role not found")
        authority_basis_uuid = self._authority_basis_for_actor(
            team, "identity", self._identity_uuid,
        )
        return self.append_governance_record(team.uuid, {
            "type": "team_member_opening",
            "member_role_uuid": member.uuid,
            "previous_opening_uuid": "",
            "state": "open",
            "opened_by": self._identity_uuid,
            "opened_at": self._now(),
            "authority_basis_uuid": authority_basis_uuid,
        })

    def close_member_opening(
        self, team_uuid: str, opening_uuid: str,
    ) -> SessionResult:
        team = self._node(team_uuid, "team")
        opening = self._governance_node(
            team, opening_uuid, "team_member_opening",
        ) if team else None
        if not team or not opening or opening.data.get("previous_opening_uuid"):
            return SessionResult("error", reason="Member opening not found")
        projection = self.member_opening_projection(team, opening.uuid)
        if projection["state"] != "open":
            return SessionResult("error", reason="Member opening is not open")
        authority_basis_uuid = self._authority_basis_for_actor(
            team, "identity", self._identity_uuid,
        )
        now = self._now()
        return self.append_governance_record(team.uuid, {
            "type": "team_member_opening",
            "member_role_uuid": opening.data["member_role_uuid"],
            "previous_opening_uuid": projection["current_uuid"],
            "state": "closed",
            "opened_by": self._identity_uuid,
            "opened_at": opening.data["opened_at"],
            "authority_basis_uuid": authority_basis_uuid,
            "closed_at": now,
        })

    def submit_member_application(
        self, team_uuid: str, opening_uuid: str,
    ) -> SessionResult:
        team = self._node(team_uuid, "team")
        opening = self._governance_node(
            team, opening_uuid, "team_member_opening",
        ) if team else None
        if not team or not opening or opening.data.get("previous_opening_uuid"):
            return SessionResult("error", reason="Member opening not found")
        if self._is_current_member(team, self._identity_uuid):
            return SessionResult("error", reason="you are already a Member")
        for application in self.member_application_roots(team, opening.uuid):
            if application.data.get("actor_uuid") != self._identity_uuid:
                continue
            if (
                self.member_application_projection(
                    team, application.uuid,
                )["state"] == "submitted"
                and self.member_resolution_projection(
                    team, application.uuid,
                )["state"] == "pending"
            ):
                return SessionResult("error", reason="you already have a pending application")
        return self.append_governance_record(team.uuid, {
            "type": "team_member_application",
            "opening_uuid": opening.uuid,
            "previous_application_uuid": "",
            "actor_uuid": self._identity_uuid,
            "submitted_at": self._now(),
            "state": "submitted",
        })

    def withdraw_member_application(
        self, team_uuid: str, application_uuid: str,
    ) -> SessionResult:
        team = self._node(team_uuid, "team")
        application = self._governance_node(
            team, application_uuid, "team_member_application",
        ) if team else None
        if (
            not team or not application
            or application.data.get("previous_application_uuid")
            or application.data.get("actor_uuid") != self._identity_uuid
        ):
            return SessionResult("error", reason="Member application not found")
        projection = self.member_application_projection(
            team, application.uuid,
        )
        if projection["state"] != "submitted":
            return SessionResult("error", reason="application is not pending")
        return self.append_governance_record(team.uuid, {
            "type": "team_member_application",
            "opening_uuid": application.data["opening_uuid"],
            "previous_application_uuid": projection["current_uuid"],
            "actor_uuid": self._identity_uuid,
            "submitted_at": application.data["submitted_at"],
            "state": "withdrawn",
            "withdrawn_at": self._now(),
        })

    def resolve_member_application(
        self, team_uuid: str, application_uuid: str, outcome: str,
        signals: str = "", consideration: str = "", expectation: str = "",
    ) -> SessionResult:
        team = self._node(team_uuid, "team")
        application = self._governance_node(
            team, application_uuid, "team_member_application",
        ) if team else None
        normalized = str(outcome or "").strip().lower()
        if not team or not application or application.data.get(
            "previous_application_uuid",
        ):
            return SessionResult("error", reason="Member application not found")
        if normalized not in {"accepted", "rejected"}:
            return SessionResult("error", reason="outcome must be accepted or rejected")
        if self.member_application_projection(
            team, application.uuid,
        )["state"] != "submitted":
            return SessionResult("error", reason="application is no longer pending")
        if self.member_resolution_projection(
            team, application.uuid,
        )["state"] != "pending":
            return SessionResult("error", reason="application is already resolved")
        authority_basis_uuid = self._authority_basis_for_actor(
            team, "identity", self._identity_uuid,
        )
        return self.append_governance_record(team.uuid, {
            "type": "team_member_resolution",
            "opening_uuid": application.data["opening_uuid"],
            "application_uuid": application.uuid,
            "actor_uuid": application.data["actor_uuid"],
            "outcome": normalized,
            "resolved_by": self._identity_uuid,
            "resolved_at": self._now(),
            "authority_basis_uuid": authority_basis_uuid,
            "signals": str(signals or "").strip(),
            "consideration": str(consideration or "").strip(),
            "expectation": str(expectation or "").strip(),
        })

    def record_trustee_action(
        self,
        team_uuid: str,
        trust: str,
        subject_uuid: str,
        payload: dict | None = None,
        signals: str = "",
        consideration: str = "",
        expectation: str = "",
        action_kind: str = "domain_action",
    ) -> SessionResult:
        team = self._node(team_uuid, "team")
        normalized_trust = str(trust or "").strip().lower()
        normalized_kind = str(action_kind or "").strip()
        normalized_subject = str(subject_uuid or "").strip()
        if not team:
            return SessionResult("error", reason="team not found")
        if normalized_trust not in self.TRUSTS:
            return SessionResult("error", reason="unknown trusteeship")
        if normalized_kind not in self.ACTION_KINDS:
            return SessionResult("error", reason="unsupported trustee action kind")
        if not normalized_subject:
            return SessionResult("error", reason="action subject is required")
        if payload is not None and not isinstance(payload, dict):
            return SessionResult("error", reason="action payload must be an object")
        basis_uuid = self._authority_basis_for_actor(
            team, normalized_trust, self._identity_uuid,
        )
        return self.append_governance_record(team.uuid, {
            "type": "team_trustee_action",
            "trust": normalized_trust,
            "action_kind": normalized_kind,
            "subject_uuid": normalized_subject,
            "acted_by": self._identity_uuid,
            "acted_at": self._now(),
            "authority_basis_uuid": basis_uuid,
            "signals": str(signals or "").strip(),
            "consideration": str(consideration or "").strip(),
            "expectation": str(expectation or "").strip(),
            "payload": copy.deepcopy(payload or {}),
        })

    def append_trustee_reality(
        self, team_uuid: str, action_uuid: str, reality: str,
    ) -> SessionResult:
        team = self._node(team_uuid, "team")
        action = self._governance_node(
            team, action_uuid, "team_trustee_action",
        ) if team else None
        normalized_reality = str(reality or "").strip()
        if not team or not action:
            return SessionResult("error", reason="trustee action not found")
        if not normalized_reality:
            return SessionResult("error", reason="Reality is required")
        facilitator_trust = (
            "trust" if action.data.get("trust") == "identity" else "identity"
        )
        basis_uuid = self._authority_basis_for_actor(
            team, facilitator_trust, self._identity_uuid,
        )
        return self.append_governance_record(team.uuid, {
            "type": "team_trustee_reality",
            "action_uuid": action.uuid,
            "observed_by": self._identity_uuid,
            "observed_at": self._now(),
            "reality": normalized_reality,
            "authority_basis_uuid": basis_uuid,
        })

    def trustee_actions_payload(self, team: ProtocolNode) -> list[dict]:
        people = self._known_people()
        actions = self.governance_records(team, "team_trustee_action")
        realities = self.governance_records(team, "team_trustee_reality")
        groups: dict[tuple[str, str, str], list[ProtocolNode]] = {}
        for action in actions:
            key = (
                str(action.data.get("trust") or ""),
                str(action.data.get("action_kind") or ""),
                str(action.data.get("subject_uuid") or ""),
            )
            groups.setdefault(key, []).append(action)
        payload = []
        for action in actions:
            actor_uuid = str(action.data.get("acted_by") or "")
            actor = people.get(actor_uuid) or {}
            key = (
                str(action.data.get("trust") or ""),
                str(action.data.get("action_kind") or ""),
                str(action.data.get("subject_uuid") or ""),
            )
            facilitator_trust = (
                "trust" if key[0] == "identity" else "identity"
            )
            observations = []
            for observation in realities:
                if observation.data.get("action_uuid") != action.uuid:
                    continue
                observer_uuid = str(observation.data.get("observed_by") or "")
                observer = people.get(observer_uuid) or {}
                observations.append({
                    "uuid": observation.uuid,
                    "reality": observation.data.get("reality") or "",
                    "observed_at": observation.data.get("observed_at"),
                    "observed_by": observer_uuid,
                    "observer_name": observer.get("name") or "Trustee",
                })
            signals = str(action.data.get("signals") or "")
            payload.append({
                "uuid": action.uuid,
                "trust": key[0],
                "action_kind": key[1],
                "subject_uuid": key[2],
                "acted_by": actor_uuid,
                "actor_name": actor.get("name") or "Trustee",
                "acted_at": action.data.get("acted_at"),
                "signals": signals,
                "signals_missing": not bool(signals.strip()),
                "consideration": action.data.get("consideration") or "",
                "expectation": action.data.get("expectation") or "",
                "payload": copy.deepcopy(action.data.get("payload") or {}),
                "contested": len(groups[key]) > 1,
                "peer_action_uuids": [
                    peer.uuid for peer in groups[key] if peer.uuid != action.uuid
                ],
                "realities": observations,
                "can_observe": bool(self._authority_basis_for_actor(
                    team, facilitator_trust, self._identity_uuid,
                )),
            })
        return payload

    def _pool_node(self, pool_uuid: str | None) -> ProtocolNode | None:
        if not pool_uuid:
            return None
        node = self.session.protocol.index.get(pool_uuid)
        container = self._find_team_container()
        return node if (
            node
            and node.data.get("type") == "team_pool"
            and container
            and node.parent_uuid == container.uuid
        ) else None

    def pool_records(
        self, pool: ProtocolNode, node_type: str | None = None,
    ) -> list[ProtocolNode]:
        return sorted(
            [
                child for child in pool.live_children()
                if child.data.get("type") in self.POOL_RECORD_TYPES
                and (node_type is None or child.data.get("type") == node_type)
            ],
            key=lambda node: (node.created_at, node.uuid),
        )

    def pool_application_projection(
        self, pool: ProtocolNode, application_uuid: str,
    ) -> dict:
        records = self.pool_records(pool, "team_pool_application")
        by_uuid = {record.uuid: record for record in records}
        root = by_uuid.get(application_uuid)
        blank = {
            "root_uuid": application_uuid, "current_uuid": "",
            "state": "missing", "contenders": [],
        }
        if root is None or root.data.get("previous_application_uuid"):
            return blank
        by_previous: dict[str, list[ProtocolNode]] = {}
        for record in records:
            previous = str(record.data.get("previous_application_uuid") or "")
            if previous:
                by_previous.setdefault(previous, []).append(record)
        current = root
        seen = {root.uuid}
        while True:
            successors = [
                record for record in by_previous.get(current.uuid, [])
                if record.uuid not in seen
            ]
            if not successors:
                return {
                    **blank, "current_uuid": current.uuid,
                    "state": str(current.data.get("state") or ""),
                }
            if len(successors) > 1:
                return {
                    **blank, "current_uuid": current.uuid,
                    "state": "contested",
                    "contenders": [record.uuid for record in successors],
                }
            current = successors[0]
            seen.add(current.uuid)

    def pool_application_roots(
        self, pool: ProtocolNode, invitation_uuid: str | None = None,
    ) -> list[ProtocolNode]:
        return [
            record for record in self.pool_records(
                pool, "team_pool_application",
            )
            if not record.data.get("previous_application_uuid")
            and (
                invitation_uuid is None
                or record.data.get("invitation_uuid") == invitation_uuid
            )
        ]

    def pool_resolution_for(
        self, pool: ProtocolNode, application_uuid: str,
    ) -> list[ProtocolNode]:
        return [
            record for record in self.pool_records(
                pool, "team_pool_resolution",
            )
            if record.data.get("application_uuid") == application_uuid
        ]

    @staticmethod
    def _timestamp(value: str) -> datetime | None:
        normalized = TeamLogic._normalize_expiry(value)
        return (
            datetime.fromisoformat(normalized.replace("Z", "+00:00"))
            if normalized else None
        )

    def assess_pool_record(
        self, pool: ProtocolNode, node: ProtocolNode,
        verification: str | None = None,
    ) -> dict:
        verification = verification or self.session.revision_verification(node)
        if verification == "unknown":
            return {"status": "deferred", "reason": "the signing key is not known"}
        if verification != "valid":
            return {"status": "invalid", "reason": "authorship signature is invalid"}
        schema_error = self.pool_schema_error(node)
        if schema_error:
            return {"status": "invalid", "reason": schema_error}
        if node.parent_uuid != pool.uuid:
            return {"status": "invalid", "reason": "Pool records must be direct children"}
        data = node.data
        actor_field = {
            "team_pool_invitation": "published_by",
            "team_pool_application": "actor_uuid",
            "team_pool_resolution": "resolved_by",
        }[data["type"]]
        actor_uuid = str(data.get(actor_field) or "")
        status, reason = self._signed_actor_status(node, actor_uuid)
        if status != "authorized":
            return {"status": status, "reason": reason}
        if data.get("team_uuid") != pool.data.get("team_uuid"):
            return {"status": "invalid", "reason": "record names another Team"}

        team = self._node(str(pool.data.get("team_uuid") or ""), "team")
        if data["type"] == "team_pool_invitation":
            published = self._timestamp(data["published_at"])
            expires = self._timestamp(data["expires_at"])
            if not published or not expires or expires <= published:
                return {"status": "invalid", "reason": "invitation expiry is invalid"}
            if data.get("team_title") != pool.data.get("team_title"):
                return {"status": "invalid", "reason": "invitation Team title does not match the Pool"}
            if team:
                opening = self._governance_node(
                    team, data["opening_uuid"], "team_member_opening",
                )
                if opening is None:
                    return {"status": "deferred", "reason": "Member opening is not available"}
                status, reason = self._trust_authority(
                    team, "identity", actor_uuid,
                    data["authority_basis_uuid"],
                )
                if status != "authorized":
                    return {"status": status, "reason": reason}
        elif data["type"] == "team_pool_application":
            invitation = next((
                record for record in self.pool_records(
                    pool, "team_pool_invitation",
                )
                if record.uuid == data["invitation_uuid"]
            ), None)
            if invitation is None:
                return {"status": "deferred", "reason": "Pool invitation is not available"}
            if (
                data.get("opening_uuid") != invitation.data.get("opening_uuid")
                or data.get("team_uuid") != invitation.data.get("team_uuid")
            ):
                return {"status": "invalid", "reason": "application does not match its invitation"}
            submitted = self._timestamp(data["submitted_at"])
            published = self._timestamp(str(invitation.data.get("published_at") or ""))
            expires = self._timestamp(str(invitation.data.get("expires_at") or ""))
            if not submitted or not published or not expires or not (
                published <= submitted < expires
            ):
                return {"status": "unauthorized", "reason": "invitation was not active when the application was submitted"}
            if data["state"] == "withdrawn":
                previous = next((
                    record for record in self.pool_records(
                        pool, "team_pool_application",
                    )
                    if record.uuid == data["previous_application_uuid"]
                ), None)
                root = next((
                    record for record in self.pool_application_roots(pool)
                    if record.uuid == (previous.uuid if previous else "")
                ), None)
                if (
                    not previous or not root
                    or previous.data.get("actor_uuid") != actor_uuid
                    or previous.data.get("state") != "submitted"
                    or self.pool_application_projection(
                        pool, root.uuid,
                    ).get("current_uuid") != previous.uuid
                    or self.pool_resolution_for(pool, root.uuid)
                ):
                    return {"status": "unauthorized", "reason": "withdrawal does not match a pending application"}
            elif any(
                root.data.get("actor_uuid") == actor_uuid
                and root.data.get("invitation_uuid") == data["invitation_uuid"]
                and self.pool_application_projection(
                    pool, root.uuid,
                ).get("state") == "submitted"
                and not self.pool_resolution_for(pool, root.uuid)
                for root in self.pool_application_roots(pool)
            ):
                return {"status": "unauthorized", "reason": "the Actor already applied through this invitation"}
        else:
            application = next((
                record for record in self.pool_application_roots(pool)
                if record.uuid == data["application_uuid"]
            ), None)
            invitation = next((
                record for record in self.pool_records(
                    pool, "team_pool_invitation",
                )
                if record.uuid == data["invitation_uuid"]
            ), None)
            if application is None or invitation is None:
                return {"status": "deferred", "reason": "Pool application evidence is not available"}
            if (
                application.data.get("invitation_uuid") != invitation.uuid
                or application.data.get("actor_uuid") != data.get("actor_uuid")
                or application.data.get("opening_uuid") != data.get("opening_uuid")
                or invitation.data.get("published_by") != actor_uuid
            ):
                return {"status": "invalid", "reason": "resolution does not match its application or publisher"}
            if (
                self.pool_application_projection(
                    pool, application.uuid,
                ).get("state") != "submitted"
                or self.pool_resolution_for(pool, application.uuid)
            ):
                return {"status": "unauthorized", "reason": "application is no longer pending"}
            if team:
                status, reason = self._trust_authority(
                    team, "identity", actor_uuid,
                    data["authority_basis_uuid"],
                )
                if status != "authorized":
                    return {"status": status, "reason": reason}
        return {"status": "authorized", "reason": ""}

    def append_pool_record(
        self, pool_uuid: str, data: dict,
    ) -> SessionResult:
        pool = self._pool_node(pool_uuid)
        if not pool:
            return SessionResult("error", reason="Pool not found")
        candidate = ProtocolNode(
            copy.deepcopy(data), parent_uuid=pool.uuid,
            revision_origin=self.session.identity.data["identity_key"],
        )
        assessment = self.assess_pool_record(
            pool, candidate, verification="valid",
        )
        if assessment["status"] != "authorized":
            return SessionResult("error", reason=assessment["reason"])
        return self.session.create_child(pool.uuid, data, {})

    def publish_pool_invitation(
        self, team_uuid: str, opening_uuid: str, expires_at: str = "",
    ) -> SessionResult:
        team = self._node(team_uuid, "team")
        pool = self.pool_for_team(team) if team else None
        opening = self._governance_node(
            team, opening_uuid, "team_member_opening",
        ) if team else None
        if not team or not pool or not opening:
            return SessionResult("error", reason="Team Pool or Member opening not found")
        if self.member_opening_projection(
            team, opening.uuid,
        ).get("state") != "open":
            return SessionResult("error", reason="Member opening is not open")
        basis_uuid = self._authority_basis_for_actor(
            team, "identity", self._identity_uuid,
        )
        normalized_expiry = self._normalize_expiry(expires_at)
        if not normalized_expiry:
            normalized_expiry = (
                datetime.now(timezone.utc) + timedelta(days=7)
            ).isoformat().replace("+00:00", "Z")
        if self._is_expired(normalized_expiry):
            return SessionResult("error", reason="invitation expiry must be in the future")
        return self.append_pool_record(pool.uuid, {
            "type": "team_pool_invitation",
            "team_uuid": team.uuid,
            "team_title": str(team.data.get("title") or "Untitled team"),
            "opening_uuid": opening.uuid,
            "published_by": self._identity_uuid,
            "published_at": self._now(),
            "expires_at": normalized_expiry,
            "authority_basis_uuid": basis_uuid,
        })

    def submit_pool_application(
        self, pool_uuid: str, invitation_uuid: str,
    ) -> SessionResult:
        pool = self._pool_node(pool_uuid)
        invitation = next((
            record for record in self.pool_records(
                pool, "team_pool_invitation",
            )
            if record.uuid == invitation_uuid
        ), None) if pool else None
        if not pool or not invitation:
            return SessionResult("error", reason="active Pool invitation not found")
        if self._is_expired(str(invitation.data.get("expires_at") or "")):
            return SessionResult("error", reason="Pool invitation has expired")
        return self.append_pool_record(pool.uuid, {
            "type": "team_pool_application",
            "invitation_uuid": invitation.uuid,
            "team_uuid": invitation.data["team_uuid"],
            "opening_uuid": invitation.data["opening_uuid"],
            "actor_uuid": self._identity_uuid,
            "submitted_at": self._now(),
            "state": "submitted",
            "previous_application_uuid": "",
        })

    def withdraw_pool_application(
        self, pool_uuid: str, application_uuid: str,
    ) -> SessionResult:
        pool = self._pool_node(pool_uuid)
        application = next((
            record for record in self.pool_application_roots(pool)
            if record.uuid == application_uuid
        ), None) if pool else None
        if (
            not pool or not application
            or application.data.get("actor_uuid") != self._identity_uuid
        ):
            return SessionResult("error", reason="Pool application not found")
        projection = self.pool_application_projection(pool, application.uuid)
        if projection.get("state") != "submitted" or self.pool_resolution_for(
            pool, application.uuid,
        ):
            return SessionResult("error", reason="Pool application is not pending")
        return self.append_pool_record(pool.uuid, {
            **dict(application.data),
            "previous_application_uuid": str(projection["current_uuid"]),
            "state": "withdrawn",
            "withdrawn_at": self._now(),
        })

    def resolve_pool_application(
        self, pool_uuid: str, application_uuid: str, outcome: str,
        signals: str = "", consideration: str = "", expectation: str = "",
    ) -> SessionResult:
        pool = self._pool_node(pool_uuid)
        application = next((
            record for record in self.pool_application_roots(pool)
            if record.uuid == application_uuid
        ), None) if pool else None
        invitation = next((
            record for record in self.pool_records(
                pool, "team_pool_invitation",
            )
            if application and record.uuid == application.data.get("invitation_uuid")
        ), None) if pool else None
        normalized = str(outcome or "").strip().lower()
        if not pool or not application or not invitation:
            return SessionResult("error", reason="Pool application not found")
        if normalized not in {"accepted", "rejected"}:
            return SessionResult("error", reason="outcome must be accepted or rejected")
        if invitation.data.get("published_by") != self._identity_uuid:
            return SessionResult(
                "error", reason="only the Identity who published this invitation may resolve it",
            )
        if self.pool_application_projection(
            pool, application.uuid,
        ).get("state") != "submitted" or self.pool_resolution_for(
            pool, application.uuid,
        ):
            return SessionResult("error", reason="Pool application is not pending")
        team = self._node(str(pool.data.get("team_uuid") or ""), "team")
        if not team:
            return SessionResult("error", reason="linked Team is not available")
        basis_uuid = self._authority_basis_for_actor(
            team, "identity", self._identity_uuid,
        )
        token = None
        team_record = None
        if normalized == "accepted":
            compose = getattr(
                self.collaboration, "compose_topic_invitation", None,
            )
            if not callable(compose):
                return SessionResult("error", reason="Team invitation service is unavailable")
            coordinates = compose(team.uuid)
            if not getattr(coordinates, "ok", False):
                return SessionResult(
                    "error", reason=getattr(coordinates, "reason", "Team has no home channel"),
                )
            token = copy.deepcopy(coordinates.value)
            team_record = self.append_governance_record(team.uuid, {
                "type": "team_external_member_resolution",
                "pool_uuid": pool.uuid,
                "pool_invitation_uuid": invitation.uuid,
                "pool_application_uuid": application.uuid,
                "opening_uuid": application.data["opening_uuid"],
                "actor_uuid": application.data["actor_uuid"],
                "outcome": "accepted",
                "resolved_by": self._identity_uuid,
                "resolved_at": self._now(),
                "authority_basis_uuid": basis_uuid,
                "application_evidence_hash": application.state_hash,
                "signals": str(signals or "").strip(),
                "consideration": str(consideration or "").strip(),
                "expectation": str(expectation or "").strip(),
            })
            if team_record.status != "ok":
                return team_record
        data = {
            "type": "team_pool_resolution",
            "invitation_uuid": invitation.uuid,
            "application_uuid": application.uuid,
            "team_uuid": application.data["team_uuid"],
            "opening_uuid": application.data["opening_uuid"],
            "actor_uuid": application.data["actor_uuid"],
            "outcome": normalized,
            "resolved_by": self._identity_uuid,
            "resolved_at": self._now(),
            "authority_basis_uuid": basis_uuid,
            "signals": str(signals or "").strip(),
            "consideration": str(consideration or "").strip(),
            "expectation": str(expectation or "").strip(),
        }
        if token is not None:
            data["team_invitation_token"] = token
        resolved = self.append_pool_record(pool.uuid, data)
        if resolved.status == "ok" and team_record:
            resolved.effects = [*team_record.effects, *resolved.effects]
        return resolved

    def mount_accepted_team(
        self, pool_uuid: str, application_uuid: str,
    ) -> SessionResult:
        pool = self._pool_node(pool_uuid)
        application = next((
            record for record in self.pool_application_roots(pool)
            if record.uuid == application_uuid
        ), None) if pool else None
        resolutions = self.pool_resolution_for(
            pool, application_uuid,
        ) if pool else []
        resolution = resolutions[0] if len(resolutions) == 1 else None
        if (
            not pool or not application or not resolution
            or application.data.get("actor_uuid") != self._identity_uuid
            or resolution.data.get("actor_uuid") != self._identity_uuid
            or resolution.data.get("outcome") != "accepted"
        ):
            return SessionResult("error", reason="accepted Pool application not found")
        token = resolution.data.get("team_invitation_token")
        accept = getattr(
            self.collaboration, "accept_topic_invitation_token", None,
        )
        if not isinstance(token, dict) or not callable(accept):
            return SessionResult("error", reason="Team coordinates are unavailable")
        mounted = accept(copy.deepcopy(token))
        if not getattr(mounted, "ok", False):
            return SessionResult(
                "error", reason=getattr(mounted, "reason", "Team connection failed"),
            )
        return SessionResult("ok", value=copy.deepcopy(mounted.value))

    def pool_payload(self, pool: ProtocolNode) -> dict:
        people = self._known_people()
        team = self._node(str(pool.data.get("team_uuid") or ""), "team")
        invitations = []
        for invitation in self.pool_records(pool, "team_pool_invitation"):
            applications = []
            for application in self.pool_application_roots(
                pool, invitation.uuid,
            ):
                actor_uuid = str(application.data.get("actor_uuid") or "")
                person = people.get(actor_uuid) or {}
                projection = self.pool_application_projection(
                    pool, application.uuid,
                )
                resolutions = self.pool_resolution_for(
                    pool, application.uuid,
                )
                resolution = resolutions[0] if len(resolutions) == 1 else None
                applications.append({
                    "uuid": application.uuid,
                    "actor_uuid": actor_uuid,
                    "actor_name": person.get("name") or person.get("address") or "Applicant",
                    "picture": person.get("picture") or "",
                    "is_self": actor_uuid == self._identity_uuid,
                    "state": projection.get("state"),
                    "submitted_at": application.data.get("submitted_at"),
                    "resolution": (
                        resolution.data.get("outcome") if resolution
                        else ("contested" if len(resolutions) > 1 else "pending")
                    ),
                    "resolved_at": resolution.data.get("resolved_at") if resolution else None,
                    "can_withdraw": bool(
                        actor_uuid == self._identity_uuid
                        and projection.get("state") == "submitted"
                        and not resolutions
                    ),
                    "can_resolve": bool(
                        team
                        and invitation.data.get("published_by") == self._identity_uuid
                        and self._authority_basis_for_actor(
                            team, "identity", self._identity_uuid,
                        )
                        and projection.get("state") == "submitted"
                        and not resolutions
                    ),
                    "can_mount": bool(
                        resolution
                        and resolution.data.get("outcome") == "accepted"
                        and actor_uuid == self._identity_uuid
                        and isinstance(
                            resolution.data.get("team_invitation_token"), dict,
                        )
                        and not team
                    ),
                })
            expired = self._is_expired(
                str(invitation.data.get("expires_at") or ""),
            )
            own_pending = any(
                application["is_self"]
                and application["state"] == "submitted"
                and application["resolution"] == "pending"
                for application in applications
            )
            invitations.append({
                "uuid": invitation.uuid,
                "team_uuid": invitation.data.get("team_uuid"),
                "team_title": invitation.data.get("team_title"),
                "opening_uuid": invitation.data.get("opening_uuid"),
                "published_by": invitation.data.get("published_by"),
                "published_at": invitation.data.get("published_at"),
                "expires_at": invitation.data.get("expires_at"),
                "expired": expired,
                "active": not expired,
                "can_apply": bool(
                    not expired
                    and not own_pending
                    and not (team and self._is_current_member(
                        team, self._identity_uuid,
                    ))
                ),
                "applications": applications,
            })
        return {
            "uuid": pool.uuid,
            "team_uuid": pool.data.get("team_uuid"),
            "team_title": pool.data.get("team_title"),
            "created_at": pool.data.get("created_at"),
            "active_invitations": [
                invitation for invitation in invitations if invitation["active"]
            ],
            "history": invitations,
            "can_publish": bool(
                team and self._authority_basis_for_actor(
                    team, "identity", self._identity_uuid,
                )
            ),
            "publishable_openings": (
                [
                    {
                        "uuid": opening.uuid,
                        "opened_at": opening.data.get("opened_at"),
                    }
                    for opening in self.member_opening_roots(team)
                    if self.member_opening_projection(
                        team, opening.uuid,
                    ).get("state") == "open"
                ] if team else []
            ),
            "linked_team_present": bool(team),
        }

    def governance_attempts(self, team: ProtocolNode) -> list[dict]:
        attempts = []
        for address in self.session.peer_addresses(team.uuid):
            for event in self.session.analyze_peer_transitions(address, team.uuid):
                if event.get("type") == "in_agreement":
                    continue
                node = self.session.get_cached_peer_subtree(
                    address, event.get("node_uuid"),
                )
                if not node or node.data.get("type") not in self.GOVERNANCE_RECORD_TYPES:
                    continue
                assessment = self.assess_governance_record(team, node)
                if assessment["status"] == "authorized" and event.get("type") == "local_missing_node":
                    continue
                reason = assessment["reason"]
                if event.get("type") != "local_missing_node" and assessment["status"] == "authorized":
                    reason = "governance records are append-only and cannot be changed"
                attempts.append({
                    "peer_addr": address,
                    "node_uuid": node.uuid,
                    "record_type": node.data.get("type"),
                    "status": assessment["status"],
                    "reason": reason,
                })
        return sorted(attempts, key=lambda item: (
            item["record_type"], item["node_uuid"], item["peer_addr"],
        ))

    def accountabilities(self, role: ProtocolNode) -> list[ProtocolNode]:
        return self._ordered(role, "team_accountability")

    def domains(self, role: ProtocolNode) -> list[ProtocolNode]:
        return self._ordered(role, "team_domain")

    def create_role(self, team_uuid: str, name: str) -> SessionResult:
        team = self._node(team_uuid, "team")
        if not team:
            return SessionResult("error", reason="team not found")
        allowed = self._interaction_guard(team)
        if allowed.status != "ok":
            return allowed
        normalized = str(name or "").strip()
        if not normalized:
            return SessionResult("error", reason="role name is required")
        normalized = self._distinct_name(
            normalized,
            [role.data.get("name") for role in self.roles(team)],
        )
        result = self.session.create_child(
            team.uuid,
            {
                "type": "team_role",
                "name": normalized,
                "purpose": "",
                "order": self.session.next_child_order(
                    team.uuid, "team_role",
                ),
            },
            {},
        )
        if result.status == "ok":
            return SessionResult(
                "ok", value=result.value.uuid, effects=result.effects,
            )
        return result

    def rename_role(self, role_uuid: str, name: str) -> SessionResult:
        return self._retitle(
            role_uuid, "team_role", "name", name, distinct=True,
        )

    def set_role_purpose(self, role_uuid: str, purpose: str) -> SessionResult:
        # A purpose may be cleared. Unlike the name it does not identify the
        # role, so _retitle's "required" rule would be wrong here.
        role = self._node(role_uuid, "team_role")
        if not role:
            return SessionResult("error", reason="role not found")
        allowed = self._interaction_guard_for_node(role.uuid)
        if allowed.status != "ok":
            return allowed
        data = dict(role.data)
        data["purpose"] = str(purpose or "").strip()
        return self.session.modify(role.uuid, data, role.weights)

    def delete_role(self, role_uuid: str) -> SessionResult:
        role = self._node(role_uuid, "team_role")
        if not role:
            return SessionResult("error", reason="role not found")
        allowed = self._interaction_guard_for_node(role.uuid)
        if allowed.status != "ok":
            return allowed
        return self.session.delete(role.uuid)

    def move_role(self, role_uuid: str, index: int) -> SessionResult:
        if not self._node(role_uuid, "team_role"):
            return SessionResult("error", reason="role not found")
        allowed = self._interaction_guard_for_node(role_uuid)
        if allowed.status != "ok":
            return allowed
        return self.session.move_child_to_index(role_uuid, index)

    def create_role_item(
        self, role_uuid: str, kind: str, text: str,
    ) -> SessionResult:
        node_type = self.ROLE_ITEM_TYPES.get(str(kind or "").strip())
        if not node_type:
            return SessionResult(
                "error", reason="kind must be accountability or domain",
            )
        role = self._node(role_uuid, "team_role")
        if not role:
            return SessionResult("error", reason="role not found")
        allowed = self._interaction_guard_for_node(role.uuid)
        if allowed.status != "ok":
            return allowed
        normalized = str(text or "").strip()
        if not normalized:
            return SessionResult("error", reason=f"{kind} text is required")
        result = self.session.create_child(
            role.uuid,
            {
                "type": node_type,
                "text": normalized,
                "order": self.session.next_child_order(role.uuid, node_type),
            },
            {},
        )
        if result.status == "ok":
            return SessionResult(
                "ok", value=result.value.uuid, effects=result.effects,
            )
        return result

    def update_role_item(self, item_uuid: str, text: str) -> SessionResult:
        item = self._role_item(item_uuid)
        if not item:
            return SessionResult("error", reason="role item not found")
        allowed = self._interaction_guard_for_node(item.uuid)
        if allowed.status != "ok":
            return allowed
        normalized = str(text or "").strip()
        if not normalized:
            return SessionResult("error", reason="text is required")
        data = dict(item.data)
        data["text"] = normalized
        return self.session.modify(item.uuid, data, item.weights)

    def delete_role_item(self, item_uuid: str) -> SessionResult:
        item = self._role_item(item_uuid)
        if not item:
            return SessionResult("error", reason="role item not found")
        allowed = self._interaction_guard_for_node(item.uuid)
        if allowed.status != "ok":
            return allowed
        return self.session.delete(item.uuid)

    def move_role_item(self, item_uuid: str, index: int) -> SessionResult:
        if not self._role_item(item_uuid):
            return SessionResult("error", reason="role item not found")
        allowed = self._interaction_guard_for_node(item_uuid)
        if allowed.status != "ok":
            return allowed
        return self.session.move_child_to_index(item_uuid, index)

    # Holding a role is two records with two authors. The Identity holder
    # writes the offer; the actor writes their own decision. A holding is
    # live only while both are present, which is what lets either side end
    # it alone: revoking deletes the offer, resigning deletes the decision,
    # and neither party can touch the other's node.
    #
    # They are siblings under the role rather than nested, because deleting
    # a container prunes its descendants - nesting the decision under the
    # offer would make revocation delete the actor's own record.
    #
    # An offer is per (role, actor), not per role: a role may be held by
    # several actors, and revoking one must not revoke the rest.

    def role_offers(self, role: ProtocolNode) -> list[ProtocolNode]:
        """Offers that still stand. A revoked one is kept but is not an offer."""
        return [
            offer for offer in self._all_role_offers(role)
            if not offer.data.get("revoked_at")
        ]

    @staticmethod
    def _all_role_offers(role: ProtocolNode) -> list[ProtocolNode]:
        return [
            child for child in role.live_children()
            if child.data.get("type") == "team_role_offer"
        ]

    def offer_role(self, role_uuid: str, actor_uuid: str) -> SessionResult:
        role = self._node(role_uuid, "team_role")
        if not role:
            return SessionResult("error", reason="role not found")
        team = self._local_team_topic(role.uuid)
        allowed = self._interaction_guard(team)
        if allowed.status != "ok":
            return allowed
        if role.data.get("system_key") == self.MEMBER_ROLE_SYSTEM_KEY:
            return SessionResult(
                "error",
                reason="Members join through an opening and application",
            )
        if not self.holds_identity(team):
            return SessionResult(
                "error", reason="only the Identity holder can offer a role",
            )
        normalized = str(actor_uuid or "").strip()
        if not normalized:
            return SessionResult("error", reason="an actor is required")
        if self._offer_for(role, normalized):
            return SessionResult(
                "error", reason="that actor has already been offered this role",
            )
        data = {
            "type": "team_role_offer",
            "actor_uuid": normalized,
            # A team can be offered a seat as readily as a person.
            "actor_kind": (
                "team"
                if self._node(normalized, "team") else "individual"
            ),
            "offered_by": self._identity_uuid,
            "offered_at": self._now(),
            "revoked_at": None,
        }
        # Offering again after a revocation revives the same record rather
        # than laying a second one beside it.
        if withdrawn := self._offer_for(role, normalized, revoked=True):
            return self.session.modify(
                withdrawn.uuid, data, withdrawn.weights,
            )
        return self.session.create_child(role.uuid, data, {})

    def revoke_role_offer(
        self, role_uuid: str, actor_uuid: str,
    ) -> SessionResult:
        """Withdraw an offer. The actor's own decision is theirs and stays.

        The offer is marked rather than deleted. Deleting it would leave the
        actor's surviving answer indistinguishable from somebody asking for
        the role unprompted, so the Identity holder would immediately be
        asked to re-offer what they had just withdrawn. Marking is still a
        withdrawal of what Identity itself wrote, so the authorship rule
        holds; it just keeps the fact that there was an offer.
        """
        role = self._node(role_uuid, "team_role")
        if not role:
            return SessionResult("error", reason="role not found")
        team = self._local_team_topic(role.uuid)
        allowed = self._interaction_guard(team)
        if allowed.status != "ok":
            return allowed
        if role.data.get("system_key") == self.MEMBER_ROLE_SYSTEM_KEY:
            return SessionResult(
                "error", reason="Member standing is governed by resolutions",
            )
        if not self.holds_identity(team):
            return SessionResult(
                "error", reason="only the Identity holder can revoke a role",
            )
        offer = self._offer_for(role, str(actor_uuid or "").strip())
        if not offer:
            return SessionResult("error", reason="offer not found")
        data = dict(offer.data)
        data["revoked_at"] = self._now()
        data["revoked_by"] = self._identity_uuid
        return self.session.modify(offer.uuid, data, offer.weights)

    def decide_role(
        self, role_uuid: str, decision: str, expires_at: str | None = None,
    ) -> SessionResult:
        """Record this participant's own answer about a role.

        An answer with no matching offer is a *request*: somebody saying they
        will take this role, waiting on the Identity holder to confirm it.
        Nothing else is needed to express that, because a holding is live
        only while both records exist - so an offer alone is an unfilled
        seat, and a decision alone is a request. It is also how a newcomer
        gets their first role at all: they hold nothing, so they cannot be
        offered anything by anyone but Identity, and asking is the move
        available to them.
        """
        role = self._node(role_uuid, "team_role")
        if not role:
            return SessionResult("error", reason="role not found")
        team = self._local_team_topic(role.uuid)
        allowed = self._interaction_guard(team)
        if allowed.status != "ok":
            return allowed
        mine = self._identity_uuid
        if role.data.get("system_key") == self.MEMBER_ROLE_SYSTEM_KEY:
            genesis = self._offer_for(role, mine)
            if not genesis or not genesis.data.get("system_genesis"):
                return SessionResult(
                    "error",
                    reason="apply through an open Member opening",
                )
        if not self._offer_for(role, mine):
            # There may be an offer that has only reached this session as a
            # proposal. If there is, answering it should take it up; if there
            # is not, this answer stands on its own as a request.
            self._adopt_offer_proposal(team, role, mine)
            role = self._node(role_uuid, "team_role") or role
        normalized_decision = str(decision or "").strip().lower()
        if normalized_decision not in {"accepted", "refused"}:
            return SessionResult(
                "error", reason="decision must be accepted or refused",
            )
        normalized_expiry = self._normalize_expiry(expires_at)
        if expires_at and normalized_expiry is None:
            return SessionResult(
                "error", reason="expiration must be an ISO date or timestamp",
            )
        recorded = self._record_role_decision(
            team, role, normalized_decision, normalized_expiry,
        )
        if recorded.status == "ok" and normalized_decision == "accepted":
            # A subteam invitation may already be cached and deliberately
            # unmounted because this session held nothing in an ancestor. It
            # does now.
            self.session.mount_cached_topics(TEAM_APPLICATION_ID)
        return recorded

    def seat_team(
        self, role_uuid: str, team_uuid: str,
    ) -> SessionResult:
        """Take a role on behalf of a team whose Identity is held here.

        The counterpart of decide_role for a Team actor. A team
        cannot answer for itself, so whoever holds its Identity answers for
        it, and decided_by records who that was.
        """
        return self._answer_seat(role_uuid, team_uuid, "accepted")

    def decline_seat(
        self, role_uuid: str, team_uuid: str,
    ) -> SessionResult:
        """Turn down a seat offered to a team, on its behalf.

        Without this an invitation a team does not want sits unanswered
        forever, since the offer belongs to the parent and only its author may
        withdraw it (2.3). The refusal is the team's own record, so it is
        written by the only person who can speak for it.
        """
        return self._answer_seat(role_uuid, team_uuid, "refused")

    def _answer_seat(
        self, role_uuid: str, team_uuid: str, decision: str,
    ) -> SessionResult:
        role = self._node(role_uuid, "team_role")
        if not role:
            return SessionResult("error", reason="role not found")
        parent = self._local_team_topic(role.uuid)
        seated = self._node(team_uuid, "team")
        if not parent or not seated:
            return SessionResult("error", reason="team not found")
        if not self.holds_identity(seated):
            return SessionResult(
                "error",
                reason="only its Identity holder can answer for that team",
            )
        if seated.uuid == parent.uuid:
            return SessionResult(
                "error", reason="a team cannot be seated in itself",
            )
        if not self._offer_for(role, seated.uuid):
            # The offer may have reached this session only as a proposal, the
            # same way a person's does. Answering it takes it up first.
            self._adopt_offer_proposal(parent, role, seated.uuid)
            role = self._node(role_uuid, "team_role") or role
            parent = self._node(parent.uuid, "team") or parent
            if not self._offer_for(role, seated.uuid):
                return SessionResult(
                    "error", reason="this role has not been offered to it",
                )
        if decision == "refused":
            return self._record_role_decision(
                parent, role, "refused", None,
                actor_uuid=seated.uuid, decided_by=self._identity_uuid,
            )
        # Only accepting can close a loop, so the walk is spent only there.
        if self._creates_cycle(seated.uuid, parent.uuid):
            return SessionResult(
                "error",
                reason="that would make the organisation circular",
            )
        outside = self._members_outside(seated, parent)
        if outside:
            return SessionResult(
                "error",
                reason=(
                    "Everybody on this team has to hold a role in "
                    f"{parent.data.get('title') or 'the parent team'} "
                    "before it can take a seat there. Not yet holding one: "
                    + ", ".join(sorted(outside))
                ),
            )
        answered = self._record_role_decision(
            parent, role, "accepted", None,
            actor_uuid=seated.uuid, decided_by=self._identity_uuid,
        )
        if answered.status != "ok":
            return answered
        seated = self._node(team_uuid, "team") or seated
        existing = next(
            (
                holding for holding in self.parent_holdings(seated)
                if holding.data.get("role_uuid") == role.uuid
            ),
            None,
        )
        if existing:
            # Reconsidering a refusal: the answer is rewritten and the seat it
            # already names is the same seat.
            return SessionResult("ok", value=existing.uuid, effects=answered.effects)
        held = self.session.create_child(
            seated.uuid,
            {
                "type": "team_role_holding",
                "parent_team_uuid": parent.uuid,
                "role_uuid": role.uuid,
                "order": self.session.next_child_order(
                    seated.uuid, "team_role_holding",
                ),
            },
            {},
        )
        if held.status != "ok":
            return held
        self.session.mount_cached_topics(TEAM_APPLICATION_ID)
        return SessionResult(
            "ok",
            value=held.value.uuid,
            effects=[*answered.effects, *held.effects],
        )

    def actors_admitted_above(self, team: ProtocolNode) -> set[str] | None:
        """Who holds a role on every team above this one, or None for a root.

        Only ever reads *upward*. Asking this team who is on it would
        be circular - its roster is what the answer is for - so the question
        is put to the parents alone, and each of them answers it of its own
        parents in turn. That walk terminates at a root, and it is what
        makes the containment transitive: somebody dropped one level up is
        already missing from the answer given here.

        Derived, never recorded, exactly as the read-only guard is - it
        reverses itself the moment the role above is taken up again.
        """
        holdings = self.parent_holdings(team)
        if not holdings:
            return None
        admitted: set[str] | None = None
        for holding in holdings:
            parent = self._node(
                str(holding.data.get("parent_team_uuid") or "").strip(),
                "team",
            )
            if not parent:
                continue
            above = self.actor_uuids(parent)
            # Every parent, not any: a second parent is a second commitment.
            admitted = above if admitted is None else (admitted & above)
        return admitted if admitted is not None else set()

    def _members_outside(
        self, seated: ProtocolNode, parent: ProtocolNode,
    ) -> set[str]:
        """Who is on this team without also being on the one above it.

        Taking a seat commits everybody already on this team to the parent,
        because being on a team below is being on the team above. Somebody
        who has not taken a role up there would be carried into a team
        they never accepted - and would then find this team read-only,
        including the trustee who accepted the seat on its behalf.

        A team seated *here* is not checked: its own members were contained
        when it took its seat, so containment holds up the chain by
        induction. Only individuals are counted.

        This can only report what it can see. A role held on a replica this
        session does not reach reads as unheld, so the answer is the
        cautious one - refuse and name them - rather than a guess.
        """
        above = self.actor_uuids(parent) | {seated.uuid}
        outside = set()
        for actor_uuid in self.actor_uuids(seated):
            if actor_uuid in above or self._node(actor_uuid, "team"):
                continue
            known = self._known_people().get(actor_uuid) or {}
            outside.add(
                known.get("name") or known.get("address")
                or "somebody you have not met",
            )
        return outside

    def seat_offers(self, team: ProtocolNode) -> list[dict]:
        """Seats offered to this team that it does not yet hold.

        An invitation to a team is written on the *parent's* page, so
        without collecting it here the only person who could see it is
        somebody looking at the parent - who need not be the person entitled
        to answer. The answer belongs to whoever holds this team's
        Identity, so the invitation is put where that answer is made.
        """
        held = {
            str(holding.data.get("role_uuid") or "").strip()
            for holding in self.parent_holdings(team)
        }
        offers = []
        for parent in self.teams():
            if parent.uuid == team.uuid:
                continue
            for role in self.roles(parent):
                if role.uuid in held:
                    continue
                offer = self._offer_for(role, team.uuid)
                if offer and offer.data.get("revoked_at"):
                    continue
                if not offer and not self._offer_proposed_to(
                    parent, role, team.uuid,
                ):
                    continue
                answer = self._role_decision_for(role, team.uuid)
                offers.append({
                    "role_uuid": role.uuid,
                    "role_name": role.data.get("name") or "Untitled role",
                    "role_purpose": role.data.get("purpose") or "",
                    "team_uuid": parent.uuid,
                    "title": parent.data.get("title") or "Untitled team",
                    "offered_at": offer.data.get("offered_at") if offer else None,
                    # Not adopted here yet. Answering adopts it, so this is a
                    # note about where the record is, not a reason to wait.
                    "proposed": not offer,
                    "answer": (answer.data.get("decision") if answer else ""),
                    # An accepted seat that would close a loop is shown and
                    # refused, rather than hidden as if it had never come.
                    "circular": self._creates_cycle(team.uuid, parent.uuid),
                })
        return offers

    def unseat_team(
        self, role_uuid: str, team_uuid: str,
    ) -> SessionResult:
        """Give up a seat, from the seated team's side.

        Both records go, because a holding is live only while both exist:
        dropping this side alone would leave the parent still showing the seat
        as accepted while the team no longer claims it, and neither view
        is wrong on its own - they simply contradict each other.
        """
        seated = self._node(team_uuid, "team")
        if not seated:
            return SessionResult("error", reason="team not found")
        if not self.holds_identity(seated):
            return SessionResult(
                "error",
                reason="only its Identity holder can give up that seat",
            )
        held = [
            holding for holding in self.parent_holdings(seated)
            if holding.data.get("role_uuid") == role_uuid
        ]
        # Whether the seat was held is read from the holdings themselves. An
        # unshared team produces no effects at all, so counting those
        # would call every offline release a failure.
        if not held:
            return SessionResult("error", reason="it does not hold that role")
        effects = []
        for holding in held:
            effects.extend(self._release_seat(seated, holding))
            dropped = self.session.delete(holding.uuid)
            if dropped.status == "ok":
                effects.extend(dropped.effects)
        return SessionResult("ok", effects=effects)

    def _release_seat(
        self, seated: ProtocolNode, holding: ProtocolNode,
    ) -> list:
        """Withdraw the answer written in the parent for one seat.

        The Team actor's resign_role: the only record this side wrote up
        there is the acceptance, so that is all that goes. The role and the
        offer are the parent's, and a role may seat several actors at once -
        deleting it to empty one seat would take everybody else's with it.
        Leaving the offer standing makes the seat unfilled rather than never
        offered, which is what lets it be answered again.
        """
        role = self._node(
            str(holding.data.get("role_uuid") or "").strip(), "team_role",
        )
        decision = self._role_decision_for(role, seated.uuid) if role else None
        if not decision:
            return []
        removed = self.session.delete(decision.uuid)
        return list(removed.effects) if removed.status == "ok" else []

    def move_parent_holding(
        self, holding_uuid: str, index: int,
    ) -> SessionResult:
        """Reorder which parent is preferred as home."""
        holding = self._node(holding_uuid, "team_role_holding")
        if not holding:
            return SessionResult("error", reason="holding not found")
        team = self._local_team_topic(holding.uuid)
        if not team or not self.holds_identity(team):
            return SessionResult(
                "error",
                reason="only its Identity holder can reorder its parents",
            )
        return self.session.move_child_to_index(holding.uuid, index)

    def parent_payload(self, team: ProtocolNode) -> list[dict]:
        """Every seat this team holds, in order, home first."""
        home = self.home_parent_uuid(team)
        out = []
        for holding in self.parent_holdings(team):
            parent_uuid = str(
                holding.data.get("parent_team_uuid") or "",
            ).strip()
            parent = self._node(parent_uuid, "team")
            role = self._node(
                str(holding.data.get("role_uuid") or "").strip(),
                "team_role",
            )
            out.append({
                "holding_uuid": holding.uuid,
                "team_uuid": parent_uuid,
                "title": (
                    parent.data.get("title") if parent
                    else "A team you have not joined"
                ),
                "role_uuid": role.uuid if role else "",
                "role_name": role.data.get("name") if role else "",
                "joined": bool(parent),
                "is_home": parent_uuid == home and bool(home),
                "live": self._holding_problem(
                    team, holding, {team.uuid},
                ) is None,
            })
        return out

    def offerable_actors(self, team: ProtocolNode) -> list[dict]:
        """Everyone and everything that could be offered a role here."""
        actors = [
            {
                "uuid": person.get("uuid"),
                "name": person.get("name") or person.get("address") or "",
                "kind": "individual",
            }
            for person in self.session.known_identities()
        ]
        for other in self.teams():
            if other.uuid == team.uuid:
                continue
            if self._creates_cycle(other.uuid, team.uuid):
                continue
            actors.append({
                "uuid": other.uuid,
                "name": other.data.get("title") or "Untitled team",
                "kind": "team",
            })
        return actors

    def resign_role(self, role_uuid: str) -> SessionResult:
        """Step out of a role. Deleting only what this participant wrote."""
        role = self._node(role_uuid, "team_role")
        if not role:
            return SessionResult("error", reason="role not found")
        allowed = self._interaction_guard_for_node(role.uuid)
        if allowed.status != "ok":
            return allowed
        decision = self._own_role_decision(role)
        if not decision:
            return SessionResult("error", reason="you do not hold this role")
        return self.session.delete(decision.uuid)

    def _record_role_decision(
        self,
        team: ProtocolNode,
        role: ProtocolNode,
        decision: str,
        expires_at: str | None,
        actor_uuid: str | None = None,
        decided_by: str | None = None,
    ) -> SessionResult:
        """One answer per actor per role, rewritten rather than added to.

        An actor who refuses and later accepts has changed their mind, not
        answered twice, and two decision nodes for one actor would leave
        which of them counts up to iteration order. `decided_by` is set only
        for a Team actor, which cannot answer for itself.
        """
        actor = actor_uuid or self._identity_uuid
        data = {
            "type": "team_role_decision",
            "actor_uuid": actor,
            "decision": decision,
            "decided_at": self._now(),
            "reference_hash": self.role_reference_hash(team, role),
            "expires_at": expires_at,
        }
        if decided_by:
            data["decided_by"] = decided_by
        existing = self._role_decision_for(role, actor)
        if existing:
            return self.session.modify(existing.uuid, data, existing.weights)
        return self.session.create_child(role.uuid, data, {})

    def _adopt_offer_proposal(
        self, team: ProtocolNode, role: ProtocolNode, actor_uuid: str,
    ) -> SessionResult:
        """Take up an offer that has only reached this session as a proposal.

        This application never merges a peer's new node automatically - it
        presents it for adoption - and an offer is no exception. Answering
        one that has not been adopted yet therefore has to adopt it first.
        Doing that here keeps it a single gesture for the person: they were
        offered a role, and they answer. The authority check is not skipped,
        because this goes through the same accept_peer_node as any other
        adoption.
        """
        for address in self.session.peer_addresses(team.uuid):
            peer_topic = self.session.get_cached_peer_subtree(
                address, team.uuid,
            )
            peer_role = (
                self._find_in_subtree(peer_topic, role.uuid)
                if peer_topic else None
            )
            if not peer_role:
                continue
            found = next(
                (
                    child for child in peer_role.live_children()
                    if (
                        child.data.get("type") == "team_role_offer"
                        and child.data.get("actor_uuid") == actor_uuid
                    )
                ),
                None,
            )
            if found:
                return self.accept_peer_node(address, found.uuid)
        return SessionResult(
            "error", reason="this role has not been offered to you",
        )

    def _offer_for(
        self, role: ProtocolNode, actor_uuid: str, revoked: bool = False,
    ) -> ProtocolNode | None:
        source = (
            self._all_role_offers(role) if revoked else self.role_offers(role)
        )
        return next(
            (
                offer for offer in source
                if offer.data.get("actor_uuid") == actor_uuid
            ),
            None,
        )

    def _own_role_decision(self, role: ProtocolNode) -> ProtocolNode | None:
        return self._role_decision_for(role, self._identity_uuid)

    def _role_decision_for(
        self, role: ProtocolNode, actor_uuid: str,
    ) -> ProtocolNode | None:
        return next(
            (
                child for child in role.live_children()
                if (
                    child.data.get("type") == "team_role_decision"
                    and child.data.get("actor_uuid") == actor_uuid
                )
            ),
            None,
        )

    def role_holders(
        self, team: ProtocolNode, role: ProtocolNode,
    ) -> list[dict]:
        """Everyone offered this role, and where their answer stands.

        A decision is credible only from the actor's own replica, so an
        answer this session cannot reach is reported as unobserved rather
        than guessed at or shown as pending. Those are different facts: one
        is "they have not answered", the other is "I cannot see whether they
        have".
        """
        return self._cached(
            ("holders", team.uuid, role.uuid),
            lambda: self._build_role_holders(team, role),
        )

    def _build_role_holders(
        self, team: ProtocolNode, role: ProtocolNode,
    ) -> list[dict]:
        people = {
            member["uuid"]: member
            for member in self._topic_members(team.uuid)
        }
        current = self.role_reference_hash(team, role)
        offers = {
            str(offer.data.get("actor_uuid") or "").strip(): offer
            for offer in self._all_role_offers(role)
        }
        decisions = self._observed_decisions(team, role)
        withdrawn = self._withdrawn_by_trustee(team, role)
        admitted = self.actors_admitted_above(team)
        mine = self._identity_uuid
        # An offer authored by the Identity holder arrives here as a proposal
        # rather than as content, because nothing merges without somebody's
        # act. Left out of this list it is invisible, so the one person who
        # can answer it is never shown that there is anything to answer -
        # which is how an offer looks, from the far end, like nothing was
        # ever sent. Answering adopts it (see decide_role).
        proposed_to_me = (
            mine not in offers
            and mine not in decisions
            and self._offer_proposed_to(team, role, mine)
        )
        holders = []
        for actor_uuid in (
            offers.keys() | decisions.keys() | ({mine} if proposed_to_me else set())
        ):
            offer = offers.get(actor_uuid)
            record = decisions.get(actor_uuid)
            member = people.get(actor_uuid)
            unmerged_offer = proposed_to_me and actor_uuid == mine
            # Somebody this session knows but who is not on this topic is
            # a different case from somebody it cannot place at all: the
            # first has simply not been invited here, which is actionable
            # and is not the same as being unable to see their answer.
            known = None if member else self._known_people().get(actor_uuid)
            revoked = (
                bool(offer and offer.data.get("revoked_at"))
                or actor_uuid in withdrawn
            )
            if revoked:
                # Withdrawal is the trustee's own act on their own record,
                # and it is final: the holding is gone whether or not the
                # actor had answered. Showing the survivors said otherwise -
                # a withdrawn offer that had been accepted stayed on the
                # roster, greyed but still there, and on the actor's own
                # side it stayed *clickable*, so the one person the offer
                # had been taken away from could put themselves back.
                #
                # The actor's answer is not deleted - it is theirs (2.3) -
                # it simply stops being half of a live holding. Offering
                # again revives the same offer record, and their surviving
                # answer makes it live at once.
                continue
            # A Team actor is never among the people on this topic, so
            # the member test below would call every one of them a stranger.
            # Its standing is read from the answer given on its behalf.
            is_team = bool(
                offer and offer.data.get("actor_kind") == "team"
            )
            if unmerged_offer:
                # Offered, and not answered - the same standing as an offer
                # that had already merged, because from the reader's side it
                # is the same fact and calls for the same act.
                status = "pending"
            elif not offer:
                # An answer nobody offered: somebody asking to take this.
                status = "requested"
            elif not member and not is_team:
                status = "uninvited" if known else "unobserved"
            elif not record:
                # For a team, no answer means either that nobody has
                # given one or that whoever could is out of reach - and only
                # its Identity holder can tell those apart.
                status = (
                    "unobserved" if is_team and not self._holds_identity_of(
                        actor_uuid,
                    ) else "pending"
                )
            elif record.get("decision") == "refused":
                status = "refused"
            elif self._is_expired(record.get("expires_at")):
                status = "expired"
            elif record.get("reference_hash") != current:
                status = "outdated"
            else:
                status = "accepted"
            # A Team actor is not among the people on this topic, so it
            # is named by the team it is, when that is joined here.
            seated = (
                self._node(actor_uuid, "team")
                if (offer and offer.data.get("actor_kind") == "team")
                else None
            )
            holders.append({
                "actor_uuid": actor_uuid,
                # A request that has since been confirmed: the offer exists,
                # but only as a proposal on the peer that wrote it. Nothing
                # merges here without somebody's act, so the person who asked
                # still has to take it up - they are told, rather than left
                # watching a request that looks unanswered forever.
                "confirmed_elsewhere": (
                    status == "requested"
                    and actor_uuid == self._identity_uuid
                    and self._offer_proposed_to(team, role, actor_uuid)
                ),
                # The offer for this one exists only on the author's replica.
                # Nothing else about it differs, so it is a note on the
                # record rather than a status of its own.
                "offered_elsewhere": unmerged_offer,
                # Accepted here, but not on a team above - so not on this
                # one either, whatever their answer here says. A team seated
                # here is exempt: its own members were contained when it
                # took its seat.
                "outside_parent": bool(
                    admitted is not None
                    and actor_uuid not in admitted
                    and not is_team
                ),
                "name": (
                    (seated.data.get("title") or "Untitled team")
                    if seated
                    # A profile with no display name still has an
                    # address, which names somebody better than a
                    # placeholder saying they are a stranger.
                    else (member or known or {}).get("name")
                    or (member or known or {}).get("address")
                    or "Somebody you have not met"
                ),
                "joined": bool(seated) if (
                    offer and offer.data.get("actor_kind") == "team"
                ) else None,
                # Individual or Team. The view draws them differently,
                # because "a person holds this" and "a body holds this" are
                # not the same fact.
                "actor_kind": (
                    (offer.data.get("actor_kind") if offer else None)
                    or "individual"
                ),
                "picture": (member or {}).get("picture") or "",
                "is_self": actor_uuid == self._identity_uuid,
                "status": status,
                "decided_at": (record or {}).get("decided_at"),
                "expires_at": (record or {}).get("expires_at"),
                "offered_at": (offer.data.get("offered_at") if offer else None),
                "offered_by": (offer.data.get("offered_by") if offer else None),
            })
        return sorted(holders, key=lambda item: (item["status"], item["name"]))

    def _withdrawn_by_trustee(
        self, team: ProtocolNode, role: ProtocolNode,
    ) -> set[str]:
        """Offers the trustee's own replica shows withdrawn.

        An offer is the trustee's record, so their replica is what it says -
        the same credibility rule 2.6 applies to an answer, pointed at the
        other author. Without it a withdrawal has to be adopted by everybody
        it is news to, and until they do the person goes on being shown as
        holding a role that was taken back: on their own client the badge
        stayed active, which is the one place it must not.

        Only consulted when somebody else holds Identity. When it is this
        session, the local record already *is* the trustee's.
        """
        holder = self.identity_holder(team)
        if not holder or holder == self._identity_uuid:
            return set()
        member = next(
            (
                person for person in self._topic_members(team.uuid)
                if person["uuid"] == holder
            ),
            None,
        )
        if not member:
            return set()
        withdrawn: set[str] = set()
        for address in member.get("addresses") or [member.get("address")]:
            if not address:
                continue
            peer_topic = self.session.get_cached_peer_subtree(
                address, team.uuid,
            )
            peer_role = (
                self._find_in_subtree(peer_topic, role.uuid)
                if peer_topic else None
            )
            if not peer_role:
                continue
            withdrawn.update(
                str(child.data.get("actor_uuid") or "")
                for child in peer_role.live_children()
                if child.data.get("type") == "team_role_offer"
                and child.data.get("revoked_at")
            )
        return withdrawn

    def _offer_proposed_to(
        self, team: ProtocolNode, role: ProtocolNode, actor_uuid: str,
    ) -> bool:
        """Whether some peer holds an offer of this role to that actor."""
        mine = actor_uuid
        for address in self.session.peer_addresses(team.uuid):
            peer_topic = self.session.get_cached_peer_subtree(
                address, team.uuid,
            )
            peer_role = (
                self._find_in_subtree(peer_topic, role.uuid)
                if peer_topic else None
            )
            if peer_role and any(
                child.data.get("type") == "team_role_offer"
                and child.data.get("actor_uuid") == mine
                and not child.data.get("revoked_at")
                for child in peer_role.live_children()
            ):
                return True
        return False

    def _observed_decisions(
        self, team: ProtocolNode, role: ProtocolNode,
    ) -> dict[str, dict]:
        """Every answer about this role this session can actually vouch for.

        Only from the replica of the person it belongs to: a peer's copy of a
        third party's answer is hearsay, and nothing signs content, so it is
        not counted. That is also what makes an unreachable answer reportable
        as unobserved rather than invented.

        A Team actor has no replica of its own - it cannot answer for
        itself - so the replica that vouches for it is the one belonging to
        whoever answered on its behalf. Same rule, applied to who gave the
        answer rather than to whose answer it is.
        """
        found: dict[str, dict] = {}
        own = self._own_role_decision(role)
        if own:
            found[self._identity_uuid] = dict(own.data)
        found.update(self._answers_given_by(role, self._identity_uuid))
        members = {
            address: member
            for member in self._topic_members(team.uuid)
            for address in member.get("addresses") or [member.get("address")]
            if address
        }
        for address in self.session.peer_addresses(team.uuid):
            member = members.get(address)
            if not member:
                continue
            peer_topic = self.session.get_cached_peer_subtree(
                address, team.uuid,
            )
            peer_role = (
                self._find_in_subtree(peer_topic, role.uuid)
                if peer_topic else None
            )
            if not peer_role:
                continue
            for child in peer_role.live_children():
                if (
                    child.data.get("type") == "team_role_decision"
                    and child.data.get("actor_uuid") == member["uuid"]
                ):
                    found[member["uuid"]] = dict(child.data)
            found.update(self._answers_given_by(peer_role, member["uuid"]))
        return found

    @staticmethod
    def _answers_given_by(role: ProtocolNode, actor_uuid: str) -> dict[str, dict]:
        """Answers this actor recorded on some team's behalf.

        `decided_by` is set only where an actor could not answer for itself,
        so its presence is what marks an answer as given rather than owned.
        """
        return {
            str(child.data.get("actor_uuid") or ""): dict(child.data)
            for child in role.live_children()
            if (
                child.data.get("type") == "team_role_decision"
                and child.data.get("decided_by") == actor_uuid
            )
        }

    @staticmethod
    def _find_in_subtree(
        root: ProtocolNode, node_uuid: str,
    ) -> ProtocolNode | None:
        if root.uuid == node_uuid:
            return root
        for child in root.children:
            if found := TeamLogic._find_in_subtree(child, node_uuid):
                return found
        return None

    def _role_item(self, item_uuid: str) -> ProtocolNode | None:
        # A stored node names its own kind, so only creation has to be told
        # which one it is.
        for node_type in self.ROLE_ITEM_TYPES.values():
            if node := self._node(item_uuid, node_type):
                return node
        return None

    def accept_team_topic_invitation(
        self, subtree: ProtocolNode,
    ) -> SessionResult:
        if subtree.data.get("type") == "team_pool":
            return self.accept_pool_invitation(subtree)
        return self.accept_team_invitation(subtree)

    def accept_pool_invitation(self, subtree: ProtocolNode) -> SessionResult:
        required = {
            "type", "team_uuid", "team_title", "title", "created_by",
            "created_at",
        }
        if (
            subtree.data.get("type") != "team_pool"
            or set(subtree.data) != required
            or not all(
                isinstance(subtree.data.get(field), str)
                and subtree.data.get(field)
                for field in required - {"type"}
            )
        ):
            return SessionResult("error", reason="invited Pool is invalid")
        status, reason = self._signed_actor_status(
            subtree, str(subtree.data.get("created_by") or ""),
        )
        if status != "authorized":
            return SessionResult("error", reason=reason)
        if any(
            child.data.get("type") not in self.POOL_RECORD_TYPES
            or self.pool_schema_error(child)
            for child in subtree.live_children()
        ):
            return SessionResult("error", reason="invited Pool contains invalid records")
        return self.session.accept_topic_invitation(
            subtree, self._team_container().uuid,
        )

    def accept_team_invitation(self, subtree: ProtocolNode) -> SessionResult:
        if subtree.data.get("type") != "team":
            return SessionResult("error", reason="invited topic is not a team")
        admission_pools = [
            pool for pool in self.pools()
            if pool.data.get("team_uuid") == subtree.uuid
        ]
        if admission_pools and not any(
            resolution.data.get("outcome") == "accepted"
            and resolution.data.get("actor_uuid") == self._identity_uuid
            for pool in admission_pools
            for resolution in self.pool_records(
                pool, "team_pool_resolution",
            )
        ):
            return SessionResult(
                "error",
                reason="this Actor has no accepted Pool application for the Team",
            )
        # The invited subtree carries its own holdings, so its ancestry can
        # be checked before it is mounted. Joining it does not require
        # holding anything in it - that comes after, by asking.
        prerequisites = self._joining_guard(subtree)
        if prerequisites.status != "ok":
            return prerequisites
        result = self.session.accept_topic_invitation(
            subtree, self._team_container().uuid,
        )
        if result.status == "ok":
            # Joining is not holding. The newcomer arrives able to read
            # and asks for a role from there (2.4b).
            self._remember_team(result.value)
        return result

    # Reacting per node is what lets a divergence be left behind. Without it
    # a team can reach a state it cannot exit: two sides edit the same
    # clause, both see "diverged", and nothing either of them does resolves
    # it. Both primitives are Session's; this application only names which
    # node types may be reacted to.
    REACTABLE = frozenset({
        "team", "team_section", "team_clause",
        "team_role", "team_accountability", "team_domain",
        "team_role_holding",
        "team_role_offer", "team_role_decision",
        *GOVERNANCE_RECORD_TYPES,
    })
    OWNED_NODE_TYPES = frozenset({
        *REACTABLE, "agenda_item",
    })

    def accept_peer_node(self, source_addr: str, node_uuid: str,
                         adopt_absence: bool = False) -> SessionResult:
        local_exists = node_uuid in self.session.protocol.index
        if ((local_exists and not self.owns_node(node_uuid))
                or (not adopt_absence
                    and not self.owns_node(node_uuid, source_addr))):
            return SessionResult("error", reason="node is not part of a team")
        peer_node = self.session.get_cached_peer_subtree(
            source_addr, node_uuid,
        )
        reference = peer_node or self.session.protocol.index.get(node_uuid)
        if reference and reference.data.get("type") in self.GOVERNANCE_RECORD_TYPES:
            if local_exists:
                return SessionResult(
                    "error",
                    reason="governance records are append-only and cannot be changed",
                )
            team = self._team_for_reaction(source_addr, node_uuid)
            if not team or not peer_node:
                return SessionResult("error", reason="governance record is unavailable")
            assessment = self.assess_governance_record(team, peer_node)
            if assessment["status"] != "authorized":
                return SessionResult("error", reason=assessment["reason"])
        allowed = self._interaction_guard_for_reaction(
            source_addr, node_uuid,
        )
        if allowed.status != "ok":
            return allowed
        authority = self._offer_authority_guard(source_addr, node_uuid)
        if authority.status != "ok":
            return authority
        return self.session.accept_peer_node(source_addr, node_uuid, adopt_absence)

    def rollback_peer_node(self, source_addr: str, node_uuid: str,
                           rollback_absence: bool = False) -> SessionResult:
        if (not self.owns_node(node_uuid)
                or (not rollback_absence
                    and not self.owns_node(node_uuid, source_addr))):
            return SessionResult("error", reason="node is not part of a team")
        allowed = self._interaction_guard_for_reaction(
            source_addr, node_uuid,
        )
        if allowed.status != "ok":
            return allowed
        return self.session.rollback_peer_node(
            source_addr, node_uuid, rollback_absence,
        )

    def adopt_peer_changes(self, source_addr: str,
                           team_uuid: str) -> SessionResult:
        team = self._node(team_uuid, "team")
        if not team or not self.owns_node(team_uuid, source_addr):
            return SessionResult("error", reason="team not found")
        allowed = self._interaction_guard_for_node(team_uuid)
        if allowed.status != "ok":
            return allowed
        changed = self.session.reconcile_peer_changes(
            source_addr,
            team_uuid,
            lambda node, event_type: self._manual_adoption_eligible(
                source_addr, team, node, event_type,
            ),
        )
        return SessionResult("ok", value=changed)

    def _manual_adoption_eligible(
        self, source_addr: str, team: ProtocolNode, node: ProtocolNode,
        event_type: str,
    ) -> bool:
        node_type = node.data.get("type")
        if node_type not in self.GOVERNANCE_RECORD_TYPES:
            return node_type != "team_role_decision"
        if event_type != "local_missing_node":
            return False
        peer_node = self.session.get_cached_peer_subtree(
            source_addr, node.uuid,
        )
        return bool(
            peer_node
            and self.assess_governance_record(team, peer_node)["status"]
            == "authorized"
        )

    def reconcile_governance_updates(self) -> SessionResult:
        """Auto-adopt only verified, authorized, immutable governance facts."""
        changed = False
        for team in self.teams():
            for address in self.session.peer_addresses(team.uuid):
                adopted = self.session.reconcile_peer_changes(
                    address,
                    team.uuid,
                    lambda node, event_type, peer=address, body=team: (
                        self._governance_adoption_eligible(
                            peer, body, node, event_type,
                        )
                    ),
                )
                changed = adopted or changed
        for pool in self.pools():
            for address in self.session.peer_addresses(pool.uuid):
                adopted = self.session.reconcile_peer_changes(
                    address,
                    pool.uuid,
                    lambda node, event_type, peer=address, dmz=pool: (
                        self._pool_adoption_eligible(
                            peer, dmz, node, event_type,
                        )
                    ),
                )
                changed = adopted or changed
        return SessionResult("ok", value=changed)

    def _pool_adoption_eligible(
        self, peer_addr: str, pool: ProtocolNode, node: ProtocolNode,
        event_type: str,
    ) -> bool:
        if (
            event_type != "local_missing_node"
            or node.data.get("type") not in self.POOL_RECORD_TYPES
        ):
            return False
        peer_node = self.session.get_cached_peer_subtree(
            peer_addr, node.uuid,
        )
        if not peer_node:
            return False
        assessment = self.assess_pool_record(pool, peer_node)
        self.session.trace_event(
            "team.pool_assessment",
            peer_addr=peer_addr,
            pool_uuid=pool.uuid,
            node_uuid=node.uuid,
            record_type=node.data.get("type"),
            status=assessment["status"],
            reason=assessment["reason"],
        )
        return assessment["status"] == "authorized"

    def _governance_adoption_eligible(
        self, peer_addr: str, team: ProtocolNode, node: ProtocolNode,
        event_type: str,
    ) -> bool:
        if (
            event_type != "local_missing_node"
            or node.data.get("type") not in self.GOVERNANCE_RECORD_TYPES
        ):
            return False
        peer_node = self.session.get_cached_peer_subtree(peer_addr, node.uuid)
        if not peer_node:
            return False
        assessment = self.assess_governance_record(team, peer_node)
        self.session.trace_event(
            "team.governance_assessment",
            peer_addr=peer_addr,
            team_uuid=team.uuid,
            node_uuid=node.uuid,
            record_type=node.data.get("type"),
            status=assessment["status"],
            reason=assessment["reason"],
        )
        return assessment["status"] == "authorized"

    def transition_events(
        self, team_uuid: str, network: dict | None = None,
    ) -> list[dict]:
        events: list[dict] = []
        for address in self.session.peer_addresses():
            if not self.session.peer_discusses_node(address, team_uuid):
                continue
            peer_info = ((network or {}).get("peers") or {}).get(address) or {}
            liveness = peer_info.get("channel_liveness")
            if liveness is None and network is None:
                resolver = getattr(
                    self.collaboration, "peer_liveness_for_address", None,
                )
                liveness = (
                    resolver(address, team_uuid)
                    if resolver else {"state": "unknown"}
                )
            liveness = liveness or {"state": "unknown"}
            for event in self.session.analyze_peer_transitions(
                address, team_uuid,
            ):
                node_uuid = event.get("node_uuid")
                local_node = self.session.protocol.index.get(node_uuid)
                peer_node = self.session.get_cached_peer_subtree(
                    address, node_uuid,
                )
                observed = peer_node or local_node
                if (
                    observed
                    and observed.data.get("type") not in self.OWNED_NODE_TYPES
                ):
                    continue
                if (
                    event["stage"] == "in_flight"
                    and liveness.get("state") == "stale"
                ):
                    continue
                event["changes"] = (
                    [] if event["type"] == "in_agreement"
                    else self.describe_peer_changes(
                        address, event.get("node_uuid"),
                        authored_locally=event["type"] in (
                            "local_made_changes", "peer_missing_node",
                        ),
                    )
                )
                events.append(event)
        return events

    # What the divergence list reads from. Core's shared.js composes one
    # sentence per difference out of node_label / authored_act /
    # authored_detail, so an application that publishes no change records
    # falls through to the bare "Missing in <peer>" - which tells the reader
    # that something differs while withholding what.
    NODE_LABELS = {
        "team": "Team",
        "team_section": "Section",
        "team_clause": "Clause",
        "team_role": "Role",
        "team_accountability": "Accountability",
        "team_domain": "Domain",
        "team_role_offer": "Role offer",
        "team_role_decision": "Role answer",
        "team_role_holding": "Seat",
        "agenda_item": "Discussion topic",
        "team_trustee_state": "Trusteeship state",
        "team_member_opening": "Member opening",
        "team_member_application": "Member application",
        "team_member_resolution": "Member resolution",
        "team_trustee_election": "Trustee election",
        "team_trustee_candidacy": "Trustee candidacy",
        "team_trustee_action": "Trustee action",
        "team_trustee_reality": "Reality observation",
        "team_external_member_resolution": "Pool membership resolution",
    }
    # Text-bearing fields, by the name they are read under. "Title" alone
    # would be ambiguous on a team node, which now carries two.
    TEXT_FIELDS = {
        "title": "Title",
        "agreement_title": "Agreement title",
        "name": "Name",
        "text": "Text",
        "purpose": "Purpose",
    }

    def describe_peer_changes(
        self, peer_addr: str, node_uuid: str | None,
        authored_locally: bool = False,
    ) -> list[dict]:
        """Describe the peer's current version of a node against this one.

        Semantic current-version differences, not an audit log: in a genuine
        two-sided divergence they say what the peer's version holds relative
        to mine without claiming which operation produced it.
        """
        if not node_uuid:
            return []
        local = self.session.protocol.index.get(node_uuid)
        peer = self.session.get_cached_peer_subtree(peer_addr, node_uuid)
        if not local and not peer:
            return []
        node = peer or local
        node_type = node.data.get("type") or "node"
        label = self.NODE_LABELS.get(node_type, "Item")
        if not local:
            change = {
                "kind": "presence",
                "field": "node",
                "label": label,
                "summary": f"{label} exists only in the peer version",
                "local_summary": f"Keep {label.lower()} absent",
            }
            if node_type in self.GOVERNANCE_RECORD_TYPES and peer:
                team = self._team_for_reaction(peer_addr, node.uuid)
                if team:
                    assessment = self.assess_governance_record(team, peer)
                    change["governance_status"] = assessment["status"]
                    change["governance_reason"] = assessment["reason"]
                    if assessment["status"] != "authorized":
                        change["summary"] = (
                            f"{label} is disregarded: {assessment['reason']}"
                        )
            return self._annotate_authorship(
                [change], label, authored_locally,
            )
        if not peer:
            return self._annotate_authorship([{
                "kind": "presence",
                "field": "node",
                "label": label,
                "summary": f"{label} exists only in your version",
                "local_summary": f"Keep your {label.lower()}",
            }], label, authored_locally)
        if (
            local.state_hash == peer.state_hash
            and local.parent_uuid == peer.parent_uuid
        ):
            return []
        return self._annotate_authorship(
            self._field_changes(peer_addr, local, peer, node_type, label),
            label,
            authored_locally,
        )

    def _field_changes(
        self, peer_addr: str, local: ProtocolNode, peer: ProtocolNode,
        node_type: str, label: str,
    ) -> list[dict]:
        changes: list[dict] = []
        if local.deleted != peer.deleted:
            changes.append({
                "kind": "deletion",
                "field": "deleted",
                "label": label,
                "local_value": local.deleted,
                "peer_value": peer.deleted,
                "summary": (
                    f"{label} is deleted in the peer version"
                    if peer.deleted else
                    f"{label} is present in the peer version"
                ),
                "local_summary": (
                    f"Keep your {label.lower()} present"
                    if peer.deleted else
                    f"Keep your {label.lower()} deleted"
                ),
            })
        for field, field_label in self.TEXT_FIELDS.items():
            if local.data.get(field) == peer.data.get(field):
                continue
            changes.append({
                "kind": "field",
                "field": field,
                "label": field_label,
                "local_value": local.data.get(field),
                "peer_value": peer.data.get(field),
                "summary": (
                    f"{field_label}: \"{local.data.get(field) or ''}\""
                    f" → \"{peer.data.get(field) or ''}\""
                ),
                "local_summary": f"Keep your {field_label.lower()}",
            })
        changes.extend(self._holding_changes(local, peer, node_type))
        if local.data.get("order") != peer.data.get("order"):
            changes.append({
                "kind": "position",
                "field": "order",
                "label": "Position",
                "local_value": local.data.get("order"),
                "peer_value": peer.data.get("order"),
                "summary": f"{label} sits elsewhere in the peer version",
                "local_summary": f"Keep your {label.lower()} where it is",
            })
        # A team is a topic root, and every peer grafts a topic under
        # its own container - so the parents always differ and always will.
        # Session excludes that from classification; the description has to
        # exclude it too, or every shared team reads as "moved".
        if node_type != "team" and local.parent_uuid != peer.parent_uuid:
            changes.append({
                "kind": "move",
                "field": "parent_uuid",
                "label": "Location",
                "local_value": local.parent_uuid,
                "peer_value": peer.parent_uuid,
                "local_label": self._node_display_name(
                    self.session.protocol.index.get(local.parent_uuid),
                ),
                "peer_label": self._node_display_name(
                    self.session.get_cached_peer_subtree(
                        peer_addr, peer.parent_uuid,
                    ),
                ),
                "summary": f"{label} sits under a different parent",
                "local_summary": f"Keep your {label.lower()} where it is",
            })
        return changes

    def _holding_changes(
        self, local: ProtocolNode, peer: ProtocolNode, node_type: str,
    ) -> list[dict]:
        """The three records that say who holds what.

        They carry no text at all, so without this every offer, answer and
        handover reads as an unnamed "Item changed" - which is exactly the
        kind of difference somebody most needs told.
        """
        if node_type == "__obsolete_mutable_trustee__":
            field = "holder_actor_uuid"
            if local.data.get(field) == peer.data.get(field):
                return []
            return [{
                "kind": "identity",
                "field": field,
                "label": "Identity",
                "local_value": local.data.get(field),
                "peer_value": peer.data.get(field),
                "local_label": self._actor_name(local.data.get(field)),
                "peer_label": self._actor_name(peer.data.get(field)),
                "summary": (
                    f"Identity: {self._actor_name(local.data.get(field))}"
                    f" → {self._actor_name(peer.data.get(field))}"
                ),
                "local_summary": (
                    "Keep "
                    f"{self._actor_name(local.data.get(field))} as Identity"
                ),
            }]
        if node_type == "team_role_offer":
            if bool(local.data.get("revoked_at")) == bool(
                peer.data.get("revoked_at"),
            ):
                return []
            who = self._actor_name(peer.data.get("actor_uuid"))
            withdrawn = bool(peer.data.get("revoked_at"))
            return [{
                "kind": "offer",
                "field": "revoked_at",
                "label": "Role offer",
                "local_value": local.data.get("revoked_at"),
                "peer_value": peer.data.get("revoked_at"),
                "peer_label": who,
                "summary": (
                    f"The offer to {who} is withdrawn in the peer version"
                    if withdrawn else
                    f"The offer to {who} stands in the peer version"
                ),
                "local_summary": (
                    f"Keep the offer to {who}" if withdrawn
                    else f"Keep the offer to {who} withdrawn"
                ),
            }]
        if node_type == "team_role_decision":
            if (
                local.data.get("decision") == peer.data.get("decision")
                and local.data.get("expires_at") == peer.data.get("expires_at")
            ):
                return []
            who = self._actor_name(peer.data.get("actor_uuid"))
            return [{
                "kind": "answer",
                "field": "decision",
                "label": "Role answer",
                "local_value": local.data.get("decision"),
                "peer_value": peer.data.get("decision"),
                "peer_label": who,
                "summary": (
                    f"{who} answered {peer.data.get('decision') or 'nothing'}"
                    " in the peer version"
                ),
                "local_summary": (
                    f"Keep {who} as "
                    f"{local.data.get('decision') or 'unanswered'}"
                ),
            }]
        return []

    def _actor_name(self, actor_uuid: str | None) -> str:
        normalized = str(actor_uuid or "").strip()
        if not normalized:
            return "nobody"
        if normalized == self._identity_uuid:
            return "you"
        if known := self._known_people().get(normalized):
            return known.get("name") or known.get("address") or "somebody"
        if seated := self._node(normalized, "team"):
            return seated.data.get("title") or "a team"
        return "somebody you have not met"

    @staticmethod
    def _node_display_name(node: ProtocolNode | None) -> str:
        if not node:
            return "Unknown"
        return str(
            node.data.get("title")
            or node.data.get("name")
            or node.data.get("text")
            or "Untitled",
        )

    @staticmethod
    def _annotate_authorship(
        changes: list[dict], label: str, authored_locally: bool,
    ) -> list[dict]:
        """Name what the author did, in words neither side has to invert.

        The rest of a change record is peer-relative ("...in the peer
        version"), which is right for choosing between versions and wrong
        for saying what happened: it makes the person who made the change
        read their own edit described from the far end. These fields state
        the act, so each side renders "<act> by me" or "<act> by <name>"
        from one record.
        """
        for change in changes:
            kind = change.get("kind")
            detail = ""
            # A suffix belongs to the verb and follows the author directly;
            # a detail is a list of what changed and sits behind a colon.
            suffix = ""
            if kind == "presence":
                act, noun = "created", "creation"
            elif kind == "deletion":
                deleted_by_author = (
                    bool(change.get("peer_value")) != authored_locally
                )
                act = "deleted" if deleted_by_author else "restored"
                noun = "deletion" if deleted_by_author else "restoration"
            elif kind == "move":
                act, noun = "moved", "move"
                # Name where the author put it - their own side of the
                # comparison. The other end is where it came from.
                target = change.get(
                    "local_label" if authored_locally else "peer_label",
                )
                if target:
                    suffix = f'under "{target}"'
                counterpart = change.get(
                    "peer_label" if authored_locally else "local_label",
                )
                if counterpart:
                    change["counter_suffix"] = f'under "{counterpart}"'
            elif kind == "position":
                act, noun = "reordered", "reordering"
            elif kind == "identity":
                given = change.get(
                    "local_value" if authored_locally else "peer_value",
                )
                if str(given or "").strip():
                    act, noun = "handed on", "handover"
                    target = change.get(
                        "local_label" if authored_locally else "peer_label",
                    )
                    if target:
                        suffix = f"to {target}"
                else:
                    # Emptied, not given away. "Handed on to nobody" names a
                    # recipient who does not exist, and reads as a mistake.
                    act, noun = "vacated", "resignation"
            elif kind == "offer":
                withdrawn = bool(change.get("peer_value")) != authored_locally
                act = "withdrawn" if withdrawn else "offered"
                noun = "withdrawal" if withdrawn else "offer"
                if who := change.get("peer_label"):
                    suffix = f"to {who}"
            elif kind == "answer":
                act, noun = "answered", "answer"
                given = change.get(
                    "local_value" if authored_locally else "peer_value",
                )
                detail = str(given or "not yet answered")
            else:
                act, noun = "modified", "modification"
                detail = f"{str(change.get('label') or '').lower()} changed"
            change["node_label"] = label
            change["authored_act"] = act
            change["authored_noun"] = noun
            change["authored_suffix"] = suffix
            change["authored_detail"] = detail
        return changes

    def document_payload(
        self, team_uuid: str | None = None,
        network: dict | None = None,
        pool_uuid: str | None = None,
    ) -> dict:
        with self._reading():
            selected_pool = self._pool_node(pool_uuid) if pool_uuid else None
            if selected_pool or (not self.teams() and self.pools()):
                return self._build_pool_document_payload(
                    selected_pool or self.pools()[0], network,
                )
            return self._build_document_payload(team_uuid, network)

    def _build_pool_document_payload(
        self, pool: ProtocolNode, network: dict | None = None,
    ) -> dict:
        network = (
            self._network_info(pool.uuid) if network is None else network
        )
        return {
            "view": "pool",
            "address": self.session.address,
            "team": None,
            "teams": [
                self._document_node_dict(node) for node in self.teams()
            ],
            "pools": [
                {
                    "uuid": item.uuid,
                    "team_uuid": item.data.get("team_uuid"),
                    "team_title": item.data.get("team_title"),
                }
                for item in self.pools()
            ],
            "pool": self.pool_payload(pool),
            "transition_events": [],
            "transition_by_node": {},
            "proposed_nodes": [],
            "network": network,
            "agenda_items": [],
            "identity_uuid": self._identity_uuid,
            "known_identities": self.session.known_identities(),
            "organization": self.organization_payload(),
            "interaction": {"allowed": True, "reason": ""},
        }

    def _build_document_payload(
        self, team_uuid: str | None = None,
        network: dict | None = None,
    ) -> dict:
        teams = self.teams()
        selected = self._selected_team(team_uuid, teams)
        network = (
            self._network_info(selected.uuid if selected else None)
            if network is None else network
        )
        events = (
            self.transition_events(selected.uuid, network) if selected else []
        )
        return {
            "view": "team",
            "address": self.session.address,
            # Payload key, not a node type. The page reads it as
            # payload.team, and the wire vocabulary is deliberately not
            # moving with the stored types.
            "team": (
                self._document_node_dict(selected) if selected else None
            ),
            "teams": [
                self._document_node_dict(node) for node in teams
            ],
            "transition_events": events,
            "transition_by_node": self.transition_by_node(events),
            # Team changes are proposals until explicitly accepted.
            # Expose only the peer-only team nodes needed to present
            # those proposals; the application does not receive or manage
            # channel state, nor does the UI need the complete peer cache.
            "proposed_nodes": self._proposed_nodes(events),
            "network": network,
            # Agendas are Session's, so this application only forwards the
            # merged list for the topic in view.
            "agenda_items": [
                node.to_dict() for node in
                (self.session.agenda_items(selected.uuid) if selected else [])
            ],
            "identity_uuid": self._identity_uuid,
            "known_identities": self.session.known_identities(),
            "organization": self.organization_payload(),
            "is_organization": (
                self.is_organization(selected) if selected else False
            ),
            "trusteeships": (
                {
                    trust: self.trustee_projection(selected, trust)
                    for trust in sorted(self.TRUSTS)
                } if selected else {}
            ),
            "governance_attempts": (
                self.governance_attempts(selected) if selected else []
            ),
            "participants": (
                self.participants(selected.uuid) if selected else []
            ),
            "membership": (
                self.membership_payload(selected) if selected
                else {"openings": [], "can_resolve": False, "is_member": False}
            ),
            "trustee_elections": (
                self.trustee_elections_payload(selected) if selected else []
            ),
            "trustee_actions": (
                self.trustee_actions_payload(selected) if selected else []
            ),
            "pool": (
                {
                    "uuid": pool.uuid,
                    "team_uuid": pool.data.get("team_uuid"),
                    "team_title": pool.data.get("team_title"),
                    "active_invitation_count": len([
                        invitation for invitation in self.pool_records(
                            pool, "team_pool_invitation",
                        )
                        if not self._is_expired(str(
                            invitation.data.get("expires_at") or "",
                        ))
                    ]),
                }
                if selected and (pool := self.pool_for_team(selected))
                else None
            ),
            # Whether this session holds a role here. Taking a role is the
            # only way to be part of a team, so this is what the view
            # asks before offering anything that only a participant does.
            "holds_role": (
                self._has_current_acceptance(selected) if selected else False
            ),
            "identity": (
                self.identity_payload(selected) if selected
                else {"state": "vacant"}
            ),
            "trust": (
                self.trust_payload(selected) if selected
                else {"state": "vacant"}
            ),
            # Resolved here rather than in the view: a holder's status
            # depends on peer replicas the browser never sees.
            "role_holders": (
                {
                    role.uuid: self.role_holders(selected, role)
                    for role in self.roles(selected)
                } if selected else {}
            ),
            "holds_identity": (
                self.holds_identity(selected) if selected else False
            ),
            "holds_trust": (
                self.holds_trust(selected) if selected else False
            ),
            # Template, instantiated or working - a count of actors, not a
            # kind of node (2.8).
            "state": self.team_state(selected) if selected else "",
            "offerable_actors": (
                self.offerable_actors(selected) if selected else []
            ),
            # Where this team is drawn, and every other seat it
            # holds - never hidden, or deleting the first parent would
            # take away something load-bearing nobody could see.
            "parents": self.parent_payload(selected) if selected else [],
            # Seats offered to this team. They are written on the
            # parent's page, so they are brought here, where the only person
            # who can answer them is looking.
            "seat_offers": self.seat_offers(selected) if selected else [],
            "interaction": (
                self.interaction_payload(selected) if selected else {
                    "allowed": False, "reason": "",
                }
            ),
            "refusal_consequences": (
                [
                    {
                        "uuid": item.uuid,
                        "title": item.data.get("title")
                        or "Untitled team",
                    }
                    for item in self.descendant_teams(selected.uuid)
                ]
                if selected else []
            ),
        }

    # Records about the team rather than content of it. They have their
    # own storage nodes and their own presentation - badges, an Identity line
    # - so they stay out of the document serialization and are never rendered
    # as document-change proposals. Their divergences are unaffected:
    # transition events come from the protocol tree, not from this view.
    NON_DOCUMENT_TYPES = frozenset({
        "team_role_offer", "team_role_decision",
        *GOVERNANCE_RECORD_TYPES,
    })

    @classmethod
    def _document_node_dict(cls, node: ProtocolNode) -> dict:
        """Serialize document content without the records kept beside it."""
        payload = node.to_dict()

        def remove_records(item: dict) -> None:
            children = [
                child for child in item.get("children") or []
                if child.get("data", {}).get("type")
                not in cls.NON_DOCUMENT_TYPES
            ]
            item["children"] = children
            for child in children:
                remove_records(child)

        remove_records(payload)
        return payload

    def document_snapshot(
        self, team_uuid: str | None = None, pool_uuid: str | None = None,
    ) -> dict:
        """Build team state under Session without consulting transport."""
        payload = self.document_payload(team_uuid, {}, pool_uuid)
        decorated = []
        for event in payload.get("transition_events", []):
            node_uuid = event.get("node_uuid")
            view = self.transition_by_node([event]).get(node_uuid)
            if view:
                decorated.append((event, view))
        topic = payload.get("team") or payload.get("pool") or {}
        return {
            "payload": payload,
            "topic_uuid": topic.get("uuid"),
            "transition_views": decorated,
        }

    @classmethod
    def merge_document_observation(
        cls, snapshot: dict, network: dict,
    ) -> dict:
        """Decorate a detached team snapshot with channel liveness."""
        payload = snapshot["payload"]
        visible_events = []
        grouped = {}
        for event, view in snapshot.get("transition_views", []):
            if not cls._transition_visible(event, network):
                continue
            visible_events.append(event)
            node_uuid = event.get("node_uuid")
            current = grouped.get(node_uuid)
            if (
                current is None
                or Session.transition_rank(event)
                > Session.transition_rank(current)
            ):
                grouped[node_uuid] = view
        payload["network"] = network
        payload["transition_events"] = visible_events
        payload["transition_by_node"] = grouped
        return payload

    @staticmethod
    def _transition_visible(event: dict, network: dict) -> bool:
        if event.get("stage") != "in_flight":
            return True
        peer = ((network.get("peers") or {}).get(
            event.get("peer_addr"),
        ) or {})
        state = (peer.get("channel_liveness") or {}).get("state", "unknown")
        return state != "stale"

    def _proposed_nodes(self, events: list[dict]) -> list[dict]:
        proposals: list[dict] = []
        seen: set[str] = set()
        for event in events:
            if event.get("type") != "local_missing_node":
                continue
            node_uuid = event.get("node_uuid")
            source_addr = event.get("peer_addr")
            if not node_uuid or not source_addr or node_uuid in seen:
                continue
            peer_node = self.session.get_cached_peer_subtree(
                source_addr, node_uuid,
            )
            if (
                not peer_node
                or peer_node.deleted
                or peer_node.data.get("type") not in self.REACTABLE
            ):
                continue
            seen.add(node_uuid)
            proposals.append({
                "source_addr": source_addr,
                "node": peer_node.to_dict(),
            })
        return proposals

    def _selected_team(self, requested_uuid: str | None,
                            teams: list[ProtocolNode]) -> ProtocolNode | None:
        selected_uuid = requested_uuid or self._metadata().get("selected_team_uuid")
        selected = self._node(selected_uuid, "team") if selected_uuid else None
        if selected:
            return selected
        if teams:
            return teams[0]
        return None

    def transition_by_node(self, events: list[dict]) -> dict:
        grouped: dict[str, dict] = {}
        for event in events:
            node_uuid = event.get("node_uuid")
            if not node_uuid:
                continue
            current = grouped.get(node_uuid)
            if not current or (Session.transition_rank(event)
                               > Session.transition_rank(current)):
                # The reaction rides with the transition so the view never has
                # to work out whether this side or the peer holds the stale
                # revision.
                grouped[node_uuid] = dict(
                    event, reaction=self.session.reaction_for_event(event),
                )
        return grouped

    def collaboration_context(
        self, topic_uuid: str, network: dict | None = None,
    ) -> dict:
        team = self._node(topic_uuid, "team")
        if not team:
            return {}
        events = self.transition_events(topic_uuid, network)
        return {
            "agenda_items": [
                item.to_dict() for item in self.session.agenda_items(topic_uuid)
            ],
            "transition_events": events,
            "transition_by_node": self.transition_by_node(events),
            "identity_uuid": self._identity_uuid,
            "known_identities": self.session.known_identities(),
        }

    def _network_info(self, topic_uuid: str | None) -> dict:
        if self.collaboration:
            return self.collaboration.network_info(topic_uuid)
        return self.session.get_network_info()

    def interaction_payload(self, team: ProtocolNode) -> dict:
        result = self._interaction_guard(team)
        return {
            "allowed": result.status == "ok",
            "reason": result.reason or "",
        }

    def descendant_teams(
        self, team_uuid: str,
    ) -> list[ProtocolNode]:
        """Locally joined descendants in deterministic parent-first order."""
        root = self._node(team_uuid, "team")
        if not root:
            return []
        descendants = []
        pending = [root]
        seen = {root.uuid}
        while pending:
            parent = pending.pop(0)
            for child_uuid, role in self.child_teams(parent):
                child = self._node(child_uuid, "team")
                if not child or child.uuid in seen:
                    continue
                # Both sides have to name the same seat. A role offered to
                # a team that never took it is not a subteam.
                if not any(
                    holding.data.get("parent_team_uuid") == parent.uuid
                    and holding.data.get("role_uuid") == role.uuid
                    for holding in self.parent_holdings(child)
                ):
                    continue
                seen.add(child.uuid)
                descendants.append(child)
                pending.append(child)
        return descendants

    def participants(self, team_uuid: str) -> list[dict]:
        with self._reading():
            return self._build_participants(team_uuid)

    def _build_participants(self, team_uuid: str) -> list[dict]:
        """Everyone on this topic, and what each of them holds.

        Two populations that used to be one. *Peers* are who this session
        syncs the topic with; *actors* are who has taken a role. Neither
        contains the other: somebody present holding nothing is an observer,
        visible but not part of the team, and somebody holding a role
        this session cannot reach is the reverse, listed with their answer
        unobserved rather than guessed at.
        """
        team = self._node(team_uuid, "team")
        if not team:
            return []
        people = {
            member["uuid"]: {**member, "actor_kind": "individual", "roles": []}
            for member in self._topic_members(team_uuid)
        }
        for role in self.roles(team):
            for holder in self.role_holders(team, role):
                person = people.get(holder["actor_uuid"])
                if person is None:
                    person = people[holder["actor_uuid"]] = {
                        "uuid": holder["actor_uuid"],
                        "name": holder["name"],
                        "picture": holder["picture"],
                        "actor_kind": holder["actor_kind"],
                        "address": "",
                        "addresses": [],
                        "is_self": holder["is_self"],
                        "roles": [],
                    }
                person["roles"].append({
                    "uuid": role.uuid,
                    "name": role.data.get("name") or "Untitled role",
                    "status": holder["status"],
                    "decided_at": holder["decided_at"],
                    "expires_at": holder["expires_at"],
                })
        member = self.member_role(team)
        known = self._known_people()
        if member is not None:
            for application in self.member_application_roots(team):
                actor_uuid = str(application.data.get("actor_uuid") or "")
                resolution = self.member_resolution_projection(
                    team, application.uuid,
                )
                if resolution["state"] not in {"accepted", "contested"}:
                    continue
                person = people.get(actor_uuid)
                if person is None:
                    identity = known.get(actor_uuid) or {}
                    person = people[actor_uuid] = {
                        "uuid": actor_uuid,
                        "name": identity.get("name") or identity.get("address") or "Member",
                        "picture": identity.get("picture") or "",
                        "actor_kind": "individual",
                        "address": identity.get("address") or "",
                        "addresses": identity.get("addresses") or [],
                        "is_self": actor_uuid == self._identity_uuid,
                        "roles": [],
                    }
                if not any(role["uuid"] == member.uuid for role in person["roles"]):
                    person["roles"].append({
                        "uuid": member.uuid,
                        "name": member.data.get("name") or "Member",
                        "status": resolution["state"],
                        "decided_at": None,
                        "expires_at": None,
                    })
        for person in people.values():
            person["is_observer"] = not any(
                item["status"] == "accepted" for item in person["roles"]
            )
        return sorted(
            people.values(),
            key=lambda item: (
                item["is_observer"], not item["is_self"], item["name"],
            ),
        )

    # How many actors are in it is the whole of what distinguishes a template
    # from a working team (2.8). No flag, no separate node type, no mode
    # to switch: a template becomes real by being joined and goes back to
    # being one by being left.
    def actor_uuids(self, team: ProtocolNode) -> set[str]:
        """Every actor currently holding something here.

        Identity counts, because holding Identity is holding a role. A
        request does not: an answer with no offer behind it is somebody
        asking to be in, which is not the same as being in.

        Nor does somebody who has dropped out of a team above this one.
        Their answer here stands and is untouched, but being on a team below
        is being on the team above, so it is no longer a holding - and
        counting it here would let the containment be satisfied one level
        down by somebody the level above had already lost.
        """
        actors = set()
        if holder := self.identity_holder(team):
            actors.add(holder)
        if holder := self.trust_holder(team):
            actors.add(holder)
        actors.update(
            str(application.data.get("actor_uuid") or "")
            for application in self.member_application_roots(team)
            if self.member_resolution_projection(
                team, application.uuid,
            )["state"] == "accepted"
        )
        actors.discard("")
        for role in self.roles(team):
            actors.update(
                holder["actor_uuid"]
                for holder in self.role_holders(team, role)
                if holder["status"] == "accepted"
                and not holder["outside_parent"]
            )
        return actors

    def team_state(self, team: ProtocolNode) -> str:
        count = len(self.actor_uuids(team))
        if not count:
            return "template"
        return "instantiated" if count == 1 else "working"

    def role_reference_hash(
        self, team: ProtocolNode, role: ProtocolNode,
    ) -> str:
        """What accepting this role commits you to.

        The document body plus this role's own definition, and nothing else.
        Hashing the whole team would mean editing the Treasurer's
        accountabilities re-opens the Secretary's acceptance and every
        subteam's; scoping it this way keeps the churn proportional to
        what actually changed for that person.
        """
        return self._cached(
            ("role_hash", team.uuid, role.uuid),
            lambda: self._build_role_reference_hash(team, role),
        )

    def _build_role_reference_hash(
        self, team: ProtocolNode, role: ProtocolNode,
    ) -> str:
        body = self._cached(
            ("body_hash", team.uuid),
            lambda: self.team_reference_hash(team),
        )
        definition = self._content_hash(role, {
            "team_role", "team_accountability", "team_domain",
        })
        combined = f"{body}|{definition}".encode("utf-8")
        return f"sha256:{hashlib.sha256(combined).hexdigest()}"

    def team_reference_hash(self, team: ProtocolNode) -> str:
        """Hash team content without participant decision records.

        Role nodes are deliberately absent. An acceptance covers the document
        body plus the definitions of the roles that participant *holds*, so
        that editing one role does not re-open everybody else's acceptance.
        Nobody holds a role yet, which makes the held-role contribution empty
        and this hash exactly right for now; the scoping becomes visible when
        holdings arrive.
        """
        return self._content_hash(team, {
            "team", "team_section", "team_clause",
        })

    @staticmethod
    def _content_hash(root: ProtocolNode, included_types: set[str]) -> str:
        def content(node: ProtocolNode) -> dict | None:
            if node.deleted or node.data.get("type") not in included_types:
                return None
            children = [
                item
                for child in node.children
                if (item := content(child)) is not None
            ]
            children.sort(key=lambda item: item["uuid"])
            return {
                "uuid": node.uuid,
                "data": copy.deepcopy(node.data),
                "weights": copy.deepcopy(node.weights),
                "children": children,
            }

        encoded = json.dumps(
            content(root),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"

    def _ancestry_problem(
        self, team: ProtocolNode,
    ) -> tuple[str, str] | None:
        """The first thing standing between this team and a root.

        You are on a team only by holding a role on it, and that goes for
        every team above it: a body sits inside each of its parents, so
        taking part in it is taking part in all of them. Every holding must
        therefore lead to a root with each step of that path live - not
        merely one of them. A second parent is a second commitment, not a
        spare route around the first.

        Returns None when every path is clear, otherwise the problem on the
        first holding in order.

        Roots have no holdings and are always reachable.
        """
        return self._path_problem(team, {team.uuid})

    def _path_problem(
        self, team: ProtocolNode, visiting: set[str],
    ) -> tuple[str, str] | None:
        for holding in self.parent_holdings(team):
            problem = self._holding_problem(team, holding, visiting)
            if problem is not None:
                return problem
        return None

    def _holding_problem(
        self, holder: ProtocolNode, holding: ProtocolNode, visiting: set[str],
    ) -> tuple[str, str] | None:
        parent_uuid = str(
            holding.data.get("parent_team_uuid") or "",
        ).strip()
        if parent_uuid in visiting:
            return ("cycle", "")
        parent = self._node(parent_uuid, "team")
        if not parent:
            return ("unjoined", "")
        if not self._holding_is_live(holder, holding):
            return ("unseated", parent.data.get("title") or "")
        if not self._has_current_acceptance(parent):
            return ("stale", parent.data.get("title") or "Parent team")
        return self._path_problem(parent, visiting | {parent_uuid})

    def home_parent_uuid(self, team: ProtocolNode) -> str:
        """Where this team is drawn: the first holding that works.

        Derived, never stored, so it reverses itself when a parent recovers
        and there is no home field to keep in step. Display and navigation
        only - a second parent is a second commitment rather than a spare
        route, so which one a team is *drawn* under decides nothing
        about whether it may be worked in.
        """
        for holding in self.parent_holdings(team):
            if self._holding_problem(
                team, holding, {team.uuid},
            ) is None:
                return str(
                    holding.data.get("parent_team_uuid") or "",
                ).strip()
        return ""

    def _creates_cycle(self, child_uuid: str, parent_uuid: str) -> bool:
        """Whether seating `child` under `parent` would close a loop.

        Best-effort per replica: only teams this session has joined can
        be walked, so a cycle may exist globally that nobody sees whole.
        """
        pending = [parent_uuid]
        seen: set[str] = set()
        while pending:
            uuid = pending.pop()
            if uuid == child_uuid:
                return True
            if uuid in seen:
                continue
            seen.add(uuid)
            node = self._node(uuid, "team")
            if not node:
                continue
            pending.extend(
                str(holding.data.get("parent_team_uuid") or "").strip()
                for holding in self.parent_holdings(node)
            )
        return False

    def _check_parent_chain(self, parent: ProtocolNode) -> SessionResult:
        """Whether a subteam may be seated under `parent`.

        Unlike the read-only guard this includes `parent` itself: hanging
        something below a team means taking part in that team, not
        merely being able to reach it. The guard proper excludes the
        team being written to, which is why a root is always writable.
        """
        if not self._has_current_acceptance(parent):
            title = parent.data.get("title") or "parent team"
            return SessionResult(
                "error",
                reason=(
                    f"Accept the current version of {title} before joining "
                    "its subteam"
                ),
            )
        return self._joining_guard(parent)

    def _joining_guard(self, team: ProtocolNode) -> SessionResult:
        problem = self._ancestry_problem(team)
        if not problem:
            return SessionResult("ok")
        kind, title = problem
        return SessionResult("error", reason={
            "cycle": "team hierarchy contains a cycle",
            "unjoined": (
                "Join and accept every parent team before joining this "
                "subteam"
            ),
            "unseated": (
                "The parent team has not accepted this subteam yet"
            ),
            "stale": (
                f"Accept the current version of {title} before joining its "
                "subteam"
            ),
        }[kind])

    def _has_current_acceptance(self, team: ProtocolNode) -> bool:
        """Whether this participant currently holds a role in this team.

        Taking a role is the only way to be part of a team, so this is
        what "accepted" now means. Deliberately local-only: it runs inside
        the ancestor walk of every guard, and what matters there is this
        session's own standing, which needs no peer lookup.
        """
        # Identity is a role - singular, and shaped differently only for that
        # reason - so holding it is being part of the team. Otherwise the
        # person who speaks for a team could be told to take a role in
        # it before they may act, which is nonsense.
        if (
            self.holds_identity(team)
            or self.holds_trust(team)
            or self._is_current_member(team, self._identity_uuid)
        ):
            return True
        mine = self._identity_uuid
        for role in self.roles(team):
            if not self._offer_for(role, mine):
                continue
            own = self._own_role_decision(role)
            if (
                own
                and own.data.get("decision") == "accepted"
                and not self._is_expired(own.data.get("expires_at"))
                and own.data.get("reference_hash")
                == self.role_reference_hash(team, role)
            ):
                return True
        return False

    def _known_people(self) -> dict[str, dict]:
        """Everyone this session can put a name to, on this topic or not."""
        return self._cached(
            ("known",),
            lambda: {
                person["uuid"]: person
                for person in self.session.known_identities()
                if person.get("uuid")
            },
        )

    def _topic_members(self, team_uuid: str) -> list[dict]:
        return self._cached(
            ("members", team_uuid),
            lambda: self._build_topic_members(team_uuid),
        )

    def _build_topic_members(self, team_uuid: str) -> list[dict]:
        identities = self.session.known_identities()
        by_address = {
            address: identity
            for identity in identities
            for address in (
                identity.get("addresses") or [identity.get("address")]
            )
            if address
        }
        self_identity = next(
            (
                item for item in identities
                if item.get("uuid") == self._identity_uuid
            ),
            {},
        )
        people = [{
            "uuid": self._identity_uuid,
            "name": self_identity.get("name") or "You",
            "picture": self_identity.get("picture") or "",
            "address": self.session.address,
            "addresses": [self.session.address],
            "is_self": True,
        }]
        seen = {self._identity_uuid}
        for address in self.session.peer_addresses(team_uuid):
            identity = by_address.get(address) or {}
            identity_uuid = identity.get("uuid") or f"address:{address}"
            if identity_uuid in seen:
                continue
            seen.add(identity_uuid)
            people.append({
                "uuid": identity_uuid,
                "name": identity.get("name") or address,
                "picture": identity.get("picture") or "",
                "address": address,
                "addresses": identity.get("addresses") or [address],
                "is_self": False,
            })
        return people

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _normalize_expiry(value: str | None) -> str | None:
        normalized = str(value or "").strip()
        if not normalized:
            return None
        try:
            parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat().replace(
            "+00:00", "Z",
        )

    @staticmethod
    def _is_expired(value: str | None) -> bool:
        normalized = TeamLogic._normalize_expiry(value)
        if not normalized:
            return False
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        return parsed <= datetime.now(timezone.utc)

    def organization_payload(self) -> dict:
        with self._reading():
            return self._build_organization_payload()

    def _build_organization_payload(self) -> dict:
        """Return the locally consented team hierarchy.

        The holding graph is a DAG - a team may hold seats in several
        others - but it is drawn as a tree by projecting through home: the
        first holding in order that actually reaches a root (2.5). Home edges
        are a subset of holding edges with at most one per team, so the
        projection is a forest for free.

        The seats home leaves out are *not* hidden. They ride along on the
        team as other_parents, because a second parent nobody can see is
        a trap for whoever deletes the first.

        Membership is topic-scoped: a person appears on a team only
        when this Session knows that peer to discuss that exact topic.
        """
        teams = self.teams()
        summaries = {}
        for team in teams:
            parents = self.parent_payload(team)
            summaries[team.uuid] = {
                "uuid": team.uuid,
                "title": team.data.get("title") or "Untitled team",
                "joined": True,
                "state": self.team_state(team),
                "is_organization": self.is_organization(team),
                "interaction_allowed": (
                    self._interaction_guard(team).status == "ok"
                ),
                "home_parent_uuid": next(
                    (
                        item["team_uuid"] for item in parents
                        if item["is_home"]
                    ),
                    "",
                ),
                "other_parents": [
                    {"uuid": item["team_uuid"], "title": item["title"]}
                    for item in parents if not item["is_home"]
                ],
                "holds_seats": bool(parents),
                "members": self._topic_members(team.uuid),
                "children": [],
            }

        parent_for: dict[str, str] = {}
        children_for: dict[str, list[dict]] = {
            team.uuid: [] for team in teams
        }
        for uuid, summary in summaries.items():
            home = summary["home_parent_uuid"]
            if home and home in summaries:
                parent_for[uuid] = home
                children_for[home].append({"uuid": uuid, "joined": True})

        # Seats offered to teams this session has not joined: their
        # topics are somebody else's to invite, so only the seat shows.
        for parent in teams:
            for child_uuid, role in self.child_teams(parent):
                if child_uuid in summaries or child_uuid == parent.uuid:
                    continue
                children_for[parent.uuid].append({
                    "uuid": child_uuid,
                    "title": role.data.get("name") or "Restricted subteam",
                    "joined": False,
                    # Whose seat this is, is all that is visible from here.
                    "state": "",
                    "interaction_allowed": False,
                    "home_parent_uuid": parent.uuid,
                    "other_parents": [],
                    "holds_seats": True,
                    "members": [],
                    "children": [],
                })

        def build(uuid: str) -> dict:
            summary = dict(summaries[uuid])
            if summary["holds_seats"] and uuid not in parent_for:
                # It says it holds a seat somewhere, but no path from here
                # reaches a root, so it is drawn where it can be seen.
                summary["relationship_status"] = "awaiting_parent_team"
            else:
                summary["relationship_status"] = (
                    "linked" if uuid in parent_for else "root"
                )
            summary["children"] = [
                (
                    build(child["uuid"])
                    if child.get("joined")
                    else dict(child, relationship_status="linked")
                )
                for child in children_for[uuid]
            ]
            return summary

        roots = [
            build(team.uuid)
            for team in teams
            if team.uuid not in parent_for
        ]
        return {"roots": roots, "team_count": len(teams)}

    def _interaction_guard(self, team: ProtocolNode) -> SessionResult:
        problem = self._ancestry_problem(team)
        if not problem:
            return SessionResult("ok")
        kind, title = problem
        return SessionResult("error", reason={
            "cycle": "Read-only: team hierarchy has a cycle",
            "unjoined": "Read-only until every parent team is joined",
            "unseated": (
                "Read-only until the parent accepts this subteam "
                "relationship"
            ),
            "stale": f"Read-only because {title} is not currently accepted",
        }[kind])

    def _interaction_guard_for_node(self, node_uuid: str) -> SessionResult:
        team = self._local_team_topic(node_uuid)
        if not team:
            return SessionResult("error", reason="team not found")
        return self._interaction_guard(team)

    def _interaction_guard_for_reaction(
        self, peer_addr: str, node_uuid: str,
    ) -> SessionResult:
        team = self._team_for_reaction(peer_addr, node_uuid)
        if not team:
            return SessionResult("error", reason="team not found")
        return self._interaction_guard(team)

    def _team_for_reaction(
        self, peer_addr: str, node_uuid: str,
    ) -> ProtocolNode | None:
        if local := self._local_team_topic(node_uuid):
            return local
        for topic_uuid in self.session.peer_topics_for_node(
            peer_addr, node_uuid,
        ):
            if team := self._node(topic_uuid, "team"):
                return team
        return None

    def _offer_authority_guard(
        self, peer_addr: str, node_uuid: str,
    ) -> SessionResult:
        """Only the Identity holder's role offers are adopted.

        A coordination rule, not a security boundary. Nothing in the protocol
        signs content, so this holds exactly as far as trusting the peers you
        chose to sync with - recorded in DESIGN_ROLES_AND_ACTORS.md rather
        than pretended away here. What it does guarantee is that every side
        reaches the same verdict, because it reads only replicated state.
        """
        node = (
            self.session.get_cached_peer_subtree(peer_addr, node_uuid)
            or self.session.protocol.index.get(node_uuid)
        )
        if not node or node.data.get("type") != "team_role_offer":
            return SessionResult("ok")
        team = self._team_for_reaction(peer_addr, node_uuid)
        if not team:
            return SessionResult("ok")
        identity = self.identity_payload(team)
        if identity.get("state") not in {"held", "contested"}:
            return SessionResult(
                "error",
                reason=(
                    "Identity is vacant, so role offers have no authority"
                ),
            )
        if node.data.get("offered_by") != identity.get("holder_actor_uuid"):
            return SessionResult(
                "error",
                reason="this role offer was not made by the Identity holder",
            )
        return SessionResult("ok")

    def _node(self, node_uuid: str | None,
              node_type: str) -> ProtocolNode | None:
        # Every lookup snapshots a subtree out of Session, and one payload
        # asks for the same teams and roles dozens of times over. Cached
        # for the length of a read only, so a mutation always looks again -
        # which matters, because modifying a node replaces the object rather
        # than mutating it.
        if not node_uuid:
            return None
        return self._cached(
            ("node", node_uuid, node_type),
            lambda: self._lookup_node(node_uuid, node_type),
        )

    def _lookup_node(self, node_uuid: str,
                     node_type: str) -> ProtocolNode | None:
        node = self.session.protocol.index.get(node_uuid)
        return (
            node
            if (
                node
                and node.data.get("type") == node_type
                and self.owns_node(node_uuid)
            )
            else None
        )

    def owns_node(self, node_uuid: str, peer_addr: str | None = None) -> bool:
        """Whether one side's node belongs to a Team topic and schema."""
        if peer_addr is not None:
            node = self.session.get_cached_peer_subtree(peer_addr, node_uuid)
            if not node or node.data.get("type") not in self.OWNED_NODE_TYPES:
                return False
            topic_uuids = set(
                self.session.peer_topics_for_node(peer_addr, node_uuid),
            )
            if local_topic := self._local_team_topic(node_uuid):
                topic_uuids.add(local_topic.uuid)
            return any(
                (topic := self.session.get_cached_peer_subtree(peer_addr, topic_uuid))
                and topic.data.get("type") == "team"
                and self._subtree_contains(topic, node_uuid)
                for topic_uuid in topic_uuids
            )

        node = self.session.protocol.index.get(node_uuid)
        if not node or node.data.get("type") not in self.OWNED_NODE_TYPES:
            return False
        return self._local_team_topic(node_uuid) is not None

    def _local_team_topic(self, node_uuid: str) -> ProtocolNode | None:
        node = self.session.protocol.index.get(node_uuid)
        if not node:
            return None
        seen = set()
        current = node
        while current and current.uuid not in seen:
            seen.add(current.uuid)
            if current.data.get("type") == "team":
                parent = self.session.protocol.index.get(current.parent_uuid)
                return current if (
                    parent
                    and parent.data.get("type") == "team_app"
                    and parent.data.get("name") == TEAM_APP_NAME
                ) else None
            current = self.session.protocol.index.get(current.parent_uuid)
        return None

    @staticmethod
    def _subtree_contains(root: ProtocolNode, node_uuid: str) -> bool:
        return root.uuid == node_uuid or any(
            TeamLogic._subtree_contains(child, node_uuid)
            for child in root.children
        )

    def create_agenda_item(
        self, team_uuid: str, text: str, priority: str | None = None,
    ) -> SessionResult:
        team = self._node(team_uuid, "team")
        if not team:
            return SessionResult("error", reason="team not found")
        allowed = self._interaction_guard(team)
        if allowed.status != "ok":
            return allowed
        return self.session.create_agenda_item(
            team.uuid, text, priority,
        )

    def delete_agenda_item(self, item_uuid: str) -> SessionResult:
        if not self.owns_node(item_uuid):
            return SessionResult("error", reason="agenda item not found")
        allowed = self._interaction_guard_for_node(item_uuid)
        if allowed.status != "ok":
            return allowed
        return self.session.delete_agenda_item(item_uuid)

    def set_agenda_item_priority(
        self, item_uuid: str, priority: str | None,
    ) -> SessionResult:
        if not self.owns_node(item_uuid):
            return SessionResult("error", reason="agenda item not found")
        allowed = self._interaction_guard_for_node(item_uuid)
        if allowed.status != "ok":
            return allowed
        return self.session.set_agenda_item_priority(item_uuid, priority)

    def move_agenda_item(self, item_uuid: str, index: int) -> SessionResult:
        if not self.owns_node(item_uuid):
            return SessionResult("error", reason="agenda item not found")
        allowed = self._interaction_guard_for_node(item_uuid)
        if allowed.status != "ok":
            return allowed
        return self.session.move_agenda_item(item_uuid, index)

    def _metadata(self) -> dict:
        """Return a detached read copy of this application's metadata.

        Session hands out the live namespace only to a caller holding its
        lock, so readers snapshot it and writers open their own transaction.
        """
        with self.session.lock:
            return copy.deepcopy(
                self.session.application_metadata(TEAM_APPLICATION_ID),
            )

    def _remember_team(self, team_uuid: str) -> None:
        with self.session.lock:
            metadata = self.session.application_metadata(
                TEAM_APPLICATION_ID,
            )
            metadata["selected_team_uuid"] = team_uuid

    def _team_container(self) -> ProtocolNode:
        return self._folder(
            self._apps_folder(), TEAM_APP_NAME, "team_app",
        )

    def _find_team_container(self) -> ProtocolNode | None:
        apps = next(
            (
                child for child in self.session.protocol.root.live_children()
                if child.data.get("type") == "folder"
                and child.data.get("name") == "apps"
            ),
            None,
        )
        if not apps:
            return None
        return next(
            (
                child for child in apps.live_children()
                if child.data.get("type") == "team_app"
                and child.data.get("name") == TEAM_APP_NAME
            ),
            None,
        )

    def _apps_folder(self) -> ProtocolNode:
        return self._folder(self.session.protocol.root, "apps")

    def _folder(self, parent: ProtocolNode, name: str,
                node_type: str = "folder") -> ProtocolNode:
        for child in parent.children:
            if (child.data.get("name") == name
                    and child.data.get("type") in ("folder", node_type)):
                return child
        return self.session.create_child(
            parent.uuid, {"type": node_type, "name": name}, {},
        ).value
