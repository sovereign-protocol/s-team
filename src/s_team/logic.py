"""Team documents and their consent-based organizational hierarchy.

Every team remains an independently shared topic.  A subteam is an
Team holding a role in its parent: the parent carries an ordinary role
answered for by a Team actor, and the child carries an
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
from pathlib import Path

from sovereign import ApplicationRegistration, ProtocolNode, Session, SessionResult


TEAM_APPLICATION_ID = "team"
TEAM_APP_NAME = "S-Team"
SNAPSHOT_FORMAT = "s-protocol.item-snapshot"
SNAPSHOT_FORMAT_VERSION = 1
FLOW_APPLICATION_ID = "flow"
FLOW_FACADE_API_VERSION = 1
INITIATIVE_APPLICATION_ID = "initiative"
INITIATIVE_FACADE_API_VERSION = 1
class TeamLogic:
    GOVERNANCE_RECORD_TYPES = frozenset({
        "team_trustee_state",
        "team_acceptance",
        "team_membership",
        "team_membership_application",
        "team_membership_invitation",
        "team_item_list",
        "team_trustee_election",
        "team_trustee_candidacy",
        "team_trustee_action",
        "team_trustee_reality",
    })
    # The clause shape: a piece of text and where it sits among its
    # siblings, whose children are the same shape again. Four types use it -
    # a section names itself with a title, the other three carry text - and
    # it is a *shape* rather than a type on purpose. The machinery around it
    # already works without knowing what the text is called: Core's
    # next_child_order takes a type name from the caller, and _content_hash
    # takes a set of them. So another application can hold the same shape
    # under its own names without either importing the other, and without
    # this vocabulary reaching Core.
    #
    # Two levels, not arbitrary depth: a section holds clauses and a clause
    # holds nothing. The shape permits nesting; this document does not use it.
    CONTENT_TYPES = frozenset({
        "team_agreement",
        "team_section", "team_clause", "team_accountability", "team_domain",
    })
    # What each content type calls the words it carries.
    CONTENT_TEXT_FIELDS = {
        "team_agreement": "name",
        "team_section": "title",
    }
    CONTENT_FIELDS = {
        "team_agreement": (
            frozenset({"type", "name", "version", "order"}), frozenset(),
        ),
        "team_section": (frozenset({"type", "title", "order"}), frozenset()),
        "team_clause": (frozenset({"type", "text", "order"}), frozenset()),
        "team_accountability": (
            frozenset({"type", "text", "order"}), frozenset(),
        ),
        "team_domain": (frozenset({"type", "text", "order"}), frozenset()),
    }

    # Taking part in a role is recorded, not stored as content. A role and
    # its accountabilities are what people agree to and are edited like any
    # other text; an answer and a seat are facts *about* who is doing what,
    # and facts are appended. They used to be neither: an answer was
    # rewritten in place, and giving up a seat deleted the holding outright -
    # so who held a role, and when, was not anywhere.
    #
    # There is no third record. A role was once offered before it could be
    # answered, which made taking one an act with two authors and gave every
    # holding a second, revocable half. Nobody offers now: a member takes a
    # role, and a team whose members are already members here takes a seat,
    # so the answer is the whole of it.
    ROLE_RECORD_TYPES = frozenset({
        "team_role_decision", "team_role_holding",
    })
    ROLE_DECISIONS = frozenset({"accepted", "refused"})
    HOLDING_STATES = frozenset({"held", "given_up"})
    ROLE_RECORD_FIELDS = {
        # decided_by names who answered on a Team's behalf, and
        # seated_member_uuids is what they saw when they did: every member of
        # the seated team, all of whom had to be members here already. The
        # set is kept rather than hashed, following the electorate on an
        # election, so it can be read back rather than only compared.
        "team_role_decision": (
            frozenset({
                "type", "actor_uuid", "decision", "previous_decision_uuid",
                "decided_at", "reference_hash",
            }),
            frozenset({"expires_at", "decided_by", "seated_member_uuids"}),
        ),
        "team_role_holding": (
            frozenset({
                "type", "parent_team_uuid", "role_uuid", "order", "state",
                "previous_holding_uuid",
            }),
            frozenset(),
        ),
    }
    TRUSTS = frozenset({"identity", "trust"})
    # Which trusteeship decides who belongs. Invitations and removals rest on
    # this one, and it was the same string written out at each of them. Named
    # here so that "membership is Identity's" is something the model says
    # once, in a place that can be read, rather than a literal repeated
    # sixteen times.
    #
    # What Identity decides is narrower than it was: which memberships this
    # team supports and when each is open, plus removing one person after the
    # fact. Whether to be on the team is the Actor's own answer.
    MEMBERSHIP_TRUST = "identity"
    TRUSTEE_CAUSES = frozenset({
        "genesis", "election", "resignation", "resolution",
    })
    # How a badge came to stand or stop standing. Identity issues founding
    # and accepted badges. The holder may invalidate their own badge, while
    # Identity may terminate it.
    MEMBERSHIP_CAUSES = frozenset({
        "genesis", "acceptance", "departure", "removal",
    })
    ACTION_KINDS = frozenset({
        "membership_invitation", "membership_removal", "trustee_resignation",
        "election_implementation", "domain_action",
    })
    GOVERNANCE_FIELDS = {
        "team_trustee_state": (
            frozenset({
                "type", "trust", "holder_actor_uuid", "previous_state_uuid",
                "cause", "acted_by", "acted_at", "authority_basis_uuid",
                "signals", "consideration", "expectation",
            }),
            # The election that informed it, when one did. A pointer for
            # whoever reads the trail, not a proof: nothing here checks the
            # holder against the result, because a person settles the seat.
            frozenset({"process_uuid"}),
        ),
        # Standing, the Actor's answer to the membership requirement, and any
        # Agreement consent. An accepted badge names the application Identity
        # issued it for; genesis, departure and removal name none.
        #
        # reference_hash preserves the exact text the Actor saw for audit and
        # divergence review. Badge freshness follows Identity's explicit
        # Agreement version: edits within that version are non-substantial;
        # changing the version requires renewal.
        "team_membership": (
            frozenset({
                "type", "actor_uuid", "state", "membership_type_uuid",
                "previous_membership_uuid", "cause", "reference_hash",
                "acted_by", "acted_at", "authority_basis_uuid",
                "acceptance_text", "agreement_accepted",
                "agreement_version", "membership_info",
                "acceptance_requirement",
                "signals", "consideration", "expectation",
            }),
            frozenset({"invitation_uuid", "application_uuid"}),
        ),
        # An Actor's acceptance of one agreement, at the text it had when
        # they accepted. The membership record keeps its own copy of what was
        # asked and answered at admission - that is evidence of an event, and
        # stays where the event is. This is the standing fact instead: it is
        # renewed when the agreement changes, without anybody being admitted
        # again.
        #
        # The hash is what makes it mean anything. A version label is a
        # sentence somebody typed; `reference_hash` is the agreement as it
        # actually read, so "who accepted this exact text" is answerable from
        # the tree rather than taken on trust.
        "team_acceptance": (
            frozenset({
                "type", "actor_uuid", "agreement_uuid", "reference_hash",
                "text", "previous_acceptance_uuid", "accepted_at",
            }),
            frozenset(),
        ),
        # The Actor's signed application. It snapshots the invitation's
        # request and the Actor's response so Identity can issue a badge for
        # exactly what was asked and answered, even if the editable document
        # subsequently changes.
        "team_membership_application": (
            frozenset({
                "type", "actor_uuid", "membership_type_uuid",
                "invitation_uuid", "previous_membership_uuid", "applied_at",
                "membership_info", "acceptance_requirement",
                "acceptance_text", "agreement_accepted",
                "agreement_version", "reference_hash",
            }),
            frozenset(),
        ),
        # Identity opening one membership type to the pool, for a window.
        # One chain per type: reopening continues it rather than starting a
        # second, so there is only ever one invitation per type at a time and
        # the rest is history.
        "team_membership_invitation": (
            frozenset({
                "type", "membership_type_uuid", "previous_invitation_uuid",
                "state", "opened_by", "opened_at", "expires_at",
                "authority_basis_uuid",
            }),
            frozenset({"closed_at"}),
        ),
        # One member's answer to "what of this team's work do I have
        # here". Not a record per item: an item is not a decision anybody
        # takes, it is something a client either holds or does not, and the
        # list is that client's own statement of it. Appended rather than
        # rewritten because that is what carries it to the others without
        # each of them being asked to accept a stranger's list.
        "team_item_list": (
            frozenset({
                "type", "actor_uuid", "items", "previous_list_uuid",
                "recorded_at",
            }),
            frozenset(),
        ),
        # An election is a flow the team runs, and this says which flow
        # is one. It used to carry the whole apparatus of a verified
        # decision - the electorate, the target seat, the facilitator and
        # their authority - because implementing it was automatic and had
        # to be checked. Nothing is implemented automatically now: the
        # result informs whoever settles the seat, and they answer for it.
        "team_trustee_election": (
            frozenset({
                "type", "trust", "process_uuid",
                "triggered_by", "triggered_at",
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
        # The decision itself: what was decided, about what, on what
        # reading, expecting what. `value` is the decision in words;
        # `payload` is whatever structure the act also needs.
        "team_trustee_action": (
            frozenset({
                "type", "trust", "action_kind", "subject_uuid", "acted_by",
                "acted_at", "authority_basis_uuid", "value", "signals",
                "consideration", "expectation", "payload",
            }),
            frozenset(),
        ),
        # What turned out to be so. One record per observation rather than a
        # list on the decision: observers differ, they write at different
        # times, and concurrent observations have to merge as a set instead
        # of one list overwriting another.
        #
        # It names no action, because it is a child of the one it observes.
        "team_trustee_reality": (
            frozenset({
                "type", "observed_by", "observed_at", "reality",
                "authority_basis_uuid",
            }),
            frozenset(),
        ),
    }
    # A membership this team supports: a name and what it asks of somebody.
    # Content rather than a record - it is edited in place, it is part of what
    # the pool reads before answering, and Identity creates and deletes it.
    #
    # Deleting one needs no cascade. A membership names its type by uuid, so
    # the type going away stops every membership on it from resolving and
    # those actors are back in the pool - without one record being rewritten.
    MEMBERSHIP_TYPE_TYPE = "team_membership_type"

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
            frozenset({"team"}),
            self.shared_topics,
            self.accept_team_topic_invitation,
            assignment_scoped=True,
            mount_invitation=True,
            on_peer_update=self.reconcile_governance_updates,
        )

    def shared_topics(self) -> list[ProtocolNode]:
        return self.teams()

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

    # A name is the whole of how a role or a team is referred to: a
    # badge, a seat in a parent, a line in the organization tree.
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

    # No container under an agreement or a section: each holds one kind, so
    # the parent is already the predicate. A container there would only add
    # depth - and a level that has to exist before a peer's section can be
    # adopted, which would cost the one-pass adoption of a new subtree.
    def sections(self, team: ProtocolNode) -> list[ProtocolNode]:
        agreement = self.agreement(team, create=False)
        return self._ordered(agreement) if agreement else []

    def clauses(self, section: ProtocolNode) -> list[ProtocolNode]:
        return self._ordered(section)

    # A subteam is not a link any more: it is a Team holding a
    # role in its parent, the same shape as a person holding one. The parent
    # side is an ordinary role with an answer given for a Team actor; the
    # child side is a team_role_holding naming which role in which parent.
    #
    # The child keeps its own record rather than only the parent holding one,
    # because somebody who has joined the child but not the parent still has
    # to know a parent exists - that is what tells them the team is
    # read-only until they join it.

    def parent_holdings(self, team: ProtocolNode) -> list[ProtocolNode]:
        """This team's roles in other teams, in declared order.

        The seats it holds now: the end of each seat's chain, and only where
        that end still says held. A seat given up stays as history, which is
        what it did not do while unseating deleted the record.
        """
        records = self._held(team, "seats")
        live = []
        seen = set()
        for record in records:
            seat = (
                record.data.get("parent_team_uuid"),
                record.data.get("role_uuid"),
            )
            if seat in seen:
                continue
            seen.add(seat)
            head = self._chain_head(
                [
                    other for other in records
                    if (
                        other.data.get("parent_team_uuid"),
                        other.data.get("role_uuid"),
                    ) == seat
                ],
                "previous_holding_uuid",
            )
            if head is not None and head.data.get("state") == "held":
                live.append(head)
        return live

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
        """(child team uuid, the role it answered for) for each subunit.

        Read from the answers, because the answer is the only record there
        is. It used to be read from the invitations, which listed a team as a
        subunit from the moment somebody suggested it - the seat it never
        took drew a branch of the tree that nobody had agreed to.
        """
        found = []
        for role in self.roles(team):
            for child in self._held(role, "answers"):
                # Only a Team is answered *for*, so the presence of somebody
                # who gave the answer is what says this is one.
                if not str(child.data.get("decided_by") or "").strip():
                    continue
                child_uuid = str(child.data.get("actor_uuid") or "").strip()
                if child_uuid:
                    found.append((child_uuid, role))
        return found

    def _team_holds_role(
        self, role: ProtocolNode, actor_uuid: str,
    ) -> bool:
        """Whether a Team actor's holding of this role is live.

        Its accepted answer, exactly as for a person. Deliberately not
        checking that the answer is against the current version: that would
        mean every edit to a parent freezes every subteam until somebody
        re-accepts on each one's behalf, on top of each person re-accepting
        their own roles. Left for step 3b to decide with the ANY-path guard.
        """
        # The end of the actor's chain, not the first link in it. An actor
        # who took the seat and later stepped out has two answers now that
        # stepping out appends rather than deletes, and reading the earlier
        # one said they still held it.
        answer = self._role_decision_for(role, actor_uuid)
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
    def _ordered(parent: ProtocolNode, node_type: str | None = None) -> list[ProtocolNode]:
        return sorted(
            [
                child for child in parent.live_children()
                if node_type is None or child.data.get("type") == node_type
            ],
            key=lambda node: (float(node.data.get("order", 0)), node.created_at),
        )

    # Every kind of node a team holds lives in a container of its own. The
    # container's uuid is what Core is handed - to order siblings, to declare
    # adoption over a scope, to hash one - so none of those need a type name,
    # and this vocabulary stays here rather than reaching Core.
    #
    # The names are this application's convention: it looks its own container
    # up by name under a parent it already holds, and passes on a uuid.
    CONTAINER_TYPE = "team_container"

    def _container(self, parent: ProtocolNode | str,
                   name: str, create: bool = True) -> ProtocolNode | None:
        index = self.session.protocol.index
        # A node handed in is used as given: it may be a peer's, read out of a
        # perspective and so absent from the local index. Only a uuid needs
        # resolving, and only a node this client holds can gain a container.
        parent_node = index.get(parent) if isinstance(parent, str) else parent
        if parent_node is None:
            return None
        parent_uuid = parent_node.uuid
        for child in parent_node.live_children():
            if (child.data.get("name") == name
                    and child.data.get("type") == self.CONTAINER_TYPE):
                return child
        # A caller may be holding a node read before the container existed.
        # The uuid is derived, so the index answers without the parent having
        # to be current.
        held = index.get(f"{name}:{parent_uuid}")
        if held is not None and not held.deleted:
            return held
        if not create:
            return None
        result = self.session.ensure_container(
            parent_uuid, name, self.CONTAINER_TYPE,
        )
        if result.status != "ok":
            return None
        return index.get(result.value.uuid)

    def _is_in(self, node: ProtocolNode | None,
               parent: ProtocolNode, name: str) -> bool:
        """Whether this node sits in that parent's named container."""
        if node is None:
            return False
        container = self._container(parent, name, create=False)
        return container is not None and node.parent_uuid == container.uuid

    def _held(self, parent: ProtocolNode | str, name: str) -> list[ProtocolNode]:
        """What one of this parent's containers holds, in order."""
        container = self._container(parent, name, create=False)
        return self._ordered(container) if container is not None else []

    # Where each kind of record lives. One container per handling class, so
    # a declaration, an ordering and a hash scope are each one uuid rather
    # than a list of type names.
    RECORD_CONTAINERS = {
        "team_acceptance": "acceptances",
        "team_membership": "members",
        "team_membership_application": "membership-applications",
        "team_membership_invitation": "membership-invitations",
        "team_item_list": "lists",
        "team_trustee_state": "trusteeship",
        "team_trustee_election": "elections",
        "team_trustee_candidacy": "candidacies",
        "team_trustee_action": "actions",
    }
    # The agreement is a node of its own rather than two fields on the team.
    # A team is a body of people; its agreement is the text they hold to, and
    # an acceptance names one - which needs something to name.
    #
    # Its uuid is derived like a container's, so every client reaches the same
    # agreement without adopting a shell, and only what is written in it -
    # name, version, sections - is negotiated. Further agreements, if a team
    # ever keeps more than one, are ordinary content beside it.
    AGREEMENT_TYPE = "team_agreement"

    def agreement(self, team: ProtocolNode,
                  create: bool = True) -> ProtocolNode | None:
        container = self._container(team, "agreements", create=create)
        if container is None:
            return None
        # The container is searched before the index, because `team` may be a
        # peer's root read out of a perspective: the uuid is the same on both
        # sides, so the index would answer with this client's copy.
        for child in container.live_children():
            if child.data.get("type") == self.AGREEMENT_TYPE:
                return child
        node_uuid = f"agreement:{team.uuid}"
        held = self.session.protocol.index.get(node_uuid)
        if held is not None and not held.deleted:
            return held
        if not create:
            return None
        created = self.session.create_child(
            container.uuid,
            {"type": self.AGREEMENT_TYPE, "name": "", "version": "", "order": 0},
            {},
            node_uuid=node_uuid,
        )
        if created.status != "ok":
            return None
        return self.session.protocol.index.get(node_uuid)

    # Everybody the records name. Derived rather than stored, because an
    # Actor record would repeat what is already said twice over: who somebody
    # is comes from Core's identities, and that they have anything to do with
    # this team comes from the membership, answer and acceptance chains. A
    # third copy could only go stale against the two it was copied from.
    ACTOR_SOURCES = (
        ("team_membership", "actor_uuid"),
        ("team_membership_application", "actor_uuid"),
        ("team_acceptance", "actor_uuid"),
    )

    def actors(self, team: ProtocolNode) -> list[dict]:
        """Everyone this team knows about, person or team.

        A team is an actor here exactly as a person is: it answers on a role
        and takes a seat, which is why `kind` is read from what the uuid
        turns out to name rather than from anything the record says.
        """
        found: dict[str, None] = {}
        for node_type, field in self.ACTOR_SOURCES:
            for record in self.governance_records(team, node_type):
                if actor_uuid := str(record.data.get(field) or "").strip():
                    found.setdefault(actor_uuid, None)
        for role in self.roles(team):
            for answer in self._held(role, "answers"):
                if actor_uuid := str(answer.data.get("actor_uuid") or "").strip():
                    found.setdefault(actor_uuid, None)
        # Members first: it is the only source that names this session "You"
        # rather than by whatever their profile happens to say.
        people = {
            **self._known_people(),
            **{
                person["uuid"]: person
                for person in self._topic_members(team.uuid)
                if person.get("uuid")
            },
        }
        actors = []
        for actor_uuid in found:
            node = self.session.protocol.index.get(actor_uuid)
            is_team = bool(node) and node.data.get("type") == "team"
            person = people.get(actor_uuid, {})
            actors.append({
                "uuid": actor_uuid,
                "kind": "team" if is_team else "person",
                "name": (
                    str(node.data.get("title") or "") if is_team
                    else str(person.get("name") or "")
                ),
                "membership": self.membership_projection(
                    team, actor_uuid,
                )["state"],
                "is_self": actor_uuid == self._identity_uuid,
            })
        return sorted(actors, key=lambda item: (
            item["kind"], item["name"].lower(), item["uuid"],
        ))

    def accept_agreement(self, team_uuid: str, text: str = "") -> SessionResult:
        """Record that this Actor accepts the agreement as it now reads.

        Appended, never rewritten: accepting an updated agreement continues
        the Actor's chain, so what somebody accepted and when stays readable
        rather than being overwritten by what they accept next.
        """
        team = self._node(team_uuid, "team")
        if not team:
            return SessionResult("error", reason="team not found")
        agreement = self.agreement(team, create=False)
        if agreement is None or not self.agreement_exists(team):
            return SessionResult(
                "error", reason="there is no agreed Agreement to accept",
            )
        reference_hash = self.team_reference_hash(team)
        if not reference_hash:
            return SessionResult(
                "error", reason="there is no agreed Agreement to accept",
            )
        current = self._acceptance_head(team, self._identity_uuid)
        return self.append_governance_record(team.uuid, {
            "type": "team_acceptance",
            "actor_uuid": self._identity_uuid,
            "agreement_uuid": agreement.uuid,
            "reference_hash": reference_hash,
            "text": str(text or "").strip(),
            "previous_acceptance_uuid": current.uuid if current else "",
            "accepted_at": self._now(),
        })

    def _realities_of(self, action: ProtocolNode) -> list[ProtocolNode]:
        """What was observed of one decision. An action holds only these."""
        return sorted(
            action.live_children(),
            key=lambda node: (node.created_at, node.uuid),
        )

    def _acceptance_head(
        self, team: ProtocolNode, actor_uuid: str,
    ) -> ProtocolNode | None:
        return self._chain_head(
            [
                record
                for record in self.governance_records(team, "team_acceptance")
                if record.data.get("actor_uuid") == actor_uuid
            ],
            "previous_acceptance_uuid",
        )

    def acceptance_projection(
        self, team: ProtocolNode, actor_uuid: str,
    ) -> dict:
        """Where this Actor's acceptance of the agreement has got to.

        Derived from the chain rather than stored: whether an acceptance is
        current is a comparison against the agreement as it reads now, and a
        recorded answer would go on being true after it stopped being.
        """
        head = self._acceptance_head(team, actor_uuid)
        if head is None:
            return {"state": "absent", "uuid": "", "reference_hash": ""}
        accepted = str(head.data.get("reference_hash") or "")
        return {
            "state": (
                "current" if accepted == self.team_reference_hash(team)
                else "outdated"
            ),
            "uuid": head.uuid,
            "reference_hash": accepted,
            "agreement_uuid": str(head.data.get("agreement_uuid") or ""),
            "text": str(head.data.get("text") or ""),
            "accepted_at": str(head.data.get("accepted_at") or ""),
        }

    def _acceptance_schema_error(self, data: dict) -> str | None:
        for field in ("agreement_uuid", "reference_hash", "accepted_at"):
            if not str(data.get(field) or "").strip():
                return f"an acceptance requires {field}"
        return None

    def _assess_agreement_acceptance(
        self, team: ProtocolNode, data: dict, actor_uuid: str,
    ) -> dict | None:
        """Nobody accepts on anybody else's behalf, and only what is here.

        Authorship is already checked against `actor_uuid`, so what is left
        is that the agreement named is this team's - an acceptance of some
        other team's text says nothing about this one.
        """
        agreement = self.agreement(team, create=False)
        if agreement is None or data.get("agreement_uuid") != agreement.uuid:
            return {
                "status": "invalid",
                "reason": "an acceptance must name this Team's Agreement",
            }
        return None

    # Containers this team always has, and the per-role ones beneath them.
    # Answers and seats stay under the role they are about: the role is the
    # object, and a hash scope excludes them by container rather than by
    # naming their types.
    TEAM_CONTAINERS = (
        "agreements", "roles", "membership-types", "seats",
        *RECORD_CONTAINERS.values(),
    )
    ROLE_CONTAINERS = ("accountabilities", "domains", "answers", "holdings")
    ROLE_RECORD_CONTAINERS = {
        "team_role_decision": "answers",
        "team_role_holding": "holdings",
    }

    def _ensure_containers(self, team: ProtocolNode) -> None:
        for name in self.TEAM_CONTAINERS:
            self._container(team, name)
        self.agreement(team)
        for role in self.roles(team):
            for name in self.ROLE_CONTAINERS:
                self._container(role, name)

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
            identity = self._create_trusteeship(result.value, "identity")
            current = self._node(result.value.uuid, "team")
            member = self._found_membership(current)
            trust = self._create_trusteeship(result.value, "trust")
            self._remember_team(result.value.uuid)
            return SessionResult(
                "ok",
                value=result.value.uuid,
                effects=[
                    *result.effects, *member.effects, *identity.effects,
                    *trust.effects,
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
                "error",
                reason="only the Identity holder can fill a role with a team",
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
        identity = self._create_trusteeship(child, "identity")
        current = self._node(child.uuid, "team")
        member = self._found_membership(current)
        trust = self._create_trusteeship(child, "trust")
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
                *trust.effects, *seated.effects,
            ],
        )

    # What a copy carries. Everything a team holds beyond this is
    # somebody's record of taking part in it - Identity, answers, the seats
    # it holds elsewhere - and copying the text is not copying who agreed
    # to it.
    CLONED_TYPES = frozenset({
        AGREEMENT_TYPE, "team_section", "team_clause",
        "team_role", "team_accountability", "team_domain",
    })
    # The containers those live in travel too: a copy of the text without the
    # places it sits in is not the same document.
    CLONED_CONTAINERS = frozenset({
        "agreements", "roles", "accountabilities", "domains",
    })

    def _is_cloned(self, data: dict) -> bool:
        if data.get("type") in self.CLONED_TYPES:
            return True
        return (
            data.get("type") == self.CONTAINER_TYPE
            and data.get("name") in self.CLONED_CONTAINERS
        )

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
        if agreement_version := source.data.get("agreement_version"):
            data["agreement_version"] = agreement_version
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

    def export_snapshot(
        self, team_uuid: str, name: str = "", description: str = "",
    ) -> SessionResult:
        source = self._node(team_uuid, "team")
        if not source:
            return SessionResult("error", reason="team not found")
        source_name = str(source.data.get("title") or "Untitled team")
        content = {
            "agreement_title": str(source.data.get("agreement_title") or ""),
            "agreement_version": str(source.data.get("agreement_version") or ""),
            "children": self._export_snapshot_content(source),
        }
        return SessionResult("ok", value={
            "format": SNAPSHOT_FORMAT,
            "format_version": SNAPSHOT_FORMAT_VERSION,
            "item_type": "team",
            "name": str(name or "").strip() or f"{source_name} snapshot",
            "description": str(description or "").strip(),
            "source_name": source_name,
            "saved_at": self._now(),
            "content": content,
        })

    def create_from_snapshot(
        self, document: dict, title: str = "",
    ) -> SessionResult:
        error = self._snapshot_error(document, "team")
        if error:
            return SessionResult("error", reason=error)
        content = document["content"]
        requested = str(title or "").strip() or str(
            document.get("source_name") or document.get("name") or "Untitled team"
        )
        data = {
            "type": "team",
            "title": self._distinct_name(requested, self._team_titles()),
        }
        for field in ("agreement_title", "agreement_version"):
            if content.get(field):
                data[field] = str(content[field])
        created = self.session.create_child(self._team_container().uuid, data, {})
        if created.status != "ok":
            return created
        copied = self._import_snapshot_content(
            content.get("children"), created.value.uuid,
        )
        if copied.status != "ok":
            self.session.delete(created.value.uuid)
            return copied
        self._remember_team(created.value.uuid)
        return SessionResult(
            "ok", value=created.value.uuid,
            effects=[*created.effects, *copied.effects],
        )

    def _export_snapshot_content(self, source: ProtocolNode) -> list[dict]:
        return [
            {
                "data": dict(child.data),
                "weights": dict(child.weights),
                "children": self._export_snapshot_content(child),
            }
            for child in source.live_children()
            if self._is_cloned(child.data)
        ]

    def _import_snapshot_content(
        self, children: object, target_uuid: str,
    ) -> SessionResult:
        if not isinstance(children, list):
            return SessionResult("error", reason="snapshot team content is invalid")
        effects = []
        for child in children:
            if not isinstance(child, dict) or not isinstance(child.get("data"), dict):
                return SessionResult("error", reason="snapshot team item is invalid")
            data = child["data"]
            if not self._is_cloned(data):
                return SessionResult("error", reason="snapshot contains an unsupported team item")
            weights = child.get("weights", {})
            if not isinstance(weights, dict):
                return SessionResult("error", reason="snapshot team item weights are invalid")
            created = self.session.create_child(target_uuid, dict(data), dict(weights))
            if created.status != "ok":
                return created
            nested = self._import_snapshot_content(
                child.get("children", []), created.value.uuid,
            )
            if nested.status != "ok":
                return nested
            effects.extend([*created.effects, *nested.effects])
        return SessionResult("ok", effects=effects)

    @staticmethod
    def _snapshot_error(document: object, item_type: str) -> str:
        if not isinstance(document, dict):
            return "snapshot file is invalid"
        if document.get("format") != SNAPSHOT_FORMAT:
            return "not an S-Protocol item snapshot"
        if document.get("format_version") != SNAPSHOT_FORMAT_VERSION:
            return "snapshot version is not supported"
        if document.get("item_type") != item_type:
            return f"snapshot does not contain a {item_type}"
        if not isinstance(document.get("content"), dict):
            return "snapshot content is invalid"
        return ""

    def _copy_content(
        self, source: ProtocolNode, target_uuid: str,
    ) -> SessionResult:
        """Recreate a node's copyable children under a new parent."""
        effects = []
        for child in source.live_children():
            if not self._is_cloned(child.data):
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
        agreement = self.agreement(team)
        if agreement is None:
            return SessionResult("error", reason="agreement unavailable")
        result = self.session.create_child(
            agreement.uuid,
            {
                "type": "team_section",
                "title": normalized,
                "order": self.session.next_child_order(agreement.uuid),
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
                "order": self.session.next_child_order(section.uuid),
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
        team = self._node(team_uuid, "team")
        agreement = self.agreement(team) if team else None
        if agreement is None:
            return SessionResult("error", reason="team not found")
        return self._retitle(
            agreement.uuid, self.AGREEMENT_TYPE, "name", title,
        )

    def set_agreement_version(
        self, team_uuid: str, version: str,
    ) -> SessionResult:
        """Set the Agreement's human-readable version label.

        This is ordinary Agreement content. It has no authority of its own;
        authority comes from the Identity holders exposing the same complete
        Agreement in their perspectives.
        """
        team = self._node(team_uuid, "team")
        agreement = self.agreement(team) if team else None
        if agreement is None:
            return SessionResult("error", reason="team not found")
        return self._retitle(
            agreement.uuid, self.AGREEMENT_TYPE, "version", version,
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
        release = self.session.end_topic_sharing(team.uuid)
        result = self.session.delete(team.uuid)
        if result.status != "ok":
            return result
        result.effects = [*effects, *release.effects, *result.effects]
        remaining = [item for item in self.teams() if item.uuid != team.uuid]
        self._remember_team(remaining[0].uuid if remaining else "")
        return result

    ARCHIVE_FORMAT = "s-team.archive"
    ARCHIVE_FORMAT_VERSION = 1

    def _archive_directory(self) -> Path:
        configured = str(self.config.get("archive_directory") or "").strip()
        if configured:
            return Path(configured)
        # Beside this client's own data, because that is what an archive is.
        # Never the working directory: that is shared with whatever else is
        # running there and belongs to nobody in particular.
        return Path(
            str(self.config.get("data_directory") or "").strip() or ".",
        ) / "team-archive"

    def archives(self) -> list[dict]:
        """Every archive this client has written, newest first."""
        directory = self._archive_directory()
        if not directory.is_dir():
            return []
        found = []
        for path in directory.glob("*.json"):
            try:
                with path.open(encoding="utf-8") as handle:
                    document = json.load(handle)
            except (OSError, ValueError):
                continue
            if document.get("format") != self.ARCHIVE_FORMAT:
                continue
            found.append({
                "file": path.name,
                "title": document.get("title") or "Untitled team",
                "team_uuid": (document.get("team") or {}).get("uuid") or "",
                "archived_at": document.get("archived_at") or "",
                "restorable": not self.session.has_node(
                    (document.get("team") or {}).get("uuid") or "",
                ),
            })
        return sorted(found, key=lambda item: item["archived_at"], reverse=True)

    def archive_team(self, team_uuid: str) -> SessionResult:
        """Write a team out as a file and take it off this client.

        Local, and only local. Nothing is sent: sharing ends, so this
        client stops publishing and polling, and every other client keeps
        its own copy and its own access. Archiving is not deleting for
        everybody, and it is not a decision about the team.

        The file carries **no relay coordinates**. An archive is a record of
        what the team was, not a way back onto a channel - restoring one
        brings the content back as a private topic that has to be put on a
        bridge again deliberately, by somebody who still has the invitation.

        And it leaves **no stub**. A row saying "there used to be a team
        here" is a second thing to keep in step with the file, and the file
        is the record.
        """
        team = self._node(team_uuid, "team")
        if not team:
            return SessionResult("error", reason="team not found")
        document = {
            "format": self.ARCHIVE_FORMAT,
            "format_version": self.ARCHIVE_FORMAT_VERSION,
            "archived_at": self._now(),
            "archived_by": self._identity_uuid,
            "title": team.data.get("title") or "Untitled team",
            "team": team.to_dict(),
        }
        directory = self._archive_directory()
        stem = re.sub(r"[^A-Za-z0-9._-]+", "-", document["title"]).strip("-")
        path = directory / f"{stem or 'team'}-{team.uuid[:8]}.json"
        try:
            directory.mkdir(parents=True, exist_ok=True)
            # Written and closed before anything is removed. A half-written
            # archive beside a deleted team is the one outcome worth ruling
            # out, and it costs one flush to do it.
            with path.open("w", encoding="utf-8") as handle:
                json.dump(document, handle, ensure_ascii=False, indent=2)
        except OSError as error:
            return SessionResult(
                "error", reason=f"could not write the archive: {error}",
            )
        removed = self.delete_team(team.uuid)
        if removed.status != "ok":
            path.unlink(missing_ok=True)
            return removed
        return SessionResult(
            "ok", value=str(path), effects=removed.effects,
        )

    def restore_team(self, file_name: str) -> SessionResult:
        """Graft an archived team back in, as a private topic.

        The same graft a topic invitation uses, because it is the same act:
        a subtree arriving from outside. What it does not bring back is any
        channel - the archive never carried one - so a restored team is
        private until somebody puts it back on one.
        """
        path = self._archive_directory() / Path(str(file_name or "")).name
        if not path.is_file():
            return SessionResult("error", reason="archive not found")
        try:
            with path.open(encoding="utf-8") as handle:
                document = json.load(handle)
        except (OSError, ValueError) as error:
            return SessionResult(
                "error", reason=f"could not read the archive: {error}",
            )
        if document.get("format") != self.ARCHIVE_FORMAT:
            return SessionResult("error", reason="not a Team archive")
        stored = document.get("team")
        if not stored:
            return SessionResult("error", reason="the archive holds no team")
        subtree = ProtocolNode.from_dict(stored)
        if self.session.has_node(subtree.uuid):
            return SessionResult("error", reason="that team is already here")
        grafted = self.session.accept_topic_invitation(
            subtree, self._team_container().uuid,
        )
        if grafted.status != "ok":
            return grafted
        self._remember_team(grafted.value)
        return grafted

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
        member = self._found_membership(team)
        identity = self._create_trusteeship(team, "identity")
        trust = self._create_trusteeship(team, "trust")
        return SessionResult(
            "ok",
            value=identity.value,
            effects=[
                *member.effects, *identity.effects, *trust.effects,
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

    FOUNDING_MEMBERSHIP_TYPE = "Member"

    def _found_membership(self, team: ProtocolNode) -> SessionResult:
        """Every team starts with one membership type and one member on it.

        The type comes first because the membership names it: standing is
        the pair "the chain says member" and "the type it names still
        exists", so a genesis membership with nothing to point at would read
        as somebody in the pool of their own team.

        One type, not a set of them. What the team supports beyond the plain
        case is a judgement about that team, and a fixture shipped with every
        new one would be this application deciding it in advance.
        """
        types = self._container(team, "membership-types")
        members = self._container(team, self.RECORD_CONTAINERS["team_membership"])
        if types is None or members is None:
            return SessionResult("error", reason="team containers unavailable")
        created = self.session.create_child(
            types.uuid,
            {
                "type": self.MEMBERSHIP_TYPE_TYPE,
                "name": self.FOUNDING_MEMBERSHIP_TYPE,
                "requirements": "",
                "acceptance": "",
                "order": 0,
            },
            {},
        )
        if created.status != "ok":
            return created
        membership = self.session.create_child(
            members.uuid,
            {
                "type": "team_membership",
                "actor_uuid": self._identity_uuid,
                "state": "member",
                "membership_type_uuid": created.value.uuid,
                "previous_membership_uuid": "",
                "cause": "genesis",
                # The founder wrote the document, so there is nothing yet to
                # have accepted an earlier version of.
                "reference_hash": self.team_reference_hash(team),
                "acted_by": self._identity_uuid,
                "acted_at": self._now(),
                "authority_basis_uuid": "",
                "acceptance_text": "",
                "agreement_accepted": False,
                "agreement_version": "",
                "membership_info": "",
                "acceptance_requirement": "",
                "signals": "",
                "consideration": "",
                "expectation": "",
            },
            {},
        )
        return SessionResult(
            membership.status,
            value=membership.value,
            reason=membership.reason,
            effects=[*created.effects, *membership.effects],
        )

    def _held_membership_type_uuid(
        self, team: ProtocolNode, actor_uuid: str,
    ) -> str:
        """Which membership type an Actor's chain currently names."""
        current_uuid = self.membership_projection(
            team, actor_uuid,
        )["current_uuid"]
        record = self._governance_node(
            team, current_uuid, "team_membership",
        ) if current_uuid else None
        return str(record.data.get("membership_type_uuid") or "") if record else ""

    def apply_for_membership(
        self, team_uuid: str, invitation_uuid: str,
        agreement_accepted: bool = False,
        acceptance_text: str = "",
    ) -> SessionResult:
        """Apply for an open membership; this does not issue a badge."""
        team = self._node(team_uuid, "team")
        if not team:
            return SessionResult("error", reason="team not found")
        invitation = self._governance_node(
            team, str(invitation_uuid or "").strip(),
            "team_membership_invitation",
        )
        if invitation is None:
            return SessionResult("error", reason="invitation not found")
        root_uuid = self._invitation_root_uuid(team, invitation)
        acted_at = self._now()
        live = self.membership_invitation_projection(team, root_uuid)
        if live.get("state") != "open":
            return SessionResult(
                "error", reason="that membership is not open",
            )
        head = self._governance_node(
            team, live.get("current_uuid") or "",
            "team_membership_invitation",
        )
        if head is None or not self._within_invitation_window(
            head.data, acted_at,
        ):
            return SessionResult("error", reason="that invitation has expired")
        type_uuid = str(head.data.get("membership_type_uuid") or "")
        if not self.membership_type_lives(team, type_uuid):
            return SessionResult(
                "error", reason="that membership type no longer exists",
            )
        membership_type = self._node(type_uuid, self.MEMBERSHIP_TYPE_TYPE)
        if not str(
            membership_type.data.get("acceptance") if membership_type else ""
        ).strip():
            self.session.trace_event(
                "team.membership_acceptance_unexpected",
                team_uuid=team.uuid,
                invitation_uuid=head.uuid,
                reason="open membership has no Acceptance Requirement",
            )
            return SessionResult(
                "error", reason="a membership acceptance requirement is required",
            )
        answer = str(acceptance_text or "").strip()
        if not answer:
            return SessionResult(
                "error", reason="your Acceptance Text is required",
            )
        agreement = self.agreement_projection(team)
        if agreement.get("state") not in {"agreed", "absent"}:
            self.session.trace_event(
                "team.membership_application_blocked",
                team_uuid=team.uuid,
                invitation_uuid=head.uuid,
                agreement_state=agreement.get("state"),
                reason=agreement.get("reason"),
            )
            return SessionResult(
                "error",
                reason="the Identity holders do not expose one agreed Agreement",
            )
        has_agreement = agreement.get("state") == "agreed"
        local_snapshot, local_error = self._agreement_snapshot(team)
        local_hash = (
            self._agreement_snapshot_hash(local_snapshot)
            if not local_error else ""
        )
        if local_error or local_hash != agreement.get("reference_hash"):
            self.session.trace_event(
                "team.membership_application_blocked",
                team_uuid=team.uuid,
                invitation_uuid=head.uuid,
                agreement_state=agreement.get("state"),
                reason=(
                    local_error
                    or "the Actor's Agreement copy is not aligned to Identity"
                ),
            )
            return SessionResult(
                "error",
                reason="align your Agreement copy with Identity before applying",
            )
        if has_agreement and agreement_accepted is not True:
            return SessionResult(
                "error", reason="Agreement acceptance must be explicit",
            )
        if not has_agreement and agreement_accepted is True:
            self.session.trace_event(
                "team.membership_acceptance_unexpected",
                team_uuid=team.uuid,
                invitation_uuid=head.uuid,
                reason="Agreement accepted although no Agreement exists",
            )
            return SessionResult(
                "error", reason="this team has no Agreement to accept",
            )
        standing = self.membership_projection(team, self._identity_uuid)
        if standing["state"] == "contested":
            return SessionResult(
                "error", reason="your membership here is contested",
            )
        if (
            standing["state"] == "member"
            and self._held_membership_type_uuid(
                team, self._identity_uuid,
            ) == type_uuid
            and self.membership_status(team, self._identity_uuid) == "accepted"
        ):
            return SessionResult(
                "error", reason="you are already on that membership",
            )
        if any(
            application.data.get("actor_uuid") == self._identity_uuid
            and application.data.get("membership_type_uuid") == type_uuid
            for application in self.pending_membership_applications(team)
        ):
            return SessionResult(
                "error", reason="you already have a pending application",
            )
        return self.append_governance_record(team.uuid, {
            "type": "team_membership_application",
            "actor_uuid": self._identity_uuid,
            "membership_type_uuid": type_uuid,
            "previous_membership_uuid": standing["current_uuid"],
            "invitation_uuid": head.uuid,
            "applied_at": acted_at,
            "membership_info": str(
                membership_type.data.get("requirements") or "",
            ),
            "acceptance_requirement": str(
                membership_type.data.get("acceptance") or "",
            ),
            "acceptance_text": answer,
            "agreement_accepted": bool(agreement_accepted),
            "agreement_version": str(agreement.get("version") or ""),
            "reference_hash": str(agreement.get("reference_hash") or ""),
        })

    def issue_membership_badge(
        self, team_uuid: str, application_uuid: str,
    ) -> SessionResult:
        """Identity accepts one application by issuing the standing badge."""
        team = self._node(team_uuid, "team")
        if not team:
            return SessionResult("error", reason="team not found")
        application = self._governance_node(
            team, str(application_uuid or "").strip(),
            "team_membership_application",
        )
        if application is None:
            return SessionResult(
                "error", reason="membership application not found",
            )
        if application.uuid not in {
            item.uuid for item in self.pending_membership_applications(team)
        }:
            return SessionResult(
                "error", reason="that application has already been resolved",
            )
        data = application.data
        actor_uuid = str(data.get("actor_uuid") or "")
        standing = self.membership_projection(team, actor_uuid)
        if standing.get("state") == "contested":
            return SessionResult(
                "error", reason="the applicant's membership is contested",
            )
        if standing.get("current_uuid") != data.get("previous_membership_uuid"):
            return SessionResult(
                "error", reason="the applicant's membership has changed",
            )
        agreement = self.agreement_projection(team)
        if agreement.get("state") not in {"agreed", "absent"}:
            self.session.trace_event(
                "team.membership_badge_issue_blocked",
                team_uuid=team.uuid,
                application_uuid=application.uuid,
                agreement_state=agreement.get("state"),
                reason=agreement.get("reason"),
            )
            return SessionResult(
                "error",
                reason="the Identity holders do not expose one agreed Agreement",
            )
        if data.get("agreement_version") != agreement.get("version"):
            return SessionResult(
                "error",
                reason="the Agreement version changed after this application",
            )
        membership_type = self._node(
            str(data.get("membership_type_uuid") or ""),
            self.MEMBERSHIP_TYPE_TYPE,
        )
        if not self._is_in(membership_type, team, "membership-types"):
            return SessionResult("error", reason="membership type not found")
        if (
            str(membership_type.data.get("requirements") or "")
            != data.get("membership_info")
            or str(membership_type.data.get("acceptance") or "")
            != data.get("acceptance_requirement")
        ):
            return SessionResult(
                "error", reason="the membership terms changed after application",
            )
        return self.append_governance_record(team.uuid, {
            "type": "team_membership",
            "actor_uuid": actor_uuid,
            "state": "member",
            "membership_type_uuid": data["membership_type_uuid"],
            "previous_membership_uuid": data["previous_membership_uuid"],
            "cause": "acceptance",
            "reference_hash": data["reference_hash"],
            "acted_by": self._identity_uuid,
            "acted_at": self._now(),
            "authority_basis_uuid": self._authority_basis_for_actor(
                team, self.MEMBERSHIP_TRUST, self._identity_uuid,
            ),
            "invitation_uuid": data["invitation_uuid"],
            "application_uuid": application.uuid,
            "membership_info": data["membership_info"],
            "acceptance_requirement": data["acceptance_requirement"],
            "acceptance_text": data["acceptance_text"],
            "agreement_accepted": data["agreement_accepted"],
            "agreement_version": data["agreement_version"],
            "signals": "",
            "consideration": "",
            "expectation": "",
        })

    def end_membership(
        self, team_uuid: str, actor_uuid: str,
        signals: str = "", consideration: str = "", expectation: str = "",
    ) -> SessionResult:
        """Identity takes somebody off the team, on behalf of the team.

        The only thing Identity decides about a particular person, and the
        counterpart of nobody being able to keep them out while an invitation
        is open.

        Their roles are not touched, and nothing is written into them. What
        somebody answered about a piece of work stays true as a record; that
        it no longer counts is read from their standing beside it, which is
        why taking a membership up again brings the holdings back without
        anybody re-answering.
        """
        team = self._node(team_uuid, "team")
        if not team:
            return SessionResult("error", reason="team not found")
        subject = str(actor_uuid or "").strip()
        if not subject:
            return SessionResult("error", reason="an actor is required")
        if not self._is_current_member(team, subject):
            return SessionResult(
                "error", reason="that actor is not a current Member",
            )
        standing = self.membership_projection(team, subject)
        current = self._governance_node(
            team, standing["current_uuid"], "team_membership",
        )
        if current is None:
            self.session.trace_event(
                "team.membership_termination_unexpected",
                team_uuid=team.uuid,
                actor_uuid=subject,
                reason="current membership badge is unavailable",
            )
            return SessionResult(
                "error", reason="current membership badge is unavailable",
            )
        return self.append_governance_record(team.uuid, {
            "type": "team_membership",
            "actor_uuid": subject,
            "state": "former",
            "membership_type_uuid": self._held_membership_type_uuid(
                team, subject,
            ),
            "previous_membership_uuid": current.uuid,
            "cause": "removal",
            "reference_hash": current.data["reference_hash"],
            "acted_by": self._identity_uuid,
            "acted_at": self._now(),
            "authority_basis_uuid": self._authority_basis_for_actor(
                team, self.MEMBERSHIP_TRUST, self._identity_uuid,
            ),
            "acceptance_text": "",
            "agreement_accepted": False,
            "agreement_version": str(
                current.data.get("agreement_version") or "",
            ),
            "membership_info": str(
                current.data.get("membership_info") or "",
            ),
            "acceptance_requirement": str(
                current.data.get("acceptance_requirement") or "",
            ),
            "signals": str(signals or "").strip(),
            "consideration": str(consideration or "").strip(),
            "expectation": str(expectation or "").strip(),
        })

    def leave_team(self, team_uuid: str) -> SessionResult:
        """Stop being a member. Nobody's decision but your own."""
        team = self._node(team_uuid, "team")
        if not team:
            return SessionResult("error", reason="team not found")
        if not self._is_current_member(team, self._identity_uuid):
            return SessionResult(
                "error", reason="you are not a current Member",
            )
        standing = self.membership_projection(team, self._identity_uuid)
        current = self._governance_node(
            team, standing["current_uuid"], "team_membership",
        )
        if current is None:
            self.session.trace_event(
                "team.membership_departure_unexpected",
                team_uuid=team.uuid,
                actor_uuid=self._identity_uuid,
                reason="current membership badge is unavailable",
            )
            return SessionResult(
                "error", reason="current membership badge is unavailable",
            )
        return self.append_governance_record(team.uuid, {
            "type": "team_membership",
            "actor_uuid": self._identity_uuid,
            "state": "former",
            "membership_type_uuid": self._held_membership_type_uuid(
                team, self._identity_uuid,
            ),
            "previous_membership_uuid": current.uuid,
            "cause": "departure",
            "reference_hash": current.data["reference_hash"],
            "acted_by": self._identity_uuid,
            "acted_at": self._now(),
            "authority_basis_uuid": "",
            "acceptance_text": "",
            "agreement_accepted": False,
            "agreement_version": str(
                current.data.get("agreement_version") or "",
            ),
            "membership_info": str(
                current.data.get("membership_info") or "",
            ),
            "acceptance_requirement": str(
                current.data.get("acceptance_requirement") or "",
            ),
            "signals": "",
            "consideration": "",
            "expectation": "",
        })

    def _create_trusteeship(
        self, team: ProtocolNode, trust: str,
        actor_uuid: str | None = None,
    ) -> SessionResult:
        actor = actor_uuid or self._identity_uuid
        container = self._container(team, self.RECORD_CONTAINERS["team_trustee_state"])
        if container is None:
            return SessionResult("error", reason="trusteeship container unavailable")
        return self.session.create_child(
            container.uuid,
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
            "election_under_way": False,
            "can_settle": False,
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
            # One election per seat at a time, so the card can say why the
            # button is off rather than letting the write explain it.
            "election_under_way": bool(
                self.elections_under_way(team, trust),
            ),
            # Whoever holds the counterpart seat, or is acting in it, is who
            # reads the result and puts somebody in this one.
            "can_settle": bool(
                (facilitator := self._sole_facilitating_trust(trust))
                and self._authority_basis_for_actor(
                    team, facilitator, self._identity_uuid,
                )
            ),
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
    ROLE_ITEM_CONTAINERS = {
        "team_accountability": "accountabilities",
        "team_domain": "domains",
    }

    def roles(self, team: ProtocolNode) -> list[ProtocolNode]:
        return self._held(team, "roles")

    def governance_records(
        self, team: ProtocolNode, node_type: str | None = None,
    ) -> list[ProtocolNode]:
        # Observations are the one kind with no container of their own: they
        # sit under the decision they observe, so they are gathered from
        # there rather than from a place beside it.
        if node_type == "team_trustee_reality":
            found = [
                reality
                for action in self._held(team, "actions")
                for reality in self._realities_of(action)
            ]
        else:
            names = (
                [self.RECORD_CONTAINERS[node_type]] if node_type
                else list(dict.fromkeys(self.RECORD_CONTAINERS.values()))
            )
            found = [
                record for name in names
                for record in self._held(team, name)
            ]
            if node_type is None:
                found.extend(
                    reality
                    for action in self._held(team, "actions")
                    for reality in self._realities_of(action)
                )
        return sorted(found, key=lambda node: (node.created_at, node.uuid))

    def content_schema_error(self, node: ProtocolNode) -> str | None:
        """Whether a piece of document content is the shape its type declares.

        Content is edited rather than appended, and that is deliberate - it
        is what people agree to, and agreements are rewritten. Editable is
        not the same as unchecked, though: a peer's clause used to be
        whatever they sent, and somebody was asked to accept it as a
        proposal without anything having looked at it.
        """
        node_type = node.data.get("type")
        contract = self.CONTENT_FIELDS.get(node_type)
        if contract is None:
            return "not document content"
        required, optional = contract
        fields = set(node.data)
        missing = sorted(required - fields)
        extra = sorted(fields - required - optional)
        if missing:
            return "missing content fields: " + ", ".join(missing)
        if extra:
            return "unsupported content fields: " + ", ".join(extra)
        text_field = self.CONTENT_TEXT_FIELDS.get(node_type, "text")
        if not isinstance(node.data.get(text_field), str):
            return f"{text_field} must be a string"
        order = node.data.get("order")
        if isinstance(order, bool) or not isinstance(order, (int, float)):
            return "order must be a number"
        # The shape nests, and only these types may appear inside it. A
        # clause carrying a role would be a document that owns its own
        # participants.
        for child in node.children:
            if child.deleted:
                continue
            # A container is the place content sits in, not content itself.
            # What it holds is checked on its own account.
            if child.data.get("type") == self.CONTAINER_TYPE:
                continue
            if child.data.get("type") not in self.CONTENT_TYPES:
                return "document content may only contain document content"
        return None

    def role_record_schema_error(self, node: ProtocolNode) -> str | None:
        """Whether a participation record is the shape its type declares.

        The check governance records have always had. These had none: they
        travel the proposal path, so a peer's answer was whatever they sent,
        and a person was asked to accept it sight unseen.
        """
        node_type = node.data.get("type")
        contract = self.ROLE_RECORD_FIELDS.get(node_type)
        if contract is None:
            return "not a participation record"
        if node.children:
            return "participation records cannot contain children"
        required, optional = contract
        fields = set(node.data)
        missing = sorted(required - fields)
        extra = sorted(fields - required - optional)
        if missing:
            return "missing participation fields: " + ", ".join(missing)
        if extra:
            return "unsupported participation fields: " + ", ".join(extra)

        data = node.data
        # `order` is a sort key and `seated_member_uuids` a list of them;
        # everything else a participation record carries is text.
        for field in required - {"type", "order"}:
            if not isinstance(data.get(field), str):
                return f"{field} must be a string"
        for field in optional - {"seated_member_uuids"}:
            if field in data and not isinstance(data[field], str):
                return f"{field} must be a string"
        if node_type == "team_role_decision":
            if data.get("decision") not in self.ROLE_DECISIONS:
                return "decision must be accepted or refused"
            seated = data.get("seated_member_uuids")
            if seated is not None and (
                not isinstance(seated, list)
                or not all(isinstance(actor, str) and actor for actor in seated)
            ):
                return "seated_member_uuids must be a list of actor UUIDs"
        elif node_type == "team_role_holding":
            if data.get("state") not in self.HOLDING_STATES:
                return "holding state must be held or given_up"
            order = data.get("order")
            if isinstance(order, bool) or not isinstance(order, (int, float)):
                return "order must be a number"
            if data.get("state") == "given_up" and not data.get(
                "previous_holding_uuid",
            ):
                return "a seat given up requires a predecessor"
        return None

    def governance_schema_error(self, node: ProtocolNode) -> str | None:
        """Whether a governance record is the shape its type declares.

        The field contract first, which is the same question for every one of
        them, then whatever that one type requires of its own values.
        """
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
        # Everything a governance record carries is text, bar structured
        # payloads and explicit boolean consent.
        scalar_exceptions = {"payload", "items", "agreement_accepted"}
        for field in required - {"type"} - scalar_exceptions:
            if not isinstance(data.get(field), str):
                return f"{field} must be a string"
        for field in optional:
            if field in data and not isinstance(data[field], str):
                return f"{field} must be a string"
        # Read off the contract rather than from a second list of which types
        # carry a trusteeship, which would be one more thing to keep in step.
        if "trust" in required and data.get("trust") not in self.TRUSTS:
            return "trust must be identity or trust"
        checker = self.GOVERNANCE_RECORDS[node_type][1]
        return getattr(self, checker)(data) if checker else None

    # Each check below is what one record type asks of its own values, beyond
    # the fields it must carry. They answer with the complaint, or nothing.

    def _item_list_schema_error(self, data: dict) -> str | None:
        items = data.get("items")
        if not isinstance(items, list):
            return "items must be a list"
        for item in items:
            if not isinstance(item, dict):
                return "each item must be an object"
            if set(item) != {"topic_uuid", "application_id", "title"}:
                return (
                    "each item carries a topic_uuid, an application_id and "
                    "a title"
                )
            if any(not isinstance(value, str) for value in item.values()):
                return "every item field must be a string"
            if not item["topic_uuid"] or not item["application_id"]:
                return "an item names a topic and the application that owns it"
        return None

    def _trustee_state_schema_error(self, data: dict) -> str | None:
        cause = data.get("cause")
        if cause not in self.TRUSTEE_CAUSES:
            return "unsupported trustee-state cause"
        if cause == "genesis" and (
            data.get("previous_state_uuid") or data.get("authority_basis_uuid")
        ):
            return "genesis cannot name previous state or authority basis"
        if cause != "genesis" and not data.get("previous_state_uuid"):
            return "non-genesis trustee state requires previous_state_uuid"
        if cause == "election" and not data.get("process_uuid"):
            return "an election state names the process it read"
        return None

    def _membership_schema_error(self, data: dict) -> str | None:
        if data.get("state") not in {"member", "former"}:
            return "membership state must be member or former"
        cause = data.get("cause")
        if cause not in self.MEMBERSHIP_CAUSES:
            return "unsupported membership cause"
        if not str(data.get("membership_type_uuid") or "").strip():
            return "a membership names the membership type it is on"
        if not str(data.get("reference_hash") or "").strip():
            return "a membership names the Agreement it answers"
        if not isinstance(data.get("agreement_accepted"), bool):
            return "agreement_accepted must be true or false"
        if cause == "genesis":
            if (
                data.get("previous_membership_uuid")
                or data.get("authority_basis_uuid")
            ):
                return (
                    "genesis membership cannot name a predecessor "
                    "or authority basis"
                )
            if data.get("state") != "member":
                return "genesis membership must be a membership"
        if cause == "acceptance":
            if not data.get("invitation_uuid"):
                return "an acceptance must name the invitation it answers"
            if not data.get("application_uuid"):
                return "an acceptance badge must name its application"
            if data.get("state") != "member":
                return "an acceptance must be a membership"
            if not str(data.get("acceptance_text") or "").strip():
                return "an acceptance requires the Actor's Acceptance Text"
        if cause in {"departure", "removal"} and data.get("state") != "former":
            return "leaving must end the membership"
        # Leaving is the holder's own act and rests on nothing.
        if cause == "departure" and data.get(
            "authority_basis_uuid",
        ):
            return f"a {cause} rests on no authority basis"
        return None

    @staticmethod
    def _membership_application_schema_error(data: dict) -> str | None:
        for field in (
            "actor_uuid", "membership_type_uuid", "invitation_uuid",
            "applied_at", "acceptance_requirement", "acceptance_text",
            "reference_hash",
        ):
            if not str(data.get(field) or "").strip():
                return f"a membership application requires {field}"
        if not isinstance(data.get("agreement_accepted"), bool):
            return "agreement_accepted must be true or false"
        return None

    def _membership_invitation_schema_error(self, data: dict) -> str | None:
        state = data.get("state")
        if state not in {"open", "closed"}:
            return "invitation state must be open or closed"
        if not str(data.get("membership_type_uuid") or "").strip():
            return "an invitation names the membership type it opens"
        opened_at = str(data.get("opened_at") or "")
        expires_at = str(data.get("expires_at") or "")
        # A window that closes before it opens is not a window, and open
        # would mean nothing. Both are recorded values, so every replica
        # reads the same answer.
        if not (opened_at and expires_at and expires_at > opened_at):
            return "an invitation expires after it opens"
        if state == "open" and data.get("closed_at"):
            return "an open invitation cannot name when it closed"
        if state == "closed" and not data.get("closed_at"):
            return "a closed invitation requires closed_at"
        return None

    def _trustee_election_schema_error(self, data: dict) -> str | None:
        if not str(data.get("process_uuid") or "").strip():
            return "an election names the flow that is running it"
        return None

    def _trustee_candidacy_schema_error(self, data: dict) -> str | None:
        state = data.get("state")
        if state not in {"active", "withdrawn"}:
            return "candidacy state must be active or withdrawn"
        if state == "active" and data.get("previous_candidacy_uuid"):
            return "initial candidacy cannot name a predecessor"
        if state == "withdrawn" and (
            not data.get("withdrawn_at")
            or not data.get("previous_candidacy_uuid")
        ):
            return "withdrawn candidacy requires withdrawn_at and a predecessor"
        return None

    def _trustee_action_schema_error(self, data: dict) -> str | None:
        if data.get("action_kind") not in self.ACTION_KINDS:
            return "unsupported trustee action kind"
        if not isinstance(data.get("payload"), dict):
            return "trustee action payload must be an object"
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

    def membership_invitation_projection(
        self, team: ProtocolNode, invitation_uuid: str,
    ) -> dict:
        return self._record_chain_projection(
            team, "team_membership_invitation", invitation_uuid,
            "previous_invitation_uuid",
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

    def membership_invitation_roots(
        self, team: ProtocolNode, membership_type_uuid: str | None = None,
    ) -> list[ProtocolNode]:
        return [
            record
            for record in self.governance_records(
                team, "team_membership_invitation",
            )
            if not record.data.get("previous_invitation_uuid")
            and (
                membership_type_uuid is None
                or record.data.get("membership_type_uuid")
                == membership_type_uuid
            )
        ]

    def _invitation_root_uuid(
        self, team: ProtocolNode, invitation: ProtocolNode,
    ) -> str:
        """Walk back to the record that started this type's chain.

        A caller holds whichever link it was handed - the page sends the
        head, an adopting replica may hold a middle one - and the projection
        only reads from a root.
        """
        by_uuid = {
            record.uuid: record
            for record in self.governance_records(
                team, "team_membership_invitation",
            )
        }
        current = invitation
        seen = {current.uuid}
        while True:
            previous_uuid = str(
                current.data.get("previous_invitation_uuid") or "",
            )
            previous = by_uuid.get(previous_uuid)
            if previous is None or previous.uuid in seen:
                return current.uuid
            seen.add(previous.uuid)
            current = previous

    @staticmethod
    def _within_invitation_window(data: dict, moment: str) -> bool:
        """Whether an answer given at this moment fell inside the window.

        Read from recorded values on both sides - the invitation's own
        opened_at and expires_at, and the acceptance's acted_at - never from
        the clock. Two replicas holding the same records therefore always
        agree about whether somebody is a member, however late one of them
        receives the answer.
        """
        opened_at = str(data.get("opened_at") or "")
        expires_at = str(data.get("expires_at") or "")
        if not (opened_at and expires_at):
            return False
        return opened_at <= moment < expires_at

    def open_membership_uuids(self, team: ProtocolNode) -> dict[str, str]:
        """Which membership types the pool may take up, by type uuid.

        Open means the chain's head says open *and* its window contains now.
        A window that has run out closes the door without anybody touching
        the record, which is what an expiry is for.
        """
        now = self._now()
        live: dict[str, str] = {}
        for root in self.membership_invitation_roots(team):
            projection = self.membership_invitation_projection(team, root.uuid)
            if projection.get("state") != "open":
                continue
            head = self._governance_node(
                team, projection.get("current_uuid") or "",
                "team_membership_invitation",
            )
            if head is None or not self._within_invitation_window(
                head.data, now,
            ):
                continue
            live[str(head.data.get("membership_type_uuid") or "")] = head.uuid
        return live

    def membership_records(
        self, team: ProtocolNode, actor_uuid: str | None = None,
    ) -> list[ProtocolNode]:
        return [
            record for record in self.governance_records(
                team, "team_membership",
            )
            if actor_uuid is None
            or record.data.get("actor_uuid") == actor_uuid
        ]

    def membership_applications(
        self, team: ProtocolNode, actor_uuid: str | None = None,
    ) -> list[ProtocolNode]:
        return [
            record for record in self.governance_records(
                team, "team_membership_application",
            )
            if actor_uuid is None
            or record.data.get("actor_uuid") == actor_uuid
        ]

    def pending_membership_applications(
        self, team: ProtocolNode,
    ) -> list[ProtocolNode]:
        issued = {
            str(record.data.get("application_uuid") or "")
            for record in self.membership_records(team)
            if record.data.get("cause") == "acceptance"
        }
        return [
            application
            for application in self.membership_applications(team)
            if application.uuid not in issued
        ]

    def membership_projection(
        self, team: ProtocolNode, actor_uuid: str,
    ) -> dict:
        """Where one Actor's membership chain has got to.

        One chain per Actor, and only one: somebody admitted, gone and
        admitted again continues the chain rather than starting a second,
        so the whole history is one line and being re-admitted is
        distinguishable from never having left.

        That is what lets a second root mean something. Taking a membership
        up again used to start one, so two roots could be either a return or
        two replicas writing one for the same person at once, and the second
        was resolved silently by taking the newest. Now it is a contest, and
        shown. Moving between membership types continues the chain for the
        same reason.

        **The type is read too.** Standing is the pair "the head says member"
        and "the type it names still exists", so deleting a membership type
        puts everybody on it back in the pool without one record being
        rewritten. That is the only place standing depends on anything
        outside the chain, and the alternative is a cascade over other
        people's records.
        """
        records = self.membership_records(team, actor_uuid)
        roots = [
            record for record in records
            if not record.data.get("previous_membership_uuid")
        ]
        if not roots:
            return {
                "current_uuid": "", "state": "pool",
                "membership_type_uuid": "", "contenders": [],
            }
        if len(roots) > 1:
            return {
                "current_uuid": "",
                "state": "contested",
                "membership_type_uuid": "",
                "contenders": [record.uuid for record in roots],
            }
        root = roots[0]
        projection = self._record_chain_projection(
            team, "team_membership", root.uuid, "previous_membership_uuid",
        )
        current_uuid = projection.get("current_uuid") or root.uuid
        state = projection.get("state") or "pool"
        current = next(
            (record for record in records if record.uuid == current_uuid), None,
        )
        type_uuid = str(
            current.data.get("membership_type_uuid") or "",
        ) if current else ""
        if state == "member" and not self.membership_type_lives(
            team, type_uuid,
        ):
            state = "pool"
        return {
            "current_uuid": current_uuid,
            "state": state,
            "membership_type_uuid": type_uuid,
            "contenders": projection.get("contenders") or [],
        }

    def member_standing(self, team: ProtocolNode, actor_uuid: str) -> str:
        """Membership is one question with one answer, read from one place.

        There used to be a second: teams made before membership was its own
        record said "member" three other ways, and standing fell through to
        those when no record existed. There is one way in now and it writes a
        `team_membership`, so a path that quietly supplies an answer the
        model no longer produces is worse than no answer.
        """
        return {
            "member": "accepted",
            "contested": "contested",
            "former": "former",
        }.get(
            self.membership_projection(team, actor_uuid)["state"],
            "pool",
        )

    def membership_status(self, team: ProtocolNode, actor_uuid: str) -> str:
        """What the badge on an actor's row says.

        Two states and no more. A membership does not expire - an invitation
        does - and refusing one is simply not taking it. Identity declares
        whether an Agreement change is substantial by changing its version;
        the exact content hash remains evidence, not badge validity.
        """
        projection = self.membership_projection(team, actor_uuid)
        if projection["state"] != "member":
            return projection["state"]
        current = self._governance_node(
            team, projection["current_uuid"], "team_membership",
        )
        agreement = self.agreement_projection(team)
        if agreement.get("state") not in {"agreed", "absent"}:
            return "outdated"
        accepted = str(
            current.data.get("agreement_version") or "",
        ) if current else ""
        return (
            "accepted" if accepted == str(agreement.get("version") or "")
            else "outdated"
        )

    def membership_types(self, team: ProtocolNode) -> list[ProtocolNode]:
        return self._held(team, "membership-types")

    def membership_type_lives(
        self, team: ProtocolNode, membership_type_uuid: str,
    ) -> bool:
        """Whether the team still supports this membership.

        Asked of the team's live children rather than of the index, because
        a deleted node is still in the index and the whole point of deleting
        a type is that everybody on it goes back to the pool.
        """
        if not membership_type_uuid:
            return False
        return any(
            node.uuid == membership_type_uuid
            for node in self.membership_types(team)
        )

    def identity_holder_uuids(self, team: ProtocolNode) -> list[str]:
        """Every Actor whose Identity perspective currently has to agree.

        The ordinary settled case has one holder. During a contested
        transition the incumbent and every named successor are all included:
        disagreement between them cannot accidentally manufacture a Team
        truth while the trusteeship is being resolved.
        """
        projection = self.trustee_projection(team, "identity")
        holders = {
            str(projection.get("holder_actor_uuid") or "").strip(),
        }
        if projection.get("state") == "contested":
            states = {
                record.uuid: record
                for record in self.governance_records(
                    team, "team_trustee_state",
                )
            }
            for state_uuid in projection.get("contenders") or []:
                state = states.get(state_uuid)
                if state:
                    holders.add(
                        str(state.data.get("holder_actor_uuid") or "").strip(),
                    )
        if projection.get("state") == "vacant":
            holders.update(
                str(candidate.data.get("actor_uuid") or "").strip()
                for candidate in self.active_trustee_candidates(
                    team, "identity",
                )
            )
        holders.discard("")
        return sorted(holders)

    def _actor_agreement_perspectives(
        self, team: ProtocolNode, actor_uuid: str,
    ) -> list[tuple[str, ProtocolNode]]:
        roots: list[tuple[str, ProtocolNode]] = []
        if actor_uuid == self._identity_uuid:
            roots.append(("local", team))
        person = self._known_people().get(actor_uuid) or {}
        addresses = set(
            person.get("addresses") or [person.get("address")]
        )
        addresses.discard(None)
        addresses.discard("")
        for address in self.session.peer_addresses(team.uuid):
            if address not in addresses:
                continue
            root = self.session.get_cached_peer_subtree(address, team.uuid)
            if root is not None:
                roots.append((address, root))
        return roots

    def _agreement_snapshot(self, root: ProtocolNode) -> tuple[dict, str]:
        def order_key(node: ProtocolNode) -> tuple[int, float, str]:
            value = node.data.get("order")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return (1, 0.0, node.uuid)
            return (0, float(value), node.uuid)

        agreement = self.agreement(root, create=False)
        title = agreement.data.get("name", "") if agreement else ""
        version = agreement.data.get("version", "") if agreement else ""
        if not isinstance(title, str):
            return {}, "agreement name must be a string"
        if not isinstance(version, str):
            return {}, "agreement version must be a string"

        sections = []
        for section in sorted(
            self._ordered(agreement) if agreement else [],
            key=order_key,
        ):
            section_title = section.data.get("title")
            section_order = section.data.get("order")
            if not isinstance(section_title, str):
                return {}, f"section {section.uuid} title must be a string"
            if (
                isinstance(section_order, bool)
                or not isinstance(section_order, (int, float))
            ):
                return {}, f"section {section.uuid} order must be a number"
            unexpected = [
                child for child in section.live_children()
                if child.data.get("type") != "team_clause"
            ]
            if unexpected:
                return {}, (
                    f"section {section.uuid} contains unexpected node "
                    f"{unexpected[0].uuid}"
                )
            clauses = []
            for clause in sorted(
                self._ordered(section),
                key=order_key,
            ):
                text = clause.data.get("text")
                order = clause.data.get("order")
                if not isinstance(text, str):
                    return {}, f"clause {clause.uuid} text must be a string"
                if isinstance(order, bool) or not isinstance(order, (int, float)):
                    return {}, f"clause {clause.uuid} order must be a number"
                if clause.live_children():
                    return {}, f"clause {clause.uuid} cannot contain children"
                clauses.append({
                    "uuid": clause.uuid, "text": text, "order": order,
                })
            sections.append({
                "uuid": section.uuid,
                "title": section_title,
                "order": section_order,
                "clauses": clauses,
            })
        snapshot = {
            "name": title.strip(),
            "version": version.strip(),
            "sections": sections,
        }
        if (
            (snapshot["name"] or snapshot["version"] or sections)
            and not (snapshot["name"] and snapshot["version"])
        ):
            return {}, "an Agreement requires both a name and a version"
        return snapshot, ""

    @staticmethod
    def _agreement_snapshot_hash(snapshot: dict) -> str:
        encoded = json.dumps(
            snapshot, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"

    def agreement_projection(self, team: ProtocolNode) -> dict:
        """The Agreement truth derived from Identity perspectives only."""
        return self._cached(
            ("agreement_projection", team.uuid),
            lambda: self._build_agreement_projection(team),
        )

    def _build_agreement_projection(self, team: ProtocolNode) -> dict:
        holders = self.identity_holder_uuids(team)
        blank = {
            "state": "no_identity", "holder_uuids": holders,
            "name": "", "version": "", "reference_hash": "",
            "reason": "this Team has no Identity holder",
        }
        if not holders:
            return blank

        observations = []
        for holder_uuid in holders:
            perspectives = self._actor_agreement_perspectives(
                team, holder_uuid,
            )
            if not perspectives:
                return {
                    **blank,
                    "state": "unavailable",
                    "reason": (
                        "an Identity holder's Agreement perspective is "
                        "not available"
                    ),
                }
            for source, root in perspectives:
                snapshot, error = self._agreement_snapshot(root)
                if error:
                    self.session.trace_event(
                        "team.agreement_projection_unexpected",
                        team_uuid=team.uuid,
                        holder_actor_uuid=holder_uuid,
                        source=source,
                        reason=error,
                    )
                    return {
                        **blank, "state": "invalid", "reason": error,
                    }
                observations.append({
                    "holder_uuid": holder_uuid,
                    "source": source,
                    "snapshot": snapshot,
                    "reference_hash": self._agreement_snapshot_hash(snapshot),
                })

        hashes = {item["reference_hash"] for item in observations}
        if len(hashes) != 1:
            return {
                **blank,
                "state": "disputed",
                "reason": "Identity holders do not expose one Agreement",
            }
        agreed = observations[0]
        snapshot = agreed["snapshot"]
        state = "agreed" if (
            snapshot["name"] or snapshot["version"] or snapshot["sections"]
        ) else "absent"
        return {
            **blank,
            "state": state,
            "name": snapshot["name"],
            "version": snapshot["version"],
            "reference_hash": agreed["reference_hash"],
            "reason": "",
        }

    def agreement_exists(self, team: ProtocolNode) -> bool:
        return self.agreement_projection(team).get("state") == "agreed"

    def onboarding_pool_uuids(self, team: ProtocolNode) -> list[str]:
        """Everybody publishing on this team's channel who is not on it.

        Derived, and that is the whole definition. There is no pool record
        and no waiting room to be let into: being on the channel *is* being
        in the pool, reached the way every other topic is, by being given it.

        Which means topic access is the outer gate and this is the inner one.
        It also means the pool can read the Agreement - necessarily, because
        taking a membership is accepting that text, and nobody can accept a
        document they cannot see.
        """
        return [
            person["uuid"]
            for person in self._topic_members(team.uuid)
            if not self._is_current_member(team, person["uuid"])
        ]

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

        can_resolve = bool(self._authority_basis_for_actor(
            team, self.MEMBERSHIP_TRUST, self._identity_uuid,
        ))
        standing = self.membership_projection(team, self._identity_uuid)
        held_type_uuid = standing.get("membership_type_uuid") or ""
        is_member = standing["state"] == "member"
        now = self._now()
        # Two different facts, named for whose state each describes.
        # `state` says whether the Identity holders agree with each other;
        # `my_agreement_current` says whether this client's own copy matches
        # what they publish. You can be current with an absent Agreement, and
        # out of date against a perfectly agreed one.
        agreement = self.agreement_projection(team)
        local_agreement, local_agreement_error = self._agreement_snapshot(team)
        my_agreement_current = bool(
            not local_agreement_error
            and agreement.get("state") in {"agreed", "absent"}
            and self._agreement_snapshot_hash(local_agreement)
            == agreement.get("reference_hash")
        )
        pending = self.pending_membership_applications(team)

        types = []
        for node in self.membership_types(team):
            live = None
            for root in self.membership_invitation_roots(team, node.uuid):
                projection = self.membership_invitation_projection(
                    team, root.uuid,
                )
                head = self._governance_node(
                    team, projection.get("current_uuid") or "",
                    "team_membership_invitation",
                )
                if head is None or projection.get("state") != "open":
                    continue
                # Open on the record and open in fact are two questions: the
                # window running out closes the door with nobody touching it.
                if not self._within_invitation_window(head.data, now):
                    continue
                live = {
                    "uuid": root.uuid,
                    "current_uuid": head.uuid,
                    "opened_at": head.data.get("opened_at"),
                    "expires_at": head.data.get("expires_at"),
                }
            is_mine = is_member and held_type_uuid == node.uuid
            types.append({
                "uuid": node.uuid,
                "name": node.data.get("name") or "Untitled membership",
                "requirements": node.data.get("requirements") or "",
                "acceptance": node.data.get("acceptance") or "",
                "invitation": live,
                "members": [
                    actor_payload(actor_uuid)
                    for actor_uuid in self.current_member_uuids(team)
                    if self.membership_projection(
                        team, actor_uuid,
                    ).get("membership_type_uuid") == node.uuid
                ],
                "is_mine": is_mine,
                # Anybody may answer an open invitation who is not already on
                # this membership: the pool joins, a member of another type
                # moves, and somebody who left or was removed takes it up
                # again. It used to compare the *type* alone, which meant a
                # former member's chain still named the type they had been
                # on - so the one person who most needed the control was the
                # one it was hidden from.
                "can_apply": bool(live) and my_agreement_current and (
                    not is_mine
                    or self.membership_status(
                        team, self._identity_uuid,
                    ) != "accepted"
                ) and not any(
                    application.data.get("actor_uuid") == self._identity_uuid
                    and application.data.get("membership_type_uuid") == node.uuid
                    for application in pending
                ),
            })

        return {
            "types": types,
            "pool": [
                actor_payload(actor_uuid)
                for actor_uuid in self.onboarding_pool_uuids(team)
            ],
            "can_resolve": can_resolve,
            "is_member": is_member,
            "status": self.membership_status(team, self._identity_uuid),
            "membership_type_uuid": held_type_uuid,
            "agreement_exists": agreement.get("state") == "agreed",
            "agreement": agreement,
            "my_agreement_current": my_agreement_current,
            "applications": [
                {
                    "uuid": application.uuid,
                    "actor": actor_payload(str(
                        application.data.get("actor_uuid") or "",
                    )),
                    "membership_type_uuid": application.data.get(
                        "membership_type_uuid",
                    ),
                    "membership_info": application.data.get(
                        "membership_info",
                    ),
                    "acceptance_requirement": application.data.get(
                        "acceptance_requirement",
                    ),
                    "acceptance_text": application.data.get(
                        "acceptance_text",
                    ),
                    "agreement_accepted": application.data.get(
                        "agreement_accepted",
                    ),
                    "agreement_version": application.data.get(
                        "agreement_version",
                    ),
                    "applied_at": application.data.get("applied_at"),
                    "can_issue": can_resolve,
                }
                for application in pending
            ],
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
        """Everyone on this team right now.

        Membership records are the only source: there is one way on, and it
        ends in one, so there is nowhere else standing can come from. A
        membership whose type has been deleted is not one - the projection
        reads both.
        """
        return sorted(
            actor_uuid
            for actor_uuid in {
                str(record.data.get("actor_uuid") or "")
                for record in self.membership_records(team)
            }
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

    def elections_under_way(
        self, team: ProtocolNode, trust: str,
    ) -> list[ProtocolNode]:
        """Elections for this trusteeship that nobody has settled.

        Read from this team's own records and nothing else. It used to ask
        S-Flow whether the process had ended, which meant a client that
        could not see the process could not tell either - and a record it
        could never resolve froze the seat for good. Settling the seat is
        what ends an election now, and that is written here.
        """
        settled = {
            str(state.data.get("process_uuid") or "")
            for state in self.governance_records(team, "team_trustee_state")
            if state.data.get("cause") == "election"
        }
        settled.discard("")
        return [
            election
            for election in self.trustee_election_records(team, trust)
            if str(election.data.get("process_uuid") or "") not in settled
        ]

    def _holder_may_be_a_trustee(self, holder_actor_uuid: str) -> tuple[str, str]:
        """Only an Individual may hold a trusteeship.

        A Team in a role brings everybody on it into the team below, which is
        why seating one is an admission. A Team *holding* a trusteeship would
        go further: admissions, resignations and elections would rest on an
        authority with no person answerable for it. So the holder is a person.

        Checked here rather than in the schema because the answer is not in
        the record - it is whether the uuid names a Team - and a check that
        reads the tree does not belong in a pure function of node.data. An
        actor this replica cannot place defers and retries, the same as an
        unknown signing key: absence of a Team node is not evidence of a
        person.
        """
        if not holder_actor_uuid:
            # A vacancy names nobody, and nobody is not a Team.
            return ("authorized", "")
        if self._node(holder_actor_uuid, "team"):
            return ("unauthorized", "only an Individual may hold a trusteeship")
        if not self.session.identity_key_for_actor(holder_actor_uuid):
            return ("deferred", "the named holder is not known")
        return ("authorized", "")

    def _sole_facilitating_trust(self, trust: str) -> str:
        """Which trusteeship facilitates an action of this one, if only one can.

        No trusteeship supervises itself, and while there are two that
        leaves exactly one. It returns nothing rather than choosing once a
        third exists, so the caller refuses: "the other one" written as an
        if/else would quietly become "Identity facilitates everything" the
        moment a third trusteeship was added, which is a decision nobody
        would have made on purpose.
        """
        eligible = sorted(self.TRUSTS - {trust})
        return eligible[0] if len(eligible) == 1 else ""

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
        facilitator_trust = self._sole_facilitating_trust(normalized_trust)
        if not facilitator_trust:
            return SessionResult(
                "error",
                reason="the facilitating trusteeship must be chosen explicitly",
            )
        # Who facilitates is an input to the process, not an authority this
        # record rests on: nothing is implemented from the result, so there
        # is no basis to check here. What it still has to be is somebody -
        # S-Flow needs a facilitator, and the counterpart trusteeship is
        # where one comes from, because no trusteeship supervises itself.
        facilitator = self.trustee_projection(team, facilitator_trust)
        requested_facilitator = str(facilitator_actor_uuid or "").strip()
        settled_facilitator = str(facilitator.get("holder_actor_uuid") or "")
        if settled_facilitator:
            facilitator_actor_uuid = settled_facilitator
            if requested_facilitator and requested_facilitator != settled_facilitator:
                return SessionResult(
                    "error",
                    reason=f"{facilitator_trust.title()} is held by another Actor",
                )
        else:
            candidate_actors = [
                str(candidate.data.get("actor_uuid") or "")
                for candidate in self.active_trustee_candidates(
                    team, facilitator_trust,
                )
            ]
            if requested_facilitator:
                facilitator_actor_uuid = requested_facilitator
            elif self._identity_uuid in candidate_actors:
                facilitator_actor_uuid = self._identity_uuid
            elif len(candidate_actors) == 1:
                facilitator_actor_uuid = candidate_actors[0]
            else:
                facilitator_actor_uuid = ""
        if not target.get("current_state_uuid"):
            return SessionResult(
                "error", reason="the target trusteeship is not configured",
            )
        # One seat, one decision at a time. Two elections running side by
        # side are two answers for one chair, and whoever settles it would
        # be choosing which of them counted.
        if self.elections_under_way(team, normalized_trust):
            return SessionResult(
                "error",
                reason=(
                    f"an election for {normalized_trust.title()} is already "
                    "under way; settle it first"
                ),
            )
        if not facilitator_actor_uuid:
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
        # An election is the team's act, so it travels the way the team
        # does. Without this the process stays on whoever started it and
        # every other elector sees a record naming a process they cannot
        # reach - which is what "the election is unavailable" meant.
        #
        # Not required to succeed: a team nobody shares has nothing to put
        # the election on, and an election held alone is still a perfectly
        # good record of a decision made alone.
        bridged = self._bridge_to_team(process_uuid, team)
        recorded = self.append_governance_record(team.uuid, {
            "type": "team_trustee_election",
            "trust": normalized_trust,
            "process_uuid": process_uuid,
            "triggered_by": self._identity_uuid,
            "triggered_at": self._now(),
        })
        if recorded.status != "ok":
            if callable(getattr(flow, "delete_process", None)):
                flow.delete_process(process_uuid)
            return recorded
        # An election is a flow this team runs, so it is one of the team's
        # items like any other - it was not, because this path predates the
        # lists and never said who had it. Named only when it was published:
        # a process the others can never fetch is not the team's work, it is
        # this client's.
        if bridged:
            self.publish_my_items(
                self._node(team.uuid, "team") or team, process_uuid,
            )
        recorded.effects = [*created.effects, *recorded.effects]
        return recorded

    def adopt_live_elections(self) -> list[str]:
        """Ask for every live election on every team, on this client's poll.

        Called from the read route and not from the peer-update hook, which
        is where it belongs by subject and not by lock: following a topic
        goes through the RelayManager, and taking that lock underneath
        Session's is the reverse of the order Core requires. The route runs
        before the locked read, so it is an act like any other.
        """
        adopted = []
        for team in self.teams():
            adopted.extend(self.adopt_team_elections(team))
        return adopted

    def adopt_team_elections(self, team: ProtocolNode) -> list[str]:
        """Take up the team's live elections without being asked.

        Every other item waits for somebody to connect to it, because
        nobody has to care about it. An election is the one thing a member
        is required to take part in, so being a member is the consent -
        which reverses an earlier decision on purpose. Core still grafts
        nothing on its own; this is the application asking, on behalf of
        somebody who already agreed to be here.

        Asked once, and never again after a refusal. Whether this client
        has ever held it is readable from its own lists: they are a chain,
        so a topic named in an earlier one and not in the current one was
        put down deliberately, and putting it back would be arguing.
        """
        if not self._is_current_member(team, self._identity_uuid):
            return []
        join = getattr(self.collaboration, "join_bridged_topic", None)
        if not callable(join):
            return []
        ever_mine = {
            str(item.get("topic_uuid") or "")
            for record in self.governance_records(team, "team_item_list")
            if record.data.get("actor_uuid") == self._identity_uuid
            for item in record.data.get("items") or []
        }
        adopted = []
        for trust in sorted(self.TRUSTS):
            for election in self.elections_under_way(team, trust):
                process_uuid = str(election.data.get("process_uuid") or "")
                if not process_uuid or process_uuid in ever_mine:
                    continue
                if self.session.get_node(process_uuid) is not None:
                    continue
                if getattr(join(process_uuid, team.uuid), "ok", False):
                    adopted.append(process_uuid)
        if adopted:
            self.session.mount_cached_topics(FLOW_APPLICATION_ID)
        return adopted

    def settle_trusteeship(
        self, team_uuid: str, trust: str, holder_actor_uuid: str,
        process_uuid: str = "",
        signals: str = "", consideration: str = "", expectation: str = "",
    ) -> SessionResult:
        """Put somebody in the seat. The facilitator's own decision.

        An election informs it and does not make it: the process says what
        the electorate arrived at, and a person reads that and answers for
        seating somebody. Nothing here checks the name against the result -
        it could, and deliberately does not, because a decision nobody
        takes is a decision nobody can be answerable for. What the record
        says is who settled it, on what authority, and which process they
        were reading; the trail carries all three.
        """
        team = self._node(team_uuid, "team")
        normalized_trust = str(trust or "").strip().lower()
        if not team:
            return SessionResult("error", reason="team not found")
        if normalized_trust not in self.TRUSTS:
            return SessionResult("error", reason="unknown trusteeship")
        facilitator_trust = self._sole_facilitating_trust(normalized_trust)
        if not facilitator_trust:
            return SessionResult(
                "error",
                reason="the facilitating trusteeship must be chosen explicitly",
            )
        basis_uuid = self._authority_basis_for_actor(
            team, facilitator_trust, self._identity_uuid,
        )
        if not basis_uuid:
            return SessionResult(
                "error",
                reason=(
                    f"only {facilitator_trust.title()} or an authorised "
                    "acting candidate may settle this trusteeship"
                ),
            )
        holder = str(holder_actor_uuid or "").strip()
        if not holder:
            return SessionResult("error", reason="name who holds it")
        # Membership is not asked here. Standing for a trusteeship needs it,
        # and holding one does not confer it - a trustee whose membership
        # ends keeps the seat until somebody fills it, which is a state
        # worth seeing rather than papering over. The picker offers members
        # because that is the sensible choice, not because it is the rule.
        target = self.trustee_projection(team, normalized_trust)
        if target.get("state") == "contested":
            return SessionResult(
                "error", reason="the trusteeship is already contested",
            )
        named = str(process_uuid or "").strip()
        # Replacing a sitting trustee is what an election is for. Without
        # one this is a facilitator writing over somebody who is still in
        # the seat, which is a different power from filling an empty one -
        # the way out of an occupied seat is the holder's own resignation.
        if not named and target.get("state") != "vacant":
            return SessionResult(
                "error",
                reason=(
                    "the trusteeship is not vacant; an election is how a "
                    "sitting trustee is replaced"
                ),
            )
        if named and not [
            election for election in self.trustee_election_records(
                team, normalized_trust,
            )
            if election.data.get("process_uuid") == named
        ]:
            return SessionResult(
                "error", reason="that election is not this team's",
            )
        record = {
            "type": "team_trustee_state",
            "trust": normalized_trust,
            "holder_actor_uuid": holder,
            "previous_state_uuid": str(target.get("current_state_uuid") or ""),
            # An election when one informed it, and a plain resolution when
            # nobody ran one - the seat can be filled without a process.
            "cause": "election" if named else "resolution",
            "acted_by": self._identity_uuid,
            "acted_at": self._now(),
            "authority_basis_uuid": basis_uuid,
            "signals": str(signals or "").strip(),
            "consideration": str(consideration or "").strip(),
            "expectation": str(expectation or "").strip(),
        }
        if named:
            record["process_uuid"] = named
        return self.append_governance_record(team.uuid, record)

    def _bridge_to_team(self, topic_uuid: str, team: ProtocolNode) -> bool:
        """Publish a topic the team owns wherever the team is published."""
        bridge = getattr(self.collaboration, "bridge_topic_like", None)
        if not callable(bridge):
            self.session.trace_event(
                "team.item_bridge_failed",
                team_uuid=team.uuid,
                topic_uuid=str(topic_uuid),
                reason="collaboration bridge is unavailable",
            )
            return False
        result = bridge(topic_uuid, team.uuid)
        if getattr(result, "ok", False):
            return True
        self.session.trace_event(
            "team.item_bridge_failed",
            team_uuid=team.uuid,
            topic_uuid=str(topic_uuid),
            reason=str(getattr(result, "reason", "could not bridge topic") or ""),
        )
        return False

    # ---- what the team runs --------------------------------------------
    #
    # An initiative or a flow a team runs is another application's topic,
    # published on the team's channel. **Nothing about its contents is
    # recorded here.** What the team keeps is who says they hold it, which
    # is the only thing the others could not work out for themselves.
    #
    # Listing and connecting are Core's, and know nothing about initiatives
    # or flows. Making one and removing it are that application's own calls,
    # so they are named in this table and nowhere else. A fourth application
    # is listed and connected to for free; it needs a row here before one
    # can be made or removed from this page.
    ITEM_APPLICATIONS = {
        INITIATIVE_APPLICATION_ID: {
            "label": "Initiative",
            "api_version": INITIATIVE_FACADE_API_VERSION,
            "path": "/apps/initiative?board=",
            "delete": "delete_board",
            "template_required": False,
        },
        FLOW_APPLICATION_ID: {
            "label": "Flow",
            "api_version": FLOW_FACADE_API_VERSION,
            "path": "/apps/flow?process_uuid=",
            "delete": "delete_process",
            "template_required": True,
        },
    }

    def _application_facade(self, application_id: str):
        entry = self.ITEM_APPLICATIONS.get(application_id)
        if self.facades is None or not entry:
            return None
        try:
            return self.facades.find(application_id, entry["api_version"])
        except ValueError:
            return None

    def _item_entry(
        self, topic_uuid: str, node: ProtocolNode | None, active: bool,
    ) -> dict | None:
        """One item, or nothing when no application here claims the topic.

        Core answers which application owns a root type, so this never has
        to know what a board or a process is - and a topic belonging to
        S-Team itself is left out by the same test.
        """
        handler = (
            self.session.shared_topic_handler_for(node) if node else None
        )
        application_id = str(getattr(handler, "application_id", "") or "")
        entry = self.ITEM_APPLICATIONS.get(application_id)
        if not entry:
            return None
        data = node.data if node else {}
        return {
            "topic_uuid": topic_uuid,
            "application_id": application_id,
            "label": entry["label"],
            "title": str(
                data.get("title") or data.get("name") or "Untitled",
            ),
            "href": f"{entry['path']}{topic_uuid}",
            "active": active,
        }

    def item_lists(self, team: ProtocolNode) -> dict[str, list[dict]]:
        """What each member currently says they hold, by actor.

        The end of each actor's chain, and nothing before it: an earlier
        list is what they used to have.
        """
        by_actor: dict[str, list[ProtocolNode]] = {}
        for record in self.governance_records(team, "team_item_list"):
            by_actor.setdefault(
                str(record.data.get("actor_uuid") or ""), [],
            ).append(record)
        current = {}
        for actor_uuid, records in by_actor.items():
            head = self._chain_head(records, "previous_list_uuid")
            if head is None:
                # Two lists claiming to follow the same one is a contest,
                # and a contest holds nothing - the same answer every other
                # chain here gives.
                continue
            current[actor_uuid] = list(head.data.get("items") or [])
        return current

    def team_items(self, team: ProtocolNode) -> list[dict]:
        """Every initiative and flow this team runs.

        The union of what its members say they have. An item is listed while
        at least one of them still holds it and stops being listed when the
        last one drops it - which is the whole of what "the team runs this"
        can mean, since a client that holds none of it has nothing else to
        go on.

        It cannot be read off the channel instead. An explicit relay target
        polls only what this client has assigned to it and what it has
        already consented to receive, so an item nobody has told you about
        is not merely unread - it is unreachable. The list is what carries
        the uuid.
        """
        found: dict[str, dict] = {}
        for items in self.item_lists(team).values():
            for item in items:
                topic_uuid = str(item.get("topic_uuid") or "")
                application_id = str(item.get("application_id") or "")
                entry = self.ITEM_APPLICATIONS.get(application_id)
                if not topic_uuid or not entry or topic_uuid in found:
                    continue
                found[topic_uuid] = {
                    "topic_uuid": topic_uuid,
                    "application_id": application_id,
                    "label": entry["label"],
                    "title": str(item.get("title") or "Untitled"),
                    "href": f"{entry['path']}{topic_uuid}",
                    # Held here, not merely known about. Read from the tree
                    # rather than from this client's own list, so a copy
                    # deleted from the Cockpit reads as gone at once.
                    "active": self.session.get_node(topic_uuid) is not None,
                }
        return sorted(
            found.values(),
            key=lambda item: (item["label"], item["title"].lower()),
        )

    def _named_by_the_team(self, team: ProtocolNode) -> set[str]:
        """Every topic any member says is this team's."""
        named = {
            str(item.get("topic_uuid") or "")
            for items in self.item_lists(team).values()
            for item in items
        }
        named.discard("")
        return named

    def _my_items(
        self, team: ProtocolNode, including: str = "",
    ) -> list[dict]:
        """What this client holds of this team's work, right now.

        Read from the tree: something the team names, that this client
        actually has. Deliberately *not* read from the channel - asking
        which channel a topic sits on takes a lock beneath Session's and is
        the wrong question besides, since an item is the team's because a
        member says so, not because of where it is published.

        `including` is the one nobody has said anything about yet: what this
        client has just made or just offered, which becomes the team's by
        being said here first.
        """
        named = self._named_by_the_team(team)
        if including:
            named.add(including)
        mine = []
        for topic_uuid in sorted(named):
            entry = self._item_entry(
                topic_uuid, self.session.get_node(topic_uuid), True,
            )
            if entry:
                mine.append({
                    "topic_uuid": entry["topic_uuid"],
                    "application_id": entry["application_id"],
                    "title": entry["title"],
                })
        return mine

    def publish_my_items(
        self, team: ProtocolNode, including: str = "",
    ) -> SessionResult:
        """Say what this client holds, if that is not what it last said.

        Computed from the tree every time rather than kept up by hand: a
        stored "I have it" that nothing recomputes goes stale the moment
        somebody deletes the board from the Cockpit instead, and a list that
        lies is worse than no list.
        """
        mine = self._my_items(team, including)
        lists = self.item_lists(team)
        if mine == lists.get(self._identity_uuid, []):
            return SessionResult("ok", value=False)
        head = self._chain_head(
            [
                record for record in self.governance_records(
                    team, "team_item_list",
                )
                if record.data.get("actor_uuid") == self._identity_uuid
            ],
            "previous_list_uuid",
        )
        recorded = self.append_governance_record(team.uuid, {
            "type": "team_item_list",
            "actor_uuid": self._identity_uuid,
            "items": mine,
            "previous_list_uuid": head.uuid if head else "",
            "recorded_at": self._now(),
        })
        if recorded.status != "ok":
            return recorded
        return SessionResult("ok", value=True, effects=recorded.effects)

    def offerable_items(self, team: ProtocolNode) -> list[dict]:
        """This client's own items that are not on the team's channel yet.

        What makes the private case work: a team with no channel cannot
        publish anything, so an item made for it is simply this person's
        until there is somewhere to put it. Offering it then is one act.
        """
        named = self._named_by_the_team(team)
        out = []
        for topic_uuid in self.session.shared_topic_uuids():
            if topic_uuid == team.uuid or topic_uuid in named:
                continue
            entry = self._item_entry(
                topic_uuid, self.session.get_node(topic_uuid), True,
            )
            if entry:
                out.append(entry)
        return sorted(out, key=lambda item: (item["label"], item["title"].lower()))

    def item_kinds(self) -> list[dict]:
        """What can be made here, and what each can be started from.

        Only applications actually loaded in this process: the facades are
        per-process, so a standalone S-Team can list and connect but has
        nothing to make one with.
        """
        kinds = []
        for application_id, entry in sorted(self.ITEM_APPLICATIONS.items()):
            facade = self._application_facade(application_id)
            if facade is None:
                continue
            kinds.append({
                "application_id": application_id,
                "label": entry["label"],
                "template_required": entry["template_required"],
                "templates": self._item_templates(application_id, facade),
            })
        return kinds

    def _item_templates(self, application_id: str, facade) -> list[dict]:
        """What a new item can be copied from, as (value, name) pairs.

        An initiative starts from one of this client's own, which is what
        makes a template a template. A flow starts from a bundled
        definition, and must: a process with no workflow is not a process.
        """
        if application_id == INITIATIVE_APPLICATION_ID:
            boards = getattr(facade, "boards", None)
            return [
                {
                    "value": board.uuid,
                    "name": str(board.data.get("name") or "Untitled"),
                }
                for board in (boards() if callable(boards) else [])
            ]
        templates = getattr(facade, "templates", None)
        return [
            {
                "value": str(template.get("id") or ""),
                "name": str(template.get("name") or template.get("id") or ""),
            }
            for template in (templates() if callable(templates) else [])
        ]

    def _item_guard(self, team_uuid: str) -> tuple[ProtocolNode | None, SessionResult]:
        team = self._node(team_uuid, "team")
        if not team:
            return None, SessionResult("error", reason="team not found")
        if not self._is_current_member(team, self._identity_uuid):
            return None, SessionResult(
                "error",
                reason="only a current Member runs the team's work",
            )
        return team, SessionResult("ok")

    def create_team_item(
        self, team_uuid: str, application_id: str, title: str,
        template: str = "",
    ) -> SessionResult:
        """Make an initiative or a flow, and put it on the team's channel.

        Any member's act. Publishing is attempted and not required: a team
        nobody shares has nowhere to put it, and the item is that person's
        until the team has a channel and somebody offers it (see
        offer_team_item).
        """
        team, allowed = self._item_guard(team_uuid)
        if allowed.status != "ok":
            return allowed
        entry = self.ITEM_APPLICATIONS.get(str(application_id or "").strip())
        if not entry:
            return SessionResult("error", reason="unknown kind of item")
        facade = self._application_facade(application_id)
        if facade is None:
            return SessionResult(
                "error",
                reason=f"{entry['label']}s are not available on this client",
            )
        normalized = str(title or "").strip()
        if not normalized:
            return SessionResult("error", reason="a name is required")
        created = (
            self._create_initiative(facade, normalized, template)
            if application_id == INITIATIVE_APPLICATION_ID
            else self._create_flow(facade, normalized, template)
        )
        if created.status != "ok":
            return created
        # A team with no channel has nowhere to put it, and saying the team
        # runs something the others can never fetch would be a lie. It stays
        # this person's until there is somewhere - and offering it then is
        # one act (see offer_team_item).
        if self._bridge_to_team(str(created.value or ""), team):
            self.publish_my_items(
                self._node(team_uuid, "team") or team, str(created.value),
            )
        return created

    def _create_initiative(self, facade, title: str, template: str):
        source = str(template or "").strip()
        if not source:
            created = facade.create_board(title)
            return created
        copied = facade.copy_board(source)
        if copied.status != "ok":
            return copied
        # copy_board names the copy after its source. The name asked for
        # here is the one that was meant.
        board_uuid = getattr(copied.value, "uuid", copied.value)
        renamed = facade.rename_board(str(board_uuid), title)
        if renamed.status != "ok":
            return renamed
        return SessionResult(
            "ok", value=str(board_uuid), effects=copied.effects,
        )

    def _create_flow(self, facade, title: str, template: str):
        definition = str(template or "").strip()
        chosen = next(
            (
                item for item in (facade.templates() or [])
                if str(item.get("id") or "") == definition
            ),
            None,
        )
        if not chosen:
            return SessionResult("error", reason="choose a workflow to start from")
        created = facade.create_process(
            title, definition, str(chosen.get("version") or ""),
        )
        if created.status != "ok":
            return created
        return SessionResult(
            "ok",
            value=str(getattr(created.value, "uuid", created.value) or ""),
            effects=created.effects,
        )

    def offer_team_item(self, team_uuid: str, topic_uuid: str) -> SessionResult:
        """Put an item this client already holds on the team's channel."""
        team, allowed = self._item_guard(team_uuid)
        if allowed.status != "ok":
            return allowed
        node = self.session.get_node(str(topic_uuid or "").strip())
        if self._item_entry(str(topic_uuid), node, True) is None:
            return SessionResult("error", reason="that is not an item")
        if not self._bridge_to_team(str(topic_uuid), team):
            return SessionResult(
                "error",
                reason=(
                    "this team has no channel yet, so there is nowhere to "
                    "publish it"
                ),
            )
        self.publish_my_items(
            self._node(team_uuid, "team") or team, str(topic_uuid),
        )
        return SessionResult("ok", value=str(topic_uuid))

    def connect_team_item(self, team_uuid: str, topic_uuid: str) -> SessionResult:
        """Take up an item the team runs. This client's own consent.

        The same act as joining an election, and separate for the same
        reason: Core will not graft a topic into this tree because it
        happens to share a channel with one already here.
        """
        team, allowed = self._item_guard(team_uuid)
        if allowed.status != "ok":
            return allowed
        join = getattr(self.collaboration, "join_bridged_topic", None)
        if not callable(join):
            return SessionResult(
                "error", reason="this client cannot join shared topics",
            )
        normalized_topic = str(topic_uuid or "").strip()
        joined = join(normalized_topic, team.uuid)
        if not getattr(joined, "ok", False):
            reason = getattr(joined, "reason", "could not connect to it")
            self.session.trace_event(
                "team.item_connect_failed",
                team_uuid=team.uuid,
                topic_uuid=normalized_topic,
                reason=str(reason or ""),
            )
            return SessionResult(
                "error",
                reason=reason,
            )
        for application_id in self.ITEM_APPLICATIONS:
            self.session.mount_cached_topics(application_id)
        # Joining records both the receiving consent and this replica's
        # publication binding before the first local copy has to exist.
        if self.session.get_node(normalized_topic) is not None:
            self.publish_my_items(
                self._node(team_uuid, "team") or team, normalized_topic,
            )
        return SessionResult("ok", value=normalized_topic)

    def remove_team_item(self, team_uuid: str, topic_uuid: str) -> SessionResult:
        """Take an item off this client, and nothing more.

        The same act as deleting it from the Cockpit, because it is the same
        act: the owning application's own delete. Everybody else keeps
        theirs, and the item goes on being offered here for as long as one
        of them publishes it.
        """
        team, allowed = self._item_guard(team_uuid)
        if allowed.status != "ok":
            return allowed
        node = self.session.get_node(str(topic_uuid or "").strip())
        item = self._item_entry(str(topic_uuid), node, True)
        if item is None:
            return SessionResult("error", reason="you do not have that item")
        entry = self.ITEM_APPLICATIONS[item["application_id"]]
        facade = self._application_facade(item["application_id"])
        remove = getattr(facade, entry["delete"], None) if facade else None
        if not callable(remove):
            return SessionResult(
                "error",
                reason=f"{entry['label']}s are not available on this client",
            )
        removed = remove(str(topic_uuid))
        if getattr(removed, "status", "") != "ok":
            return removed
        # Saying so is the whole of what the others learn from it: the item
        # stays on the team's list while somebody else still has it, and
        # comes off it when the last of them says this.
        self.publish_my_items(self._node(team_uuid, "team") or team)
        return removed

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

    def _is_current_member(self, team: ProtocolNode, actor_uuid: str) -> bool:
        """Membership is one question with one answer, asked here.

        It used to be two: a standing read from the application records,
        plus a second look at the system Member role for whoever founded
        the team. Both now go through member_standing, which is the only
        place that knows how membership was written.
        """
        return self.member_standing(team, actor_uuid) == "accepted"

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
            # Judged against the state the record names, not against the head
            # of the chain now. Requiring the basis to still be current meant
            # a trustee's whole trail became unauthorized the moment they
            # resigned - invisibly, because records already adopted stayed,
            # so only a replica that received them afterwards refused them.
            # Whether somebody was a member then depended on where a sync
            # happened to fall. Decisions taken in office stand; that is what
            # an append-only trail is for.
            #
            # The cost, taken deliberately: somebody who has left can still
            # write new records naming the state they used to hold. They are
            # signed, attributed and visible, and the signatures are there to
            # say who did what rather than to prevent it.
            if state.data.get("trust") != trust:
                return ("unauthorized", "the authority basis is another trusteeship")
            if state.data.get("holder_actor_uuid") != actor_uuid:
                return ("unauthorized", f"the Actor does not hold {trust.title()}")
            return ("authorized", "")
        candidacy = self._governance_node(
            team, basis_uuid, "team_trustee_candidacy",
        )
        if candidacy is None:
            return ("deferred", "the authority basis is not available")
        if (
            candidacy.data.get("trust") != trust
            or candidacy.data.get("actor_uuid") != actor_uuid
            or candidacy.data.get("previous_candidacy_uuid")
        ):
            return ("unauthorized", "the candidacy does not grant this authority")
        # The vacancy the candidacy answers, read as a record. Whether the
        # seat is still empty and the candidacy still active are questions
        # about now, and asking them here made an acting trustee's past
        # decisions stop being authorized the moment the seat was filled.
        # Nothing new becomes writable: composing an acting record still
        # goes through _authority_basis_for_actor, which hands out a basis
        # only while the seat is vacant and the candidacy is live.
        vacancy = self._governance_node(
            team, str(candidacy.data.get("vacant_state_uuid") or ""),
            "team_trustee_state",
        )
        if vacancy is None:
            return ("deferred", "the vacancy the candidacy answers is not available")
        if vacancy.data.get("trust") != trust or vacancy.data.get(
            "holder_actor_uuid",
        ):
            return ("unauthorized", "the candidacy does not answer a vacancy")
        if not self._is_current_member(team, actor_uuid):
            return ("unauthorized", "the acting candidate is not a current Member")
        return ("authorized", "")

    # One row per governance record type, in the order the three questions
    # are asked of it: which field names its author, what its own shape
    # requires beyond the field contract, and what has to be true before it
    # may be adopted. Adding a type is a row and two short methods beside
    # their siblings, rather than another branch in two long functions that
    # every change to any type had to be threaded through.
    #
    # An empty middle column means the field contract is the whole of that
    # type's shape.
    GOVERNANCE_RECORDS = {
        "team_trustee_state": (
            "acted_by", "_trustee_state_schema_error", "_assess_trustee_state",
        ),
        "team_membership": (
            "acted_by", "_membership_schema_error", "_assess_membership",
        ),
        "team_acceptance": (
            "actor_uuid", "_acceptance_schema_error",
            "_assess_agreement_acceptance",
        ),
        "team_membership_application": (
            "actor_uuid", "_membership_application_schema_error",
            "_assess_membership_application",
        ),
        "team_membership_invitation": (
            "opened_by", "_membership_invitation_schema_error",
            "_assess_membership_invitation",
        ),
        "team_trustee_election": (
            "triggered_by", "_trustee_election_schema_error",
            "_assess_trustee_election",
        ),
        "team_trustee_candidacy": (
            "actor_uuid", "_trustee_candidacy_schema_error",
            "_assess_trustee_candidacy",
        ),
        "team_trustee_action": (
            "acted_by", "_trustee_action_schema_error",
            "_assess_trustee_action",
        ),
        "team_item_list": (
            "actor_uuid", "_item_list_schema_error", "_assess_item_list",
        ),
        "team_trustee_reality": ("observed_by", "", "_assess_trustee_reality"),
    }

    def assess_governance_record(
        self, team: ProtocolNode, node: ProtocolNode,
        verification: str | None = None,
    ) -> dict:
        """Whether a governance record may be adopted here.

        Four questions every record answers - is it signed, is it the shape
        its type declares, is it in the right place, and did the Actor it
        names write it - and then whatever its own type requires, which is
        its assessor's business rather than this one's.
        """
        verification = verification or self.session.revision_verification(node)
        if verification == "unknown":
            return {"status": "deferred", "reason": "the signing key is not known"}
        if verification != "valid":
            return {"status": "invalid", "reason": "authorship signature is invalid"}
        schema_error = self.governance_schema_error(node)
        if schema_error:
            return {"status": "invalid", "reason": schema_error}
        node_type = node.data.get("type")
        if node_type == "team_trustee_reality":
            # An observation sits under the decision it observes: which one
            # that is is a fact about where it is, not a uuid it carries and
            # could carry wrongly.
            parent = self.session.protocol.index.get(node.parent_uuid or "")
            placed = (
                parent is not None
                and parent.data.get("type") == "team_trustee_action"
            )
        else:
            container = self.RECORD_CONTAINERS.get(node_type)
            placed = bool(container) and self._is_in(node, team, container)
        if not placed:
            return {
                "status": "invalid",
                "reason": "Governance records must sit in their Team's container for that record.",
            }
        data = node.data
        author_field, _, assessor = self.GOVERNANCE_RECORDS[data["type"]]
        actor_uuid = data.get(author_field) or ""
        status, reason = self._signed_actor_status(node, actor_uuid)
        if status != "authorized":
            return {"status": status, "reason": reason}
        if node_type == "team_trustee_reality":
            objection = self._assess_trustee_reality(
                team, data, actor_uuid, node.parent_uuid or "",
            )
        else:
            objection = getattr(self, assessor)(team, data, actor_uuid)
        return objection or {"status": "authorized", "reason": ""}

    # Every assessor below answers with an objection, or with nothing when it
    # has none, so each reads as the list of ways one record can be wrong.

    def _authority_refusal(
        self, team: ProtocolNode, trust: str, actor_uuid: str, basis_uuid: str,
    ) -> dict | None:
        """The trusteeship check, as an objection or nothing."""
        status, reason = self._trust_authority(
            team, trust, actor_uuid, basis_uuid,
        )
        if status == "authorized":
            return None
        return {"status": status, "reason": reason}

    def _membership_authority_refusal(
        self, team: ProtocolNode, data: dict, actor_uuid: str,
    ) -> dict | None:
        return self._authority_refusal(
            team, self.MEMBERSHIP_TRUST, actor_uuid,
            data["authority_basis_uuid"],
        )

    def _assess_trustee_state(
        self, team: ProtocolNode, data: dict, actor_uuid: str,
    ) -> dict | None:
        trust = data["trust"]
        holder_status, holder_reason = self._holder_may_be_a_trustee(
            str(data.get("holder_actor_uuid") or ""),
        )
        if holder_status != "authorized":
            return {"status": holder_status, "reason": holder_reason}
        same_trust = [
            state
            for state in self.governance_records(team, "team_trustee_state")
            if state.data.get("trust") == trust
        ]
        if data["cause"] == "genesis":
            if same_trust:
                return {"status": "unauthorized", "reason": "trusteeship genesis already exists"}
            if data["holder_actor_uuid"] != actor_uuid:
                return {"status": "unauthorized", "reason": "genesis must be authored by its holder"}
            return None
        previous = self._governance_node(
            team, data["previous_state_uuid"], "team_trustee_state",
        )
        if previous is None or previous.data.get("trust") != trust:
            return {"status": "deferred", "reason": "previous trustee state is not available"}
        if previous.uuid != self.trustee_projection(team, trust).get(
            "current_state_uuid",
        ):
            competing = any(
                state.data.get("previous_state_uuid") == previous.uuid
                for state in same_trust
            )
            if not competing:
                return {"status": "unauthorized", "reason": "previous trustee state is stale"}
        if data["cause"] == "resignation":
            return self._assess_resignation(data, previous, actor_uuid)
        if data["cause"] == "election":
            named = [
                election
                for election in self.trustee_election_records(team, trust)
                if election.data.get("process_uuid")
                == data.get("process_uuid")
            ]
            if not named:
                return {
                    "status": "deferred",
                    "reason": "the trustee election record is not available",
                }
        facilitator = self._sole_facilitating_trust(trust)
        if not facilitator:
            return {
                "status": "invalid",
                "reason": "the facilitating trusteeship is ambiguous",
            }
        return self._authority_refusal(
            team, facilitator, actor_uuid, data["authority_basis_uuid"],
        )

    def _assess_resignation(
        self, data: dict, previous: ProtocolNode, actor_uuid: str,
    ) -> dict | None:
        if data["authority_basis_uuid"] != previous.uuid:
            return {"status": "unauthorized", "reason": "resignation basis must be the previous state"}
        if previous.data.get("holder_actor_uuid") != actor_uuid:
            return {"status": "unauthorized", "reason": "only the incumbent may resign"}
        if data["holder_actor_uuid"]:
            return {"status": "invalid", "reason": "resignation must leave the trusteeship vacant"}
        return None

    def _assess_membership(
        self, team: ProtocolNode, data: dict, actor_uuid: str,
    ) -> dict | None:
        subject_uuid = str(data.get("actor_uuid") or "")
        cause = data["cause"]
        if cause == "genesis":
            # The first membership of a team is its founder's own, and there
            # can only ever be one: everybody after them is admitted by
            # somebody who is already here.
            if self.governance_records(team, "team_membership"):
                return {"status": "unauthorized", "reason": "the team already has a founding membership"}
            if subject_uuid != actor_uuid:
                return {"status": "unauthorized", "reason": "a founding membership is the founder's own"}
            return None
        if cause == "acceptance":
            return self._assess_acceptance(team, data, actor_uuid, subject_uuid)
        return self._assess_membership_ending(
            team, data, actor_uuid, subject_uuid, cause,
        )

    def _assess_acceptance(
        self, team: ProtocolNode, data: dict, actor_uuid: str,
        subject_uuid: str,
    ) -> dict | None:
        """An Identity-issued badge for one signed Actor application."""
        authority = self._membership_authority_refusal(team, data, actor_uuid)
        if authority:
            return authority
        application = self._governance_node(
            team, str(data.get("application_uuid") or ""),
            "team_membership_application",
        )
        if application is None:
            return {"status": "deferred", "reason": "the membership application is not available"}
        if application.data.get("actor_uuid") != subject_uuid:
            return {"status": "invalid", "reason": "the badge names another applicant"}
        copied = {
            "membership_type_uuid", "invitation_uuid",
            "previous_membership_uuid", "membership_info",
            "acceptance_requirement", "acceptance_text",
            "agreement_accepted", "agreement_version", "reference_hash",
        }
        if any(data.get(field) != application.data.get(field) for field in copied):
            return {"status": "invalid", "reason": "the badge does not reproduce its application"}
        return None

    def _assess_membership_application(
        self, team: ProtocolNode, data: dict, actor_uuid: str,
    ) -> dict | None:
        if data.get("actor_uuid") != actor_uuid:
            return {"status": "unauthorized", "reason": "an Actor authors their own application"}
        invitation = self._governance_node(
            team, str(data.get("invitation_uuid") or ""),
            "team_membership_invitation",
        )
        if invitation is None:
            return {"status": "deferred", "reason": "the invitation is not available"}
        if invitation.data.get("membership_type_uuid") != data.get(
            "membership_type_uuid",
        ):
            return {"status": "invalid", "reason": "the application answers another membership type"}
        if invitation.data.get("state") != "open":
            return {"status": "invalid", "reason": "the application does not name an opening"}
        if not self._within_invitation_window(
            invitation.data, str(data.get("applied_at") or ""),
        ):
            return {"status": "unauthorized", "reason": "the invitation was not open when the Actor applied"}
        named = str(data.get("previous_membership_uuid") or "")
        if named:
            previous = self._governance_node(team, named, "team_membership")
            if previous is None:
                return {"status": "deferred", "reason": "the previous membership is not available"}
            if previous.data.get("actor_uuid") != actor_uuid:
                return {"status": "invalid", "reason": "the application continues somebody else's membership"}
        if bool(data.get("agreement_version")) != bool(
            data.get("agreement_accepted"),
        ):
            return {"status": "invalid", "reason": "Agreement consent does not match the referenced Agreement"}
        return None

    def _assess_membership_ending(
        self, team: ProtocolNode, data: dict, actor_uuid: str,
        subject_uuid: str, cause: str,
    ) -> dict | None:
        # An ending always points at the membership it ends. There used to be
        # an exception for standing written before membership records
        # existed, which had nothing to name; without it, naming nothing is a
        # way to end a membership without pointing at it.
        named = str(data["previous_membership_uuid"] or "")
        if not named:
            return {"status": "unauthorized", "reason": "there is no current membership to end"}
        previous = self._governance_node(team, named, "team_membership")
        if previous is None:
            return {"status": "deferred", "reason": "the membership being ended is not available"}
        if previous.data.get("actor_uuid") != subject_uuid:
            return {"status": "invalid", "reason": "the ending names somebody else's membership"}
        # Checked as a record: what it names must be a standing membership.
        # Not that it is still the current one - that would make an ending
        # stop being authorized as soon as anything followed it.
        if previous.data.get("state") != "member":
            return {"status": "invalid", "reason": "the membership being ended is not a standing one"}
        if cause == "departure":
            # Leaving is the member's own act and nobody else's, which is the
            # counterpart of Identity's power to remove.
            if subject_uuid != actor_uuid:
                return {"status": "unauthorized", "reason": "only the member themselves may leave"}
            return None
        return self._membership_authority_refusal(team, data, actor_uuid)

    def _assess_membership_invitation(
        self, team: ProtocolNode, data: dict, actor_uuid: str,
    ) -> dict | None:
        """Identity opening a membership type to the pool, or closing it.

        One chain per type, so a first invitation is only a first if nothing
        already opened that type - anything after continues what is there.
        That is what makes "one invitation per type at a time" a property of
        the records rather than a rule the page remembers to apply.
        """
        type_uuid = str(data.get("membership_type_uuid") or "")
        membership_type = self._node(type_uuid, self.MEMBERSHIP_TYPE_TYPE)
        if not self._is_in(membership_type, team, "membership-types"):
            return {"status": "deferred", "reason": "the membership type is not available"}
        named = str(data["previous_invitation_uuid"] or "")
        if named:
            previous = self._governance_node(
                team, named, "team_membership_invitation",
            )
            if previous is None:
                return {"status": "deferred", "reason": "the previous invitation is not available"}
            if previous.data.get("membership_type_uuid") != type_uuid:
                return {"status": "invalid", "reason": "the invitation continues another type's chain"}
            if data["state"] == "closed" and previous.data.get("state") != "open":
                return {"status": "invalid", "reason": "a closure must follow an opening"}
        elif data["state"] == "closed":
            return {"status": "invalid", "reason": "a closure must name the opening it closes"}
        elif self.membership_invitation_roots(team, type_uuid):
            # A second root would be a second live invitation for one type,
            # which is the thing the chain exists to prevent.
            return {"status": "invalid", "reason": "that membership type already has an invitation chain"}
        return self._membership_authority_refusal(team, data, actor_uuid)

    def _assess_trustee_election(
        self, team: ProtocolNode, data: dict, actor_uuid: str,
    ) -> dict | None:
        """Any member may start one, and only one per seat at a time.

        There is nothing else to judge. Starting an election decides
        nothing - it opens a process - so the questions that used to be
        asked here belong where the seat is actually filled.
        """
        if not self._is_current_member(team, actor_uuid):
            return {
                "status": "unauthorized",
                "reason": "only a current Member may start an election",
            }
        if data["trust"] not in self.TRUSTS:
            return {"status": "invalid", "reason": "unknown trusteeship"}
        outstanding = [
            election for election in self.elections_under_way(
                team, data["trust"],
            )
            if election.data.get("process_uuid") != data.get("process_uuid")
        ]
        if outstanding:
            return {
                "status": "unauthorized",
                "reason": (
                    "an election for this trusteeship is already under way"
                ),
            }
        return None

    def _assess_item_list(
        self, team: ProtocolNode, data: dict, actor_uuid: str,
    ) -> dict | None:
        """Only a member, and only about themselves.

        There is nothing else to judge: a list says what one client has, not
        what anybody may do, so the only way to get it wrong is to write
        somebody else's.
        """
        if data["actor_uuid"] != actor_uuid:
            return {
                "status": "unauthorized",
                "reason": "a list of items is its own holder's",
            }
        if not self._is_current_member(team, actor_uuid):
            return {
                "status": "unauthorized",
                "reason": "only a current Member runs the team's work",
            }
        return None

    def _assess_trustee_candidacy(
        self, team: ProtocolNode, data: dict, actor_uuid: str,
    ) -> dict | None:
        vacancy = self._governance_node(
            team, data["vacant_state_uuid"], "team_trustee_state",
        )
        if vacancy is None:
            return {"status": "deferred", "reason": "vacant trustee state is not available"}
        projection = self.trustee_projection(team, data["trust"])
        if (
            projection.get("state") != "vacant"
            or projection.get("current_state_uuid") != vacancy.uuid
            or vacancy.data.get("trust") != data["trust"]
        ):
            return {"status": "unauthorized", "reason": "trusteeship is not currently vacant"}
        if data["state"] == "withdrawn":
            objection = self._assess_candidacy_withdrawal(
                team, data, actor_uuid,
            )
            if objection:
                return objection
        elif any(
            candidate.data.get("actor_uuid") == actor_uuid
            and candidate.data.get("vacant_state_uuid") == vacancy.uuid
            and self.trustee_candidacy_projection(
                team, candidate.uuid,
            ).get("state") == "active"
            for candidate in self.trustee_candidacy_roots(team, data["trust"])
        ):
            return {"status": "unauthorized", "reason": "the Actor is already a candidate"}
        if not self._is_current_member(team, actor_uuid):
            return {"status": "unauthorized", "reason": "only a current Member may become a candidate"}
        return None

    def _assess_candidacy_withdrawal(
        self, team: ProtocolNode, data: dict, actor_uuid: str,
    ) -> dict | None:
        previous = self._governance_node(
            team, data["previous_candidacy_uuid"], "team_trustee_candidacy",
        )
        if previous is None:
            return {"status": "deferred", "reason": "previous candidacy is not available"}
        root = next((
            candidate
            for candidate in self.trustee_candidacy_roots(team, data["trust"])
            if candidate.uuid == previous.uuid
            or self.trustee_candidacy_projection(
                team, candidate.uuid,
            ).get("current_uuid") == previous.uuid
        ), None)
        if (
            root is None
            or root.data.get("actor_uuid") != actor_uuid
            or root.data.get("vacant_state_uuid") != data["vacant_state_uuid"]
            or self.trustee_candidacy_projection(
                team, root.uuid,
            ).get("current_uuid") != previous.uuid
            or previous.data.get("state") != "active"
        ):
            return {"status": "invalid", "reason": "withdrawal does not match the active candidacy"}
        return None

    def _assess_trustee_action(
        self, team: ProtocolNode, data: dict, actor_uuid: str,
    ) -> dict | None:
        return self._authority_refusal(
            team, data["trust"], actor_uuid, data["authority_basis_uuid"],
        )

    def _assess_trustee_reality(
        self, team: ProtocolNode, data: dict, actor_uuid: str,
        parent_uuid: str = "",
    ) -> dict | None:
        action = self._governance_node(
            team, parent_uuid, "team_trustee_action",
        )
        if action is None:
            return {"status": "deferred", "reason": "observed trustee action is not available"}
        facilitator = self._sole_facilitating_trust(
            str(action.data.get("trust") or ""),
        )
        if not facilitator:
            return {
                "status": "invalid",
                "reason": "the facilitating trusteeship is ambiguous",
            }
        return self._authority_refusal(
            team, facilitator, actor_uuid, data["authority_basis_uuid"],
        )

    def append_governance_record(
        self, team_uuid: str, data: dict, parent_uuid: str = "",
    ) -> SessionResult:
        """Write one record where its kind belongs.

        `parent_uuid` is for the one kind whose place is another record
        rather than a container of its own - an observation under the
        decision it observes.
        """
        team = self._node(team_uuid, "team")
        if not team:
            return SessionResult("error", reason="team not found")
        allowed = self._interaction_guard(team)
        if allowed.status != "ok":
            return allowed
        if parent_uuid:
            container = self.session.protocol.index.get(parent_uuid)
        else:
            name = self.RECORD_CONTAINERS.get(data.get("type"))
            container = self._container(team, name) if name else None
        if container is None:
            return SessionResult("error", reason="record container unavailable")
        candidate = ProtocolNode(
            copy.deepcopy(data), parent_uuid=container.uuid,
            revision_origin=self.session.identity.data["identity_key"],
        )
        assessment = self.assess_governance_record(
            team, candidate, verification="valid",
        )
        if assessment["status"] != "authorized":
            return SessionResult("error", reason=assessment["reason"])
        return self.session.create_child(container.uuid, data, {})

    # Membership types are Identity's to declare: which memberships this
    # team supports, and what each asks of somebody. Content rather than
    # records - edited in place like a role - but guarded, because a role is
    # work anybody on the team may define and a membership is the door.

    def create_membership_type(
        self, team_uuid: str, name: str, requirements: str = "",
        acceptance: str = "",
    ) -> SessionResult:
        team = self._node(team_uuid, "team")
        if not team:
            return SessionResult("error", reason="team not found")
        allowed = self._interaction_guard(team)
        if allowed.status != "ok":
            return allowed
        if not self._authority_basis_for_actor(
            team, self.MEMBERSHIP_TRUST, self._identity_uuid,
        ):
            return SessionResult(
                "error", reason="only the Identity holder declares memberships",
            )
        normalized = str(name or "").strip()
        if not normalized:
            return SessionResult("error", reason="a membership needs a name")
        normalized = self._distinct_name(normalized, [
            node.data.get("name") for node in self.membership_types(team)
        ])
        container = self._container(team, "membership-types")
        if container is None:
            return SessionResult(
                "error", reason="membership types container unavailable",
            )
        return self.session.create_child(
            container.uuid,
            {
                "type": self.MEMBERSHIP_TYPE_TYPE,
                "name": normalized,
                "requirements": str(requirements or "").strip(),
                "acceptance": str(acceptance or "").strip(),
                "order": self.session.next_child_order(container.uuid),
            },
            {},
        )

    def rename_membership_type(
        self, membership_type_uuid: str, name: str,
    ) -> SessionResult:
        return self._edit_membership_type(
            membership_type_uuid, "name", name, distinct=True,
        )

    def set_membership_requirements(
        self, membership_type_uuid: str, requirements: str,
    ) -> SessionResult:
        return self._edit_membership_type(
            membership_type_uuid, "requirements", requirements,
        )

    def set_membership_acceptance(
        self, membership_type_uuid: str, acceptance: str,
    ) -> SessionResult:
        """What somebody is agreeing to when they take this membership up.

        The counterpart of `requirements`, and a separate field because they
        are addressed to different moments: requirements are read while
        deciding, and this is what the decision itself says. Rolling them
        into one would make the sentence somebody accepts a description of
        who may apply.
        """
        return self._edit_membership_type(
            membership_type_uuid, "acceptance", acceptance,
        )

    def _edit_membership_type(
        self, membership_type_uuid: str, field: str, value: str,
        distinct: bool = False,
    ) -> SessionResult:
        node = self._node(membership_type_uuid, self.MEMBERSHIP_TYPE_TYPE)
        if not node:
            return SessionResult("error", reason="membership type not found")
        team = self._local_team_topic(node.uuid)
        if not team or not self._authority_basis_for_actor(
            team, self.MEMBERSHIP_TRUST, self._identity_uuid,
        ):
            return SessionResult(
                "error", reason="only the Identity holder declares memberships",
            )
        allowed = self._interaction_guard_for_node(node.uuid)
        if allowed.status != "ok":
            return allowed
        normalized = str(value or "").strip()
        if distinct:
            if not normalized:
                return SessionResult("error", reason="a membership needs a name")
            normalized = self._distinct_name(normalized, [
                other.data.get("name")
                for other in self.membership_types(team)
                if other.uuid != node.uuid
            ])
        data = dict(node.data)
        data[field] = normalized
        return self.session.modify(node.uuid, data, node.weights)

    def delete_membership_type(
        self, membership_type_uuid: str,
    ) -> SessionResult:
        """Stop supporting a membership. Everybody on it returns to the pool.

        No cascade, and that is the point: a membership names its type by
        uuid, so the type going away stops those chains resolving without one
        of them being rewritten. The trail still says what everybody was, and
        their roles lapse the way they do for anybody who is not a member.
        """
        node = self._node(membership_type_uuid, self.MEMBERSHIP_TYPE_TYPE)
        if not node:
            return SessionResult("error", reason="membership type not found")
        team = self._local_team_topic(node.uuid)
        if not team or not self._authority_basis_for_actor(
            team, self.MEMBERSHIP_TRUST, self._identity_uuid,
        ):
            return SessionResult(
                "error", reason="only the Identity holder declares memberships",
            )
        allowed = self._interaction_guard_for_node(node.uuid)
        if allowed.status != "ok":
            return allowed
        return self.session.delete(node.uuid)

    def open_membership_invitation(
        self, team_uuid: str, membership_type_uuid: str, expires_at: str,
    ) -> SessionResult:
        """Open one membership type to the pool, until a stated moment.

        Open and closed are one toggle over one chain per type, so there is
        never more than one live invitation for a membership and reopening
        continues the history rather than starting beside it.
        """
        team = self._node(team_uuid, "team")
        if not team:
            return SessionResult("error", reason="team not found")
        membership_type = self._node(
            str(membership_type_uuid or "").strip(), self.MEMBERSHIP_TYPE_TYPE,
        )
        if not self._is_in(membership_type, team, "membership-types"):
            return SessionResult("error", reason="membership type not found")
        if not str(membership_type.data.get("acceptance") or "").strip():
            self.session.trace_event(
                "team.membership_invitation_unexpected",
                team_uuid=team.uuid,
                membership_type_uuid=membership_type.uuid,
                reason="membership has no Acceptance Requirement",
            )
            return SessionResult(
                "error", reason="an Acceptance Requirement is required",
            )
        agreement = self.agreement_projection(team)
        if agreement.get("state") not in {"agreed", "absent"}:
            self.session.trace_event(
                "team.membership_invitation_blocked",
                team_uuid=team.uuid,
                membership_type_uuid=membership_type.uuid,
                agreement_state=agreement.get("state"),
                reason=agreement.get("reason"),
            )
            return SessionResult(
                "error",
                reason="Identity holders must align their Agreement first",
            )
        now = self._now()
        expiry = str(expires_at or "").strip()
        # An expiry already behind us would open a door nobody could walk
        # through: every acceptance is judged against this window, so it
        # would refuse them all while the page said open.
        if not expiry or expiry <= now:
            return SessionResult(
                "error", reason="an invitation expires in the future",
            )
        existing = self.membership_invitation_roots(team, membership_type.uuid)
        previous_uuid = ""
        if existing:
            projection = self.membership_invitation_projection(
                team, existing[0].uuid,
            )
            if projection["state"] == "open":
                return SessionResult(
                    "error", reason="that membership is already open",
                )
            if projection["state"] == "contested":
                return SessionResult(
                    "error", reason="that membership's invitation is contested",
                )
            previous_uuid = projection["current_uuid"]
        return self.append_governance_record(team.uuid, {
            "type": "team_membership_invitation",
            "membership_type_uuid": membership_type.uuid,
            "previous_invitation_uuid": previous_uuid,
            "state": "open",
            "opened_by": self._identity_uuid,
            "opened_at": now,
            "expires_at": expiry,
            "authority_basis_uuid": self._authority_basis_for_actor(
                team, self.MEMBERSHIP_TRUST, self._identity_uuid,
            ),
        })

    def close_membership_invitation(
        self, team_uuid: str, membership_type_uuid: str,
    ) -> SessionResult:
        team = self._node(team_uuid, "team")
        if not team:
            return SessionResult("error", reason="team not found")
        roots = self.membership_invitation_roots(
            team, str(membership_type_uuid or "").strip(),
        )
        if not roots:
            return SessionResult("error", reason="that membership is not open")
        projection = self.membership_invitation_projection(team, roots[0].uuid)
        if projection["state"] != "open":
            return SessionResult("error", reason="that membership is not open")
        head = self._governance_node(
            team, projection["current_uuid"], "team_membership_invitation",
        )
        if head is None:
            return SessionResult("error", reason="that membership is not open")
        return self.append_governance_record(team.uuid, {
            "type": "team_membership_invitation",
            "membership_type_uuid": head.data["membership_type_uuid"],
            "previous_invitation_uuid": head.uuid,
            "state": "closed",
            "opened_by": self._identity_uuid,
            "opened_at": head.data["opened_at"],
            "expires_at": head.data["expires_at"],
            "authority_basis_uuid": self._authority_basis_for_actor(
                team, self.MEMBERSHIP_TRUST, self._identity_uuid,
            ),
            "closed_at": self._now(),
        })

    def record_trustee_action(
        self,
        team_uuid: str,
        trust: str,
        subject_uuid: str,
        payload: dict | None = None,
        value: str = "",
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
        # The subject is not enforced. It is a reference somebody writes down
        # so the record can be found again, and a record that says who
        # decided what, and when, is a record whether or not they had one to
        # give. Refusing to keep it was the page losing the decision to
        # protect a field.
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
            "value": str(value or "").strip(),
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
        facilitator_trust = self._sole_facilitating_trust(
            str(action.data.get("trust") or ""),
        )
        if not facilitator_trust:
            return SessionResult(
                "error",
                reason="the facilitating trusteeship must be chosen explicitly",
            )
        basis_uuid = self._authority_basis_for_actor(
            team, facilitator_trust, self._identity_uuid,
        )
        return self.append_governance_record(team.uuid, {
            "type": "team_trustee_reality",
            "observed_by": self._identity_uuid,
            "observed_at": self._now(),
            "reality": normalized_reality,
            "authority_basis_uuid": basis_uuid,
        }, parent_uuid=action.uuid)

    def trustee_actions_payload(self, team: ProtocolNode) -> list[dict]:
        people = self._known_people()
        actions = self.governance_records(team, "team_trustee_action")
        realities = self.governance_records(team, "team_trustee_reality")
        def group_key(node: ProtocolNode) -> tuple[str, str, str]:
            """What two records have to share to be records of one act.

            The subject is what names the act, and it is not required. A
            record without one names nothing, so it can only ever be
            grouped with itself - keyed on the empty string, every
            unlabelled decision in a trusteeship would report every other
            one as a conflicting record of the same thing.
            """
            subject = str(node.data.get("subject_uuid") or "")
            return (
                str(node.data.get("trust") or ""),
                str(node.data.get("action_kind") or ""),
                subject or f"#{node.uuid}",
            )

        groups: dict[tuple[str, str, str], list[ProtocolNode]] = {}
        for action in actions:
            groups.setdefault(group_key(action), []).append(action)
        payload = []
        for action in actions:
            actor_uuid = str(action.data.get("acted_by") or "")
            actor = people.get(actor_uuid) or {}
            key = group_key(action)
            facilitator_trust = self._sole_facilitating_trust(key[0])
            observations = []
            for observation in self._realities_of(action):
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
                "subject_uuid": str(action.data.get("subject_uuid") or ""),
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

    def decision_trail_payload(self, team: ProtocolNode) -> list[dict]:
        """Everything that has been decided here, newest first.

        One row per record: when it happened, who did it, what they were
        doing and how it came out. The panel used to show only trustee
        actions, which left the acts that actually move a team - stepping
        out of a trusteeship, admitting a member, taking a role - asking
        for their signals and then recording them nowhere anybody reads.

        A Reality is not a row: it is an observation of an action, so it
        stays on the action it observes.
        """
        people = self._known_people()
        trail: list[dict] = []

        def named(actor_uuid: str | None) -> tuple[str, bool]:
            normalized = str(actor_uuid or "").strip()
            if not normalized:
                return ("Nobody", False)
            # A result reads as a sentence about somebody, so it says "You"
            # rather than falling back to your own address - which is what a
            # profile with no display name would otherwise be called here.
            if normalized == self._identity_uuid:
                return ("You", True)
            person = people.get(normalized)
            if person:
                name = person.get("name") or person.get("address")
            else:
                seated = self._node(normalized, "team")
                name = seated.data.get("title") if seated else ""
            return (name or "Somebody you have not met", False)

        def entry(record: ProtocolNode, at, actor_uuid, intent, result,
                  asked: bool = False, **extra) -> dict:
            actor_name, is_self = named(actor_uuid)
            signals = str(record.data.get("signals") or "")
            return {
                "uuid": record.uuid,
                "kind": record.data.get("type"),
                # Records written before this application knew to stamp
                # them still have the node's own creation time.
                "at": str(at or record.created_at or ""),
                "actor_uuid": str(actor_uuid or ""),
                "actor_name": actor_name,
                "actor_is_self": is_self,
                "intent": intent,
                "result": result,
                "signals": signals,
                # Only a record that asked for signals can be missing them.
                # Genesis and a role decision were never asked, so marking
                # them would make every trail open with a warning.
                "signals_missing": bool(asked and not signals.strip()),
                "consideration": str(record.data.get("consideration") or ""),
                "expectation": str(record.data.get("expectation") or ""),
                "contested": False,
                "realities": [],
                "can_observe": False,
                "process_uuid": "",
                **extra,
            }

        def trust_label(record: ProtocolNode) -> str:
            return str(record.data.get("trust") or "").title() or "Trusteeship"

        for state in self.governance_records(team, "team_trustee_state"):
            label = trust_label(state)
            cause = str(state.data.get("cause") or "")
            holder, holder_is_self = named(state.data.get("holder_actor_uuid"))
            holds = f"{holder} {'hold' if holder_is_self else 'holds'} {label}"
            intent, result = {
                "genesis": (f"{label} genesis", holds),
                "election": (f"{label} election implemented", holds),
                "resignation": (f"Step out of {label}", f"{label} is vacant"),
                "resolution": (f"{label} resolution", holds),
            }.get(cause, (f"{label} change", holds))
            trail.append(entry(
                state, state.data.get("acted_at"), state.data.get("acted_by"),
                intent, result,
                asked=cause != "genesis",
                process_uuid=str(state.data.get("process_uuid") or ""),
            ))

        settled_elections = {
            str(state.data.get("process_uuid") or "")
            for state in self.governance_records(team, "team_trustee_state")
            if state.data.get("cause") == "election"
        }
        for election in self.trustee_election_records(team):
            label = trust_label(election)
            process_uuid = str(election.data.get("process_uuid") or "")
            # Starting the Flow decides nothing in Team. The election remains
            # under way until a trustee settles the seat in a Team record;
            # S-Flow owns every intermediate and terminal process result.
            standing = (
                "Settled" if process_uuid in settled_elections else "Under way"
            )
            trail.append(entry(
                election, election.data.get("triggered_at"),
                election.data.get("triggered_by"),
                f"{label} election", standing,
                process_uuid=process_uuid,
            ))

        for candidacy in self.governance_records(
            team, "team_trustee_candidacy",
        ):
            label = trust_label(candidacy)
            withdrawn = candidacy.data.get("state") == "withdrawn"
            trail.append(entry(
                candidacy,
                candidacy.data.get("withdrawn_at") if withdrawn
                else candidacy.data.get("submitted_at"),
                candidacy.data.get("actor_uuid"),
                f"Act for {label}",
                "Stood down" if withdrawn else "Standing in",
            ))

        for application in self.membership_applications(team):
            subject, subject_is_self = named(
                application.data.get("actor_uuid"),
            )
            trail.append(entry(
                application,
                application.data.get("applied_at"),
                application.data.get("actor_uuid"),
                "Apply for membership",
                f"{subject} {'applied' if not subject_is_self else 'applied'}",
            ))

        for membership in self.governance_records(team, "team_membership"):
            subject, subject_is_self = named(membership.data.get("actor_uuid"))
            cause = str(membership.data.get("cause") or "")
            is_are = "are" if subject_is_self else "is"
            trail.append(entry(
                membership, membership.data.get("acted_at"),
                membership.data.get("acted_by"),
                {
                    "genesis": "Found the team",
                    "acceptance": "Issue a membership badge",
                    "departure": "Leave the team",
                    "removal": "End a membership",
                }.get(cause, "Membership"),
                f"{subject} {is_are} "
                + ("no longer a Member"
                   if membership.data.get("state") == "former"
                   else "a Member"),
                # Removal is the only membership act that asks for decision
                # context. Issuing a badge answers the application itself.
                asked=cause == "removal",
            ))

        for invitation in self.governance_records(
            team, "team_membership_invitation",
        ):
            closed = invitation.data.get("state") == "closed"
            membership_type = self._node(
                str(invitation.data.get("membership_type_uuid") or ""),
                self.MEMBERSHIP_TYPE_TYPE,
            )
            name = str(
                membership_type.data.get("name"),
            ) if membership_type else "a membership"
            trail.append(entry(
                invitation,
                invitation.data.get("closed_at") if closed
                else invitation.data.get("opened_at"),
                invitation.data.get("opened_by"),
                f"Invite the pool to {name}",
                "Closed" if closed
                else f"Open until {invitation.data.get('expires_at') or ''}",
                asked=True,
            ))

        for action in self.trustee_actions_payload(team):
            actor_name, actor_is_self = named(action.get("acted_by"))
            trail.append({
                **action,
                "kind": "team_trustee_action",
                "at": str(action.get("acted_at") or ""),
                "actor_uuid": action.get("acted_by") or "",
                "actor_name": actor_name,
                "actor_is_self": actor_is_self,
                "intent": (
                    f"{str(action.get('trust') or '').title()} action"
                    f" · {action.get('subject_uuid') or ''}"
                ).strip(" ·"),
                "result": (
                    (action.get("payload") or {}).get("decision")
                    or "Recorded"
                ),
                "process_uuid": "",
            })

        for role in self.roles(team):
            name = str(role.data.get("name") or "Role")
            for child in self._held(role, "answers"):
                # A team cannot answer for itself, so the actor is who
                # answered and the answer is about the team.
                answered_for = str(child.data.get("actor_uuid") or "")
                subject, _ = named(answered_for)
                decision = str(child.data.get("decision") or "answered")
                trail.append(entry(
                    child, child.data.get("decided_at"),
                    child.data.get("decided_by") or answered_for,
                    f"Take {name}",
                    f"{subject} {decision}",
                ))

        trail.sort(key=lambda item: (item["at"], item["uuid"]), reverse=True)
        return trail

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
        return self._held(role, "accountabilities")

    def domains(self, role: ProtocolNode) -> list[ProtocolNode]:
        return self._held(role, "domains")

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
        container = self._container(team, "roles")
        if container is None:
            return SessionResult("error", reason="roles container unavailable")
        result = self.session.create_child(
            container.uuid,
            {
                "type": "team_role",
                "name": normalized,
                "purpose": "",
                "order": self.session.next_child_order(container.uuid),
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
        container = self._container(role, self.ROLE_ITEM_CONTAINERS[node_type])
        if container is None:
            return SessionResult("error", reason=f"{kind} container unavailable")
        result = self.session.create_child(
            container.uuid,
            {
                "type": node_type,
                "text": normalized,
                "order": self.session.next_child_order(container.uuid),
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

    # Holding a role is one record: the actor's own answer. It used to be
    # two - an invitation written by somebody else, and an answer to it -
    # and a holding was live only while both stood, which meant the person
    # who invited you could end what you had taken on. Nobody invites now,
    # so the answer stands alone and only its author can withdraw it.
    #
    # An answer is per (role, actor), not per role: a role may be held by
    # several actors at once, and each of them answers for themselves.

    def decide_role(
        self, role_uuid: str, decision: str, expires_at: str | None = None,
    ) -> SessionResult:
        """Take a role, or turn one down. A member's own act.

        Identity decides membership, not what a member does once they are
        here - so an answer is not a request waiting to be confirmed, it is
        somebody taking on work. That is the whole of it: nobody invites and
        nobody countersigns.

        Being a member is what it turns on. Somebody who is not on this team
        cannot take a role on it, which is the same statement as "membership
        is how you are on a team" read from the other end.
        """
        role = self._node(role_uuid, "team_role")
        if not role:
            return SessionResult("error", reason="role not found")
        team = self._local_team_topic(role.uuid)
        allowed = self._interaction_guard(team)
        if allowed.status != "ok":
            return allowed
        mine = self._identity_uuid
        if not self._is_current_member(team, mine):
            return SessionResult(
                "error",
                reason="only a current Member can take a role on this team",
            )
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
            # A subteam's topic may already be cached and deliberately
            # unmounted because this session held nothing in an ancestor. It
            # does now.
            self.session.mount_cached_topics(TEAM_APPLICATION_ID)
        return recorded

    def seat_team(
        self, role_uuid: str, team_uuid: str,
    ) -> SessionResult:
        """Take a role on behalf of a team whose Identity is held here.

        The counterpart of decide_role for a Team actor, and it needs an
        invitation no more than that one does. A team cannot answer for
        itself, so whoever holds its Identity answers for it, and decided_by
        records who that was.

        What stands in for an invitation is containment: a team every one of
        whose members is already a member here is not a stranger asking to be
        let in. That is checked below, and it is the whole entitlement.
        """
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
        if self._creates_cycle(seated.uuid, parent.uuid):
            return SessionResult(
                "error",
                reason="that would make the organisation circular",
            )
        # A team with nobody on it contains no strangers either, so
        # containment alone would let an empty - or abandoned - team hold a
        # seat in every parent there is.
        members = self.current_member_uuids(seated)
        if not members:
            return SessionResult(
                "error",
                reason="a team with no members cannot take a seat",
            )
        outside = self._members_outside(seated, parent)
        if outside:
            return SessionResult(
                "error",
                reason=(
                    "Everybody on this team has to be a member of "
                    f"{parent.data.get('title') or 'the parent team'} "
                    "before it can take a seat there. Not yet a member: "
                    + ", ".join(sorted(outside))
                ),
            )
        answered = self._record_role_decision(
            parent, role, "accepted", None,
            actor_uuid=seated.uuid, decided_by=self._identity_uuid,
            seated_member_uuids=members,
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
            # Reconsidering a refusal: the answer moved on and the seat it
            # already names is the same seat.
            return SessionResult("ok", value=existing.uuid, effects=answered.effects)
        # Taking a seat that was given up before continues that seat's
        # chain. Starting a second root would leave two claims on one seat,
        # which is what a chain reads as a contest.
        released = self._given_up_seat(seated, parent.uuid, role.uuid)
        seats = self._container(seated, "seats")
        if seats is None:
            return SessionResult("error", reason="seats container unavailable")
        held = self.session.create_child(
            seats.uuid,
            {
                "type": "team_role_holding",
                "parent_team_uuid": parent.uuid,
                "role_uuid": role.uuid,
                "order": (
                    released.data.get("order", 0) if released
                    else self.session.next_child_order(
                        seats.uuid,
                    )
                ),
                "state": "held",
                "previous_holding_uuid": released.uuid if released else "",
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

    def _given_up_seat(
        self, seated: ProtocolNode, parent_uuid: str, role_uuid: str,
    ) -> ProtocolNode | None:
        """The end of a seat's chain when that end says it was given up."""
        head = self._chain_head(
            [
                record for record in self._held(seated, "seats")
                if record.data.get("parent_team_uuid") == parent_uuid
                and record.data.get("role_uuid") == role_uuid
            ],
            "previous_holding_uuid",
        )
        if head is not None and head.data.get("state") == "given_up":
            return head
        return None

    def _members_outside(
        self, seated: ProtocolNode, parent: ProtocolNode,
    ) -> set[str]:
        """Who is on this team without already being on the one above it.

        A Team may hold a seat only while everybody on it is a member of the
        team it sits in. It is inferred rather than assigned: nobody grants
        a team membership, it either contains no strangers or it does not.

        Seating admits nobody. It used to be described the other way round -
        a team in a role brought everybody on it into the parent - and that
        made a subteam a way into a team you had never been admitted to.
        Containment is the precondition now, not the consequence, so the
        people come first and the seat follows.

        Checked when the seat is taken, and the answer recorded with it. Not
        re-derived on every read: a parent replica need not have the subteam
        mounted at all, so a rule evaluated continuously would leave a team
        unable to tell whether its own role was held.

        A team seated *here* is not checked: its own members were contained
        when it took its seat, so containment holds up the chain by
        induction. Only individuals are counted.

        This can only report what it can see. Somebody whose membership is
        recorded on a replica this session does not reach reads as absent,
        so the answer is the cautious one - refuse and name them - rather
        than a guess.
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

    def unseat_team(
        self, role_uuid: str, team_uuid: str,
    ) -> SessionResult:
        """Give up a seat, from the seated team's side.

        Both records go, because a holding is live only while both exist:
        dropping this side alone would leave the parent still showing the
        seat as accepted while the team no longer claims it, and neither view
        is wrong on its own - they simply contradict each other. The two are
        the answer written in the parent and the holding written here, one
        team's record each; neither is anybody's invitation.
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
            # Appended, not deleted. Deleting it left no record that the
            # seat was ever held, which is the one thing a holding is for.
            given_up = self.session.create_child(
                self._container(seated, "seats").uuid,
                {
                    "type": "team_role_holding",
                    "parent_team_uuid": holding.data["parent_team_uuid"],
                    "role_uuid": holding.data["role_uuid"],
                    "order": holding.data.get("order", 0),
                    "state": "given_up",
                    "previous_holding_uuid": holding.uuid,
                },
                {},
            )
            if given_up.status == "ok":
                effects.extend(given_up.effects)
        return SessionResult("ok", effects=effects)

    def _release_seat(
        self, seated: ProtocolNode, holding: ProtocolNode,
    ) -> list:
        """Withdraw the answer written in the parent for one seat.

        The Team actor's resign_role: the only record this side wrote up
        there is the acceptance, so that is all that goes. The role is the
        parent's, and it may seat several actors at once - answering for one
        actor is what empties one seat.

        Appended, not deleted, for the same reason the holding beside it is:
        stepping out is a thing that happened, and deleting the answer left
        no record that the seat was ever taken. It also left the answer
        undeletable in practice - a participation record is append-only, so
        the peer holding a copy could never take the deletion, and the two
        sides sat in a divergence neither was allowed to settle.
        """
        role = self._node(
            str(holding.data.get("role_uuid") or "").strip(), "team_role",
        )
        decision = self._role_decision_for(role, seated.uuid) if role else None
        if not decision or decision.data.get("decision") == "refused":
            return []
        team = self._local_team_topic(role.uuid)
        if team is None:
            return []
        answered = self._record_role_decision(
            team, role, "refused", None,
            actor_uuid=seated.uuid, decided_by=self._identity_uuid,
            seated_member_uuids=[],
        )
        return list(answered.effects) if answered.status == "ok" else []

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

    def seatable_roles_payload(self, team: ProtocolNode) -> list[dict]:
        """Roles in other teams this one could take, and why not where not.

        Offered from the seated team's own page, because that is where the
        actor is: whoever holds *this* team's Identity answers for it, and
        the parent's page has no business drawing a control only somebody
        else can use.

        Bounded by what this client has. Both sides of a seat have to be
        written and containment is judged against the other team's members,
        so a team whose topic nobody has handed over is unreachable rather
        than merely unread - it cannot appear here, and that is the honest
        limit rather than a gap to paper over.
        """
        offers = []
        for other in self.teams():
            if other.uuid == team.uuid:
                continue
            reason = ""
            if self._creates_cycle(team.uuid, other.uuid):
                reason = "it would sit inside itself"
            elif not self.current_member_uuids(team):
                # Containment is vacuously true of an empty team, and an
                # abandoned one would otherwise be seatable anywhere.
                reason = "this team has no members"
            else:
                outside = self._members_outside(team, other)
                if outside:
                    reason = (
                        f"{len(outside)} here "
                        f"{'is' if len(outside) == 1 else 'are'} not on it"
                    )
            for role in self.roles(other):
                offers.append({
                    "role_uuid": role.uuid,
                    "role_name": role.data.get("name") or "Untitled role",
                    "team_uuid": other.uuid,
                    "team_title": other.data.get("title") or "Untitled team",
                    "eligible": not reason,
                    "reason": reason,
                })
        return sorted(
            offers,
            key=lambda entry: (
                not entry["eligible"], entry["team_title"],
                entry["role_name"],
            ),
        )

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
        seated_member_uuids: list[str] | None = None,
    ) -> SessionResult:
        """One chain per actor per role, appended to rather than rewritten.

        An actor who refuses and later accepts has changed their mind, not
        answered twice - so the new answer continues their chain and which
        one counts is the end of it, not iteration order. It used to be the
        same record rewritten, which said the same thing about standing and
        left no trace of when anybody took a role or stepped out of one.

        `decided_by` is set only for a Team actor, which cannot answer for
        itself, and `seated_member_uuids` records what was true of it then.
        """
        actor = actor_uuid or self._identity_uuid
        existing = self._role_decision_for(role, actor)
        data = {
            "type": "team_role_decision",
            "actor_uuid": actor,
            "decision": decision,
            "previous_decision_uuid": existing.uuid if existing else "",
            "decided_at": self._now(),
            "reference_hash": self.role_reference_hash(team, role),
        }
        if expires_at:
            data["expires_at"] = expires_at
        if decided_by:
            data["decided_by"] = decided_by
        if seated_member_uuids is not None:
            data["seated_member_uuids"] = list(seated_member_uuids)
        container = self._container(role, "answers")
        if container is None:
            return SessionResult("error", reason="answers container unavailable")
        return self.session.create_child(container.uuid, data, {})

    def _own_role_decision(self, role: ProtocolNode) -> ProtocolNode | None:
        return self._role_decision_for(role, self._identity_uuid)

    def _role_decision_for(
        self, role: ProtocolNode, actor_uuid: str,
    ) -> ProtocolNode | None:
        """This actor's current answer on this role - the end of their chain."""
        return self._role_chain_head(
            role, "team_role_decision", actor_uuid, "previous_decision_uuid",
        )

    def _role_chain_head(
        self, role: ProtocolNode, node_type: str, actor_uuid: str,
        predecessor_field: str,
    ) -> ProtocolNode | None:
        return self._chain_head(
            [
                child for child in self._held(
                    role, self.ROLE_RECORD_CONTAINERS[node_type],
                )
                if child.data.get("actor_uuid") == actor_uuid
            ],
            predecessor_field,
        )

    @staticmethod
    def _chain_head(
        records: list[ProtocolNode], predecessor_field: str,
    ) -> ProtocolNode | None:
        """The end of one append-only chain, or nothing when it forks.

        The same walk the governance projections do, without the reporting:
        a single root advances through single successors, and more than one
        of either is a contest. A contest holds nothing, which is what a
        divergence should mean here - two answers about one seat are two
        people to talk to, not a race to settle by sort order.
        """
        by_previous: dict[str, list[ProtocolNode]] = {}
        for record in records:
            by_previous.setdefault(
                str(record.data.get(predecessor_field) or ""), [],
            ).append(record)
        roots = by_previous.get("", [])
        if len(roots) != 1:
            return None
        current = roots[0]
        seen = {current.uuid}
        while True:
            successors = [
                record for record in by_previous.get(current.uuid, [])
                if record.uuid not in seen
            ]
            if not successors:
                return current
            if len(successors) > 1:
                return None
            current = successors[0]
            seen.add(current.uuid)

    def role_holders(
        self, team: ProtocolNode, role: ProtocolNode,
    ) -> list[dict]:
        """Everyone whose answer says they hold this role, and how it stands.

        An answer is credible only from the actor's own replica, so this
        lists exactly the answers this session can vouch for. There is
        nothing else to list: nobody is invited to a role, so an actor this
        session cannot reach is not a holder waiting to be seen - there is
        simply no record of them here.
        """
        return self._cached(
            ("holders", team.uuid, role.uuid),
            lambda: self._build_role_holders(team, role),
        )

    def _answer_status(self, record: dict | None, current: str) -> str:
        """What an actor's own answer says about the holding.

        Read the same way whether or not anybody invited them, because a
        member's answer is what holds a role either way. It used to be read
        only for invited actors; an uninvited one was "requested" no matter
        what they had said, which is how an expired or superseded answer
        went on looking like somebody waiting to be let in.
        """
        if not record:
            return "pending"
        if record.get("decision") == "refused":
            return "refused"
        if self._is_expired(record.get("expires_at")):
            return "expired"
        if record.get("reference_hash") != current:
            return "outdated"
        return "accepted"

    def _build_role_holders(
        self, team: ProtocolNode, role: ProtocolNode,
    ) -> list[dict]:
        people = {
            member["uuid"]: member
            for member in self._topic_members(team.uuid)
        }
        current = self.role_reference_hash(team, role)
        decisions = self._observed_decisions(team, role)
        admitted = self.actors_admitted_above(team)
        # Standing is read from the team as it is now, not from the node the
        # caller happens to be holding. A snapshot taken before somebody
        # took a membership up carries none of their records, and reading
        # membership off it would drop them from every role they hold.
        standing_team = self._node(team.uuid, "team") or team
        holders = []
        for actor_uuid, record in decisions.items():
            member = people.get(actor_uuid)
            # Somebody this session knows but who is not on this topic is a
            # different case from somebody it cannot place at all.
            known = None if member else self._known_people().get(actor_uuid)
            # A Team actor is never among the people on this topic, so the
            # member test would call every one of them a stranger. It is told
            # apart by having been answered *for*: only a body that cannot
            # answer for itself has somebody who did.
            seated = self._node(actor_uuid, "team")
            is_team = bool(seated) or bool(record.get("decided_by"))
            # A role is work a *member* holds, so an answer given by somebody
            # who is no longer on the team holds nothing. The record stays -
            # nothing is written into it, and taking a membership up again
            # brings the holding back without anybody re-answering - but it
            # stops being a holding while the membership is not there.
            #
            # Individuals only. A seated Team has no membership of its own to
            # read: its standing is containment, checked when it took the
            # seat, so asking this of one would unseat every subteam.
            if not is_team and not self._is_current_member(
                standing_team, actor_uuid,
            ):
                continue
            # A Team that stepped out of its seat is not a holder of it. Its
            # refusal is somebody else's act on its behalf - a body is seated
            # and unseated, it does not answer for itself - so there is no
            # "they said no" worth showing, unlike a person's own refusal,
            # which stays struck through beside the others.
            if is_team and self._answer_status(record, current) == "refused":
                continue
            holders.append({
                "actor_uuid": actor_uuid,
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
                # Whether the team holding this seat is one this session has
                # joined. Only ever asked of a team.
                "joined": bool(seated) if is_team else None,
                # Individual or Team. The view draws them differently,
                # because "a person holds this" and "a body holds this" are
                # not the same fact.
                "actor_kind": "team" if is_team else "individual",
                "picture": (member or {}).get("picture") or "",
                "is_self": actor_uuid == self._identity_uuid,
                "status": self._answer_status(record, current),
                "decided_at": record.get("decided_at"),
                "expires_at": record.get("expires_at"),
            })
        return sorted(holders, key=lambda item: (item["status"], item["name"]))

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
            for child in self._held(peer_role, "answers"):
                if child.data.get("actor_uuid") == member["uuid"]:
                    found[member["uuid"]] = dict(child.data)
            found.update(self._answers_given_by(peer_role, member["uuid"]))
        return found

    def _answers_given_by(self, role: ProtocolNode, actor_uuid: str) -> dict[str, dict]:
        """Answers this actor recorded on some team's behalf.

        `decided_by` is set only where an actor could not answer for itself,
        so its presence is what marks an answer as given rather than owned.
        """
        return {
            str(child.data.get("actor_uuid") or ""): dict(child.data)
            for child in self._held(role, "answers")
            if child.data.get("decided_by") == actor_uuid
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
        return self.accept_team_invitation(subtree)

    def accept_team_invitation(self, subtree: ProtocolNode) -> SessionResult:
        """Take the topic. Nothing here decides whether you are on the team.

        Getting the channel and being a member are two different things now,
        and this is the first: it makes you somebody who can read the
        Agreement and therefore somebody who could accept it. Whoever hands
        the topic out decides who may ever ask; the invitation on a
        membership type decides what they may ask for.
        """
        if subtree.data.get("type") != "team":
            return SessionResult("error", reason="invited topic is not a team")
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
        "team", AGREEMENT_TYPE, "team_section", "team_clause",
        "team_role", "team_accountability", "team_domain",
        "team_role_holding", "team_role_decision",
        # A membership type is content people read before answering, so it
        # is reactable the way a role is: disagreeing with what a membership
        # asks of somebody is a thing to say about the team.
        MEMBERSHIP_TYPE_TYPE,
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
        if reference and reference.data.get("type") in self.ROLE_RECORD_TYPES:
            if local_exists:
                return SessionResult(
                    "error",
                    reason=(
                        "participation records are append-only and cannot "
                        "be changed"
                    ),
                )
            if not peer_node:
                return SessionResult(
                    "error", reason="participation record is unavailable",
                )
            schema_error = self.role_record_schema_error(peer_node)
            if schema_error:
                return SessionResult("error", reason=schema_error)
        if reference and reference.data.get("type") in self.CONTENT_TYPES:
            # No append-only check here: content is edited, so a peer's node
            # replacing a local one is the ordinary case rather than a
            # rewrite of somebody's record.
            checked = peer_node or reference
            schema_error = self.content_schema_error(checked)
            if schema_error:
                return SessionResult("error", reason=schema_error)
        allowed = self._interaction_guard_for_reaction(
            source_addr, node_uuid,
        )
        if allowed.status != "ok":
            return allowed
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
        self.publish_adoption_metadata(team)
        changed = self.session.reconcile_peer_changes(
            source_addr, team_uuid, deciding=True,
        )
        return SessionResult("ok", value=changed)

    def reconcile_governance_updates(self) -> SessionResult:
        """Auto-adopt verified governance facts and peer-authored role answers."""
        changed = False
        # What this client holds changes without S-Team being told - a
        # connected item arrives on a later sync, and one deleted from the
        # Cockpit leaves without a word. Recomputing here is what keeps the
        # published list from saying something that stopped being true.
        for team in self.teams():
            said = self.publish_my_items(team)
            changed = bool(said.value) or changed
            changed = self._reconcile_identity_membership_definitions(
                team,
            ) or changed
        for team in self.teams():
            self.publish_adoption_metadata(team)
            for address in self.session.peer_addresses(team.uuid):
                adopted = self.session.reconcile_peer_changes(
                    address, team.uuid,
                )
                changed = adopted or changed
        return SessionResult("ok", value=changed)

    def publish_adoption_metadata(self, team: ProtocolNode) -> None:
        """Declare how this team's nodes are handled, for Core to enforce.

        What is declarable today is that a governance record is its author's:
        it is created by one actor and is never anyone else's to rewrite, so
        every held record names `same-origin` and Core refuses a revision from
        any other origin. The agreement content itself - sections, clauses,
        roles - stays adoptable, because that is what members negotiate.

        What is not declarable is S-Team's authority assessment. Whether an
        incoming record was authored by the actor entitled to author it is
        computed from membership and role state, not read from a field, so
        `assess_governance_record` remains the gate for a record this client
        does not yet hold. See Core's DESIGN_ADOPTION_METADATA.md.
        """
        # Containers first. They are structure rather than content, and a
        # peer's node cannot be adopted before the container it hangs in is
        # here - additions are shallow and parents-first. Every client derives
        # the same uuid for each, so materialising them locally is not a
        # decision anybody has to take.
        self._ensure_containers(team)
        # Held back by default: agreement content is what members negotiate,
        # so it waits for a decision rather than arriving on its own. The
        # manual pass reconciles with `deciding`, which passes through `hold` -
        # that decision being exactly what `hold` waits for.
        self.session.set_topic_adoption_default(
            team.uuid, adopt="hold", additions="hold",
        )
        self.session.set_adoption_classifier(
            team.uuid,
            lambda node, default, uuid=team.uuid: (
                self._classify_incoming_node(node)
            ),
        )
        self.session.set_adoption_resolver(
            team.uuid,
            lambda peer_node, local_node, peer_addr, uuid=team.uuid: (
                self._resolve_held_node(uuid, peer_node, peer_addr)
            ),
        )
        # A record already held is nobody's to rewrite, including its author's.
        # One statement per container rather than one per record type: the
        # container's uuid says which nodes are meant, so Core is handed a
        # place instead of a list of names. Agendas need no statement at all -
        # Core declares its own container.
        record_containers = [
            *dict.fromkeys(self.RECORD_CONTAINERS.values()),
            "seats",
        ]
        for role in self.roles(team):
            for name in ("answers", "holdings"):
                self._declare_record_container(role, name)
        for name in record_containers:
            self._declare_record_container(team, name)

    def _declare_record_container(
        self, parent: ProtocolNode, name: str,
    ) -> None:
        """Records inside are frozen and their author's; the place is neither.

        `author` is written on the records and never on the container. A
        container is authored by whoever created the team, so `same-origin`
        there would read as "only they may add records here" - which is the
        opposite of what an append-only container is for.

        `additions` stays `hold`, which is what sends an arriving record to
        the resolver and so through `assess_governance_record`. `auto` would
        take it on the strength of its position alone, and whether its author
        was entitled to write it is exactly the question a position cannot
        answer.
        """
        container = self._container(parent, name, create=False)
        if container is None:
            return
        self.session.set_adoption_metadata_for_subtree(
            container.uuid, adopt="never", author="same-origin",
        )
        self.session.set_adoption_metadata(
            container.uuid, adopt="never", additions="hold",
        )

    @staticmethod
    def _classify_incoming_node(node: ProtocolNode) -> dict | None:
        """What a node this team does not yet hold *is*.

        Only facts that do not move belong here, because the answer is stored:
        an agenda item is Session's, projected from its author's perspective
        and never adopted. Whether a record is *authorized* is not such a fact
        - it is computed from membership and role state, both of which change -
        so it is answered by the resolver at the moment of decision instead.
        """
        if node.data.get("type") == "agenda_item":
            return {"adopt": "never", "additions": "never"}
        return None

    def _resolve_held_node(
        self, team_uuid: str, node: ProtocolNode, peer_addr: str,
    ) -> str:
        """Whether a held record settles now, is refused, or waits for a member.

        Authority is assessed here rather than stored, because it is derived
        from membership and role state: a verdict recorded when the record
        first arrived would go on being true after it stopped being true.

        A record that fails assessment is refused outright - no member's
        decision makes an unauthorized record authorized. Everything else is
        deferred: agreement content is what members negotiate, so it waits for
        somebody to adopt it.
        """
        team = self._node(team_uuid, "team")
        if team is None:
            return "defer"
        node_type = node.data.get("type")
        if node_type == "team_role_decision":
            authorized = self._role_answer_authorized(team, node, peer_addr)
        elif node_type in self.GOVERNANCE_RECORD_TYPES:
            assessment = self.assess_governance_record(team, node)
            authorized = assessment["status"] == "authorized"
            self.session.trace_event(
                "team.governance_assessment",
                peer_addr=peer_addr,
                team_uuid=team.uuid,
                node_uuid=node.uuid,
                record_type=node_type,
                status=assessment["status"],
                reason=assessment["reason"],
            )
        else:
            return "defer"
        return "adopt" if authorized else "refuse"

    def _author_actor_uuid(self, team: ProtocolNode, node: ProtocolNode) -> str:
        """The actor whose key signed this revision.

        Attribution follows the signature, not the delivery path. A revision
        carries the identity key that authored it and forwarding preserves it,
        so a record relayed through a third party is still attributed to the
        actor who wrote it - where matching on the sending address would
        disown it.
        """
        origin = str(node.revision_origin or "")
        if not origin:
            return ""
        for person in self._topic_members(team.uuid):
            if person.get("identity_key") == origin:
                return str(person.get("uuid") or "")
        return ""

    def _role_answer_authorized(
        self, team: ProtocolNode, node: ProtocolNode, peer_addr: str,
    ) -> bool:
        schema_error = self.role_record_schema_error(node)
        author_actor_uuid = self._author_actor_uuid(team, node)
        answered_by = str(
            node.data.get("decided_by") or node.data.get("actor_uuid") or ""
        )
        authorized = bool(
            not schema_error and author_actor_uuid
            and answered_by == author_actor_uuid
        )
        self.session.trace_event(
            "team.role_answer_assessment",
            peer_addr=peer_addr,
            team_uuid=team.uuid,
            node_uuid=node.uuid,
            revision_origin=str(node.revision_origin or ""),
            status="authorized" if authorized else "disregarded",
            reason=(
                schema_error
                or (
                    "the signing key is not a recognized team actor"
                    if not author_actor_uuid
                    else "the answer was not authored by the actor it names"
                )
            ),
        )
        return authorized

    def _peer_actor_uuid(
        self, team: ProtocolNode, peer_addr: str,
    ) -> str:
        for person in self._topic_members(team.uuid):
            if peer_addr in (
                person.get("addresses") or [person.get("address")]
            ):
                return str(person.get("uuid") or "")
        return ""

    def _identity_membership_definition_aligned(
        self, team: ProtocolNode, node_uuid: str,
    ) -> bool:
        observed = []
        for holder_uuid in self.identity_holder_uuids(team):
            perspectives = self._actor_agreement_perspectives(
                team, holder_uuid,
            )
            if not perspectives:
                return False
            for _source, root in perspectives:
                node = self._find_in_subtree(root, node_uuid)
                observed.append(
                    "absent" if node is None
                    else f"{node.deleted}:{node.content_hash}"
                )
        return bool(observed) and len(set(observed)) == 1

    def _reconcile_identity_membership_definitions(
        self, team: ProtocolNode,
    ) -> bool:
        """Align membership definitions only to recognized Identity copies."""
        changed = False
        holders = set(self.identity_holder_uuids(team))
        for address in self.session.peer_addresses(team.uuid):
            actor_uuid = self._peer_actor_uuid(team, address)
            for event in self.session.analyze_peer_transitions(
                address, team.uuid,
            ):
                if event.get("type") == "in_agreement":
                    continue
                node_uuid = str(event.get("node_uuid") or "")
                peer = self.session.get_cached_peer_subtree(
                    address, node_uuid,
                )
                local = self.session.protocol.index.get(node_uuid)
                observed = peer or local
                if not observed or observed.data.get(
                    "type",
                ) != self.MEMBERSHIP_TYPE_TYPE:
                    continue
                if not actor_uuid or actor_uuid not in holders:
                    self.session.trace_event(
                        "team.membership_definition_disregarded",
                        team_uuid=team.uuid,
                        peer_addr=address,
                        actor_uuid=actor_uuid,
                        node_uuid=node_uuid,
                        event_type=event.get("type"),
                        reason="the peer is not a recognized Identity holder",
                    )
                    continue
                if not self._identity_membership_definition_aligned(
                    team, node_uuid,
                ):
                    self.session.trace_event(
                        "team.membership_definition_disputed",
                        team_uuid=team.uuid,
                        node_uuid=node_uuid,
                        reason="Identity holders expose different definitions",
                    )
                    continue
                if event.get("type") == "peer_missing_node":
                    result = self.session.delete(node_uuid)
                else:
                    result = self.session.accept_peer_node(address, node_uuid)
                self.session.trace_event(
                    "team.membership_definition_aligned",
                    team_uuid=team.uuid,
                    peer_addr=address,
                    actor_uuid=actor_uuid,
                    node_uuid=node_uuid,
                    event_type=event.get("type"),
                    ok=result.status == "ok",
                    reason=result.reason,
                )
                changed = changed or result.status == "ok"
        return changed

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
                # Agenda records are already represented by the perspective
                # projection. They are not proposals merely because this
                # client has deliberately not adopted a duplicate copy.
                if observed and observed.data.get("type") == "agenda_item":
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
        "team_role_decision": "Role answer",
        "team_role_holding": "Seat",
        "agenda_item": "Discussion topic",
        "team_trustee_state": "Trusteeship state",
        "team_membership": "Membership",
        "team_membership_application": "Membership application",
        "team_membership_type": "Membership type",
        "team_membership_invitation": "Membership invitation",
        "team_trustee_election": "Trustee election",
        "team_trustee_candidacy": "Trustee candidacy",
        "team_trustee_action": "Trustee action",
        "team_trustee_reality": "Reality observation",
    }
    # Text-bearing fields, by the name they are read under. "Title" alone
    # would be ambiguous on a team node, which now carries two.
    TEXT_FIELDS = {
        "title": "Title",
        "agreement_title": "Agreement title",
        "agreement_version": "Agreement version",
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

        They carry no text at all, so without this every answer and
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
    ) -> dict:
        with self._reading():
            return self._build_document_payload(team_uuid, network)

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
            # A peer's version of something this client already holds. A new
            # node shows on the document as a proposal; a *changed* one used
            # to show only in the divergence list, so a renamed agreement was
            # invisible at the place its name is read.
            "proposed_changes": self._proposed_changes(events),
            "network": network,
            # Agendas are Session's, so this application only forwards the
            # merged list for the topic in view.
            "agenda_items": [
                node.to_dict() for node in
                (self._agenda_items(selected.uuid) if selected else [])
            ],
            "identity_uuid": self._identity_uuid,
            "known_identities": self.session.known_identities(),
            "organization": self.organization_payload(),
            # Local to this client and to nobody else, which is why they are
            # listed beside the organization rather than inside a team.
            "archives": self.archives(),
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
                else {
                    "types": [], "pool": [], "can_resolve": False,
                    "is_member": False, "status": "pool",
                    "membership_type_uuid": "",
                }
            ),
            # Trustee actions are rows in the trail like every other record,
            # so they are not sent twice. The facade still answers for them
            # on their own, because another application asking about them is
            # asking a different question.
            "decision_trail": (
                self.decision_trail_payload(selected) if selected else []
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
            # What the team runs. Derived from the channel on every read,
            # because that is where the answer lives - see team_items.
            "items": self.team_items(selected) if selected else [],
            "offerable_items": (
                self.offerable_items(selected) if selected else []
            ),
            "item_kinds": self.item_kinds() if selected else [],
            # Where this team is drawn, and every other seat it
            # holds - never hidden, or deleting the first parent would
            # take away something load-bearing nobody could see.
            "parents": self.parent_payload(selected) if selected else [],
            "seatable_roles": (
                self.seatable_roles_payload(selected) if selected else []
            ),
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
        "team_role_decision",
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

    def document_snapshot(self, team_uuid: str | None = None) -> dict:
        """Build team state under Session without consulting transport."""
        payload = self.document_payload(team_uuid, {})
        decorated = []
        for event in payload.get("transition_events", []):
            node_uuid = event.get("node_uuid")
            view = self.transition_by_node([event]).get(node_uuid)
            if view:
                decorated.append((event, view))
        topic = payload.get("team") or {}
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

    def _proposed_changes(self, events: list[dict]) -> dict[str, dict]:
        """What a peer says a node this client holds should say instead.

        Only where the peer has moved and this client has not answered yet -
        a difference this client authored is its own, not a proposal to it.
        """
        proposed: dict[str, dict] = {}
        for event in events:
            if event.get("type") not in ("peer_made_changes", "divergence"):
                continue
            node_uuid = event.get("node_uuid")
            source_addr = event.get("peer_addr")
            if not node_uuid or not source_addr or node_uuid in proposed:
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
            proposed[node_uuid] = {
                "source_addr": source_addr,
                "node": peer_node.to_dict(),
            }
        return proposed

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
                item.to_dict() for item in self._agenda_items(topic_uuid)
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
                # Both sides have to name the same seat. An answer given
                # for a team that never wrote its own holding is not a
                # subteam.
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
        # Membership is a fact about the person, not a badge among their
        # roles. It used to be pushed into the roles list as the system
        # Member role, which made "on this team" and "doing this work"
        # the same kind of thing and read as a role nobody could refuse.
        known = self._known_people()
        for actor_uuid in self.current_member_uuids(team):
            if actor_uuid in people:
                continue
            identity = known.get(actor_uuid) or {}
            people[actor_uuid] = {
                "uuid": actor_uuid,
                "name": (
                    identity.get("name") or identity.get("address")
                    or "Member"
                ),
                "picture": identity.get("picture") or "",
                "actor_kind": "individual",
                "address": identity.get("address") or "",
                "addresses": identity.get("addresses") or [],
                "is_self": actor_uuid == self._identity_uuid,
                "roles": [],
            }
        # A Team that could take a seat here gets no row. It used to get
        # one - every team containing no strangers was listed among the
        # actors, drawn with an outline chip per role it might take - and
        # the row stated nothing: a seat nobody has taken is not a fact
        # about anybody, and the only person who could have acted on it was
        # whoever holds that team's Identity, who was usually looking at a
        # different page. A team takes a seat from its own line on its own
        # page, the way every other actor acts from theirs. A Team appears
        # here once it *holds* something, which role_holders already does.
        for person in people.values():
            standing = (
                "accepted" if person["actor_kind"] == "team"
                else self.member_standing(team, person["uuid"])
            )
            if person["actor_kind"] == "team":
                # Only whoever holds that team's Identity answers for it, so
                # only they see its badges as controls.
                subteam = self._node(person["uuid"], "team")
                person["speaks_for"] = bool(
                    subteam is not None and self.holds_identity(subteam),
                )
            person["membership"] = standing
            person["is_member"] = standing in {"accepted", "contested"}
            # The badge on the right of the row. Only an Individual carries
            # one: a Team is not a member of anything, it holds a seat, and
            # a badge saying it had accepted the Agreement would be somebody
            # else's answer written under its name.
            person["membership_status"] = (
                "" if person["actor_kind"] == "team"
                else self.membership_status(team, person["uuid"])
            )
            person["membership_type"] = ""
            person["membership_badge"] = None
            if person["membership_status"] in {"accepted", "outdated"}:
                membership_projection = self.membership_projection(
                    team, person["uuid"],
                )
                held = self._node(
                    membership_projection.get("membership_type_uuid") or "",
                    self.MEMBERSHIP_TYPE_TYPE,
                )
                person["membership_type"] = str(
                    held.data.get("name") or "",
                ) if held else ""
                badge = self._governance_node(
                    team,
                    membership_projection.get("current_uuid") or "",
                    "team_membership",
                )
                if badge is None:
                    self.session.trace_event(
                        "team.membership_badge_unexpected",
                        team_uuid=team.uuid,
                        actor_uuid=person["uuid"],
                        reason="standing membership badge is unavailable",
                    )
                else:
                    person["membership_badge"] = {
                        "uuid": badge.uuid,
                        "membership_info": badge.data.get(
                            "membership_info", "",
                        ),
                        "acceptance_requirement": badge.data.get(
                            "acceptance_requirement", "",
                        ),
                        "acceptance_text": badge.data.get(
                            "acceptance_text", "",
                        ),
                        "agreement_accepted": badge.data.get(
                            "agreement_accepted", False,
                        ),
                        "agreement_version": badge.data.get(
                            "agreement_version", "",
                        ),
                        "reference_hash": badge.data.get(
                            "reference_hash", "",
                        ),
                        "issued_by": badge.data.get("acted_by", ""),
                        "issued_at": badge.data.get("acted_at", ""),
                    }
            # An observer is here without being on the team. A member who
            # has taken no work is not an observer - they are a member with
            # nothing to do yet.
            person["is_observer"] = not (
                person["is_member"]
                or any(
                    item["status"] == "accepted" for item in person["roles"]
                )
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
        """Every actor on this team.

        Membership is the whole of it for an individual: being here is
        being a member, and what roles they have taken since is their own
        business. This used to add up role-holders instead, which made
        somebody who had taken no work look like somebody who was not here.

        A seated Team is not a member - it is an actor holding a role - so
        those are still counted from the roles. So are the trustees, since
        a trusteeship can be held from a team above.

        Somebody who has dropped out of a team above this one does not
        count. Their answer here stands and is untouched, but being on a
        team below is being on the team above, so counting it would let the
        containment be satisfied one level down by somebody the level above
        had already lost.
        """
        actors = set(self.current_member_uuids(team))
        if holder := self.identity_holder(team):
            actors.add(holder)
        if holder := self.trust_holder(team):
            actors.add(holder)
        actors.discard("")
        for role in self.roles(team):
            actors.update(
                holder["actor_uuid"]
                for holder in self.role_holders(team, role)
                if holder["actor_kind"] == "team"
                and holder["status"] == "accepted"
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
        """The hash of the Agreement the Identity holders agree on.

        Role nodes are deliberately absent. An acceptance covers the document
        body plus the definition of the role being accepted - see
        role_reference_hash - so that editing one role does not re-open
        everybody else's acceptance.

        Editing the body still re-opens everyone's, at every level below,
        and that is not a defect to be worked around: if the document people
        agreed to has changed, their agreement to it is genuinely stale and
        being asked again is the honest answer. A grace period was
        considered and rejected, because it would make whether somebody
        holds a role depend on the clock and on local settings, and two
        replicas would disagree.
        """
        projection = self.agreement_projection(team)
        if projection.get("state") not in {"agreed", "absent"}:
            return ""
        return str(projection.get("reference_hash") or "")

    def _content_hash(self, root: ProtocolNode, included_types: set[str]) -> str:
        def children_of(node: ProtocolNode) -> list[dict]:
            found = []
            for child in node.children:
                if child.deleted:
                    continue
                if child.data.get("type") == self.CONTAINER_TYPE:
                    # A container is a place, not a clause. What it holds is
                    # hashed; the container itself is not, so adding one
                    # never re-opens an acceptance of unchanged text.
                    found.extend(children_of(child))
                    continue
                item = content(child)
                if item is not None:
                    found.append(item)
            return found

        def content(node: ProtocolNode) -> dict | None:
            if node.deleted or node.data.get("type") not in included_types:
                return None
            children = children_of(node)
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
        """Whether this participant is on this team.

        Membership, now that membership is a thing of its own. It used to
        walk the roles looking for one this session had accepted, because
        holding a role was the only way to be on a team; a member who had
        taken no work therefore read as not being here at all.

        Membership alone, and not "or holds a trusteeship": a trustee is
        elected out of the members, so the shortcut only ever fired for
        somebody whose membership had ended while they still held a seat.
        That is a state worth seeing rather than papering over - the trail
        records it, and the remedy is to fill the trusteeship.

        Deliberately local-only: it runs inside the ancestor walk of every
        guard, and what matters there is this session's own standing.
        """
        return self._is_current_member(team, self._identity_uuid)

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
            # Carried so a record can be attributed to whoever signed it
            # rather than to whoever relayed it - see _author_actor_uuid.
            "identity_key": self_identity.get("identity_key") or "",
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
                "identity_key": identity.get("identity_key") or "",
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

        # Seats held by teams this session has not joined: their topics
        # are somebody else's to invite, so only the seat shows.
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
        return self.session.create_agenda_item(team.uuid, text, priority)

    def _agenda_items(self, topic_uuid: str):
        return self.session.agenda_projection(topic_uuid)

    def delete_agenda_item(self, item_uuid: str) -> SessionResult:
        if not self.owns_node(item_uuid):
            return SessionResult("error", reason="agenda item not found")
        allowed = self._interaction_guard_for_node(item_uuid)
        if allowed.status != "ok":
            return allowed
        return self.session.delete_agenda_item(item_uuid)

    def update_agenda_item(self, item_uuid: str, text: str) -> SessionResult:
        if not self.owns_node(item_uuid):
            return SessionResult("error", reason="agenda item not found")
        allowed = self._interaction_guard_for_node(item_uuid)
        if allowed.status != "ok":
            return allowed
        return self.session.update_agenda_item_text(item_uuid, text)

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
