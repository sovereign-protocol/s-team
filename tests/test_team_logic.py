import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from s_team.application import APPLICATION_MANIFEST
from s_team.logic import TeamLogic
from sovereign import (
    ApplicationRegistration, ProtocolNode, Session, SessionResult,
)
from sovereign import app_server
from sovereign.relay_logic import RelayLogic

try:
    from s_flow.facade import FlowFacade
    from s_flow.logic import FlowLogic
except ModuleNotFoundError:  # Optional cross-application test dependency.
    FlowFacade = None
    FlowLogic = None


def connect(host, guest, topic_uuid: str) -> dict:
    """Wire two runtimes the way the app does: the host decides to use its
    relay for the team, composes an invitation, the guest accepts it."""
    host.session.start_discussion(topic_uuid)
    attached = host.mailbox_channel.attach_topics(
        [topic_uuid], {"target_id": host.relay_target},
    )
    if not attached.ok:
        return {"status": "error", "reason": attached.reason}
    identity_uuid = host.session.identity.uuid
    token = host.channel_manager.compose_token([topic_uuid], {
        topic_uuid: {
            "kind": "mailbox", "target_id": host.relay_target,
        },
        identity_uuid: {
            "kind": "mailbox", "target_id": host.relay_target,
        },
    })
    if not token.ok:
        return {"status": "error", "reason": token.reason}
    result = guest.channel_manager.accept_token(token.value)
    if not result.ok:
        return {"status": "error", "reason": result.reason}
    sync(host, guest)
    return result.value


def sync(*runtimes) -> None:
    """Move work between clients the only way a relay can: each publishes
    what changed, then each reads what the others left. Twice, because a
    client given a topic in the first round has nothing of its own to
    publish until it has grafted it."""
    for _ in range(2):
        for runtime in runtimes:
            runtime.relay.write_presence()
            runtime.relay.publish_due_topics()
        for runtime in runtimes:
            def after_apply(runtime=runtime):
                for _ in range(4):
                    if not runtime.host.notify_peer_update().changed:
                        break

            runtime.relay.poll_and_apply(after_apply)


class TeamLogicTests(unittest.TestCase):
    def test_saved_snapshot_restores_agreement_without_people_or_history(self):
        session = Session("local")
        logic = TeamLogic(session)
        team_uuid = logic.create_team("Cooperative").value
        section_uuid = logic.create_section(team_uuid, "Purpose").value
        logic.create_clause(section_uuid, "Serve members")
        logic.create_role(team_uuid, "Coordinator")

        saved = logic.export_snapshot(
            team_uuid, "Cooperative baseline", "Reusable agreement",
        )
        logic.delete_team(team_uuid)
        snapshot_file = json.loads(json.dumps(saved.value))
        restored = logic.create_from_snapshot(snapshot_file, "New cooperative")

        self.assertEqual(saved.status, "ok", saved.reason)
        self.assertEqual(saved.value["format"], "s-protocol.item-snapshot")
        self.assertEqual(saved.value["description"], "Reusable agreement")
        copy = session.protocol.index[restored.value]
        sections = logic.sections(copy)
        self.assertEqual([item.data["title"] for item in sections], ["Purpose"])
        self.assertEqual(
            [item.data["text"] for item in logic.clauses(sections[0])],
            ["Serve members"],
        )
        self.assertEqual([item.data["name"] for item in logic.roles(copy)], ["Coordinator"])
        self.assertEqual(logic.actor_uuids(copy), set())
        self.assertEqual(
            [item.data["type"] for item in logic._team_container().live_children()],
            ["team"],
        )

    @staticmethod
    def flow_result(process_uuid="flow-1", **overrides):
        result = {
            "contract_id": "s-flow.decision-result",
            "contract_version": 1,
            "process_uuid": process_uuid,
            "definition_id": "integrative-election",
            "definition_version": "0.2.0",
            "lifecycle": "completed",
            "current_stage": "",
            "last_completed_stage": "Objection round",
            "terminal_outcome": "elected",
            "selected_candidate_uuid": "candidate-1",
            "participant_snapshot": [{
                "identity_uuid": "member-1",
                "role": "requiredParticipant",
                "required": True,
            }],
            "facilitator_uuid": "facilitator-1",
        }
        result.update(overrides)
        encoded = json.dumps(
            result,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        result["result_hash"] = f"sha256:{hashlib.sha256(encoded).hexdigest()}"
        return result

    @staticmethod
    def election_facades():
        class ElectionFlow:
            def __init__(self):
                self.result = None
                self.calls = []
                self.deleted = []

            def create_integrative_election(
                self, title, participants, facilitator, candidates, version,
            ):
                process_uuid = f"election-process-{len(self.calls) + 1}"
                self.calls.append({
                    "title": title,
                    "participants": list(participants),
                    "facilitator": facilitator,
                    "candidates": list(candidates),
                    "version": version,
                    "process_uuid": process_uuid,
                })
                self.result = TeamLogicTests.flow_result(
                    process_uuid,
                    lifecycle="active",
                    terminal_outcome=None,
                    selected_candidate_uuid=None,
                    participant_snapshot=[
                        {
                            "identity_uuid": actor_uuid,
                            "role": "requiredParticipant",
                            "required": True,
                        }
                        for actor_uuid in sorted(set(participants))
                    ],
                    facilitator_uuid=facilitator,
                )
                return SessionResult("ok", value=process_uuid)

            def decision_result(self, _process_uuid):
                return self.result

            def delete_process(self, process_uuid):
                self.deleted.append(process_uuid)
                return SessionResult("ok", value=process_uuid)

        class Facades:
            def __init__(self, flow):
                self.flow = flow

            def find(self, application_id, facade_api_version):
                if (application_id, facade_api_version) == ("flow", 1):
                    return self.flow
                return None

        flow = ElectionFlow()
        return flow, Facades(flow)

    def test_member_starts_election_and_only_counterpart_trustee_settles(self):
        identity = self.runtime(9635)
        member = self.runtime(9636)
        team_uuid = identity.logic.create_team("Elective Team").value
        connect(identity, member, team_uuid)
        self.admit(identity, member, team_uuid)

        flow, facades = self.election_facades()
        identity.logic.facades = facades
        member.logic.facades = facades
        identity_uuid = identity.session.identity.uuid
        member_uuid = member.session.identity.uuid
        original = identity.logic.trustee_projection(
            identity.session.protocol.index[team_uuid], "identity",
        )

        started = identity.logic.start_trustee_election(
            team_uuid, "identity",
        )

        self.assertEqual(started.status, "ok")
        call = flow.calls[0]
        self.assertEqual(
            call["participants"], sorted([identity_uuid, member_uuid]),
        )
        self.assertEqual(call["facilitator"], identity_uuid)
        self.assertEqual(call["candidates"], call["participants"])
        election = started.value
        self.assertTrue(original["current_state_uuid"])
        sync(identity, member)

        # The process running to an end changes no authority by itself.
        # Nothing here reads its result: it is a flow, read in S-Flow by
        # the person who then answers for the seat.
        self.assertEqual(
            identity.logic.identity_holder(
                identity.session.protocol.index[team_uuid],
            ),
            identity_uuid,
        )
        unauthorized = member.logic.settle_trusteeship(
            team_uuid, "identity", member_uuid,
            election.data["process_uuid"],
        )
        self.assertEqual(unauthorized.status, "error")
        self.assertIn("Trust", unauthorized.reason)

        settled = identity.logic.settle_trusteeship(
            team_uuid, "identity", member_uuid,
            election.data["process_uuid"],
            signals="The election chose them",
        )
        self.assertEqual(settled.status, "ok")
        self.assertEqual(settled.value.data["cause"], "election")
        self.assertEqual(
            settled.value.data["process_uuid"],
            election.data["process_uuid"],
        )
        self.assertEqual(
            identity.logic.identity_holder(
                identity.session.protocol.index[team_uuid],
            ),
            member_uuid,
        )
        sync(identity, member)
        self.assertEqual(
            member.logic.identity_holder(
                member.session.protocol.index[team_uuid],
            ),
            member_uuid,
        )

    def test_any_current_member_can_trigger_trustee_election(self):
        identity = self.runtime(9637)
        member = self.runtime(9638)
        team_uuid = identity.logic.create_team("Member-triggered").value
        connect(identity, member, team_uuid)
        self.admit(identity, member, team_uuid)
        flow, facades = self.election_facades()
        member.logic.facades = facades

        started = member.logic.start_trustee_election(team_uuid, "trust")

        self.assertEqual(started.status, "ok")
        self.assertEqual(
            started.value.data["triggered_by"], member.session.identity.uuid,
        )
        self.assertEqual(
            flow.calls[0]["facilitator"], identity.session.identity.uuid,
        )

    def test_withdrawn_candidate_immediately_loses_acting_authority(self):
        runtime = self.runtime(9643)
        team_uuid = runtime.logic.create_team("Revocable authority").value
        runtime.logic.resign_identity(team_uuid)

        candidacy = runtime.logic.enter_trustee_candidacy(
            team_uuid, "identity",
        )
        first = runtime.logic.record_trustee_action(
            team_uuid, "identity", "membership", {"decision": "open"},
        )
        withdrawn = runtime.logic.withdraw_trustee_candidacy(
            team_uuid, candidacy.value.uuid,
        )
        rejected = runtime.logic.record_trustee_action(
            team_uuid, "identity", "membership", {"decision": "close"},
        )

        self.assertEqual(candidacy.status, "ok")
        self.assertEqual(first.status, "ok")
        self.assertEqual(withdrawn.status, "ok")
        self.assertEqual(rejected.status, "error")
        team = runtime.session.protocol.index[team_uuid]
        self.assertEqual(
            runtime.logic.trustee_candidacy_projection(
                team, candidacy.value.uuid,
            )["state"],
            "withdrawn",
        )
        self.assertFalse(runtime.logic.identity_payload(team)["can_act"])

    def test_acting_identity_candidate_can_operate_membership(self):
        runtime = self.runtime(9644)
        team_uuid = runtime.logic.create_team("Vacant but operable").value
        team = runtime.session.protocol.index[team_uuid]
        type_uuid = runtime.logic.membership_types(team)[0].uuid
        runtime.logic.set_membership_acceptance(
            type_uuid, "Explain your acceptance.",
        )
        runtime.logic.resign_identity(team_uuid)
        runtime.logic.enter_trustee_candidacy(team_uuid, "identity")

        invitation = runtime.logic.open_membership_invitation(
            team_uuid, type_uuid, self.FAR_FUTURE,
        )

        self.assertEqual(invitation.status, "ok")
        team = runtime.session.protocol.index[team_uuid]
        self.assertTrue(runtime.logic.membership_payload(team)["can_resolve"])
        self.assertEqual(
            invitation.value.data["authority_basis_uuid"],
            runtime.logic.identity_payload(team)["candidates"][0]["uuid"],
        )

    def test_acting_candidate_can_facilitate_election(self):
        runtime = self.runtime(9645)
        team_uuid = runtime.logic.create_team("Acting election").value
        runtime.logic.resign_trusteeship(team_uuid, "trust")
        candidacy = runtime.logic.enter_trustee_candidacy(team_uuid, "trust")
        flow, facades = self.election_facades()
        runtime.logic.facades = facades

        started = runtime.logic.start_trustee_election(
            team_uuid, "identity",
        )

        self.assertEqual(started.status, "ok")
        self.assertTrue(candidacy.value.uuid)
        # It reaches S-Flow, which is the only place it is used: the record
        # keeps no authority for it, because nothing is implemented from
        # the result.
        self.assertEqual(
            flow.calls[0]["facilitator"], runtime.session.identity.uuid,
        )
        self.assertEqual(
            set(started.value.data),
            {"type", "trust", "process_uuid", "triggered_by", "triggered_at"},
        )

    def test_one_election_at_a_time_per_trusteeship(self):
        # Two elections on one seat are two valid bases for two different
        # holders, and implementing the second only contests the first. The
        # page made this a double click: two live processes, seconds apart.
        runtime = self.runtime(9646)
        team_uuid = runtime.logic.create_team("One at a time").value
        flow, facades = self.election_facades()
        runtime.logic.facades = facades

        first = runtime.logic.start_trustee_election(team_uuid, "identity")
        second = runtime.logic.start_trustee_election(team_uuid, "identity")

        self.assertEqual(first.status, "ok")
        self.assertEqual(second.status, "error")
        self.assertIn("already under way", second.reason)
        self.assertIn("Identity", second.reason)
        self.assertEqual(len(flow.calls), 1)
        # The counterpart seat is its own decision and is not blocked.
        self.assertEqual(
            runtime.logic.start_trustee_election(team_uuid, "trust").status,
            "ok",
        )
        # Settling the seat is what ends the one that was running, and
        # clears the way for the next.
        actor_uuid = runtime.session.identity.uuid
        self.assertEqual(
            runtime.logic.settle_trusteeship(
                team_uuid, "identity", actor_uuid,
                first.value.data["process_uuid"],
            ).status,
            "ok",
        )
        self.assertEqual(
            runtime.logic.start_trustee_election(team_uuid, "identity").status,
            "ok",
        )

    def test_document_refresh_succeeds_after_starting_an_election(self):
        runtime = self.runtime(9648)
        team_uuid = runtime.logic.create_team("Visible election").value
        _flow, facades = self.election_facades()
        runtime.logic.facades = facades

        started = runtime.logic.start_trustee_election(team_uuid, "identity")
        snapshot = runtime.logic.document_snapshot(team_uuid)

        self.assertEqual(started.status, "ok")
        process_uuid = started.value.data["process_uuid"]
        election = next(
            item for item in snapshot["payload"]["decision_trail"]
            if item["process_uuid"] == process_uuid
            and item["intent"] == "Identity election"
        )
        self.assertEqual(election["result"], "Under way")

    def test_the_decision_trail_carries_every_record_with_its_date(self):
        # The trail used to show only the trustee actions somebody typed in
        # by hand, so stepping out of a trusteeship asked for its signals
        # and then recorded them where nobody could read them.
        runtime = self.runtime(9649)
        team_uuid = runtime.logic.create_team("Trailed").value
        runtime.logic.resign_trusteeship(
            team_uuid, "trust",
            signals="nobody was facilitating",
            consideration="the seat is better vacant",
            expectation="somebody stands in",
        )
        role_uuid = runtime.logic.create_role(team_uuid, "Treasurer").value
        runtime.logic.decide_role(role_uuid, "accepted")

        trail = runtime.logic.decision_trail_payload(
            runtime.session.protocol.index[team_uuid],
        )

        by_intent = {item["intent"]: item for item in trail}
        stepped_out = by_intent["Step out of Trust"]
        self.assertEqual(stepped_out["result"], "Trust is vacant")
        self.assertEqual(stepped_out["signals"], "nobody was facilitating")
        self.assertEqual(stepped_out["expectation"], "somebody stands in")
        self.assertTrue(stepped_out["actor_is_self"])
        self.assertTrue(stepped_out["at"])
        # Taking a role is a record like any other.
        self.assertEqual(
            by_intent["Take Treasurer"]["result"], "You accepted",
        )
        self.assertIn("Identity genesis", by_intent)
        # Newest first, and every row dated.
        dates = [item["at"] for item in trail]
        self.assertEqual(dates, sorted(dates, reverse=True))
        self.assertTrue(all(dates))

    def test_filling_trusteeship_ends_all_acting_authority(self):
        runtime = self.runtime(9648)
        # A real person, because only an Individual may hold a trusteeship
        # and an actor this replica cannot place is deferred rather than
        # settled. A fabricated uuid used to serve here and no longer does.
        replacement = self.runtime(9656)
        team_uuid = runtime.logic.create_team("Authority ends").value
        connect(runtime, replacement, team_uuid)
        replacement.logic.accept_team_invitation(
            replacement.session.protocol.index[team_uuid],
        )
        sync(runtime, replacement)
        runtime.logic.resign_identity(team_uuid)
        runtime.logic.enter_trustee_candidacy(team_uuid, "identity")
        team = runtime.session.protocol.index[team_uuid]
        vacancy_uuid = runtime.logic.trustee_projection(
            team, "identity",
        )["current_state_uuid"]
        trust_basis = runtime.logic.trustee_projection(
            team, "trust",
        )["current_state_uuid"]

        filled = runtime.logic.append_governance_record(team_uuid, {
            "type": "team_trustee_state",
            "trust": "identity",
            "holder_actor_uuid": replacement.session.identity.uuid,
            "previous_state_uuid": vacancy_uuid,
            "cause": "resolution",
            "acted_by": runtime.session.identity.uuid,
            "acted_at": "2026-08-04T16:00:00Z",
            "authority_basis_uuid": trust_basis,
            "signals": "The vacancy needs a settled holder",
            "consideration": "Acting authority is temporary",
            "expectation": "Candidates stop acting",
        })
        rejected = runtime.logic.record_trustee_action(
            team_uuid, "identity", "policy-2", {"decision": "late"},
        )

        self.assertEqual(filled.status, "ok")
        self.assertEqual(rejected.status, "error")
        self.assertFalse(runtime.logic.identity_payload(
            runtime.session.protocol.index[team_uuid],
        )["can_act"])

    def test_a_trustees_decisions_survive_their_resignation(self):
        """Authority is judged against the state a record names, not the head
        of the chain now. A replica receiving an admission and the admitting
        Identity's resignation in one sync must still see the member."""
        identity = self.runtime(9665)
        member = self.runtime(9666)
        team_uuid = identity.logic.create_team("Trail stands").value
        connect(identity, member, team_uuid)
        member.logic.accept_team_invitation(
            member.session.protocol.index[team_uuid],
        )
        sync(identity, member)
        type_uuid = self.a_membership_type(identity, team_uuid)
        invitation = identity.logic.open_membership_invitation(
            team_uuid, type_uuid, self.FAR_FUTURE,
        )
        self.adopt_membership_terms(identity, member, team_uuid, type_uuid)

        application = member.logic.apply_for_membership(
            team_uuid, invitation.value.uuid, agreement_accepted=True,
            acceptance_text="Accepted.",
        )
        sync(identity, member)
        identity.logic.issue_membership_badge(
            team_uuid, application.value.uuid,
        )
        # Badge issue and Identity resignation travel together.
        identity.logic.resign_identity(team_uuid)
        sync(identity, member)

        who = member.session.identity.uuid
        on_peer = member.session.protocol.index[team_uuid]
        at_home = identity.session.protocol.index[team_uuid]
        self.assertEqual(member.logic.member_standing(on_peer, who), "accepted")
        self.assertEqual(identity.logic.member_standing(at_home, who), "accepted")
        acceptance = next(
            record for record in identity.logic.membership_records(at_home, who)
            if record.data.get("cause") == "acceptance"
        )
        self.assertEqual(identity.logic.assess_governance_record(
            at_home, acceptance,
        )["status"], "authorized")

    def test_giving_up_a_seat_keeps_the_record_that_it_was_held(self):
        """Unseating used to delete the holding, so nothing said the seat had
        ever been taken. It is appended now, and taking it again continues
        the same chain rather than laying a second claim beside it."""
        runtime = self.runtime(9671)
        parent_uuid = runtime.logic.create_team("Cooperative").value
        child_uuid = runtime.logic.create_subteam(
            parent_uuid, "Finance circle",
        ).value
        parent = runtime.session.protocol.index[parent_uuid]
        role_uuid = runtime.logic.child_teams(parent)[0][1].uuid

        runtime.logic.unseat_team(role_uuid, child_uuid)
        child = runtime.session.protocol.index[child_uuid]
        records = runtime.logic._held(child, "seats")

        self.assertEqual(runtime.logic.parent_holdings(child), [])
        self.assertEqual(len(records), 2)
        self.assertEqual(
            {record.data["state"] for record in records}, {"held", "given_up"},
        )

        runtime.logic.seat_team(role_uuid, child_uuid)
        child = runtime.session.protocol.index[child_uuid]
        live = runtime.logic.parent_holdings(child)
        roots = [
            node for node in runtime.logic._held(child, "seats")
            if not node.data.get("previous_holding_uuid")
        ]

        self.assertEqual(len(live), 1)
        self.assertEqual(live[0].data["state"], "held")
        # One seat, one chain - not two claims on it.
        self.assertEqual(len(roots), 1)

    def test_a_team_with_no_members_cannot_take_a_seat(self):
        """Containment is vacuously true of an empty team, so without this an
        abandoned subteam would be seatable in every parent there is."""
        runtime = self.runtime(9672)
        parent_uuid = runtime.logic.create_team("Cooperative").value
        child_uuid = runtime.logic.create_subteam(
            parent_uuid, "Finance circle",
        ).value
        parent = runtime.session.protocol.index[parent_uuid]
        role_uuid = runtime.logic.child_teams(parent)[0][1].uuid
        runtime.logic.unseat_team(role_uuid, child_uuid)
        runtime.logic.leave_team(child_uuid)

        refused = runtime.logic.seat_team(role_uuid, child_uuid)

        self.assertEqual(refused.status, "error")
        self.assertIn("no members", refused.reason)
        self.assertEqual(runtime.logic.parent_holdings(
            runtime.session.protocol.index[child_uuid],
        ), [])

    def test_document_content_is_checked_but_still_editable(self):
        """Content is edited rather than appended, and that is deliberate.
        Editable is not unchecked: a peer's clause used to be whatever they
        sent, and somebody was asked to accept it sight unseen."""
        left, right = self.runtime(9675), self.runtime(9676)
        team_uuid = left.logic.create_team("Charter").value
        section_uuid = left.logic.create_section(team_uuid, "Terms").value
        connect(left, right, team_uuid)
        right.logic.accept_team_invitation(
            right.session.protocol.index[team_uuid],
        )
        sync(left, right)

        malformed = right.session.create_child(
            section_uuid,
            {"type": "team_clause", "text": "Fine", "order": "not a number"},
            {},
        ).value
        wrong_child = right.session.create_child(
            section_uuid,
            {"type": "team_clause", "text": "Also fine", "order": 1.0},
            {},
        ).value
        right.session.create_child(
            wrong_child.uuid,
            {
                "type": "team_role", "name": "Smuggled",
                "purpose": "", "order": 0.0,
            },
            {},
        )
        sync(left, right)

        bad_order = left.logic.accept_peer_node(
            right.peer_addr, malformed.uuid,
        )
        owns_a_role = left.logic.accept_peer_node(
            right.peer_addr, wrong_child.uuid,
        )

        self.assertEqual(bad_order.status, "error")
        self.assertIn("order must be a number", bad_order.reason)
        self.assertEqual(owns_a_role.status, "error")
        self.assertIn("only contain document content", owns_a_role.reason)
        # And editing a clause in place is still the ordinary case.
        clause_uuid = left.logic.create_clause(section_uuid, "First").value
        self.assertEqual(
            left.logic.update_clause(clause_uuid, "Reworded").status, "ok",
        )

    def test_an_answer_is_attributed_to_its_signer_not_its_sender(self):
        """A relayed answer is still the answer of whoever wrote it.

        Attribution used to follow the delivery address, so an answer that
        reached this client through a third party was disowned - a false
        refusal in any topology where peers forward for one another. It
        follows the signing key now, which forwarding preserves.
        """
        left, right = self.runtime(9679), self.runtime(9680)
        team_uuid = left.logic.create_team("Charter").value
        role_uuid = left.logic.create_role(team_uuid, "Treasurer").value
        connect(left, right, team_uuid)
        right.logic.accept_team_invitation(
            right.session.protocol.index[team_uuid],
        )
        sync(left, right)

        answer = right.session.create_child(
            role_uuid,
            {
                "type": "team_role_decision",
                "actor_uuid": right.session.identity.uuid,
                "decision": "accepted",
                "previous_decision_uuid": "",
                "decided_at": "2026-01-01T00:00:00Z",
                "reference_hash": right.logic.role_reference_hash(
                    right.session.protocol.index[team_uuid],
                    right.session.protocol.index[role_uuid],
                ),
            },
            {},
        ).value
        sync(left, right)

        team = left.session.protocol.index[team_uuid]
        held = left.session.get_cached_peer_subtree(
            right.peer_addr, answer.uuid,
        )
        self.assertIsNotNone(held)
        self.assertEqual(
            left.logic._author_actor_uuid(team, held),
            right.session.identity.uuid,
        )
        # The same verdict whichever address it arrived on.
        self.assertTrue(
            left.logic._role_answer_authorized(team, held, right.peer_addr),
        )
        self.assertTrue(
            left.logic._role_answer_authorized(team, held, "relay:forwarder"),
        )

    def test_a_malformed_participation_record_is_refused(self):
        """These had no contract at all: a peer's answer was whatever they
        sent, and a person was asked to accept it sight unseen."""
        left, right = self.runtime(9673), self.runtime(9674)
        team_uuid = left.logic.create_team("Charter").value
        role_uuid = left.logic.create_role(team_uuid, "Treasurer").value
        connect(left, right, team_uuid)
        right.logic.accept_team_invitation(
            right.session.protocol.index[team_uuid],
        )
        sync(left, right)

        malformed = right.session.create_child(
            role_uuid,
            {
                "type": "team_role_decision",
                "actor_uuid": right.session.identity.uuid,
                "decision": "whatever it likes",
                "previous_decision_uuid": "",
                "decided_at": "2026-01-01T00:00:00Z",
                "reference_hash": "",
            },
            {},
        ).value
        spoofed = right.session.create_child(
            role_uuid,
            {
                "type": "team_role_decision",
                "actor_uuid": left.session.identity.uuid,
                "decision": "accepted",
                "previous_decision_uuid": "",
                "decided_at": "2026-01-01T00:00:00Z",
                "reference_hash": right.logic.role_reference_hash(
                    right.session.protocol.index[team_uuid],
                    right.session.protocol.index[role_uuid],
                ),
            },
            {},
        ).value
        sync(left, right)

        self.assertNotIn(malformed.uuid, left.session.protocol.index)
        self.assertNotIn(spoofed.uuid, left.session.protocol.index)
        refused = left.logic.accept_peer_node(right.peer_addr, malformed.uuid)

        self.assertEqual(refused.status, "error")
        self.assertIn("accepted or refused", refused.reason)

    def test_a_return_continues_the_membership_chain(self):
        """Coming back resumes the chain that was left, rather than starting
        a second one. One line per Actor is what lets a second root mean
        two replicas admitting the same person at once."""
        identity = self.runtime(9668)
        member = self.runtime(9669)
        team_uuid = identity.logic.create_team("Returns").value
        connect(identity, member, team_uuid)
        member.logic.accept_team_invitation(
            member.session.protocol.index[team_uuid],
        )
        sync(identity, member)
        who = member.session.identity.uuid

        type_uuid = self.a_membership_type(identity, team_uuid)
        # One invitation, answered twice. The window is Identity's and it is
        # still open; walking back through it is the member's own act, which
        # is exactly what makes the second answer a return rather than a
        # re-admission somebody had to grant.
        invitation = identity.logic.open_membership_invitation(
            team_uuid, type_uuid, self.FAR_FUTURE,
        )
        self.adopt_membership_terms(identity, member, team_uuid, type_uuid)

        def admit():
            taken = self.apply_and_issue(
                identity, member, team_uuid, invitation.value.uuid,
                agreement_accepted=True, acceptance_text="Accepted.",
            )
            return taken

        self.assertEqual(admit().status, "ok")
        self.assertEqual(member.logic.leave_team(team_uuid).status, "ok")
        sync(identity, member)
        self.assertEqual(admit().status, "ok")

        team = identity.session.protocol.index[team_uuid]
        records = identity.logic.membership_records(team, who)
        roots = [
            record for record in records
            if not record.data.get("previous_membership_uuid")
        ]
        # Admitted, left, admitted again - three records, one chain.
        self.assertEqual(len(records), 3)
        self.assertEqual(len(roots), 1)
        self.assertEqual(identity.logic.member_standing(team, who), "accepted")
        self.assertIn(who, identity.logic.current_member_uuids(team))

    def test_two_membership_roots_for_one_actor_are_a_contest(self):
        """What a second root now means: two replicas admitting the same
        person at once. Shown, not settled by taking whichever sorts last."""
        runtime = self.runtime(9670)
        team_uuid = runtime.logic.create_team("Two claims").value
        mine = runtime.session.identity.uuid
        runtime.session.create_child(runtime.logic._container(
            runtime.session.protocol.index[team_uuid], "members",
        ).uuid, {
            "type": "team_membership", "actor_uuid": mine, "state": "member",
            "previous_membership_uuid": "", "cause": "genesis",
            "acted_by": mine, "acted_at": "2026-08-07T14:00:00Z",
            "authority_basis_uuid": "", "signals": "",
            "acceptance_text": "", "agreement_accepted": False,
            "consideration": "", "expectation": "",
        }, {})

        team = runtime.session.protocol.index[team_uuid]
        projection = runtime.logic.membership_projection(team, mine)

        self.assertEqual(projection["state"], "contested")
        self.assertEqual(len(projection["contenders"]), 2)
        self.assertEqual(runtime.logic.member_standing(team, mine), "contested")
        self.assertFalse(runtime.logic._is_current_member(team, mine))

    def test_a_team_can_be_left_beyond_recovery(self):
        """Leave, resign Identity, resign Trust - each legitimate on its own -
        and nothing can happen on the team again. Accepted rather than
        prevented: the alternative traps the last person in a team to keep it
        alive. The record survives and a fork can carry the work on."""
        runtime = self.runtime(9667)
        team_uuid = runtime.logic.create_team("Abandoned").value

        self.assertEqual(runtime.logic.leave_team(team_uuid).status, "ok")
        self.assertEqual(runtime.logic.resign_identity(team_uuid).status, "ok")
        self.assertEqual(
            runtime.logic.resign_trusteeship(team_uuid, "trust").status, "ok",
        )

        team = runtime.session.protocol.index[team_uuid]
        self.assertEqual(runtime.logic.current_member_uuids(team), [])
        for trust in ("identity", "trust"):
            self.assertEqual(
                runtime.logic.trustee_projection(team, trust)["state"], "vacant",
            )
        # Nothing left that can bring it back. Not the invitation, whose
        # authority is Identity's, and not a second membership type, which
        # is Identity's to declare - so the pool has nothing to answer.
        self.assertEqual(
            runtime.logic.open_membership_invitation(
                team_uuid,
                runtime.logic.membership_types(team)[0].uuid,
                self.FAR_FUTURE,
            ).status,
            "error",
        )
        self.assertEqual(runtime.logic.create_membership_type(
            team_uuid, "Associate",
        ).status, "error")
        self.assertEqual(runtime.logic.enter_trustee_candidacy(
            team_uuid, "identity",
        ).status, "error")
        self.assertEqual(runtime.logic.start_trustee_election(
            team_uuid, "identity",
        ).status, "error")
        self.assertEqual(runtime.logic.settle_trusteeship(
            team_uuid, "identity", runtime.session.identity.uuid, "p", "h",
        ).status, "error")

    def test_a_team_cannot_hold_a_trusteeship(self):
        """Only an Individual. A Team holding one would leave admissions,
        resignations and elections resting on an authority with nobody
        answerable for it."""
        runtime = self.runtime(9657)
        team_uuid = runtime.logic.create_team("Holder kind").value
        other_uuid = runtime.logic.create_team("A team, not a person").value
        runtime.logic.resign_identity(team_uuid)
        team = runtime.session.protocol.index[team_uuid]
        vacancy_uuid = runtime.logic.trustee_projection(
            team, "identity",
        )["current_state_uuid"]
        trust_basis = runtime.logic.trustee_projection(
            team, "trust",
        )["current_state_uuid"]

        refused = runtime.logic.append_governance_record(team_uuid, {
            "type": "team_trustee_state",
            "trust": "identity",
            "holder_actor_uuid": other_uuid,
            "previous_state_uuid": vacancy_uuid,
            "cause": "resolution",
            "acted_by": runtime.session.identity.uuid,
            "acted_at": "2026-08-07T12:00:00Z",
            "authority_basis_uuid": trust_basis,
            "signals": "",
            "consideration": "",
            "expectation": "",
        })

        self.assertEqual(refused.status, "error")
        self.assertIn("Individual", refused.reason)
        self.assertEqual(runtime.logic.trustee_projection(
            runtime.session.protocol.index[team_uuid], "identity",
        )["state"], "vacant")

    def test_settling_fills_a_vacancy_without_an_election(self):
        """The resolution cause: the facilitating trusteeship's authority,
        and nothing else. A seat can be filled without anybody running a
        process for it - what it may not do is write over somebody who is
        sitting in one."""
        runtime = self.runtime(9659)
        holder = self.runtime(9660)
        team_uuid = runtime.logic.create_team("Settled").value
        connect(runtime, holder, team_uuid)
        holder.logic.accept_team_invitation(
            holder.session.protocol.index[team_uuid],
        )
        sync(runtime, holder)
        runtime.logic.resign_identity(team_uuid)

        occupied = runtime.logic.settle_trusteeship(
            team_uuid, "trust", holder.session.identity.uuid,
        )
        settled = runtime.logic.settle_trusteeship(
            team_uuid, "identity", holder.session.identity.uuid,
            signals="No election was needed",
        )

        # Trust is held, so it cannot be settled over.
        self.assertEqual(occupied.status, "error")
        self.assertEqual(settled.status, "ok")
        projection = runtime.logic.trustee_projection(
            runtime.session.protocol.index[team_uuid], "identity",
        )
        self.assertEqual(projection["state"], "held")
        self.assertEqual(
            projection["holder_actor_uuid"], holder.session.identity.uuid,
        )
        self.assertFalse(runtime.logic.trustee_election_records(
            runtime.session.protocol.index[team_uuid], "identity",
        ))

    def test_only_an_election_replaces_a_sitting_trustee(self):
        """The way out of an occupied seat is the holder's own resignation,
        or an election that says otherwise. Settling on a bare authority
        fills an empty seat and no more - and the model still permits the
        record, because a signed, attributable act nobody can hide is what
        the signatures are for. Preventing it outright would be a cage."""
        runtime = self.runtime(9663)
        holder = self.runtime(9664)
        team_uuid = runtime.logic.create_team("Replaceable").value
        connect(runtime, holder, team_uuid)
        holder.logic.accept_team_invitation(
            holder.session.protocol.index[team_uuid],
        )
        sync(runtime, holder)
        runtime.logic.resign_identity(team_uuid)
        runtime.logic.settle_trusteeship(
            team_uuid, "identity", holder.session.identity.uuid,
        )
        team = runtime.session.protocol.index[team_uuid]
        sitting = runtime.logic.trustee_projection(team, "identity")
        trust_basis = runtime.logic.trustee_projection(
            team, "trust",
        )["current_state_uuid"]

        refused = runtime.logic.settle_trusteeship(
            team_uuid, "identity", runtime.session.identity.uuid,
        )
        written = runtime.logic.append_governance_record(team_uuid, {
            "type": "team_trustee_state",
            "trust": "identity",
            "holder_actor_uuid": runtime.session.identity.uuid,
            "previous_state_uuid": sitting["current_state_uuid"],
            "cause": "resolution",
            "acted_by": runtime.session.identity.uuid,
            "acted_at": "2026-08-07T13:00:00Z",
            "authority_basis_uuid": trust_basis,
            "signals": "",
            "consideration": "",
            "expectation": "",
        })

        self.assertEqual(sitting["state"], "held")
        self.assertEqual(refused.status, "error")
        self.assertIn("not vacant", refused.reason)
        self.assertEqual(written.status, "ok")
        self.assertEqual(runtime.logic.trustee_projection(
            runtime.session.protocol.index[team_uuid], "identity",
        )["holder_actor_uuid"], runtime.session.identity.uuid)

    def test_settling_needs_the_facilitating_trusteeship(self):
        """Settling rests on the other trusteeship's authority, so somebody
        holding neither cannot do it. The founder holds both, which is why
        the refusal has to be tried from outside."""
        runtime = self.runtime(9661)
        outsider = self.runtime(9662)
        team_uuid = runtime.logic.create_team("Self settling").value
        connect(runtime, outsider, team_uuid)
        outsider.logic.accept_team_invitation(
            outsider.session.protocol.index[team_uuid],
        )
        runtime.logic.resign_identity(team_uuid)
        sync(runtime, outsider)

        refused = outsider.logic.settle_trusteeship(
            team_uuid, "identity", outsider.session.identity.uuid,
            "process-2", "sha256:process-2",
        )

        self.assertEqual(refused.status, "error")
        self.assertEqual(runtime.logic.trustee_projection(
            runtime.session.protocol.index[team_uuid], "identity",
        )["state"], "vacant")

    def test_holding_a_trusteeship_is_not_being_on_the_team(self):
        """A trustee is elected out of the members, so the seat never stands
        in for membership. Somebody whose membership ended while they still
        held one is a state worth seeing, not one to paper over."""
        runtime = self.runtime(9658)
        team_uuid = runtime.logic.create_team("Seat without standing").value
        actor_uuid = runtime.session.identity.uuid

        left = runtime.logic.leave_team(team_uuid)

        team = runtime.session.protocol.index[team_uuid]
        self.assertEqual(left.status, "ok")
        # The seat is still theirs...
        self.assertEqual(runtime.logic.trustee_projection(
            team, "identity",
        )["holder_actor_uuid"], actor_uuid)
        # ...and it does not put them back on the team.
        self.assertEqual(
            runtime.logic.member_standing(team, actor_uuid), "former",
        )
        self.assertFalse(
            runtime.logic.document_payload(team_uuid)["holds_role"],
        )

    def test_concurrent_acting_decisions_and_reality_remain_visible(self):
        identity = self.runtime(9646)
        member = self.runtime(9647)
        team_uuid = identity.logic.create_team("Visible conflict").value
        connect(identity, member, team_uuid)
        member.logic.accept_team_invitation(
            member.session.protocol.index[team_uuid],
        )
        sync(identity, member)
        type_uuid = self.a_membership_type(identity, team_uuid)
        invitation = identity.logic.open_membership_invitation(
            team_uuid, type_uuid, self.FAR_FUTURE,
        )
        self.adopt_membership_terms(identity, member, team_uuid, type_uuid)
        application = member.logic.apply_for_membership(
            team_uuid, invitation.value.uuid, agreement_accepted=True,
            acceptance_text="Accepted.",
        )
        sync(identity, member)
        identity.logic.issue_membership_badge(
            team_uuid, application.value.uuid,
        )
        identity.logic.resign_identity(team_uuid)
        sync(identity, member)
        identity.logic.enter_trustee_candidacy(team_uuid, "identity")
        member.logic.enter_trustee_candidacy(team_uuid, "identity")
        sync(identity, member)

        first = identity.logic.record_trustee_action(
            team_uuid, "identity", "policy-1", {"decision": "A"},
        )
        second = member.logic.record_trustee_action(
            team_uuid, "identity", "policy-1", {"decision": "B"},
            consideration="A different reading",
        )
        sync(identity, member)
        unauthorized_observation = member.logic.append_trustee_reality(
            team_uuid, first.value.uuid, "Not mine to facilitate.",
        )
        observed = identity.logic.append_trustee_reality(
            team_uuid, first.value.uuid, "The expected effect did not occur.",
        )

        self.assertEqual((first.status, second.status), ("ok", "ok"))
        self.assertEqual(unauthorized_observation.status, "error")
        self.assertEqual(observed.status, "ok")
        trail = identity.logic.trustee_actions_payload(
            identity.session.protocol.index[team_uuid],
        )
        self.assertEqual(len(trail), 2)
        self.assertTrue(all(action["contested"] for action in trail))
        self.assertTrue(all(action["signals_missing"] for action in trail))
        self.assertEqual(trail[0]["realities"][0]["reality"],
                         "The expected effect did not occur.")

    @unittest.skipIf(FlowLogic is None, "S-Flow is not installed")
    def test_real_flow_facade_drives_trustee_election_end_to_end(self):
        session = Session("local")
        flow_logic = FlowLogic(session)
        flow_facade = FlowFacade(flow_logic)

        class Facades:
            def find(self, application_id, facade_api_version):
                if (application_id, facade_api_version) == ("flow", 1):
                    return flow_facade
                return None

        team_logic = TeamLogic(session, facades=Facades())
        team_uuid = team_logic.create_team("Real election").value
        started = team_logic.start_trustee_election(team_uuid, "identity")
        self.assertEqual(started.status, "ok")
        process_uuid = started.value.data["process_uuid"]
        responses = {
            "Task_Nominate": {
                "candidateId": session.identity.uuid,
                "reason": "Available",
            },
            "Task_ChangeNominations": {"decision": "keep"},
            "Task_ObjectionRound": {"decision": "noObjection"},
        }
        while True:
            workflow = flow_logic.process_payload(process_uuid)["workflow"]
            if workflow["status"] == "completed":
                break
            task = workflow["personal"]["tasks"][0]
            submitted = flow_logic.submit_task(
                process_uuid,
                task["id"],
                responses[task["nodeId"]],
                workflow["runtime_content_hash"],
            )
            self.assertEqual(submitted.status, "ok")

        # The process ran to an end, and by itself that moved nothing. A
        # person reads it - here, the result says who was elected - and
        # settles the seat, which is the act the record attributes.
        result = flow_facade.decision_result(process_uuid)
        self.assertEqual(result["terminal_outcome"], "elected")
        settled = team_logic.settle_trusteeship(
            team_uuid, "identity", result["selected_candidate_uuid"],
            process_uuid, signals="The election chose them",
        )

        self.assertEqual(settled.status, "ok")
        self.assertEqual(settled.value.data["process_uuid"], process_uuid)
        projection = team_logic.trustee_projection(
            session.protocol.index[team_uuid], "identity",
        )
        self.assertEqual(
            projection["current_state_uuid"], settled.value.uuid,
        )
        self.assertEqual(
            projection["holder_actor_uuid"],
            result["selected_candidate_uuid"],
        )

    @unittest.skipIf(FlowLogic is None, "S-Flow is not installed")
    def test_an_election_goes_on_the_channel_the_team_is_on(self):
        # An election is the team's act, so it travels the way the team
        # does. Without this the process stayed on whoever started it, and
        # every other elector saw a record naming a process they could not
        # reach - which is the whole of what "unavailable" meant.
        left, right = self.runtime(9720), self.runtime(9721)
        team_uuid = left.logic.create_team("Bridged election").value
        connect(left, right, team_uuid)
        self.admit(left, right, team_uuid)
        left_flow = FlowLogic(left.session)
        right_flow = FlowLogic(right.session)
        left.session.register_application(left_flow.application_registration())
        right.session.register_application(right_flow.application_registration())
        flow_facade = FlowFacade(left_flow)

        class Facades:
            def find(self, application_id, facade_api_version):
                if (application_id, facade_api_version) == ("flow", 1):
                    return flow_facade
                return None

        left.logic.facades = Facades()

        started = left.logic.start_trustee_election(team_uuid, "identity")

        self.assertEqual(started.status, "ok")
        process_uuid = started.value.data["process_uuid"]
        self.assertEqual(
            left.relay_manager.target_for_topic(process_uuid),
            left.relay_manager.target_for_topic(team_uuid),
        )

        # Taking part is what membership is for, so a member's client asks
        # for the process itself rather than waiting to be told to. This
        # reverses the earlier rule deliberately, and only for elections:
        # every other item still waits to be connected to.
        sync(left, right)
        joined = SessionResult(
            "ok" if right.logic.adopt_team_elections(
                right.session.protocol.index[team_uuid],
            ) else "error",
        )
        sync(left, right)

        self.assertEqual(joined.status, "ok")
        self.assertIn(process_uuid, right.session.protocol.index)
        self.assertEqual(
            right.relay_manager.target_for_topic(process_uuid),
            right.relay_manager.target_for_topic(team_uuid),
        )

        left_workflow = left_flow.process_payload(process_uuid)["workflow"]
        right_workflow = right_flow.process_payload(process_uuid)["workflow"]
        left_task = left_workflow["personal"]["tasks"][0]
        right_task = right_workflow["personal"]["tasks"][0]
        self.assertEqual(
            left_flow.submit_task(
                process_uuid,
                left_task["id"],
                {"candidateId": left.session.identity.uuid, "reason": "Available"},
                left_workflow["runtime_content_hash"],
            ).status,
            "ok",
        )
        self.assertEqual(
            right_flow.submit_task(
                process_uuid,
                right_task["id"],
                {"candidateId": right.session.identity.uuid, "reason": "Available"},
                right_workflow["runtime_content_hash"],
            ).status,
            "ok",
        )

        sync(left, right)
        applied = left_flow.on_peer_update()
        self.assertEqual(applied.status, "ok", applied.reason)
        self.assertTrue(applied.value)
        sync(left, right)
        right_flow.on_peer_update()

        left_final = left_flow.process_payload(process_uuid)["workflow"]
        right_final = right_flow.process_payload(process_uuid)["workflow"]
        self.assertNotEqual(
            left_final["position"]["current_stages"][0]["name"],
            "Nominate candidate",
        )
        self.assertNotEqual(
            right_final["personal"]["waiting_reason"],
            {"type": "responsePending", "dependencies": []},
        )

    @unittest.skipIf(FlowLogic is None, "S-Flow is not installed")
    def test_archiving_puts_a_team_away_here_and_nowhere_else(self):
        # Archiving is local. Sharing ends, so this client stops publishing
        # and polling; every other client keeps its copy and its access,
        # because nothing was sent and nothing was decided.
        left, right = self.runtime(9730), self.runtime(9731)
        team_uuid = left.logic.create_team("Filed away").value
        left.logic.create_section(team_uuid, "Purpose")
        connect(left, right, team_uuid)
        self.admit(left, right, team_uuid)

        archived = left.logic.archive_team(team_uuid)

        self.assertEqual(archived.status, "ok")
        self.assertNotIn(team_uuid, left.session.protocol.index)
        self.assertIn(team_uuid, right.session.protocol.index)
        path = Path(archived.value)
        self.assertTrue(path.is_file())
        document = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(document["title"], "Filed away")
        self.assertEqual(document["team"]["uuid"], team_uuid)
        # No relay coordinates: an archive records what the team was, not a
        # way back onto a channel.
        encoded = json.dumps(document)
        for secret in ("descriptor", "target_id", "relay", "password", "root"):
            self.assertNotIn(f'"{secret}"', encoded)
        # And no stub: the file is the record, and a row beside it would be
        # a second thing to keep in step with it.
        self.assertEqual(
            [item.uuid for item in left.logic.teams()], [],
        )
        listed = left.logic.archives()
        self.assertEqual(
            [(item["title"], item["restorable"]) for item in listed],
            [("Filed away", True)],
        )

    def test_a_restored_team_comes_back_private(self):
        runtime = self.runtime(9732)
        team_uuid = runtime.logic.create_team("Comes back").value
        section_uuid = runtime.logic.create_section(team_uuid, "Purpose").value
        archived = runtime.logic.archive_team(team_uuid)
        file_name = Path(archived.value).name

        restored = runtime.logic.restore_team(file_name)

        self.assertEqual(restored.status, "ok")
        self.assertEqual(restored.value, team_uuid)
        team = runtime.session.protocol.index[team_uuid]
        self.assertEqual(team.data["title"], "Comes back")
        self.assertEqual(
            [node.uuid for node in runtime.logic.sections(team)],
            [section_uuid],
        )
        # The archive carried no channel, so it is on none: putting it back
        # on one is a deliberate act by somebody who still has an invitation.
        self.assertIsNone(
            runtime.relay_manager.target_for_topic(team_uuid),
        )
        # Restoring twice would be two of the same team.
        again = runtime.logic.restore_team(file_name)
        self.assertEqual(again.status, "error")
        self.assertIn("already here", again.reason)
        self.assertFalse(runtime.logic.archives()[0]["restorable"])

    def test_a_failed_archive_write_leaves_the_team_alone(self):
        runtime = self.runtime(9733)
        team_uuid = runtime.logic.create_team("Stays put").value
        # A directory where the file has to go is the ordinary shape of a
        # write that cannot happen.
        directory = runtime.logic._archive_directory()
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"Stays-put-{team_uuid[:8]}.json").mkdir()

        archived = runtime.logic.archive_team(team_uuid)

        self.assertEqual(archived.status, "error")
        self.assertIn("could not write the archive", archived.reason)
        self.assertIn(team_uuid, runtime.session.protocol.index)

    def test_document_snapshot_never_consults_transport_under_session(self):
        class NoTransport:
            def network_info(self, _topic_uuid=None):
                raise AssertionError("transport reached from Session snapshot")

            def peer_liveness_for_address(self, _peer, _topic_uuid=None):
                raise AssertionError("transport reached from Session snapshot")

        session = Session("local")
        logic = TeamLogic(session, collaboration=NoTransport())
        team_uuid = logic.create_team("Atomic view").value

        with session.lock:
            snapshot = logic.document_snapshot(team_uuid)

        payload = logic.merge_document_observation(snapshot, {"peers": {}})
        self.assertEqual(snapshot["topic_uuid"], team_uuid)
        self.assertEqual(payload["network"], {"peers": {}})

    def test_document_payload_does_not_change_implicit_selection(self):
        runtime = self.runtime(8610)
        created = runtime.logic.create_team("Read only")
        with runtime.session.lock:
            metadata = runtime.session.application_metadata("team")
            metadata.pop("selected_team_uuid", None)

        payload = runtime.logic.document_payload()

        self.assertEqual(payload["team"]["uuid"], created.value)
        with runtime.session.lock:
            self.assertNotIn(
                "selected_team_uuid",
                runtime.session.application_metadata("team"),
            )

    def test_manifest_and_minimal_document_tree(self):
        runtime = self.runtime(9401)

        team_uuid = runtime.logic.create_team("Working team").value
        section_uuid = runtime.logic.create_section(
            team_uuid, "Responsibilities",
        ).value
        clause_uuid = runtime.logic.create_clause(
            section_uuid, "Each participant reviews proposed changes.",
        ).value
        payload = runtime.logic.document_payload()

        self.assertEqual(APPLICATION_MANIFEST.application_id, "team")
        self.assertEqual(payload["team"]["uuid"], team_uuid)
        sections = self.serialized(payload["team"], "team_section")
        self.assertEqual(sections[0]["uuid"], section_uuid)
        self.assertEqual(
            self.serialized(sections[0], "team_clause")[0]["uuid"], clause_uuid,
        )

    def test_acceptance_is_a_separate_hashed_timestamped_item(self):
        runtime = self.runtime(9458)
        team_uuid = runtime.logic.create_team("Charter").value
        self.a_role(runtime, team_uuid)
        team = runtime.session.protocol.index[team_uuid]
        role = runtime.logic.roles(team)[0]
        decisions = runtime.logic._held(role, "answers")

        self.assertEqual(len(decisions), 1)
        decision = decisions[0].data
        self.assertEqual(
            decision["actor_uuid"], runtime.session.identity.uuid,
        )
        self.assertEqual(decision["decision"], "accepted")
        self.assertTrue(decision["decided_at"].endswith("Z"))
        self.assertTrue(decision["reference_hash"].startswith("sha256:"))
        # Absent rather than explicitly null, like every other optional
        # governance field.
        self.assertNotIn("expires_at", decision)
        self.assertEqual(decision["previous_decision_uuid"], "")
        # Offers and answers have their own storage nodes, but they are
        # records about the team rather than content of it, so they
        # stay out of the document serialization.
        serialized = runtime.logic.document_payload(
            team_uuid,
        )["team"]["children"]
        roles_view = next(
            child for child in serialized
            if child["data"].get("name") == "roles"
        )
        role_view = next(
            child for child in roles_view["children"]
            if child["data"].get("type") == "team_role"
        )

        def types_under(item):
            for child in item.get("children") or []:
                yield child["data"].get("type")
                yield from types_under(child)

        self.assertEqual(
            {
                node_type for node_type in types_under(role_view)
                if node_type != "team_container"
            },
            set(),
        )

    def test_refusal_updates_the_users_item_and_renders_a_badge(self):
        runtime = self.runtime(9459)
        team_uuid = runtime.logic.create_team("Charter").value
        self.a_role(runtime, team_uuid)
        team = runtime.session.protocol.index[team_uuid]
        role = runtime.logic.roles(team)[0]
        original = runtime.logic._held(role, "answers")[0]

        result = runtime.logic.decide_role(
            role.uuid, "refused", "2035-01-01T00:00:00Z",
        )

        self.assertEqual(result.status, "ok")
        role = runtime.session.protocol.index[role.uuid]
        decisions = runtime.logic._held(role, "answers")
        # Answering again continues the chain. The first answer stays where
        # it was made, so when somebody took a role and when they stepped
        # out of it are both readable; the end of the chain is what counts.
        self.assertEqual(len(decisions), 2)
        head = runtime.logic._role_decision_for(
            role, runtime.session.identity.uuid,
        )
        self.assertNotEqual(head.uuid, original.uuid)
        self.assertEqual(head.data["previous_decision_uuid"], original.uuid)
        self.assertEqual(head.data["decision"], "refused")
        self.assertEqual(original.data["decision"], "accepted")
        holder = runtime.logic.role_holders(team, role)[0]
        self.assertEqual(holder["status"], "refused")
        self.assertEqual(holder["expires_at"], "2035-01-01T00:00:00Z")
        # Refusing a role is not leaving the team: being here is membership,
        # and what work you have taken on is a separate question. Leaving is
        # its own act, and it is what ends the standing.
        self.assertTrue(
            runtime.logic._has_current_acceptance(
                runtime.session.protocol.index[team_uuid],
            ),
        )
        self.assertEqual(self.leave(runtime, team_uuid).status, "ok")
        self.assertFalse(
            runtime.logic._has_current_acceptance(
                runtime.session.protocol.index[team_uuid],
            ),
        )

    def test_content_change_makes_acceptance_outdated_until_renewed(self):
        runtime = self.runtime(9464)
        team_uuid = runtime.logic.create_team("Charter").value
        self.a_role(runtime, team_uuid)
        runtime.logic.rename_agreement(team_uuid, "Team Agreement")
        runtime.logic.set_agreement_version(team_uuid, "1")
        section_uuid = runtime.logic.create_section(
            team_uuid, "Purpose",
        ).value

        self.assertEqual(
            self.own_standing(runtime, team_uuid), "outdated",
        )

        self.accept_roles(runtime, team_uuid)
        self.assertEqual(
            self.own_standing(runtime, team_uuid), "accepted",
        )
        team = runtime.session.protocol.index[team_uuid]
        role = runtime.logic.roles(team)[0]
        own = runtime.logic._own_role_decision(role)
        self.assertEqual(
            own.data["reference_hash"],
            runtime.logic.role_reference_hash(team, role),
        )
        runtime.logic.create_clause(section_uuid, "Serve the members.")
        self.assertEqual(
            self.own_standing(runtime, team_uuid), "outdated",
        )

    def test_every_ancestor_requires_a_current_acceptance(self):
        runtime = self.runtime(9465)
        root_uuid = runtime.logic.create_team("Cooperative").value
        child_uuid = runtime.logic.create_subteam(
            root_uuid, "Operations",
        ).value
        self.leave(runtime, root_uuid)

        blocked = runtime.logic.create_subteam(child_uuid, "Purchasing")

        self.assertEqual(blocked.status, "error")
        # Only the root was left, so the root is what blocks - the level
        # between was never written to.
        self.assertIn("Cooperative", blocked.reason)
        # Only the root was left, so only the root has to be rejoined.
        self.rejoin(runtime, root_uuid)
        allowed = runtime.logic.create_subteam(
            child_uuid, "Purchasing",
        )
        self.assertEqual(allowed.status, "ok")

    def test_a_role_acceptance_can_expire_without_ending_the_membership(self):
        # An expiry is a limit on the work, not on being here. It used to be
        # both, because membership was itself a role acceptance - so a dated
        # acceptance quietly timed somebody out of the team.
        runtime = self.runtime(9466)
        parent_uuid = runtime.logic.create_team("Cooperative").value
        self.a_role(runtime, parent_uuid)
        self.accept_roles(runtime, parent_uuid, "2000-01-01T00:00:00Z")

        self.assertEqual(self.own_standing(runtime, parent_uuid), "expired")
        self.assertEqual(
            runtime.logic.create_subteam(parent_uuid, "Operations").status,
            "ok",
        )

    def test_leaving_a_parent_blocks_a_subteam(self):
        runtime = self.runtime(9496)
        parent_uuid = runtime.logic.create_team("Cooperative").value
        self.leave(runtime, parent_uuid)

        blocked = runtime.logic.create_subteam(parent_uuid, "Operations")

        self.assertEqual(blocked.status, "error")
        self.assertEqual(self.rejoin(runtime, parent_uuid).status, "ok")
        self.assertEqual(
            runtime.logic.create_subteam(parent_uuid, "Operations").status,
            "ok",
        )

    def test_leaving_a_parent_closes_its_descendants_without_writing_to_them(self):
        # Invalidity is derived, never recorded. The cascade this replaces
        # wrote a refusal into every descendant, which destroyed the
        # participant's own answers there and never undid itself when the
        # parent was taken up again.
        runtime = self.runtime(9467)
        root_uuid = runtime.logic.create_team("Cooperative").value
        child_uuid = runtime.logic.create_subteam(
            root_uuid, "Operations",
        ).value
        grandchild_uuid = runtime.logic.create_subteam(
            child_uuid, "Purchasing",
        ).value

        self.leave(runtime, root_uuid)

        def writable(team_uuid):
            return runtime.logic.interaction_payload(
                runtime.session.protocol.index[team_uuid],
            )["allowed"]

        # A root has no ancestor to be blocked by, so it stays writable; its
        # descendants do not.
        self.assertTrue(writable(root_uuid))
        self.assertFalse(writable(child_uuid))
        self.assertFalse(writable(grandchild_uuid))
        # Nothing was written into them, so the standing there survives.
        for team_uuid in (child_uuid, grandchild_uuid):
            self.assertTrue(runtime.logic._is_current_member(
                runtime.session.protocol.index[team_uuid],
                runtime.session.identity.uuid,
            ))
        self.assertEqual(
            [
                item.data["title"]
                for item in runtime.logic.descendant_teams(root_uuid)
            ],
            ["Operations", "Purchasing"],
        )

        # And because nothing was written, taking the root back up restores
        # the whole subtree at once rather than one level at a time.
        self.rejoin(runtime, root_uuid)
        self.assertTrue(writable(child_uuid))
        self.assertTrue(writable(grandchild_uuid))
    def test_blocked_subteam_is_visible_but_all_mutations_are_rejected(self):
        runtime = self.runtime(9468)
        parent_uuid = runtime.logic.create_team("Cooperative").value
        child_uuid = runtime.logic.create_subteam(
            parent_uuid, "Operations",
        ).value
        section_uuid = runtime.logic.create_section(
            child_uuid, "Responsibilities",
        ).value
        self.leave(runtime, parent_uuid)

        selected = runtime.logic.select_team(child_uuid)
        payload = runtime.logic.document_payload(child_uuid)

        self.assertEqual(selected.status, "ok")
        self.assertEqual(payload["team"]["uuid"], child_uuid)
        self.assertFalse(payload["interaction"]["allowed"])
        self.assertIn("Cooperative", payload["interaction"]["reason"])
        for result in (
            runtime.logic.rename_team(child_uuid, "Changed"),
            runtime.logic.create_section(child_uuid, "Blocked"),
            runtime.logic.rename_section(section_uuid, "Changed"),
            runtime.logic.delete_team(child_uuid),
        ):
            self.assertEqual(result.status, "error")
            self.assertIn("Read-only", result.reason)

    def test_subteam_is_linked_but_remains_an_independent_topic(self):
        runtime = self.runtime(9460)
        parent_uuid = runtime.logic.create_team("Cooperative").value

        child_uuid = runtime.logic.create_subteam(
            parent_uuid, "Finance circle",
        ).value

        parent = runtime.session.protocol.index[parent_uuid]
        child = runtime.session.protocol.index[child_uuid]
        # A subteam is a Team holding a role in its parent, so
        # the parent side is an ordinary role offered to a Team
        # actor and the child side names that same seat.
        seats = runtime.logic.child_teams(parent)
        self.assertEqual(child.parent_uuid, parent.parent_uuid)
        self.assertEqual(len(seats), 1)
        seated_uuid, role = seats[0]
        self.assertEqual(seated_uuid, child_uuid)
        self.assertEqual(role.data["name"], "Finance circle")
        holdings = runtime.logic.parent_holdings(child)
        self.assertEqual(len(holdings), 1)
        self.assertEqual(
            holdings[0].data["parent_team_uuid"], parent_uuid,
        )
        self.assertEqual(holdings[0].data["role_uuid"], role.uuid)
        self.assertEqual(
            {item.uuid for item in runtime.logic.teams()},
            {parent_uuid, child_uuid},
        )

        organization = runtime.logic.organization_payload()
        parent_view = next(
            item for item in organization["roots"]
            if item["uuid"] == parent_uuid
        )
        self.assertEqual(
            [item["uuid"] for item in parent_view["children"]],
            [child_uuid],
        )

    def test_joining_parent_does_not_join_its_subteam(self):
        left, right = self.runtime(9461), self.runtime(9462)
        parent_uuid = left.logic.create_team("Cooperative").value
        participant_uuid = left.logic.create_role(
            parent_uuid, "Participant",
        ).value
        self.assertEqual(connect(left, right, parent_uuid)["status"], "ok")

        # Joining the topic is not joining the team. Until a role is
        # held, somebody is present and nothing more.
        people = right.logic.participants(parent_uuid)
        self.assertEqual(len(people), 2)
        mine = next(person for person in people if person["is_self"])
        self.assertTrue(mine["is_observer"])
        self.assertEqual(mine["roles"], [])
        self.assertTrue(all("name" in person for person in people))
        self.assertTrue(all("picture" in person for person in people))

        # Be admitted, then take the role. Nobody has to confirm the second
        # part: Identity decides membership, not what a member does here.
        self.admit(left, right, parent_uuid)
        right.logic.decide_role(participant_uuid, "accepted")
        sync(left, right)
        self.assertEqual(next(
            holder["status"]
            for holder in right.logic.role_holders(
                right.session.protocol.index[parent_uuid],
                right.session.protocol.index[participant_uuid],
            )
            if holder["is_self"]
        ), "accepted")

        child_uuid = left.logic.create_subteam(
            parent_uuid, "Finance circle",
        ).value
        link_uuid = left.logic.child_teams(
            left.session.protocol.index[parent_uuid],
        )[0][1].uuid
        sync(left, right)

        right_teams = {item.uuid for item in right.logic.teams()}
        self.assertIn(parent_uuid, right_teams)
        self.assertNotIn(child_uuid, right_teams)
        payload = right.logic.document_payload(parent_uuid)
        self.assertIn(
            link_uuid,
            {entry["node"]["uuid"] for entry in payload["proposed_nodes"]},
        )
        self.assertEqual(
            right.logic.organization_payload()["roots"][0]["children"], [],
        )

        # Agreeing to the parent-side relationship makes the unit visible,
        # but still does not mount the separately shared child topic.
        accepted = right.logic.accept_peer_node(left.peer_addr, link_uuid)
        self.assertEqual(accepted.status, "ok")
        parent_view = right.logic.organization_payload()["roots"][0]
        restricted = parent_view["children"][0]
        self.assertEqual(restricted["uuid"], child_uuid)
        self.assertFalse(restricted["joined"])

        # Taking up the seat does not disturb anybody's acceptance of the
        # parent. A subteam seat is a role, and a role is outside the
        # document body, so adding a subunit changes nothing that anyone
        # agreed to - unlike the link it replaces, which forced everyone to
        # re-accept the parent whenever the organisation grew.
        self.assertEqual(next(
            holder["status"]
            for holder in right.logic.role_holders(
                right.session.protocol.index[parent_uuid],
                right.session.protocol.index[participant_uuid],
            )
            if holder["is_self"]
        ), "accepted")

        # The invitation is still needed, and it mounts only because a role
        # is held in the parent.
        self.assertEqual(connect(left, right, child_uuid)["status"], "ok")
        right.session.mount_cached_topics("team")
        sync(left, right)
        self.assertIn(
            child_uuid, {item.uuid for item in right.logic.teams()},
        )
        parent_view = next(
            item for item in right.logic.organization_payload()["roots"]
            if item["uuid"] == parent_uuid
        )
        self.assertTrue(parent_view["children"][0]["joined"])

    def test_a_subteam_stays_unmounted_while_no_role_is_held_above_it(self):
        # The mounting rule the test above relies on, on its own: an
        # invitation to a subteam is cached rather than mounted until
        # this session holds something in every team above it.
        left, right = self.runtime(9512), self.runtime(9513)
        parent_uuid = left.logic.create_team("Cooperative").value
        participant_uuid = left.logic.create_role(
            parent_uuid, "Participant",
        ).value
        child_uuid = left.logic.create_subteam(
            parent_uuid, "Finance circle",
        ).value
        self.assertEqual(connect(left, right, parent_uuid)["status"], "ok")
        right.logic.accept_team_invitation(
            right.session.protocol.index[parent_uuid],
        )
        sync(left, right)

        # Present in the parent, holding nothing in it.
        self.assertEqual(connect(left, right, child_uuid)["status"], "ok")
        right.session.mount_cached_topics("team")
        self.assertNotIn(
            child_uuid, {item.uuid for item in right.logic.teams()},
        )

        # Being admitted above is what opens it.
        self.admit(left, right, parent_uuid)
        right.session.mount_cached_topics("team")
        self.assertIn(
            child_uuid, {item.uuid for item in right.logic.teams()},
        )
    def test_deleting_parent_promotes_child_instead_of_deleting_it(self):
        runtime = self.runtime(9463)
        parent_uuid = runtime.logic.create_team("Cooperative").value
        child_uuid = runtime.logic.create_subteam(
            parent_uuid, "Finance circle",
        ).value

        result = runtime.logic.delete_team(parent_uuid)

        self.assertEqual(result.status, "ok")
        child = runtime.session.protocol.index[child_uuid]
        self.assertFalse(child.deleted)
        self.assertNotIn("parent_team_uuid", child.data)
        self.assertEqual(
            [item["uuid"] for item in runtime.logic.organization_payload()["roots"]],
            [child_uuid],
        )

    def test_deleting_a_seated_child_empties_its_seat_and_no_more(self):
        # A role is not a subteam's private property: the same one may
        # seat several actors. Deleting the team in it must remove its
        # answer, not the role everybody else is holding too.
        runtime = self.runtime(9524)
        parent_uuid = runtime.logic.create_team("Cooperative").value
        role_uuid = runtime.logic.create_role(parent_uuid, "Delegate").value
        runtime.logic.decide_role(role_uuid, "accepted")
        child_uuid = runtime.logic.create_seated_team(
            role_uuid, "Finance circle",
        ).value

        self.assertEqual(
            runtime.logic.delete_team(child_uuid).status, "ok",
        )

        parent = runtime.session.protocol.index[parent_uuid]
        role = runtime.session.protocol.index[role_uuid]
        self.assertIn(
            "Delegate",
            [item.data["name"] for item in runtime.logic.roles(parent)],
        )
        self.assertFalse(runtime.logic._team_holds_role(role, child_uuid))
        # The other holder is untouched: their answer is their own record,
        # and the departing child never had anything to do with it.
        holders = {
            holder["actor_uuid"]: holder
            for holder in runtime.logic.role_holders(parent, role)
        }
        self.assertEqual(
            holders[runtime.session.identity.uuid]["status"], "accepted",
        )
        self.assertNotIn(child_uuid, holders)

    def test_reacting_resolves_a_divergence_on_a_clause(self):
        # Without reactions a team can reach a state it cannot leave:
        # two sides edit the same clause, both see divergence, and nothing
        # either does resolves it. This is that dead end, and its exit.
        left, right = self.runtime(9410), self.runtime(9411)
        team_uuid = left.logic.create_team("Service terms").value
        section_uuid = left.logic.create_section(team_uuid, "Scope").value
        clause_uuid = left.logic.create_clause(section_uuid, "Original text.").value
        connect(left, right, team_uuid)

        # Both sides rewrite the same clause without seeing the other's edit.
        left.logic.update_clause(clause_uuid, "Left text.")
        right.logic.update_clause(clause_uuid, "Right text.")
        sync(left, right)
        grouped = right.logic.document_payload(team_uuid)["transition_by_node"]
        self.assertEqual(grouped[clause_uuid]["type"], "divergence")
        self.assertIn(grouped[clause_uuid]["reaction"], {"adopt", "rollback"})

        # Reacting with adopt takes the peer's revision and leaves the
        # divergence behind - the exit that did not exist before.
        self.assertEqual(
            right.logic.accept_peer_node(left.peer_addr, clause_uuid).status, "ok",
        )
        self.assertEqual(
            right.session.protocol.index[clause_uuid].data["text"], "Left text.",
        )
        settled = right.logic.document_payload(team_uuid)["transition_by_node"]
        self.assertNotEqual(settled.get(clause_uuid, {}).get("type"), "divergence")

    def test_reacting_refuses_a_node_outside_this_application(self):
        runtime = self.runtime(9412)
        runtime.logic.create_team("Service terms")
        foreign = runtime.session.create_child(
            runtime.session.protocol.root.uuid, {"type": "not_an_team"}, {},
        ).value

        result = runtime.logic.accept_peer_node("http://peer", foreign.uuid)
        self.assertEqual(result.status, "error")
        self.assertEqual(
            runtime.logic.rollback_peer_node("http://peer", foreign.uuid).status,
            "error",
        )

    def test_transition_priority_comes_from_session_not_per_application(self):
        # Applications grouping transition events per node had each copied
        # Session's ranking, and the copies drifted, so the same conflict
        # could surface as divergence in one application and something milder
        # in another.
        #
        # Only this application is checked here. Core ships these tests, and a
        # Core test that imports S-Initiative cannot run for anyone who installed
        # Core alone - which is the dependency direction the architecture
        # forbids in the first place. The cross-application comparison lives
        # in test_cross_application.py, which stays in the working repository
        # where every application is present.
        from s_team import logic as team_logic

        source = Path(team_logic.__file__).read_text(encoding="utf-8")
        self.assertRegex(
            source, r"Session\.(TRANSITION_PRIORITY|STAGE_PRIORITY|transition_rank)",
        )
        self.assertNotIn('"divergence": 5', source)
        self.assertNotIn('"divergence": 6', source)

        priority = Session.TRANSITION_PRIORITY
        self.assertGreater(priority["divergence"], priority["peer_made_changes"])
        self.assertGreater(
            priority["peer_made_changes"], priority["local_made_changes"],
        )
        self.assertEqual(priority["in_agreement"], 0)
        self.assertGreater(
            Session.STAGE_PRIORITY["awaiting_me"],
            Session.STAGE_PRIORITY["in_flight"],
        )

    def test_titles_and_text_stay_editable_after_creation(self):
        runtime = self.runtime(9403)
        team_uuid = runtime.logic.create_team("Draft").value
        section_uuid = runtime.logic.create_section(team_uuid, "Scpoe").value
        clause_uuid = runtime.logic.create_clause(section_uuid, "Frist draft.").value

        self.assertEqual(
            runtime.logic.rename_team(team_uuid, "Service terms").status, "ok",
        )
        self.assertEqual(
            runtime.logic.rename_section(section_uuid, "Scope").status, "ok",
        )
        self.assertEqual(
            runtime.logic.update_clause(clause_uuid, "First draft.").status, "ok",
        )

        payload = runtime.logic.document_payload()
        section = self.serialized(payload["team"], "team_section")[0]
        self.assertEqual(payload["team"]["data"]["title"], "Service terms")
        self.assertEqual(section["data"]["title"], "Scope")
        self.assertEqual(
            self.serialized(section, "team_clause")[0]["data"]["text"],
            "First draft.",
        )

    def test_an_observation_belongs_to_the_decision_it_sits_under(self):
        """Which decision it observes is where it is, not a uuid it carries."""
        runtime = self.runtime(9441)
        team_uuid = runtime.logic.create_team("Cooperative").value
        recorded = runtime.logic.record_trustee_action(
            team_uuid, "identity", "membership",
            value="The membership is opened",
            signals="Capacity is available",
        )
        self.assertEqual(recorded.status, "ok", recorded.reason)
        action_uuid = recorded.value.uuid

        first = runtime.logic.append_trustee_reality(
            team_uuid, action_uuid, "Two people applied.",
        )
        second = runtime.logic.append_trustee_reality(
            team_uuid, action_uuid, "One of them withdrew.",
        )

        self.assertEqual(first.status, "ok", first.reason)
        self.assertEqual(second.status, "ok", second.reason)
        index = runtime.session.protocol.index
        self.assertEqual(index[first.value.uuid].parent_uuid, action_uuid)
        self.assertEqual(index[second.value.uuid].parent_uuid, action_uuid)
        # Divergent observations are both kept: a set union, not a list one
        # side of which would have to win.
        team = index[team_uuid]
        realities = runtime.logic.governance_records(
            team, "team_trustee_reality",
        )
        self.assertEqual(
            [node.data["reality"] for node in realities],
            ["Two people applied.", "One of them withdrew."],
        )
        self.assertNotIn("action_uuid", realities[0].data)

    def test_actors_are_read_from_the_records_not_kept_as_a_list(self):
        """An Actor list would be a third copy of what two chains already say."""
        runtime = self.runtime(9439)
        team_uuid = runtime.logic.create_team("Cooperative").value
        runtime.logic.rename_agreement(team_uuid, "Terms")
        runtime.logic.set_agreement_version(team_uuid, "1")
        runtime.logic.create_section(team_uuid, "Scope")
        role_uuid = runtime.logic.create_role(team_uuid, "Treasurer").value
        runtime.logic.decide_role(role_uuid, "accepted")
        runtime.logic.accept_agreement(team_uuid, "I accept.")
        team = runtime.session.protocol.index[team_uuid]
        mine = runtime.session.identity.uuid

        actors = runtime.logic.actors(team)

        self.assertEqual([actor["uuid"] for actor in actors], [mine])
        self.assertEqual(actors[0]["kind"], "person")
        self.assertEqual(actors[0]["membership"], "member")
        self.assertTrue(actors[0]["is_self"])

    def test_a_seated_team_is_an_actor_like_a_person(self):
        runtime = self.runtime(9440)
        parent_uuid = runtime.logic.create_team("Cooperative").value
        role_uuid = runtime.logic.create_role(parent_uuid, "Finance").value
        child_uuid = runtime.logic.create_subteam(
            parent_uuid, "Finance circle",
        ).value
        runtime.logic.seat_team(role_uuid, child_uuid)
        parent = runtime.session.protocol.index[parent_uuid]

        actors = runtime.logic.actors(parent)
        teams = [actor for actor in actors if actor["kind"] == "team"]

        self.assertEqual([actor["uuid"] for actor in teams], [child_uuid])
        self.assertEqual(teams[0]["name"], "Finance circle")

    def test_an_acceptance_names_the_text_it_accepted(self):
        """A badge that named only a version label would not be falsifiable."""
        runtime = self.runtime(9436)
        team_uuid = runtime.logic.create_team("Cooperative").value
        runtime.logic.rename_agreement(team_uuid, "Terms")
        runtime.logic.set_agreement_version(team_uuid, "1")
        runtime.logic.create_section(team_uuid, "Scope")
        team = runtime.session.protocol.index[team_uuid]
        mine = runtime.session.identity.uuid

        self.assertEqual(
            runtime.logic.acceptance_projection(team, mine)["state"], "absent",
        )
        self.assertEqual(
            runtime.logic.accept_agreement(team_uuid, "I accept.").status, "ok",
        )

        team = runtime.session.protocol.index[team_uuid]
        accepted = runtime.logic.acceptance_projection(team, mine)
        self.assertEqual(accepted["state"], "current")
        self.assertEqual(
            accepted["agreement_uuid"],
            runtime.logic.agreement(team, create=False).uuid,
        )
        self.assertEqual(
            accepted["reference_hash"], runtime.logic.team_reference_hash(team),
        )

        # Editing the text it named leaves the acceptance behind, which is
        # the whole point of naming the text rather than a version label.
        runtime.logic.create_section(team_uuid, "Scope two")
        team = runtime.session.protocol.index[team_uuid]
        self.assertEqual(
            runtime.logic.acceptance_projection(team, mine)["state"], "outdated",
        )

    def test_re_accepting_continues_the_chain_rather_than_replacing_it(self):
        runtime = self.runtime(9437)
        team_uuid = runtime.logic.create_team("Cooperative").value
        runtime.logic.rename_agreement(team_uuid, "Terms")
        runtime.logic.set_agreement_version(team_uuid, "1")
        runtime.logic.create_section(team_uuid, "Scope")
        mine = runtime.session.identity.uuid
        runtime.logic.accept_agreement(team_uuid, "First.")
        runtime.logic.create_section(team_uuid, "Scope two")

        self.assertEqual(
            runtime.logic.accept_agreement(team_uuid, "Second.").status, "ok",
        )

        team = runtime.session.protocol.index[team_uuid]
        records = runtime.logic.governance_records(team, "team_acceptance")
        self.assertEqual(len(records), 2)
        head = runtime.logic.acceptance_projection(team, mine)
        self.assertEqual(head["text"], "Second.")
        self.assertEqual(head["state"], "current")
        roots = [
            record for record in records
            if not record.data.get("previous_acceptance_uuid")
        ]
        self.assertEqual(len(roots), 1)

    def test_an_acceptance_of_another_teams_agreement_is_refused(self):
        runtime = self.runtime(9438)
        team_uuid = runtime.logic.create_team("Ours").value
        other_uuid = runtime.logic.create_team("Theirs").value
        for uuid in (team_uuid, other_uuid):
            runtime.logic.rename_agreement(uuid, "Terms")
            runtime.logic.set_agreement_version(uuid, "1")
            runtime.logic.create_section(uuid, "Scope")
        team = runtime.session.protocol.index[team_uuid]
        other = runtime.session.protocol.index[other_uuid]

        assessment = runtime.logic.assess_governance_record(
            team,
            ProtocolNode(
                {
                    "type": "team_acceptance",
                    "actor_uuid": runtime.session.identity.uuid,
                    "agreement_uuid": runtime.logic.agreement(
                        other, create=False,
                    ).uuid,
                    "reference_hash": runtime.logic.team_reference_hash(team),
                    "text": "",
                    "previous_acceptance_uuid": "",
                    "accepted_at": "2026-08-16T10:00:00Z",
                },
                parent_uuid=runtime.logic._container(team, "acceptances").uuid,
                revision_origin=runtime.session.identity.data["identity_key"],
            ),
            verification="valid",
        )

        self.assertEqual(assessment["status"], "invalid")
        self.assertIn("this Team's Agreement", assessment["reason"])

    def test_the_agreement_is_named_apart_from_the_team(self):
        # One field used to serve both, so renaming the body silently
        # retitled the document its members had accepted.
        runtime = self.runtime(9433)
        team_uuid = runtime.logic.create_team("Finance").value

        payload = runtime.logic.document_payload()
        self.assertEqual(payload["team"]["data"]["title"], "Finance")
        # Unnamed rather than defaulted: an agreement nobody has named is a
        # real state, and the page shows a prompt in its place.
        self.assertNotIn("agreement_title", payload["team"]["data"])

        self.assertEqual(
            runtime.logic.rename_agreement(team_uuid, "Terms of trade").status,
            "ok",
        )
        team = runtime.session.protocol.index[team_uuid]
        self.assertEqual(
            runtime.logic.agreement_projection(team)["state"], "invalid",
        )
        self.assertEqual(
            runtime.logic.set_agreement_version(team_uuid, "2026.1").status,
            "ok",
        )
        self.assertEqual(
            runtime.logic.rename_team(team_uuid, "Treasury").status, "ok",
        )
        payload = runtime.logic.document_payload()
        self.assertEqual(payload["team"]["data"]["title"], "Treasury")
        agreement = self.serialized(payload["team"], "team_agreement")[0]
        self.assertEqual(agreement["data"]["name"], "Terms of trade")
        self.assertEqual(agreement["data"]["version"], "2026.1")
        team = runtime.session.protocol.index[team_uuid]
        self.assertEqual(
            runtime.logic.agreement_projection(team)["state"],
            "consolidated",
        )

        self.assertEqual(
            runtime.logic.rename_agreement(team_uuid, "   ").status, "error",
        )

    def test_a_copy_takes_a_new_team_name_and_keeps_the_agreement_s(self):
        # A template is a new body holding the same agreement, which is what
        # separate names are for.
        runtime = self.runtime(9434)
        team_uuid = runtime.logic.create_team("Finance").value
        runtime.logic.rename_agreement(team_uuid, "Terms of trade")
        runtime.logic.set_agreement_version(team_uuid, "2026.1")

        copy_uuid = runtime.logic.clone_team(team_uuid, "Finance copy").value
        payload = runtime.logic.document_payload(copy_uuid)
        self.assertEqual(payload["team"]["data"]["title"], "Finance copy")
        agreement = self.serialized(payload["team"], "team_agreement")[0]
        self.assertEqual(agreement["data"]["name"], "Terms of trade")
        self.assertEqual(agreement["data"]["version"], "2026.1")

    def test_renaming_rejects_blank_titles_and_unknown_nodes(self):
        runtime = self.runtime(9404)
        team_uuid = runtime.logic.create_team("Draft").value
        section_uuid = runtime.logic.create_section(team_uuid, "Scope").value

        self.assertEqual(runtime.logic.rename_team(team_uuid, "  ").status, "error")
        self.assertEqual(runtime.logic.rename_section(section_uuid, "").status, "error")
        self.assertEqual(runtime.logic.rename_section("missing", "Scope").status, "error")
        # A section uuid is not a team uuid; the type guard must hold.
        self.assertEqual(runtime.logic.rename_team(section_uuid, "Nope").status, "error")

    def test_sections_and_clauses_can_be_reordered(self):
        runtime = self.runtime(9414)
        team_uuid = runtime.logic.create_team("Terms").value
        first = runtime.logic.create_section(team_uuid, "First").value
        second = runtime.logic.create_section(team_uuid, "Second").value
        third = runtime.logic.create_section(team_uuid, "Third").value

        def section_titles():
            payload = runtime.logic.document_payload(team_uuid)
            live = [
                s for s in self.serialized(payload["team"], "team_section")
                if not s["deleted"]
            ]
            ordered = sorted(live, key=lambda s: s["data"].get("order", 0))
            return [s["data"]["title"] for s in ordered]

        self.assertEqual(section_titles(), ["First", "Second", "Third"])
        # Move "Third" to the front.
        self.assertEqual(runtime.logic.move_section(third, 0).status, "ok")
        self.assertEqual(section_titles(), ["Third", "First", "Second"])
        # Move "Third" back down one.
        self.assertEqual(runtime.logic.move_section(third, 1).status, "ok")
        self.assertEqual(section_titles(), ["First", "Third", "Second"])

        a = runtime.logic.create_clause(first, "Clause A").value
        b = runtime.logic.create_clause(first, "Clause B").value

        def clause_texts():
            payload = runtime.logic.document_payload(team_uuid)
            section = next(
                s for s in self.serialized(payload["team"], "team_section")
                if s["uuid"] == first
            )
            live = [
                c for c in self.serialized(section, "team_clause")
                if not c["deleted"]
            ]
            ordered = sorted(live, key=lambda c: c["data"].get("order", 0))
            return [c["data"]["text"] for c in ordered]

        self.assertEqual(clause_texts(), ["Clause A", "Clause B"])
        self.assertEqual(runtime.logic.move_clause(b, 0).status, "ok")
        self.assertEqual(clause_texts(), ["Clause B", "Clause A"])

    def test_agenda_items_can_be_reordered(self):
        runtime = self.runtime(9416)
        team_uuid = runtime.logic.create_team("Terms").value
        first = runtime.logic.create_agenda_item(
            team_uuid, "First topic",
        ).value
        second = runtime.logic.create_agenda_item(
            team_uuid, "Second topic",
        ).value

        result = runtime.logic.move_agenda_item(second.uuid, 0)

        self.assertEqual(result.status, "ok")
        self.assertEqual(
            [item.uuid for item in runtime.session.agenda_items(team_uuid)],
            [second.uuid, first.uuid],
        )

    def test_an_agenda_item_author_can_update_its_text(self):
        runtime = self.runtime(9417)
        team_uuid = runtime.logic.create_team("Terms").value
        item = runtime.logic.create_agenda_item(
            team_uuid, "First wording",
        ).value

        result = runtime.logic.update_agenda_item(item.uuid, "Revised wording")

        self.assertEqual(result.status, "ok")
        self.assertEqual(
            runtime.session.protocol.index[item.uuid].data["text"],
            "Revised wording",
        )

    def test_move_rejects_wrong_node_types(self):
        runtime = self.runtime(9415)
        team_uuid = runtime.logic.create_team("Terms").value
        section_uuid = runtime.logic.create_section(team_uuid, "S").value
        clause_uuid = runtime.logic.create_clause(section_uuid, "C").value
        # A clause is not a section and vice versa; the guards must hold.
        self.assertEqual(runtime.logic.move_section(clause_uuid, 0).status, "error")
        self.assertEqual(runtime.logic.move_clause(section_uuid, 0).status, "error")

    def test_deleting_a_section_removes_its_clauses(self):
        runtime = self.runtime(9405)
        team_uuid = runtime.logic.create_team("Draft").value
        kept_uuid = runtime.logic.create_section(team_uuid, "Kept").value
        removed_uuid = runtime.logic.create_section(team_uuid, "Removed").value
        clause_uuid = runtime.logic.create_clause(removed_uuid, "Goes away.").value
        runtime.logic.create_clause(kept_uuid, "Stays.")

        self.assertEqual(runtime.logic.delete_section(removed_uuid).status, "ok")

        payload = runtime.logic.document_payload()
        sections = self.serialized(payload["team"], "team_section")
        live = [
            item for item in sections
            if not item["deleted"]
        ]
        self.assertEqual([item["uuid"] for item in live], [kept_uuid])
        # Deleting a container prunes its descendants out of the index rather
        # than tombstoning each one, so the clause is gone, not flagged.
        self.assertNotIn(clause_uuid, runtime.session.protocol.index)

    def test_deleting_a_single_clause_leaves_its_siblings(self):
        runtime = self.runtime(9406)
        team_uuid = runtime.logic.create_team("Draft").value
        section_uuid = runtime.logic.create_section(team_uuid, "Scope").value
        first_uuid = runtime.logic.create_clause(section_uuid, "First.").value
        second_uuid = runtime.logic.create_clause(section_uuid, "Second.").value

        self.assertEqual(runtime.logic.delete_clause(first_uuid).status, "ok")

        payload = runtime.logic.document_payload()
        section = self.serialized(payload["team"], "team_section")[0]
        live = [
            item["uuid"] for item in self.serialized(section, "team_clause")
            if not item["deleted"]
        ]
        self.assertEqual(live, [second_uuid])

    def test_document_payload_does_not_expose_channel_management(self):
        runtime = self.runtime(9402)
        runtime.logic.create_team("Service terms")

        payload = runtime.logic.document_payload()
        self.assertNotIn("channel_targets", payload)
        self.assertNotIn("channel_target_id", payload)

    def test_team_has_no_automatic_adoption_surface(self):
        runtime = self.runtime(9412)
        runtime.logic.create_team("Manual decisions")

        payload = runtime.logic.document_payload()
        self.assertNotIn("auto_adopt_mode", payload)
        self.assertNotIn("auto_adopt_modes", payload)
        paths = {route.path for route in app_server.build_app(runtime).routes}
        self.assertNotIn("/api/team/auto_adopt", paths)

    def test_invitation_and_transition_visibility(self):
        left = self.runtime(9402)
        right = self.runtime(9403)
        team_uuid = left.logic.create_team("Shared team").value
        section_uuid = left.logic.create_section(team_uuid, "Scope").value
        clause_uuid = left.logic.create_clause(section_uuid, "Initial text").value

        accepted = connect(left, right, team_uuid)

        self.assertEqual(accepted["status"], "ok")
        self.assertIn(team_uuid, [item.uuid for item in right.logic.teams()])
        left.logic.update_clause(clause_uuid, "Proposed replacement")
        sync(left, right)
        events = right.logic.transition_events(team_uuid)
        clause_events = [event for event in events if event["node_uuid"] == clause_uuid]
        self.assertEqual(len(clause_events), 1)
        self.assertIn(clause_events[0]["type"], {"peer_made_changes", "in_transition"})

    def test_three_level_new_structure_adopts_in_one_pass_child_first(self):
        left = self.runtime(9404)
        right = self.runtime(9405)
        team_uuid = left.logic.create_team("Nested team").value
        accepted = connect(left, right, team_uuid)
        self.assertEqual(accepted["status"], "ok")

        section_uuid = left.logic.create_section(team_uuid, "New section").value
        clause_uuid = left.logic.create_clause(section_uuid, "Nested clause").value
        sync(left, right)
        proposals = {
            entry["node"]["uuid"]: entry
            for entry in right.logic.document_payload(
                team_uuid,
            )["proposed_nodes"]
        }
        self.assertIn(section_uuid, proposals)
        self.assertIn(clause_uuid, proposals)
        self.assertEqual(
            proposals[section_uuid]["node"]["data"]["title"], "New section",
        )
        events = right.session.analyze_peer_transitions(
            left.peer_addr, team_uuid,
        )
        incoming = [
            event for event in events
            if event["node_uuid"] in {section_uuid, clause_uuid}
        ]
        child_first = sorted(
            incoming, key=lambda event: event["node_uuid"] != clause_uuid,
        )

        with patch.object(
            right.session, "analyze_peer_transitions", return_value=child_first,
        ):
            adopted = right.logic.adopt_peer_changes(
                left.peer_addr, team_uuid,
            )

        self.assertEqual(adopted.status, "ok")
        self.assertTrue(adopted.value)
        self.assertIn(section_uuid, right.session.protocol.index)
        self.assertIn(clause_uuid, right.session.protocol.index)
        self.assertEqual(
            right.session.protocol.index[clause_uuid].parent_uuid, section_uuid,
        )

    def test_mailbox_invitation_mounts_team_without_core_special_case(self):
        with tempfile.TemporaryDirectory() as relay_root, \
                tempfile.TemporaryDirectory() as state_dir:
            session_a = Session("addr-a")
            logic_a = TeamLogic(session_a)
            session_a.register_application(logic_a.application_registration())
            team_uuid = logic_a.create_team("Relayed team").value
            section_uuid = logic_a.create_section(team_uuid, "Scope").value
            clause_uuid = logic_a.create_clause(section_uuid, "Mailbox clause").value
            relay_a = RelayLogic(
                session_a, self.relay_config(relay_root, "A", state_dir),
            )
            relay_a.mark_topics_shared([team_uuid])
            relay_a.publish_due_topics()
            descriptor = relay_a.channel_descriptor()

            session_b = Session("addr-b")
            logic_b = TeamLogic(session_b)
            session_b.register_application(logic_b.application_registration())
            relay_b = RelayLogic(
                session_b,
                {"relay_state_file": str(Path(state_dir) / "state-B.json")},
            )
            self.assertTrue(relay_b.adopt_storage_from_descriptor(descriptor))
            relay_b.mark_topics_desired([team_uuid])

            applied = relay_b.poll_and_apply()

            self.assertIn((team_uuid, "A"), applied)
            self.assertIn(team_uuid, [item.uuid for item in logic_b.teams()])
            self.assertIn(clause_uuid, session_b.protocol.index)

            updated = logic_a.update_clause(clause_uuid, "Updated through mailbox")
            self.assertEqual(updated.status, "ok")
            relay_a.publish_due_topics()
            self.assertIn((team_uuid, "A"), relay_b.poll_and_apply())
            events = logic_b.transition_events(team_uuid)
            self.assertTrue(any(
                event["node_uuid"] == clause_uuid
                and event["type"] != "in_agreement"
                for event in events
            ))
            adopted = logic_b.adopt_peer_changes("relay:A", team_uuid)
            self.assertTrue(adopted.value)
            self.assertEqual(
                session_b.protocol.index[clause_uuid].data["text"],
                "Updated through mailbox",
            )

    def test_delete_team_removes_the_whole_document(self):
        runtime = self.runtime(9451)
        logic: TeamLogic = runtime.logic
        team_uuid = logic.create_team("Working team").value
        section_uuid = logic.create_section(team_uuid, "Scope").value
        clause_uuid = logic.create_clause(section_uuid, "One clause.").value

        result = logic.delete_team(team_uuid)

        self.assertEqual(result.status, "ok")
        self.assertEqual(logic.teams(), [])
        for node_uuid in (team_uuid, section_uuid, clause_uuid):
            node = runtime.session.protocol.index.get(node_uuid)
            self.assertTrue(node is None or node.deleted, node_uuid)

    def test_deleting_the_last_team_leaves_none_selected(self):
        runtime = self.runtime(9452)
        logic: TeamLogic = runtime.logic
        team_uuid = logic.create_team("Working team").value

        logic.delete_team(team_uuid)

        self.assertIsNone(logic.document_payload()["team"])

    def test_delete_team_rejects_a_node_that_is_not_one(self):
        runtime = self.runtime(9453)
        logic: TeamLogic = runtime.logic
        team_uuid = logic.create_team("Working team").value
        section_uuid = logic.create_section(team_uuid, "Scope").value

        result = logic.delete_team(section_uuid)

        self.assertEqual(result.status, "error")
        self.assertEqual(len(logic.teams()), 1)

    def test_sections_and_clauses_are_returned_in_display_order(self):
        # S-Cockpit reads a team through these, so the order
        # they return is the order the document is read in.
        runtime = self.runtime(9454)
        logic: TeamLogic = runtime.logic
        team_uuid = logic.create_team("Working team").value
        first = logic.create_section(team_uuid, "First").value
        second = logic.create_section(team_uuid, "Second").value
        logic.create_clause(first, "Clause one.")
        logic.create_clause(first, "Clause two.")
        logic.move_section(second, 0)

        team = runtime.session.protocol.index[team_uuid]
        sections = logic.sections(team)

        self.assertEqual(
            [node.data["title"] for node in sections], ["Second", "First"],
        )
        self.assertEqual(
            [node.data["text"] for node in logic.clauses(sections[1])],
            ["Clause one.", "Clause two."],
        )

    def test_a_new_team_starts_with_its_creator_as_its_only_member(self):
        # A team used to ship with a system Member role its creator was
        # offered and accepted, because being on a team meant holding a role
        # on it. Membership is its own record now, so a new team has one
        # member and no roles at all: the first role is content somebody
        # writes, not a fixture.
        runtime = self.runtime(9497)
        team_uuid = runtime.logic.create_team("Charter").value
        team = runtime.session.protocol.index[team_uuid]
        mine = runtime.session.identity.uuid

        self.assertEqual(runtime.logic.roles(team), [])
        self.assertEqual(runtime.logic.current_member_uuids(team), [mine])
        founding = runtime.logic.membership_records(team, mine)
        self.assertEqual(len(founding), 1)
        self.assertEqual(founding[0].data["cause"], "genesis")
        self.assertEqual(founding[0].data["state"], "member")
        self.assertEqual(founding[0].data["actor_uuid"], mine)
        # And there can only ever be one founding: everybody after them is
        # admitted by somebody already here.
        self.assertEqual(
            runtime.logic.append_governance_record(team_uuid, {
                **founding[0].data,
                "acted_at": "2026-08-07T00:00:00Z",
            }).status,
            "error",
        )

    def test_ending_a_membership_ends_what_that_person_held(self):
        # Roles are work a *member* holds, so they are not taken away one
        # by one. Being on the team is the thing Identity decides, and the
        # holdings follow it - and come back if the person is readmitted.
        left, right = self.runtime(9709), self.runtime(9710)
        team_uuid = left.logic.create_team("Charter").value
        role_uuid = left.logic.create_role(team_uuid, "Treasurer").value
        connect(left, right, team_uuid)
        self.admit(left, right, team_uuid)
        right.logic.decide_role(role_uuid, "accepted")
        sync(left, right)
        theirs = right.session.identity.uuid

        def on_the_team():
            return left.logic.actor_uuids(
                left.session.protocol.index[team_uuid],
            )

        self.assertIn(theirs, on_the_team())

        ended = left.logic.end_membership(
            team_uuid, theirs, signals="they moved on",
        )
        sync(left, right)

        self.assertEqual(ended.status, "ok")
        self.assertNotIn(theirs, on_the_team())
        # Read from their own client too, which is the one place it must
        # not go on saying they are here.
        self.assertFalse(right.logic._is_current_member(
            right.session.protocol.index[team_uuid], theirs,
        ))
        # Their own answer about the role is theirs and is untouched.
        self.assertTrue(right.logic._own_role_decision(
            right.session.protocol.index[role_uuid],
        ))

    def test_resigning_removes_only_the_participants_own_record(self):
        runtime = self.runtime(9500)
        team_uuid = runtime.logic.create_team("Charter").value
        self.a_role(runtime, team_uuid)
        team = runtime.session.protocol.index[team_uuid]
        role = runtime.logic.roles(team)[0]

        self.assertEqual(runtime.logic.resign_role(role.uuid).status, "ok")
        role = runtime.session.protocol.index[role.uuid]
        self.assertIsNone(runtime.logic._own_role_decision(role))
        # The role is simply unheld, and the membership is untouched.
        self.assertEqual(runtime.logic.role_holders(team, role), [])
        self.assertTrue(runtime.logic._is_current_member(
            runtime.session.protocol.index[team_uuid],
            runtime.session.identity.uuid,
        ))

    def test_a_member_takes_a_role_with_nobody_offering_it(self):
        # Identity decides membership, not what a member does once they are
        # here. Taking a role used to need an offer from the Identity
        # holder, so a member could describe work they were doing and then
        # wait to be permitted to do it.
        left, right = self.runtime(9501), self.runtime(9502)
        team_uuid = left.logic.create_team("Charter").value
        role_uuid = left.logic.create_role(team_uuid, "Treasurer").value
        connect(left, right, team_uuid)
        self.admit(left, right, team_uuid)

        taken = right.logic.decide_role(role_uuid, "accepted")

        self.assertEqual(taken.status, "ok")
        role = right.session.protocol.index[role_uuid]
        team = right.session.protocol.index[team_uuid]
        self.assertEqual(
            [item["status"] for item in right.logic.role_holders(team, role)],
            ["accepted"],
        )
        sync(left, right)
        self.assertIn(taken.value.uuid, left.session.protocol.index)
        self.assertEqual(
            left.logic.document_payload(team_uuid)["transition_by_node"][
                taken.value.uuid
            ]["stage"],
            "settled",
        )
        self.assertEqual(
            [
                item["status"] for item in left.logic.role_holders(
                    left.session.protocol.index[team_uuid],
                    left.session.protocol.index[role_uuid],
                )
                if not item["is_self"]
            ],
            ["accepted"],
        )

    def test_somebody_who_is_not_a_member_cannot_take_a_role(self):
        # The other half of the same rule: roles are work members pick up,
        # so being on the team is what taking one turns on. Being able to
        # see the topic is not being on the team.
        left, right = self.runtime(9509), self.runtime(9510)
        team_uuid = left.logic.create_team("Charter").value
        role_uuid = left.logic.create_role(team_uuid, "Participant").value
        connect(left, right, team_uuid)
        right.logic.accept_team_invitation(
            right.session.protocol.index[team_uuid],
        )
        sync(left, right)

        refused = right.logic.decide_role(role_uuid, "accepted")

        self.assertEqual(refused.status, "error")
        self.assertIn("Member", refused.reason)
        # Admitted, the same call goes through.
        self.admit(left, right, team_uuid)
        self.assertEqual(
            right.logic.decide_role(role_uuid, "accepted").status, "ok",
        )

    def test_a_role_acceptance_covers_the_document_and_that_role_only(self):
        runtime = self.runtime(9506)
        team_uuid = runtime.logic.create_team("Charter").value
        treasurer_uuid = runtime.logic.create_role(
            team_uuid, "Treasurer",
        ).value
        secretary_uuid = runtime.logic.create_role(
            team_uuid, "Secretary",
        ).value
        runtime.logic.decide_role(treasurer_uuid, "accepted")

        def status():
            team = runtime.session.protocol.index[team_uuid]
            role = runtime.session.protocol.index[treasurer_uuid]
            return runtime.logic.role_holders(team, role)[0]["status"]

        self.assertEqual(status(), "accepted")
        # Somebody else's role is not this participant's business.
        runtime.logic.create_role_item(
            secretary_uuid, "accountability", "Take minutes",
        )
        runtime.logic.rename_role(secretary_uuid, "Clerk")
        self.assertEqual(status(), "accepted")
        # Their own role is.
        runtime.logic.create_role_item(
            treasurer_uuid, "accountability", "Monthly reconciliation",
        )
        self.assertEqual(status(), "outdated")
        runtime.logic.decide_role(treasurer_uuid, "accepted")
        self.assertEqual(status(), "accepted")
        # So is the document everybody is agreeing to.
        runtime.logic.create_section(team_uuid, "Terms")
        self.assertEqual(status(), "outdated")

    def test_a_holder_is_only_accepted_once_seen_from_their_own_replica(self):
        left, right = self.runtime(9507), self.runtime(9508)
        team_uuid = left.logic.create_team("Charter").value
        team = left.session.protocol.index[team_uuid]
        role_uuid = left.logic.create_role(team_uuid, "Treasurer").value
        connect(left, right, team_uuid)
        self.admit(left, right, team_uuid)
        sync(left, right)

        def status_from_left():
            current_team = left.session.protocol.index[team_uuid]
            role = left.session.protocol.index[role_uuid]
            return next(
                (
                    holder["status"]
                    for holder in left.logic.role_holders(current_team, role)
                    if not holder["is_self"]
                ),
                None,
            )

        # Nobody has said anything, so there is nobody on the line.
        self.assertIsNone(status_from_left())
        right.logic.decide_role(role_uuid, "accepted")
        sync(left, right)
        self.assertEqual(status_from_left(), "accepted")
        right.logic.decide_role(role_uuid, "refused")
        sync(left, right)
        self.assertEqual(status_from_left(), "refused")

    def two_parents(self, runtime, ports):
        """A team seated in two others, Alpha first."""
        alpha = runtime.logic.create_team("Alpha").value
        beta = runtime.logic.create_team("Beta").value
        circle = runtime.logic.create_subteam(alpha, "Circle").value
        seat = runtime.logic.create_role(beta, "Delegate").value
        self.assertEqual(
            runtime.logic.seat_team(seat, circle).status, "ok",
        )
        return alpha, beta, circle

    def test_every_parent_is_a_commitment_not_a_spare_route(self):
        # A second parent is a second commitment. A body sits inside each of
        # the teams above it, so taking part in it is taking part in all of
        # them - and losing one is losing the body, however sound the other
        # is. Reading them as alternative routes let somebody keep working
        # in a team through a parent they were still in, inside a parent
        # they had left.
        runtime = self.runtime(9514)
        alpha, beta, circle = self.two_parents(runtime, None)

        def writable():
            return runtime.logic.interaction_payload(
                runtime.session.protocol.index[circle],
            )["allowed"]

        self.assertTrue(writable())
        self.leave(runtime, alpha)
        self.assertFalse(writable())
        # Still shut with the other parent intact: Beta was never the reason
        # it was open.
        self.leave(runtime, beta)
        self.assertFalse(writable())
        # Both have to come back, because both were given up.
        self.rejoin(runtime, beta)
        self.assertFalse(writable())
        self.rejoin(runtime, alpha)
        self.assertTrue(writable())

    def test_the_roster_does_not_call_somebody_accepted_who_is_out(self):
        # Invalidity above is derived, and was derived only for whoever was
        # reading. Everybody else went on being shown as accepted here, so
        # a team's own member list stated something untrue about them.
        left, right = self.runtime(9707), self.runtime(9708)
        parent = left.logic.create_team("Cooperative").value
        child = left.logic.create_subteam(parent, "Operations").value
        roles = {
            parent: left.logic.create_role(parent, "Participant").value,
            child: left.logic.create_role(child, "Participant").value,
        }

        for topic in (parent, child):
            connect(left, right, topic)
            self.admit(left, right, topic)
            right.logic.decide_role(roles[topic], "accepted")
            sync(left, right)

        def theirs(team_uuid):
            team = left.session.protocol.index[team_uuid]
            role = left.session.protocol.index[roles[team_uuid]]
            return next(
                (
                    holder for holder in left.logic.role_holders(team, role)
                    if not holder["is_self"]
                ),
                None,
            )

        self.assertEqual(theirs(child)["status"], "accepted")
        self.assertFalse(theirs(child)["outside_parent"])

        # They leave the parent. Their answer in the child is untouched -
        # nothing is written into it - but they are out of it. Leaving is
        # what does this now: stepping out of a role above is stepping out
        # of some work, not out of the team.
        right.logic.leave_team(parent)
        sync(left, right)

        # In the parent they hold nothing at all: a role is work a *member*
        # holds, so leaving takes the holding with it rather than leaving an
        # answer standing beside a membership that is gone.
        self.assertIsNone(theirs(parent))
        # In the child their answer stands, and it is their standing above
        # that does not - which is the whole of what outside_parent says.
        self.assertTrue(theirs(child)["outside_parent"])
        # And both reverse themselves when they take a membership up again.
        self.admit(left, right, parent)
        self.assertFalse(theirs(child)["outside_parent"])
        self.assertEqual(theirs(parent)["status"], "accepted")

    def test_a_team_cannot_take_a_seat_its_members_are_not_party_to(self):
        # Being on a team below is being on the team above, so a seat
        # commits everybody already on this team to the parent. Accepting
        # one on their behalf would carry them into a team they never
        # took a role in - and would shut the team for them, including for
        # the trustee who accepted it.
        left, right = self.runtime(9705), self.runtime(9706)
        parent = left.logic.create_team("Cooperative").value
        child = right.logic.create_team("Operations").value
        seat = left.logic.create_role(parent, "Member team").value
        participant = left.logic.create_role(parent, "Participant").value

        connect(left, right, parent)
        right.logic.accept_team_invitation(
            right.session.protocol.index[parent],
        )
        sync(left, right)

        # Right speaks for the child, but holds nothing in the parent.
        refused = right.logic.seat_team(seat, child)
        self.assertEqual(refused.status, "error")
        self.assertIn("Cooperative", refused.reason)
        self.assertTrue(
            right.logic.interaction_payload(
                right.session.protocol.index[child],
            )["allowed"],
            "refusing the seat must leave the team it protects usable",
        )

        # Being on the team above first is what makes the seat available.
        self.admit(left, right, parent)

        self.assertEqual(right.logic.seat_team(seat, child).status, "ok")
        self.assertTrue(
            right.logic.interaction_payload(
                right.session.protocol.index[child],
            )["allowed"],
        )

    def test_home_is_the_first_seat_that_works_and_falls_back(self):
        runtime = self.runtime(9515)
        alpha, beta, circle = self.two_parents(runtime, None)

        def home():
            return runtime.logic.home_parent_uuid(
                runtime.session.protocol.index[circle],
            )

        self.assertEqual(home(), alpha)
        # Home is derived, so it moves on when the first seat stops working
        # and moves back when it recovers - there is no stored home to
        # disagree with the holdings.
        self.leave(runtime, alpha)
        self.assertEqual(home(), beta)
        self.rejoin(runtime, alpha)
        self.assertEqual(home(), alpha)
        # With no seat working there is no home, and it draws as a root.
        self.leave(runtime, alpha)
        self.leave(runtime, beta)
        self.assertEqual(home(), "")

    def test_reordering_the_seats_changes_where_it_is_drawn(self):
        runtime = self.runtime(9516)
        alpha, beta, circle = self.two_parents(runtime, None)
        holdings = runtime.logic.parent_holdings(
            runtime.session.protocol.index[circle],
        )
        self.assertEqual(len(holdings), 2)

        self.assertEqual(
            runtime.logic.move_parent_holding(holdings[1].uuid, 0).status, "ok",
        )
        self.assertEqual(
            runtime.logic.home_parent_uuid(
                runtime.session.protocol.index[circle],
            ),
            beta,
        )

    def test_the_organization_is_drawn_through_home_and_names_the_rest(self):
        runtime = self.runtime(9517)
        alpha, beta, circle = self.two_parents(runtime, None)

        organization = runtime.logic.organization_payload()
        roots = {item["uuid"]: item for item in organization["roots"]}
        # Drawn once, under home, with the other seat named rather than
        # hidden - a second parent nobody can see is a trap for whoever
        # deletes the first.
        self.assertEqual(set(roots), {alpha, beta})
        self.assertEqual(
            [child["uuid"] for child in roots[alpha]["children"]], [circle],
        )
        self.assertEqual(roots[beta]["children"], [])
        drawn = roots[alpha]["children"][0]
        self.assertEqual(drawn["home_parent_uuid"], alpha)
        self.assertEqual(
            [item["uuid"] for item in drawn["other_parents"]], [beta],
        )

    def test_a_seat_that_would_close_a_loop_is_refused(self):
        # Best-effort per replica, and best effort is still worth making.
        runtime = self.runtime(9518)
        alpha = runtime.logic.create_team("Alpha").value
        circle = runtime.logic.create_subteam(alpha, "Circle").value
        inner = runtime.logic.create_subteam(circle, "Inner").value

        seat = runtime.logic.create_role(inner, "Upward").value
        looped = runtime.logic.seat_team(seat, alpha)

        self.assertEqual(looped.status, "error")
        self.assertIn("circular", looped.reason)

    def test_only_the_seated_teams_identity_holder_may_take_a_seat(self):
        left, right = self.runtime(9519), self.runtime(9520)
        alpha = left.logic.create_team("Alpha").value
        circle = left.logic.create_subteam(alpha, "Circle").value
        beta = right.logic.create_team("Beta").value
        seat = right.logic.create_role(beta, "Delegate").value

        # right holds Beta's Identity, but not Circle's, and cannot answer
        # for a body that is not theirs to speak for.
        refused = right.logic.seat_team(seat, circle)
        self.assertEqual(refused.status, "error")

    def test_a_read_never_serves_what_an_edit_has_already_changed(self):
        # Building one payload asks Session for the same identity, members and
        # hashes hundreds of times, so reads memoise. The scope is the read:
        # nothing outside one caches, or an edit would be invisible until
        # something else happened to clear it.
        runtime = self.runtime(9523)
        team_uuid = runtime.logic.create_team("Charter").value
        role_uuid = self.a_role(runtime, team_uuid, "Treasurer")

        def own_roles():
            payload = runtime.logic.document_payload(team_uuid)
            me = next(
                person for person in payload["participants"]
                if person["is_self"]
            )
            return {role["name"]: role["status"] for role in me["roles"]}

        self.assertEqual(own_roles()["Treasurer"], "accepted")
        runtime.logic.rename_agreement(team_uuid, "Team Agreement")
        runtime.logic.set_agreement_version(team_uuid, "1")
        runtime.logic.create_section(team_uuid, "Purpose")
        self.assertEqual(own_roles()["Treasurer"], "outdated")
        runtime.logic.decide_role(role_uuid, "accepted")
        self.assertEqual(own_roles()["Treasurer"], "accepted")

    def test_creator_is_a_member_and_holds_both_trusteeships_at_genesis(self):
        runtime = self.runtime(9488)
        team_uuid = runtime.logic.create_team("Charter").value
        child_uuid = runtime.logic.create_subteam(
            team_uuid, "Operations",
        ).value

        for uuid in (team_uuid, child_uuid):
            team = runtime.session.protocol.index[uuid]
            self.assertTrue(runtime.logic.holds_identity(team))
            self.assertEqual(
                runtime.logic.identity_holder(team),
                runtime.session.identity.uuid,
            )
            self.assertTrue(runtime.logic.holds_trust(team))
            self.assertEqual(
                runtime.logic.trust_holder(team),
                runtime.session.identity.uuid,
            )
            self.assertTrue(runtime.logic._is_current_member(
                team, runtime.session.identity.uuid,
            ))
        payload = runtime.logic.document_payload(team_uuid)
        self.assertEqual(payload["identity"]["state"], "held")
        self.assertTrue(payload["identity"]["is_self"])
        self.assertEqual(payload["identity"]["claims"], [])
        self.assertEqual(payload["trust"]["state"], "held")
        self.assertTrue(payload["trust"]["is_self"])
        legacy = runtime.session.create_child(team_uuid, {
            "type": "team_trustee",
            "trust": "identity",
            "holder_actor_uuid": runtime.session.identity.uuid,
        }, {})
        self.assertFalse(runtime.logic.owns_node(legacy.value.uuid))

    def test_identity_is_a_record_beside_the_document_not_inside_it(self):
        runtime = self.runtime(9489)
        team_uuid = runtime.logic.create_team("Charter").value
        self.a_role(runtime, team_uuid)

        def acceptance():
            return self.own_standing(runtime, team_uuid)

        payload = runtime.logic.document_payload(team_uuid)
        # Not document content, so it never renders as a document change.
        document_types = {
            child["data"].get("type")
            for child in payload["team"]["children"]
        }
        self.assertNotIn("team_trustee", document_types)
        self.assertNotIn("team_trustee_state", document_types)
        self.assertEqual(acceptance(), "accepted")
        other = "another-actor-uuid"
        self.assertEqual(
            runtime.logic.offer_identity(team_uuid, other).status, "error",
        )
        self.assertEqual(acceptance(), "accepted")

    def test_direct_identity_handover_and_take_are_rejected(self):
        left, right = self.runtime(9490), self.runtime(9491)
        team_uuid = left.logic.create_team("Charter").value
        connect(left, right, team_uuid)
        right.logic.accept_team_invitation(
            right.session.protocol.index[team_uuid],
        )

        team = right.session.protocol.index[team_uuid]
        self.assertFalse(right.logic.holds_identity(team))
        handed = right.logic.offer_identity(
            team_uuid, right.session.identity.uuid,
        )
        self.assertEqual(handed.status, "error")
        self.assertIn("facilitated decision", handed.reason)
        self.assertEqual(right.logic.take_identity(team_uuid).status, "error")
        self.assertFalse(right.logic.holds_identity(
            right.session.protocol.index[team_uuid],
        ))

    def test_identity_resignation_auto_adopts_as_append_only_vacancy(self):
        left, right = self.runtime(9492), self.runtime(9493)
        team_uuid = left.logic.create_team("Charter").value
        connect(left, right, team_uuid)
        right.logic.accept_team_invitation(
            right.session.protocol.index[team_uuid],
        )
        sync(left, right)

        previous_uuid = left.logic.identity_payload(
            left.session.protocol.index[team_uuid],
        )["node_uuid"]
        resigned = left.logic.resign_identity(team_uuid)
        self.assertEqual(resigned.status, "ok")
        sync(left, right)
        vacancy = right.logic.identity_payload(
            right.session.protocol.index[team_uuid],
        )
        self.assertEqual(vacancy["state"], "vacant")
        self.assertNotEqual(vacancy["node_uuid"], previous_uuid)
        self.assertIn(resigned.value.uuid, right.session.protocol.index)

    def test_rejected_direct_identity_attempts_create_no_divergence(self):
        left, right = self.runtime(9495), self.runtime(9496)
        team_uuid = left.logic.create_team("Charter").value
        connect(left, right, team_uuid)
        right.logic.accept_team_invitation(
            right.session.protocol.index[team_uuid],
        )
        sync(left, right)

        self.assertEqual(
            left.logic.offer_identity(team_uuid, "third-actor-uuid").status,
            "error",
        )
        self.assertEqual(right.logic.take_identity(team_uuid).status, "error")
        sync(left, right)

        payload = left.logic.document_payload(team_uuid)
        node_uuid = payload["identity"]["node_uuid"]
        self.assertNotEqual(
            payload["transition_by_node"].get(node_uuid, {}).get("type"),
            "divergence",
        )
        self.assertEqual(
            payload["identity"]["holder_actor_uuid"],
            left.session.identity.uuid,
        )

    def test_identity_writes_obey_the_read_only_guard(self):
        runtime = self.runtime(9494)
        parent_uuid = runtime.logic.create_team("Cooperative").value
        child_uuid = runtime.logic.create_subteam(
            parent_uuid, "Operations",
        ).value
        self.leave(runtime, parent_uuid)

        for result in (
            runtime.logic.take_identity(child_uuid),
            runtime.logic.offer_identity(child_uuid, "someone"),
        ):
            self.assertEqual(result.status, "error")
            self.assertIn("Read-only", result.reason)

    def test_a_role_carries_accountabilities_and_domains_as_nodes(self):
        runtime = self.runtime(9480)
        team_uuid = runtime.logic.create_team("Charter").value
        role_uuid = runtime.logic.create_role(team_uuid, "Treasurer").value
        runtime.logic.set_role_purpose(
            role_uuid, "Keep the books honest and current",
        )
        accountability = runtime.logic.create_role_item(
            role_uuid, "accountability", "Monthly reconciliation",
        )
        domain = runtime.logic.create_role_item(
            role_uuid, "domain", "Bank accounts",
        )

        self.assertEqual(accountability.status, "ok")
        self.assertEqual(domain.status, "ok")
        team = runtime.session.protocol.index[team_uuid]
        # A team ships with no roles at all: membership is not one, and the
        # first role is content somebody writes.
        roles = runtime.logic.roles(team)
        self.assertEqual(
            [node.data["name"] for node in roles],
            ["Treasurer"],
        )
        treasurer = roles[0]
        self.assertEqual(
            treasurer.data["purpose"], "Keep the books honest and current",
        )
        # Separate nodes, not a list inside the role: two people editing
        # different accountabilities have to be able to diverge separately.
        self.assertEqual(
            [node.data["text"] for node in
             runtime.logic.accountabilities(treasurer)],
            ["Monthly reconciliation"],
        )
        self.assertEqual(
            [node.data["text"] for node in runtime.logic.domains(treasurer)],
            ["Bank accounts"],
        )

    def test_roles_and_their_items_reorder_within_their_own_type(self):
        runtime = self.runtime(9481)
        team_uuid = runtime.logic.create_team("Charter").value
        first = runtime.logic.create_role(team_uuid, "First").value
        second = runtime.logic.create_role(team_uuid, "Second").value
        runtime.logic.create_role(team_uuid, "Third")
        alpha = runtime.logic.create_role_item(
            first, "accountability", "Alpha",
        ).value
        runtime.logic.create_role_item(first, "accountability", "Beta")
        # A domain shares the role with the accountabilities, so an ordering
        # that was not type-scoped would interleave them.
        gamma = runtime.logic.create_role_item(first, "domain", "Gamma").value
        runtime.logic.create_role_item(first, "domain", "Delta")

        def names():
            team = runtime.session.protocol.index[team_uuid]
            return [node.data["name"] for node in runtime.logic.roles(team)]

        def texts(reader):
            role = runtime.session.protocol.index[first]
            return [node.data["text"] for node in reader(role)]

        self.assertEqual(
            names(), ["First", "Second", "Third"],
        )
        self.assertEqual(runtime.logic.move_role(second, 0).status, "ok")
        self.assertEqual(
            names(), ["Second", "First", "Third"],
        )

        self.assertEqual(texts(runtime.logic.accountabilities), ["Alpha", "Beta"])
        self.assertEqual(runtime.logic.move_role_item(alpha, 1).status, "ok")
        self.assertEqual(texts(runtime.logic.accountabilities), ["Beta", "Alpha"])
        # Moving an accountability left the domains alone.
        self.assertEqual(texts(runtime.logic.domains), ["Gamma", "Delta"])
        self.assertEqual(runtime.logic.move_role_item(gamma, 1).status, "ok")
        self.assertEqual(texts(runtime.logic.domains), ["Delta", "Gamma"])

    def test_deleting_a_role_takes_its_accountabilities_and_domains(self):
        runtime = self.runtime(9482)
        team_uuid = runtime.logic.create_team("Charter").value
        role_uuid = runtime.logic.create_role(team_uuid, "Treasurer").value
        item_uuid = runtime.logic.create_role_item(
            role_uuid, "accountability", "Monthly reconciliation",
        ).value

        self.assertEqual(runtime.logic.delete_role(role_uuid).status, "ok")
        # Deleting a container prunes its descendants out of the index rather
        # than tombstoning each one, as it does for a section's clauses.
        self.assertNotIn(item_uuid, runtime.session.protocol.index)
        team = runtime.session.protocol.index[team_uuid]
        self.assertEqual(
            [node.data["name"] for node in runtime.logic.roles(team)],
            [],
        )

    def test_a_purpose_may_be_cleared_but_a_name_may_not(self):
        runtime = self.runtime(9483)
        team_uuid = runtime.logic.create_team("Charter").value
        role_uuid = runtime.logic.create_role(team_uuid, "Treasurer").value
        runtime.logic.set_role_purpose(role_uuid, "Keep the books")

        self.assertEqual(
            runtime.logic.set_role_purpose(role_uuid, "").status, "ok",
        )
        role = runtime.session.protocol.index[role_uuid]
        self.assertEqual(role.data["purpose"], "")
        # The name is what identifies the role, so blanking it is refused.
        self.assertEqual(
            runtime.logic.rename_role(role_uuid, "   ").status, "error",
        )
        self.assertEqual(
            runtime.session.protocol.index[role_uuid].data["name"], "Treasurer",
        )

    def test_role_writes_reject_unknown_kinds_and_wrong_node_types(self):
        runtime = self.runtime(9484)
        team_uuid = runtime.logic.create_team("Charter").value
        role_uuid = runtime.logic.create_role(team_uuid, "Treasurer").value
        section_uuid = runtime.logic.create_section(team_uuid, "Terms").value

        self.assertEqual(
            runtime.logic.create_role(team_uuid, "  ").status, "error",
        )
        self.assertEqual(
            runtime.logic.create_role_item(role_uuid, "budget", "x").status,
            "error",
        )
        # A section is not a role, and a role is not a role item.
        self.assertEqual(
            runtime.logic.create_role_item(
                section_uuid, "accountability", "x",
            ).status,
            "error",
        )
        self.assertEqual(runtime.logic.delete_role(section_uuid).status, "error")
        self.assertEqual(
            runtime.logic.update_role_item(role_uuid, "x").status, "error",
        )

    def test_role_writes_obey_the_read_only_guard(self):
        runtime = self.runtime(9486)
        parent_uuid = runtime.logic.create_team("Cooperative").value
        child_uuid = runtime.logic.create_subteam(
            parent_uuid, "Operations",
        ).value
        role_uuid = runtime.logic.create_role(child_uuid, "Treasurer").value
        item_uuid = runtime.logic.create_role_item(
            role_uuid, "accountability", "Monthly reconciliation",
        ).value
        self.leave(runtime, parent_uuid)

        for result in (
            runtime.logic.create_role(child_uuid, "Blocked"),
            runtime.logic.rename_role(role_uuid, "Changed"),
            runtime.logic.set_role_purpose(role_uuid, "Changed"),
            runtime.logic.move_role(role_uuid, 0),
            runtime.logic.delete_role(role_uuid),
            runtime.logic.create_role_item(role_uuid, "domain", "Blocked"),
            runtime.logic.update_role_item(item_uuid, "Changed"),
            runtime.logic.move_role_item(item_uuid, 0),
            runtime.logic.delete_role_item(item_uuid),
        ):
            self.assertEqual(result.status, "error")
            self.assertIn("Read-only", result.reason)

    def test_role_nodes_are_reactable_and_owned(self):
        runtime = self.runtime(9487)
        team_uuid = runtime.logic.create_team("Charter").value
        role_uuid = runtime.logic.create_role(team_uuid, "Treasurer").value
        item_uuid = runtime.logic.create_role_item(
            role_uuid, "domain", "Bank accounts",
        ).value

        # Reactable, or a divergence on a role would have no way out.
        for node_type in (
            "team_role", "team_accountability", "team_domain",
        ):
            self.assertIn(node_type, TeamLogic.REACTABLE)
            self.assertIn(node_type, TeamLogic.OWNED_NODE_TYPES)
        self.assertTrue(runtime.logic.owns_node(role_uuid))
        self.assertTrue(runtime.logic.owns_node(item_uuid))

    # A seat is offered on the parent's page and answered on the child's,
    # because those are two different people's pages.
    def test_taking_a_seat_again_continues_the_answer_it_gave_before(self):
        # Which answer counts is the end of the chain, not iteration order,
        # so giving a seat up and taking it back must not lay a second root
        # beside the first.
        runtime = self.runtime(9501)
        parent_uuid = runtime.logic.create_team("Cooperative").value
        child_uuid = runtime.logic.create_team("Team A").value
        role_uuid = runtime.logic.create_role(parent_uuid, "Operations").value

        self.assertEqual(
            runtime.logic.seat_team(role_uuid, child_uuid).status, "ok",
        )
        self.assertEqual(
            runtime.logic.unseat_team(role_uuid, child_uuid).status, "ok",
        )
        runtime.logic.seat_team(role_uuid, child_uuid)
        role = runtime.session.protocol.index[role_uuid]
        decisions = [
            node for node in runtime.logic._held(role, "answers")
            if node.data.get("actor_uuid") == child_uuid
        ]
        self.assertEqual(len(decisions), 1)
        head = runtime.logic._role_decision_for(role, child_uuid)
        self.assertEqual(head.data["decision"], "accepted")
        self.assertEqual(
            head.data["decided_by"], runtime.session.identity.uuid,
        )
        # And it recorded who was on the team when the seat was taken.
        self.assertEqual(
            head.data["seated_member_uuids"],
            runtime.logic.current_member_uuids(
                runtime.session.protocol.index[child_uuid],
            ),
        )
        child = runtime.session.protocol.index[child_uuid]
        self.assertEqual(len(runtime.logic.parent_holdings(child)), 1)

    def test_stepping_out_of_a_seat_clears_both_sides_of_it(self):
        runtime = self.runtime(9525)
        parent_uuid = runtime.logic.create_team("Cooperative").value
        child_uuid = runtime.logic.create_subteam(
            parent_uuid, "Finance circle",
        ).value
        parent = runtime.session.protocol.index[parent_uuid]
        role_uuid = runtime.logic.child_teams(parent)[0][1].uuid

        stepped = runtime.logic.unseat_team(role_uuid, child_uuid)

        # Reported as done, rather than judged by whether there was a peer to
        # tell: a team nobody else has yet produces no effects at all.
        self.assertEqual(stepped.status, "ok")
        child = runtime.session.protocol.index[child_uuid]
        role = runtime.session.protocol.index[role_uuid]
        self.assertEqual(runtime.logic.parent_holdings(child), [])
        # And the parent no longer counts it as seated, so the two sides say
        # the same thing. The seat is simply unfilled, and can be taken again.
        self.assertFalse(runtime.logic._team_holds_role(role, child_uuid))
        self.assertEqual(
            runtime.logic.seat_team(role_uuid, child_uuid).status, "ok",
        )
        self.assertEqual(
            runtime.logic.home_parent_uuid(
                runtime.session.protocol.index[child_uuid],
            ),
            parent_uuid,
        )
        # Twice over is not an error the second time round, it is a fact:
        # there is no seat here to give up.
        runtime.logic.unseat_team(role_uuid, child_uuid)
        repeated = runtime.logic.unseat_team(role_uuid, child_uuid)
        self.assertEqual(repeated.status, "error")
        self.assertIn("does not hold that role", repeated.reason)

    def test_only_the_teams_identity_holder_answers_for_it(self):
        host = self.runtime(9502)
        guest = self.runtime(9503)
        parent_uuid = host.logic.create_team("Cooperative").value
        child_uuid = host.logic.create_team("Team A").value
        role_uuid = host.logic.create_role(parent_uuid, "Operations").value
        self.assertEqual(host.logic.offer_identity(
            child_uuid, guest.session.identity.uuid,
        ).status, "error")
        self.assertEqual(
            host.logic.seat_team(role_uuid, child_uuid).status, "ok",
        )

    def test_an_teams_own_seat_reads_as_accepted_not_unobserved(self):
        runtime = self.runtime(9507)
        parent_uuid = runtime.logic.create_team("Cooperative").value
        child_uuid = runtime.logic.create_team("Team A").value
        role_uuid = runtime.logic.create_role(parent_uuid, "Operations").value

        parent = runtime.session.protocol.index[parent_uuid]
        role = runtime.session.protocol.index[role_uuid]
        # Nothing said, so nobody on the line - a seat it could take is not
        # a seat it holds.
        self.assertEqual(runtime.logic.role_holders(parent, role), [])

        runtime.logic.seat_team(role_uuid, child_uuid)
        parent = runtime.session.protocol.index[parent_uuid]
        role = runtime.session.protocol.index[role_uuid]
        seat = next(
            holder for holder in runtime.logic.role_holders(parent, role)
            if holder["actor_uuid"] == child_uuid
        )

        # A team has no replica of its own, so its answer is vouched
        # for by the replica of whoever gave it - this one. Reporting it as
        # unobserved would call this session unable to see what it wrote.
        self.assertEqual(seat["status"], "accepted")
        self.assertEqual(seat["actor_kind"], "team")
        self.assertEqual(seat["name"], "Team A")
        self.assertTrue(seat["joined"])
        # And it is a second actor here, which is what makes this working.
        self.assertIn(child_uuid, runtime.logic.actor_uuids(parent))
        self.assertEqual(runtime.logic.team_state(parent), "working")

    def test_a_team_takes_a_seat_it_was_never_offered(self):
        runtime = self.runtime(9507)
        parent_uuid = runtime.logic.create_team("Cooperative").value
        child_uuid = runtime.logic.create_team("Team A").value
        role_uuid = runtime.logic.create_role(parent_uuid, "Operations").value

        taken = runtime.logic.seat_team(role_uuid, child_uuid)

        self.assertEqual(taken.status, "ok")
        parent = runtime.session.protocol.index[parent_uuid]
        role = runtime.session.protocol.index[role_uuid]
        self.assertEqual(
            [
                holder["actor_uuid"]
                for holder in runtime.logic.role_holders(parent, role)
                if holder["status"] == "accepted"
            ],
            [child_uuid],
        )
        # There is nothing to turn down, either: a team that does not want
        # the seat does not take it, and one that took it gives it up.
        self.assertFalse(hasattr(runtime.logic, "decline_seat"))

    # ---- what the team runs -------------------------------------------
    #
    # Nothing about an item is recorded on the team, so every one of these
    # asserts a derivation rather than a stored row. The fake application is
    # registered with Core the way a real one is, because what answers
    # "which application owns this topic" is Core's registry and not a
    # string S-Team keeps.

    @staticmethod
    def register_items_application(runtime, application_id="initiative"):
        """A second application on this session, owning one root type."""
        topics = []

        def list_topics():
            return list(topics)

        def accept_topic(subtree):
            accepted = runtime.session.accept_topic_invitation(subtree)
            if accepted.status == "ok":
                mounted = runtime.session.get_node(str(accepted.value))
                if mounted is not None and all(
                    item.uuid != mounted.uuid for item in topics
                ):
                    topics.append(mounted)
            return accepted

        runtime.session.register_application(ApplicationRegistration(
            application_id,
            frozenset({f"{application_id}_topic"}),
            list_topics,
            accept_topic,
            assignment_scoped=True,
            mount_invitation=True,
        ))
        return topics

    def an_item(self, runtime, topics, name="Roadmap",
                application_id="initiative"):
        created = runtime.session.create_child(
            runtime.session.protocol.root.uuid,
            {"type": f"{application_id}_topic", "name": name},
            {},
        )
        topics.append(created.value)
        runtime.session.start_discussion(created.value.uuid)
        return created.value.uuid

    def test_an_item_is_the_teams_when_it_is_on_the_teams_channel(self):
        runtime = self.runtime(9801)
        topics = self.register_items_application(runtime)
        team_uuid = runtime.logic.create_team("Cooperative").value
        runtime.session.start_discussion(team_uuid)
        runtime.mailbox_channel.attach_topics(
            [team_uuid], {"target_id": runtime.relay_target},
        )
        item_uuid = self.an_item(runtime, topics)
        team = runtime.session.protocol.index[team_uuid]

        # Held here, and not published beside the team: this person's own.
        self.assertEqual(runtime.logic.team_items(team), [])
        self.assertEqual(
            [item["topic_uuid"] for item in runtime.logic.offerable_items(team)],
            [item_uuid],
        )

        offered = runtime.logic.offer_team_item(team_uuid, item_uuid)

        self.assertEqual(offered.status, "ok")
        team = runtime.session.protocol.index[team_uuid]
        items = runtime.logic.team_items(team)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["topic_uuid"], item_uuid)
        self.assertEqual(items[0]["title"], "Roadmap")
        self.assertEqual(items[0]["application_id"], "initiative")
        self.assertTrue(items[0]["active"])
        # And it is no longer one of this client's unoffered own.
        self.assertEqual(runtime.logic.offerable_items(team), [])

    def test_a_private_team_has_nowhere_to_publish_an_item(self):
        # The team never got a channel, so there is nothing to put the work
        # on - and the item stays this person's until there is.
        runtime = self.runtime(9802)
        topics = self.register_items_application(runtime)
        team_uuid = runtime.logic.create_team("Private").value
        item_uuid = self.an_item(runtime, topics)

        refused = runtime.logic.offer_team_item(team_uuid, item_uuid)

        self.assertEqual(refused.status, "error")
        self.assertIn("no channel", refused.reason)
        team = runtime.session.protocol.index[team_uuid]
        self.assertEqual(
            [item["topic_uuid"] for item in runtime.logic.offerable_items(team)],
            [item_uuid],
        )

    def test_the_list_carries_the_item_where_the_channel_cannot(self):
        # The constraint the whole design turns on, asserted so it cannot be
        # assumed away again. An explicit relay target polls only what this
        # client has assigned to it plus what it has already consented to
        # receive (relay_logic.poll_and_apply) - deliberately, so a shared
        # SFTP root never enumerates unrelated discussions. Publishing an
        # item beside the team therefore does not make it visible to
        # anybody: what carries its uuid is the holder saying they have it.
        left, right = self.runtime(9803), self.runtime(9804)
        topics = self.register_items_application(left)
        self.register_items_application(right)
        team_uuid = left.logic.create_team("Cooperative").value
        connect(left, right, team_uuid)
        self.admit(left, right, team_uuid)
        item_uuid = self.an_item(left, topics)
        left.logic.offer_team_item(team_uuid, item_uuid)
        sync(left, right)

        team = right.session.protocol.index[team_uuid]
        items = right.logic.team_items(team)

        # Published, and on the same target as the team - and still not
        # something the other client's relay would ever look at.
        self.assertIn(item_uuid, left.relay.relay_topic_uuids())
        self.assertIn(item_uuid, left.relay.storage.list_topics())
        self.assertNotIn(
            item_uuid,
            right.session.peer_topic_uuids(f"relay:{left.relay.identity}"),
        )
        # The list reached them, so the item is offered: a name, and nothing
        # else, until they take it up.
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["topic_uuid"], item_uuid)
        self.assertEqual(items[0]["title"], "Roadmap")
        self.assertFalse(items[0]["active"])
        self.assertIsNone(right.session.get_node(item_uuid))
        # And consent is their own act.
        connected = right.logic.connect_team_item(team_uuid, item_uuid)
        self.assertEqual(connected.status, "ok", connected.reason)
        self.assertEqual(
            right.relay_manager.target_for_topic(item_uuid),
            right.relay_manager.target_for_topic(team_uuid),
        )
        sync(left, right)
        self.assertIn(
            item_uuid, left.session.peer_topic_sets[right.peer_addr],
        )

    def test_membership_acceptance_requires_requirement_answer_and_conditional_consent(self):
        runtime = self.runtime(9815)
        team_uuid = runtime.logic.create_team("Explicit acceptance").value
        type_uuid = runtime.logic.create_membership_type(
            team_uuid, "Associate",
        ).value.uuid
        missing_requirement = runtime.logic.open_membership_invitation(
            team_uuid, type_uuid, self.FAR_FUTURE,
        )
        self.assertEqual(missing_requirement.status, "error")
        self.assertIn("Requirement", missing_requirement.reason)

        runtime.logic.set_membership_acceptance(
            type_uuid, "I accept these membership conditions.",
        )
        opened = runtime.logic.open_membership_invitation(
            team_uuid, type_uuid, self.FAR_FUTURE,
        )
        missing_answer = runtime.logic.apply_for_membership(
            team_uuid, opened.value.uuid,
        )
        self.assertEqual(missing_answer.status, "error")
        self.assertIn("Acceptance Text", missing_answer.reason)

        application_without_agreement = runtime.logic.apply_for_membership(
            team_uuid, opened.value.uuid,
            acceptance_text="I can meet this requirement.",
        )
        self.assertEqual(
            application_without_agreement.status, "ok",
            application_without_agreement.reason,
        )
        accepted_without_agreement = runtime.logic.issue_membership_badge(
            team_uuid, application_without_agreement.value.uuid,
        )
        self.assertEqual(accepted_without_agreement.status, "ok")
        self.assertEqual(
            accepted_without_agreement.value.data["acceptance_text"],
            "I can meet this requirement.",
        )
        self.assertFalse(
            accepted_without_agreement.value.data["agreement_accepted"],
        )

        runtime.logic.rename_agreement(team_uuid, "Team Agreement")
        runtime.logic.set_agreement_version(team_uuid, "1")
        runtime.logic.create_section(team_uuid, "Agreement terms")
        second_type = runtime.logic.create_membership_type(
            team_uuid, "Partner", acceptance="Explain your commitment.",
        ).value.uuid
        second_opened = runtime.logic.open_membership_invitation(
            team_uuid, second_type, self.FAR_FUTURE,
        )
        missing_consent = runtime.logic.apply_for_membership(
            team_uuid, second_opened.value.uuid,
            acceptance_text="I commit to it.",
        )
        self.assertEqual(missing_consent.status, "error")
        self.assertIn("explicit", missing_consent.reason)
        self.assertEqual(self.apply_and_issue(
            runtime, runtime, team_uuid, second_opened.value.uuid,
            agreement_accepted=True, acceptance_text="I commit to it.",
        ).status, "ok")

    def test_application_is_not_membership_and_identity_badge_keeps_answers(self):
        identity, applicant = self.runtime(9820), self.runtime(9821)
        team_uuid = identity.logic.create_team("Badge provenance").value
        connect(identity, applicant, team_uuid)
        applicant.logic.accept_team_invitation(
            applicant.session.protocol.index[team_uuid],
        )
        type_uuid = self.a_membership_type(identity, team_uuid)
        invitation = identity.logic.open_membership_invitation(
            team_uuid, type_uuid, self.FAR_FUTURE,
        )
        self.adopt_membership_terms(
            identity, applicant, team_uuid, type_uuid,
        )

        application = applicant.logic.apply_for_membership(
            team_uuid, invitation.value.uuid,
            agreement_accepted=True,
            acceptance_text="I will meet the requirement.",
        )
        self.assertEqual(application.status, "ok", application.reason)
        applicant_team = applicant.session.protocol.index[team_uuid]
        self.assertFalse(applicant.logic._has_current_acceptance(applicant_team))

        sync(identity, applicant)
        badge = identity.logic.issue_membership_badge(
            team_uuid, application.value.uuid,
        )
        self.assertEqual(badge.status, "ok", badge.reason)
        self.assertEqual(
            badge.value.data["application_uuid"], application.value.uuid,
        )
        self.assertEqual(
            badge.value.data["acceptance_text"],
            "I will meet the requirement.",
        )
        self.assertEqual(badge.value.data["agreement_version"], "1")

        sync(identity, applicant)
        participant = next(
            person for person in identity.logic.participants(team_uuid)
            if person["uuid"] == applicant.session.identity.uuid
        )
        self.assertEqual(
            participant["membership_badge"]["acceptance_text"],
            "I will meet the requirement.",
        )
        self.assertEqual(
            participant["membership_badge"]["agreement_version"], "1",
        )

    def test_membership_definitions_align_only_to_identity(self):
        identity, observer = self.runtime(9822), self.runtime(9823)
        team_uuid = identity.logic.create_team("Identity definitions").value
        connect(identity, observer, team_uuid)
        observer.logic.accept_team_invitation(
            observer.session.protocol.index[team_uuid],
        )
        sync(identity, observer)
        identity_team = identity.session.protocol.index[team_uuid]
        type_uuid = identity.logic.membership_types(identity_team)[0].uuid

        identity.logic.set_membership_requirements(
            type_uuid, "Identity's Membership Info",
        )
        identity.logic.set_membership_acceptance(
            type_uuid, "Identity's Acceptance Requirement",
        )
        sync(identity, observer)
        observed = observer.session.protocol.index[type_uuid]
        self.assertEqual(
            observed.data["requirements"], "Identity's Membership Info",
        )
        self.assertEqual(
            observed.data["acceptance"],
            "Identity's Acceptance Requirement",
        )

        changed = dict(observed.data)
        changed["requirements"] = "Observer rewrite"
        observer.session.modify(type_uuid, changed, observed.weights)
        sync(identity, observer)
        observer.logic.reconcile_governance_updates()
        self.assertEqual(
            identity.session.protocol.index[type_uuid].data["requirements"],
            "Identity's Membership Info",
        )
        self.assertEqual(
            observer.session.protocol.index[type_uuid].data["requirements"],
            "Identity's Membership Info",
        )

    def test_identity_agreement_disagreement_blocks_membership_opening(self):
        first, second = self.runtime(9824), self.runtime(9825)
        team_uuid = first.logic.create_team("Agreement consensus").value
        connect(first, second, team_uuid)
        self.admit(first, second, team_uuid)
        team = first.session.protocol.index[team_uuid]
        type_uuid = first.logic.membership_types(team)[0].uuid

        first.logic.resign_identity(team_uuid)
        sync(first, second)
        self.assertEqual(
            first.logic.enter_trustee_candidacy(
                team_uuid, "identity",
            ).status,
            "ok",
        )
        self.assertEqual(
            second.logic.enter_trustee_candidacy(
                team_uuid, "identity",
            ).status,
            "ok",
        )
        sync(first, second)

        first.logic.set_agreement_version(team_uuid, "2")
        sync(first, second)
        team = first.session.protocol.index[team_uuid]
        self.assertEqual(
            first.logic.agreement_projection(team)["state"], "disputed",
        )
        opened = first.logic.open_membership_invitation(
            team_uuid, type_uuid, self.FAR_FUTURE,
        )
        self.assertEqual(opened.status, "error")
        self.assertIn("align", opened.reason)

    def test_an_item_stops_being_offered_when_the_last_holder_drops_it(self):
        # What "the team runs this" means: at least one member has it. The
        # creator's own list is the only thing saying so, so when they say
        # otherwise there is nothing left to offer.
        left, right = self.runtime(9809), self.runtime(9810)
        topics = self.register_items_application(left)
        self.register_items_application(right)
        team_uuid = left.logic.create_team("Cooperative").value
        connect(left, right, team_uuid)
        self.admit(left, right, team_uuid)
        item_uuid = self.an_item(left, topics)
        left.logic.offer_team_item(team_uuid, item_uuid)
        sync(left, right)

        self.assertEqual(
            len(right.logic.team_items(
                right.session.protocol.index[team_uuid],
            )),
            1,
        )

        # Deleted from the Cockpit rather than from the team page: the list
        # is recomputed from what is really here, so it catches up either
        # way.
        left.session.delete(item_uuid)
        topics.clear()
        left.logic.reconcile_governance_updates()
        sync(left, right)

        self.assertEqual(
            right.logic.team_items(
                right.session.protocol.index[team_uuid],
            ),
            [],
        )

    def test_only_a_member_runs_the_teams_work(self):
        left, right = self.runtime(9805), self.runtime(9806)
        topics = self.register_items_application(left)
        self.register_items_application(right)
        team_uuid = left.logic.create_team("Cooperative").value
        connect(left, right, team_uuid)
        right.logic.accept_team_invitation(
            right.session.protocol.index[team_uuid],
        )
        item_uuid = self.an_item(left, topics)
        left.logic.offer_team_item(team_uuid, item_uuid)
        sync(left, right)

        # On the topic, not on the team. They read what it runs, because
        # the lists are on the topic and being able to read it is what
        # being on it means - and they take nothing up and add nothing.
        team = right.session.protocol.index[team_uuid]
        self.assertEqual(
            [item["title"] for item in right.logic.team_items(team)],
            ["Roadmap"],
        )
        for refused in (
            right.logic.connect_team_item(team_uuid, item_uuid),
            right.logic.offer_team_item(team_uuid, item_uuid),
            right.logic.create_team_item(team_uuid, "initiative", "Mine"),
        ):
            self.assertEqual(refused.status, "error")
            self.assertIn("Member", refused.reason)

    def test_making_an_item_asks_its_own_application_and_publishes_it(self):
        # S-Team knows how to ask for one and where its page is, and
        # nothing else about it.
        runtime = self.runtime(9807)
        topics = self.register_items_application(runtime)
        made = {}

        class InitiativeFacade:
            def boards(self):
                return list(topics)

            def create_board(self, name):
                made["name"] = name
                return SessionResult(
                    "ok",
                    value=TeamLogicTests.an_item(
                        TeamLogicTests(), runtime, topics, name,
                    ),
                )

            def delete_board(self, board_uuid):
                made["deleted"] = board_uuid
                return SessionResult("ok", value=board_uuid)

        class Facades:
            def find(self, application_id, facade_api_version):
                if (application_id, facade_api_version) == ("initiative", 1):
                    return InitiativeFacade()
                return None

        runtime.logic.facades = Facades()
        team_uuid = runtime.logic.create_team("Cooperative").value
        runtime.session.start_discussion(team_uuid)
        runtime.mailbox_channel.attach_topics(
            [team_uuid], {"target_id": runtime.relay_target},
        )

        created = runtime.logic.create_team_item(
            team_uuid, "initiative", "Roadmap",
        )

        self.assertEqual(created.status, "ok")
        self.assertEqual(made["name"], "Roadmap")
        team = runtime.session.protocol.index[team_uuid]
        items = runtime.logic.team_items(team)
        self.assertEqual([item["title"] for item in items], ["Roadmap"])
        self.assertEqual(items[0]["href"], f"/apps/initiative?board={created.value}")
        # Only the kinds actually loaded here can be made.
        self.assertEqual(
            [kind["application_id"] for kind in runtime.logic.item_kinds()],
            ["initiative"],
        )
        # Removing is that application's own delete, and nothing else.
        removed = runtime.logic.remove_team_item(team_uuid, created.value)
        self.assertEqual(removed.status, "ok")
        self.assertEqual(made["deleted"], created.value)

    def test_an_application_this_client_does_not_run_cannot_be_asked(self):
        runtime = self.runtime(9808)
        team_uuid = runtime.logic.create_team("Cooperative").value

        refused = runtime.logic.create_team_item(
            team_uuid, "initiative", "Roadmap",
        )

        self.assertEqual(refused.status, "error")
        self.assertIn("not available on this client", refused.reason)
        self.assertEqual(runtime.logic.item_kinds(), [])

    def test_a_team_that_could_take_a_seat_is_offered_it_on_its_own_page(self):
        """A team that qualifies gets no row on the other team's page. The
        act belongs where the actor is - whoever holds *this* team's Identity
        answers for it - so the parent draws nobody, and the seat is offered
        on the line of the team that would take it."""
        runtime = self.runtime(9508)
        parent_uuid = runtime.logic.create_team("Cooperative").value
        child_uuid = runtime.logic.create_team("Team A").value
        role_uuid = runtime.logic.create_role(parent_uuid, "Operations").value

        # Nothing held yet, so nobody is drawn as an actor on either page.
        self.assertEqual(
            [
                actor["uuid"]
                for actor in runtime.logic.participants(parent_uuid)
                if actor["actor_kind"] == "team"
            ],
            [],
        )

        child = runtime.session.protocol.index[child_uuid]
        offered = runtime.logic.seatable_roles_payload(child)
        seat = next(
            entry for entry in offered if entry["role_uuid"] == role_uuid
        )
        # One member, on both teams, so Team A holds nobody the Cooperative
        # has not admitted - which is the whole of what qualifies it.
        self.assertTrue(seat["eligible"])
        self.assertEqual(seat["team_title"], "Cooperative")

        self.assertEqual(
            runtime.logic.seat_team(role_uuid, child_uuid).status, "ok",
        )
        # Once it holds the seat it is an actor there like anybody else.
        self.assertEqual(
            [
                actor["uuid"]
                for actor in runtime.logic.participants(parent_uuid)
                if actor["actor_kind"] == "team"
            ],
            [child_uuid],
        )
        self.assertTrue(
            next(
                actor for actor in runtime.logic.participants(parent_uuid)
                if actor["uuid"] == child_uuid
            )["speaks_for"],
        )

    # Templates (2.8). A count of actors, so there is no flag to assert on -
    # only who is in it.
    def test_copy_carries_the_text_and_none_of_the_taking_part(self):
        runtime = self.runtime(9490)
        source_uuid = runtime.logic.create_team("Cooperative").value
        section_uuid = runtime.logic.create_section(source_uuid, "Terms").value
        runtime.logic.create_clause(section_uuid, "Members meet monthly.")
        role_uuid = runtime.logic.create_role(source_uuid, "Treasurer").value
        runtime.logic.create_role_item(role_uuid, "accountability", "Books")
        runtime.logic.create_role_item(role_uuid, "domain", "Bank accounts")

        copy_uuid = runtime.logic.clone_team(source_uuid).value
        copy = runtime.session.protocol.index[copy_uuid]

        self.assertEqual(copy.data["title"], "Cooperative (template)")
        self.assertEqual(
            [node.data["title"] for node in runtime.logic.sections(copy)],
            ["Terms"],
        )
        copied_section = runtime.logic.sections(copy)[0]
        self.assertEqual(
            [node.data["text"] for node in runtime.logic.clauses(copied_section)],
            ["Members meet monthly."],
        )
        # Roles travel, because they are content. Membership does not: a
        # copy is a template nobody is on yet.
        copied_roles = runtime.logic.roles(copy)
        self.assertEqual(
            [node.data["name"] for node in copied_roles],
            ["Treasurer"],
        )
        self.assertEqual(runtime.logic.current_member_uuids(copy), [])
        treasurer = copied_roles[0]
        self.assertEqual(
            [node.data["text"] for node in runtime.logic.accountabilities(treasurer)],
            ["Books"],
        )
        self.assertEqual(
            [node.data["text"] for node in runtime.logic.domains(treasurer)],
            ["Bank accounts"],
        )
        # Fresh uuids, or an answer given in the original would count here:
        # acceptance is looked up by role uuid.
        self.assertNotEqual(treasurer.uuid, role_uuid)
        self.assertNotIn(copied_section.uuid, {section_uuid})
        # Nobody is in it: no Identity, no offers, no answers, no seats.
        self.assertEqual(runtime.logic.identity_holder(copy), "")
        self.assertEqual(runtime.logic.trust_holder(copy), "")
        self.assertEqual(
            runtime.logic.governance_records(copy, "team_trustee_state"),
            [],
        )
        self.assertEqual(runtime.logic.parent_holdings(copy), [])
        for role in copied_roles:
            self.assertEqual(runtime.logic.role_holders(copy, role), [])
        self.assertEqual(runtime.logic.actor_uuids(copy), set())

    def test_state_counts_actors_from_template_to_working(self):
        host = self.runtime(9491)
        guest = self.runtime(9492)
        source_uuid = host.logic.create_team("Cooperative").value
        copy_uuid = host.logic.clone_team(source_uuid).value
        copy = host.session.protocol.index[copy_uuid]

        # Nobody in it at all.
        self.assertEqual(host.logic.team_state(copy), "template")
        # Instantiation assigns Member, Identity, and Trust to one Actor.
        host.logic.take_identity(copy_uuid)
        role = host.logic.create_role(copy_uuid, "Participant").value
        copy = host.session.protocol.index[copy_uuid]
        self.assertEqual(host.logic.team_state(copy), "instantiated")
        self.assertTrue(host.logic._is_current_member(
            copy, host.session.identity.uuid,
        ))
        self.assertTrue(host.logic.holds_identity(copy))
        self.assertTrue(host.logic.holds_trust(copy))
        # Accepting a role you already hold Identity in adds no second actor.
        host.logic.decide_role(role, "accepted")
        copy = host.session.protocol.index[copy_uuid]
        self.assertEqual(host.logic.team_state(copy), "instantiated")

        connect(host, guest, copy_uuid)
        self.admit(host, guest, copy_uuid)

        copy = host.session.protocol.index[copy_uuid]
        self.assertEqual(host.logic.team_state(copy), "working")

    def test_being_able_to_see_a_team_does_not_make_you_an_actor(self):
        host = self.runtime(9493)
        guest = self.runtime(9494)
        team_uuid = host.logic.create_team("Cooperative").value
        role_uuid = host.logic.create_role(team_uuid, "Participant").value
        connect(host, guest, team_uuid)
        guest.logic.accept_team_invitation(
            guest.session.protocol.index[team_uuid],
        )
        role = host.session.protocol.index[role_uuid]

        # Joined the topic, but not admitted - so there is no role to take
        # and no actor to count.
        refused = guest.logic.decide_role(role.uuid, "accepted")
        sync(host, guest)
        team = host.session.protocol.index[team_uuid]

        self.assertEqual(refused.status, "error")
        self.assertEqual(
            [
                holder for holder in host.logic.role_holders(team, role)
                if not holder["is_self"]
            ],
            [],
        )
        self.assertEqual(host.logic.team_state(team), "instantiated")

    def test_a_template_can_be_written_but_not_taken_part_in(self):
        runtime = self.runtime(9495)
        source_uuid = runtime.logic.create_team("Cooperative").value
        copy_uuid = runtime.logic.clone_team(source_uuid).value

        # A template is for editing, so its text is not read-only.
        self.assertEqual(
            runtime.logic.create_section(copy_uuid, "Terms").status, "ok",
        )
        role_uuid = runtime.logic.create_role(copy_uuid, "Treasurer").value
        # But nobody is on it, so nobody can take a role on it - and a team
        # cannot take a seat there either, because the copy carried no
        # Identity to answer for it.
        taken = runtime.logic.decide_role(role_uuid, "accepted")
        self.assertEqual(taken.status, "error")
        self.assertIn("Member", taken.reason)
        seated = runtime.logic.seat_team(role_uuid, source_uuid)
        self.assertEqual(seated.status, "error")

    def test_state_reaches_both_payloads(self):
        runtime = self.runtime(9496)
        source_uuid = runtime.logic.create_team("Cooperative").value
        copy_uuid = runtime.logic.clone_team(source_uuid).value

        payload = runtime.logic.document_payload(copy_uuid)
        states = {
            item["uuid"]: item.get("state")
            for item in payload["organization"]["roots"]
        }

        self.assertEqual(payload["state"], "template")
        self.assertEqual(states[copy_uuid], "template")
        self.assertEqual(states[source_uuid], "instantiated")

    def test_organization_is_derived_from_a_live_parent_holding(self):
        runtime = self.runtime(9479)
        parent_uuid = runtime.logic.create_team("Cooperative").value
        role_uuid = runtime.logic.create_role(parent_uuid, "Research").value
        child_uuid = runtime.logic.create_seated_team(
            role_uuid, "Research team",
        ).value
        parent = runtime.session.protocol.index[parent_uuid]
        child = runtime.session.protocol.index[child_uuid]

        self.assertTrue(runtime.logic.is_organization(parent))
        self.assertFalse(runtime.logic.is_organization(child))
        self.assertFalse(
            runtime.logic.document_payload(child_uuid)["is_organization"],
        )
        organization = runtime.logic.organization_payload()
        parent_summary = next(
            item for item in organization["roots"]
            if item["uuid"] == parent_uuid
        )
        self.assertTrue(parent_summary["is_organization"])
        self.assertFalse(parent_summary["children"][0]["is_organization"])

        self.assertEqual(
            runtime.logic.unseat_team(role_uuid, child_uuid).status, "ok",
        )
        child = runtime.session.protocol.index[child_uuid]
        self.assertTrue(runtime.logic.is_organization(child))

    def test_standing_written_only_the_old_way_no_longer_counts(self):
        """A team from before membership was a record. Its founder's
        standing lived on a role marked system_key=member; nothing reads
        that any more, so they read as being in the pool and the failure is
        visible rather than quietly answered from a superseded shape."""
        runtime = self.runtime(9478)
        team_uuid = runtime.logic.create_team("Cooperative").value
        team = runtime.session.protocol.index[team_uuid]
        mine = runtime.session.identity.uuid
        for record in runtime.logic.membership_records(team, mine):
            runtime.session.delete(record.uuid)
        role = runtime.session.create_child(team_uuid, {
            "type": "team_role", "name": "Member", "purpose": "",
            "system_key": "member", "order": 0.0,
        }, {}).value
        runtime.session.create_child(role.uuid, {
            "type": "team_role_offer", "actor_uuid": mine,
            "actor_kind": "individual", "offered_by": mine,
            "offered_at": "2026-01-01T00:00:00Z", "system_genesis": True,
        }, {})
        team = runtime.session.protocol.index[team_uuid]
        runtime.logic._record_role_decision(team, role, "accepted", None)

        team = runtime.session.protocol.index[team_uuid]
        self.assertEqual(runtime.logic.membership_records(team, mine), [])
        self.assertEqual(runtime.logic.member_standing(team, mine), "pool")
        self.assertFalse(runtime.logic._is_current_member(team, mine))
        self.assertEqual(runtime.logic.current_member_uuids(team), [])
        # And there is no membership left to end, rather than one that can
        # be ended by naming nothing.
        ended = runtime.logic.end_membership(team_uuid, mine)
        self.assertEqual(ended.status, "error")

    def test_copying_needs_no_standing_in_the_original(self):
        runtime = self.runtime(9497)
        source_uuid = runtime.logic.create_team("Cooperative").value
        runtime.logic.create_section(source_uuid, "Terms")
        self.leave(runtime, source_uuid)

        copied = runtime.logic.clone_team(source_uuid, "Reused")

        self.assertEqual(copied.status, "ok")
        copy = runtime.session.protocol.index[copied.value]
        self.assertEqual(copy.data["title"], "Reused")
        self.assertEqual(
            [node.data["title"] for node in runtime.logic.sections(copy)],
            ["Terms"],
        )
        self.assertEqual(runtime.logic.clone_team("missing").status, "error")

    # Being part of a team is holding a role in it, so these stand
    # where a team-level accept or refuse used to.
    FAR_FUTURE = "2999-01-01T00:00:00+00:00"

    def adopt(self, guest, host, *node_uuids):
        """Take a peer's content across. Content is proposed, not published.

        Governance records auto-adopt once they are authorized; the document
        and the definitions in it are somebody's proposal until each replica
        accepts them, which is true of a membership type exactly as it is of
        a role.
        """
        for node_uuid in node_uuids:
            result = guest.logic.accept_peer_node(host.peer_addr, node_uuid)
            self.assertEqual(result.status, "ok", result.reason)

    def a_membership_type(self, runtime, team_uuid, name=None):
        """Whichever membership the team already supports, or a named one."""
        team = runtime.session.protocol.index[team_uuid]
        if name is None:
            existing = runtime.logic.membership_types(team)
            if existing:
                membership_type = existing[0]
                if not str(membership_type.data.get("acceptance") or "").strip():
                    runtime.logic.set_membership_acceptance(
                        membership_type.uuid, "I accept these membership conditions.",
                    )
                if not runtime.logic.agreement_exists(team):
                    runtime.logic.rename_agreement(
                        team_uuid, "Team Agreement",
                    )
                    runtime.logic.set_agreement_version(team_uuid, "1")
                    runtime.logic.create_section(team_uuid, "Agreement terms")
                return membership_type.uuid
            name = "Member"
        created = runtime.logic.create_membership_type(
            team_uuid, name, acceptance="I accept these membership conditions.",
        ).value.uuid
        if not runtime.logic.agreement_exists(team):
            runtime.logic.rename_agreement(team_uuid, "Team Agreement")
            runtime.logic.set_agreement_version(team_uuid, "1")
            runtime.logic.create_section(team_uuid, "Agreement terms")
        return created

    def adopt_membership_terms(self, host, guest, team_uuid, type_uuid):
        """Bring the Agreement and acceptance sentence to the joining side."""
        sync(host, guest)
        host_team = host.session.protocol.index[team_uuid]
        agreement = host.logic.agreement(host_team, create=False)
        for node in [
            host_team,
            host.session.protocol.index[type_uuid],
            *([agreement] if agreement else []),
            *host.logic.sections(host_team),
        ]:
            local = guest.session.get_node(node.uuid)
            if local is None or local.state_hash != node.state_hash:
                self.adopt(guest, host, node.uuid)
        guest.logic.reconcile_governance_updates()

    def admit(self, host, guest, team_uuid, name=None):
        """Put `guest` on the team through application and Identity issue."""
        guest.logic.accept_team_invitation(
            guest.session.protocol.index[team_uuid],
        )
        sync(host, guest)
        type_uuid = self.a_membership_type(host, team_uuid, name)
        # One invitation per type at a time, so a window already open is the
        # one to answer rather than a reason to write a second.
        team = host.session.protocol.index[team_uuid]
        live = host.logic.open_membership_uuids(team).get(type_uuid)
        invitation_uuid = live or host.logic.open_membership_invitation(
            team_uuid, type_uuid, self.FAR_FUTURE,
        ).value.uuid
        self.adopt_membership_terms(host, guest, team_uuid, type_uuid)
        # A membership type made after the guest arrived is content, so it
        # comes across as a proposal they accept. The invitation naming it
        # defers until they have, and is re-assessed on the next pass - the
        # poll does that in the app; here it is asked for.
        if guest.logic._node(type_uuid, "team_membership_type") is None:
            self.adopt(guest, host, type_uuid)
            guest.logic.reconcile_governance_updates()
        application = guest.logic.apply_for_membership(
            team_uuid, invitation_uuid, agreement_accepted=True,
            acceptance_text="Accepted.",
        )
        self.assertEqual(application.status, "ok", application.reason)
        sync(host, guest)
        issued = host.logic.issue_membership_badge(
            team_uuid, application.value.uuid,
        )
        self.assertEqual(issued.status, "ok", issued.reason)
        sync(host, guest)
        return issued

    @classmethod
    def serialized(cls, node, node_type):
        """Every node of one type in a serialized subtree, at any depth.

        Content sits in containers now, so its depth in the payload is a
        detail of where it lives rather than something a test asserts.
        """
        found = []
        for child in node.get("children") or []:
            if child["data"].get("type") == node_type:
                found.append(child)
            found.extend(cls.serialized(child, node_type))
        return found

    def a_role(self, runtime, team_uuid, name="Contributor"):
        """A role, taken. A team ships with none: membership is not one."""
        role_uuid = runtime.logic.create_role(team_uuid, name).value
        runtime.logic.decide_role(role_uuid, "accepted")
        return role_uuid

    def leave(self, runtime, team_uuid):
        """Stop being on the team. Membership is the whole of being on it."""
        return runtime.logic.leave_team(team_uuid)

    def rejoin(self, runtime, team_uuid):
        """Take a membership up again: an invitation, then your own answer.

        Identity still decides the class and the window - a member who left
        cannot let themselves back in through a closed door - but the answer
        is their own. A founder who left still holds Identity, so in a
        single-client test they open the door and then walk through it.
        """
        type_uuid = self.a_membership_type(runtime, team_uuid)
        invitation = runtime.logic.open_membership_invitation(
            team_uuid, type_uuid, self.FAR_FUTURE,
        )
        application = runtime.logic.apply_for_membership(
            team_uuid, invitation.value.uuid, agreement_accepted=True,
            acceptance_text="Accepted.",
        )
        if application.status != "ok":
            return application
        return runtime.logic.issue_membership_badge(
            team_uuid, application.value.uuid,
        )

    def apply_and_issue(
        self, identity, applicant, team_uuid, invitation_uuid, **answers,
    ):
        application = applicant.logic.apply_for_membership(
            team_uuid, invitation_uuid, **answers,
        )
        if application.status != "ok":
            return application
        if identity is not applicant:
            sync(identity, applicant)
        issued = identity.logic.issue_membership_badge(
            team_uuid, application.value.uuid,
        )
        if issued.status == "ok" and identity is not applicant:
            sync(identity, applicant)
        return issued

    def refuse_roles(self, runtime, team_uuid):
        team = runtime.session.protocol.index[team_uuid]
        for role in runtime.logic.roles(team):
            runtime.logic.decide_role(role.uuid, "refused")

    def accept_roles(self, runtime, team_uuid, expires_at=None):
        team = runtime.session.protocol.index[team_uuid]
        for role in runtime.logic.roles(team):
            runtime.logic.decide_role(role.uuid, "accepted", expires_at)

    def own_standing(self, runtime, team_uuid):
        team = runtime.session.protocol.index[team_uuid]
        role = runtime.logic.roles(team)[0]
        return next(
            holder["status"]
            for holder in runtime.logic.role_holders(team, role)
            if holder["is_self"]
        )

    def test_the_page_is_handed_the_keys_it_reads(self):
        # Stored node types and payload keys are different vocabularies, and
        # renaming the first swept up two of the second - which no test
        # noticed, because every one of them drives the logic directly. The
        # page then read payload.team, got undefined, and drew an empty
        # document with the rename control switched off, beside a team that
        # was there the whole time.
        session = Session("local")
        logic = TeamLogic(session)
        team_uuid = logic.create_team("Cooperative").value
        payload = logic.document_payload()

        self.assertEqual((payload["team"] or {})["uuid"], team_uuid)
        self.assertEqual(
            [item["uuid"] for item in payload["teams"]],
            [team_uuid],
        )
        # The Actors area reads these four, and a missing one draws an empty
        # region beside a team that has memberships, actors and seats. The
        # keys are the contract; the node types underneath are not.
        self.assertIn("seatable_roles", payload)
        membership = payload["membership"]
        for key in ("types", "pool", "can_resolve", "is_member"):
            self.assertIn(key, membership)
        founding = membership["types"][0]
        for key in (
            "uuid", "name", "requirements", "acceptance", "invitation",
            "members", "is_mine", "can_apply",
        ):
            self.assertIn(key, founding)
        # And every actor row carries the badge's two fields, whether or not
        # this one has a badge to draw.
        for person in payload["participants"]:
            self.assertIn("membership_status", person)
            self.assertIn("membership_type", person)

        # And the snapshot the controller serves has to find the same node,
        # or the shell is told no topic is open and hides what belongs to it.
        with session.lock:
            snapshot = logic.document_snapshot()
        self.assertEqual(snapshot["topic_uuid"], team_uuid)

    def test_a_name_already_taken_beside_it_is_numbered_not_duplicated(self):
        session = Session("local")
        logic = TeamLogic(session)
        first = logic.create_team("Cooperative").value
        second = logic.create_team("Cooperative").value
        self.assertEqual(
            session.protocol.index[second].data["title"], "Cooperative (2)",
        )

        role_a = logic.create_role(first, "Lead").value
        role_b = logic.create_role(first, "Lead").value
        self.assertEqual(
            session.protocol.index[role_b].data["name"], "Lead (2)",
        )
        # A third takes the next number rather than stacking suffixes.
        role_c = logic.create_role(first, "Lead (2)").value
        self.assertEqual(
            session.protocol.index[role_c].data["name"], "Lead (3)",
        )
        # Renaming obeys the same rule, and a rename to its own name is not
        # a collision with itself.
        self.assertEqual(logic.rename_role(role_a, "Lead").status, "ok")
        self.assertEqual(session.protocol.index[role_a].data["name"], "Lead")
        self.assertEqual(logic.rename_role(role_a, "Lead (2)").status, "ok")
        self.assertEqual(
            session.protocol.index[role_a].data["name"], "Lead (4)",
        )

    def test_identity_can_be_stepped_out_of_and_the_seat_is_then_vacant(self):
        # Vacancy is a successor record; genesis is never rewritten.
        session = Session("local")
        logic = TeamLogic(session)
        team_uuid = logic.create_team("Charter").value
        team = session.protocol.index[team_uuid]
        self.assertTrue(logic.holds_identity(team))

        node_uuid = logic.identity_payload(team)["node_uuid"]
        self.assertEqual(logic.resign_identity(team_uuid).status, "ok")

        team = session.protocol.index[team_uuid]
        payload = logic.identity_payload(team)
        self.assertEqual(payload["state"], "vacant")
        self.assertNotEqual(payload["node_uuid"], node_uuid)
        self.assertFalse(logic.holds_identity(team))
        # Trust remains held, but cannot exercise Identity's domain: only a
        # team's own Identity holder answers for it, and this one is vacant.
        role_uuid = logic.create_role(team_uuid, "Delegate").value
        other_team = logic.create_team("Elsewhere").value
        self.assertEqual(logic.seat_team(role_uuid, team_uuid).status, "error")
        self.assertEqual(
            logic.resign_trusteeship(team_uuid, "trust").status, "ok",
        )
        # Taking a role is still fine with both seats vacant: it is a
        # member's own act, and they are still a member. Only what a
        # trusteeship decides waits for a trustee.
        self.assertEqual(
            logic.decide_role(role_uuid, "accepted").status, "ok",
        )
        self.assertEqual(logic.seat_team(role_uuid, team_uuid).status, "error")
        self.assertNotEqual(other_team, team_uuid)
        self.assertEqual(logic.take_identity(team_uuid).status, "error")
        self.assertEqual(
            logic.resign_identity("not-an-team").status, "error",
        )

    @staticmethod
    def governance_genesis(runtime, trust="identity") -> dict:
        actor_uuid = runtime.session.identity.uuid
        return {
            "type": "team_trustee_state",
            "trust": trust,
            "holder_actor_uuid": actor_uuid,
            "previous_state_uuid": "",
            "cause": "genesis",
            "acted_by": actor_uuid,
            "acted_at": "2026-08-04T10:00:00+00:00",
            "authority_basis_uuid": "",
            "signals": "Organization created",
            "consideration": "Initial authority",
            "expectation": "Trusteeship is explicit",
        }

    @staticmethod
    def governance_action(runtime, basis_uuid: str, **overrides) -> dict:
        actor_uuid = runtime.session.identity.uuid
        data = {
            "type": "team_trustee_action",
            "trust": "identity",
            "action_kind": "membership_invitation",
            "subject_uuid": "membership",
            "acted_by": actor_uuid,
            "acted_at": "2026-08-04T10:01:00+00:00",
            "authority_basis_uuid": basis_uuid,
            "value": "The membership is opened",
            "signals": "Capacity is available",
            "consideration": "The membership may be taken up by several",
            "expectation": "The pool answers for itself",
            "payload": {"capacity": "several"},
        }
        data.update(overrides)
        return data

    @staticmethod
    def governance_basis(runtime, team_uuid: str, trust="identity") -> str:
        team = runtime.session.protocol.index[team_uuid]
        return runtime.logic.trustee_projection(
            team, trust,
        )["current_state_uuid"]

    def test_governance_records_require_current_signed_authority(self):
        runtime = self.runtime(9620)
        team_uuid = runtime.logic.create_team("Governed").value

        genesis_uuid = self.governance_basis(runtime, team_uuid)
        duplicate = runtime.logic.append_governance_record(
            team_uuid, self.governance_genesis(runtime),
        )
        self.assertEqual(duplicate.status, "error")
        team = runtime.session.protocol.index[team_uuid]
        self.assertEqual(runtime.logic.trustee_projection(team, "identity"), {
            "trust": "identity",
            "state": "held",
            "current_state_uuid": genesis_uuid,
            "holder_actor_uuid": runtime.session.identity.uuid,
            "contenders": [],
        })

        action = runtime.logic.append_governance_record(
            team_uuid, self.governance_action(runtime, genesis_uuid),
        )
        self.assertEqual(action.status, "ok")
        stale = runtime.logic.append_governance_record(
            team_uuid, self.governance_action(runtime, "missing-state"),
        )
        self.assertEqual(stale.status, "error")
        self.assertIn("authority basis", stale.reason)

        nested = ProtocolNode(
            self.governance_action(runtime, genesis_uuid),
            parent_uuid="not-the-team",
            revision_origin=runtime.session.identity.data["identity_key"],
        )
        assessment = runtime.logic.assess_governance_record(
            team, nested, verification="valid",
        )
        self.assertEqual(assessment["status"], "invalid")
        self.assertIn("container", assessment["reason"])

    def test_only_authorized_governance_auto_adopts(self):
        left, right = self.runtime(9621), self.runtime(9622)
        team_uuid = left.logic.create_team("Selective convergence").value
        connect(left, right, team_uuid)
        right.logic.accept_team_invitation(
            right.session.protocol.index[team_uuid],
        )
        sync(left, right)

        genesis_uuid = self.governance_basis(left, team_uuid)
        section_uuid = left.logic.create_section(team_uuid, "Still a proposal").value
        action = left.logic.append_governance_record(
            team_uuid, self.governance_action(left, genesis_uuid),
        )
        sync(left, right)

        self.assertIn(genesis_uuid, right.session.protocol.index)
        self.assertIn(action.value.uuid, right.session.protocol.index)
        self.assertNotIn(section_uuid, right.session.protocol.index)

    def test_signed_non_trustee_action_is_visible_but_disregarded(self):
        left, right = self.runtime(9623), self.runtime(9624)
        team_uuid = left.logic.create_team("Authority boundary").value
        connect(left, right, team_uuid)
        right.logic.accept_team_invitation(
            right.session.protocol.index[team_uuid],
        )
        sync(left, right)
        genesis_uuid = self.governance_basis(left, team_uuid)

        unauthorized = right.session.create_child(
            right.logic._container(
                right.session.protocol.index[team_uuid], "actions",
            ).uuid,
            self.governance_action(right, genesis_uuid),
            {},
        )
        self.assertEqual(unauthorized.status, "ok")
        sync(left, right)

        self.assertNotIn(unauthorized.value.uuid, left.session.protocol.index)
        team = left.session.protocol.index[team_uuid]
        attempt = next(
            item for item in left.logic.governance_attempts(team)
            if item["node_uuid"] == unauthorized.value.uuid
        )
        self.assertEqual(attempt["status"], "unauthorized")
        self.assertIn("does not hold Identity", attempt["reason"])

    def test_one_invitation_admits_several_and_each_answers_for_themselves(self):
        """Identity opens the class; the pool answers it person by person.

        Nobody is admitted and nobody is resolved. What Identity decided was
        that this membership is open until a stated moment, and each Actor
        decided the rest for themselves - which is the same Pull Principle
        the model already applies to roles.
        """
        identity = self.runtime(9630)
        first = self.runtime(9631)
        second = self.runtime(9632)
        team_uuid = identity.logic.create_team("Open membership").value
        type_uuid = self.a_membership_type(identity, team_uuid)
        for observer in (first, second):
            connect(identity, observer, team_uuid)
            observer.logic.accept_team_invitation(
                observer.session.protocol.index[team_uuid],
            )
        sync(identity, first, second)

        team = identity.session.protocol.index[team_uuid]
        # Everybody on the channel who is not on the team is the pool. There
        # is nothing to be let into and nothing to apply for.
        self.assertCountEqual(
            identity.logic.onboarding_pool_uuids(team),
            [first.session.identity.uuid, second.session.identity.uuid],
        )

        opened = identity.logic.open_membership_invitation(
            team_uuid, type_uuid, self.FAR_FUTURE,
        )
        self.assertEqual(opened.status, "ok")
        # One at a time per type, and the chain is what enforces it.
        self.assertEqual(identity.logic.open_membership_invitation(
            team_uuid, type_uuid, self.FAR_FUTURE,
        ).status, "error")
        sync(identity, first, second)

        taken = self.apply_and_issue(
            identity, first, team_uuid, opened.value.uuid,
            agreement_accepted=True, acceptance_text="Accepted.",
        )
        self.assertEqual(taken.status, "ok")
        sync(identity, first, second)

        self.assertEqual(identity.logic.close_membership_invitation(
            team_uuid, type_uuid,
        ).status, "ok")
        sync(identity, first, second)
        # Second never answered, and the door is shut. Their own act was the
        # only thing that could have put them on the team.
        late = second.logic.apply_for_membership(
            team_uuid, opened.value.uuid, agreement_accepted=True,
            acceptance_text="Accepted.",
        )
        self.assertEqual(late.status, "error")

        identity_team = identity.session.protocol.index[team_uuid]
        first_team = first.session.protocol.index[team_uuid]
        second_team = second.session.protocol.index[team_uuid]
        self.assertTrue(identity.logic._is_current_member(
            identity_team, first.session.identity.uuid,
        ))
        self.assertTrue(first.logic._has_current_acceptance(first_team))
        self.assertFalse(second.logic._has_current_acceptance(second_team))
        self.assertIn(
            first.session.identity.uuid,
            identity.logic.actor_uuids(identity_team),
        )
        self.assertEqual(
            identity.logic.onboarding_pool_uuids(identity_team),
            [second.session.identity.uuid],
        )
        first_participant = next(
            person for person in identity.logic.participants(team_uuid)
            if person["uuid"] == first.session.identity.uuid
        )
        self.assertFalse(first_participant["is_observer"])
        # Membership is a fact about the person, not a badge among their
        # roles - they hold none, and are on the team all the same.
        self.assertTrue(first_participant["is_member"])
        self.assertEqual(first_participant["membership"], "accepted")
        self.assertEqual(first_participant["roles"], [])

    def test_an_expired_window_shuts_the_door_with_nobody_touching_it(self):
        """Whether an invitation was live is read from recorded values on
        both sides - never from the clock at read time - so two replicas
        always agree, and an answer that was valid when made stays valid
        however late it arrives."""
        identity = self.runtime(9633)
        observer = self.runtime(9634)
        team_uuid = identity.logic.create_team("Guarded membership").value
        type_uuid = self.a_membership_type(identity, team_uuid)
        connect(identity, observer, team_uuid)
        observer.logic.accept_team_invitation(
            observer.session.protocol.index[team_uuid],
        )
        sync(identity, observer)
        team = identity.session.protocol.index[team_uuid]

        # An expiry already behind us would open a door nobody could walk
        # through, so it is refused rather than written.
        self.assertEqual(identity.logic.open_membership_invitation(
            team_uuid, type_uuid, "2020-01-01T00:00:00+00:00",
        ).status, "error")

        opened = identity.logic.open_membership_invitation(
            team_uuid, type_uuid, self.FAR_FUTURE,
        )
        sync(identity, observer)

        # Not on the team yet, so there is no role to take. Membership is
        # the entitlement and it has not been taken up.
        role_uuid = identity.logic.create_role(team_uuid, "Treasurer").value
        sync(identity, observer)
        self.adopt(observer, identity, role_uuid)
        self.assertEqual(
            observer.logic.decide_role(role_uuid, "accepted").status, "error",
        )

        # An application dated outside the window is refused on the record, not
        # on the reader's clock.
        observer_team = observer.session.protocol.index[team_uuid]
        membership_type = observer.logic._node(
            type_uuid, "team_membership_type",
        )
        agreement = observer.logic.agreement_projection(observer_team)
        stale = observer.logic.append_governance_record(team_uuid, {
            "type": "team_membership_application",
            "actor_uuid": observer.session.identity.uuid,
            "membership_type_uuid": type_uuid,
            "previous_membership_uuid": "",
            "invitation_uuid": opened.value.uuid,
            "applied_at": "2020-01-01T00:00:00+00:00",
            "membership_info": membership_type.data["requirements"],
            "acceptance_requirement": membership_type.data["acceptance"],
            "acceptance_text": "Accepted too late.",
            "agreement_accepted": True,
            "agreement_version": agreement["version"],
            "reference_hash": agreement["reference_hash"],
        })
        self.assertEqual(stale.status, "error")
        self.assertIn("not open when the Actor applied", stale.reason)

        self.assertEqual(self.apply_and_issue(
            identity, observer, team_uuid, opened.value.uuid,
            agreement_accepted=True, acceptance_text="Accepted.",
        ).status, "ok")
        self.assertEqual(
            observer.logic.decide_role(role_uuid, "accepted").status, "ok",
        )

    def test_deleting_a_membership_type_returns_its_members_to_the_pool(self):
        """No cascade, and no record rewritten. Standing is the pair "the
        chain says member" and "the type it names still exists", so the type
        going away is enough - and the trail still says what everybody was.
        """
        identity = self.runtime(9694)
        member = self.runtime(9695)
        team_uuid = identity.logic.create_team("Two memberships").value
        connect(identity, member, team_uuid)
        self.admit(identity, member, team_uuid, name="Associate")
        who = member.session.identity.uuid

        team = identity.session.protocol.index[team_uuid]
        associate = next(
            node for node in identity.logic.membership_types(team)
            if node.data["name"] == "Associate"
        )
        role_uuid = identity.logic.create_role(team_uuid, "Treasurer").value
        sync(identity, member)
        self.adopt(member, identity, role_uuid)
        self.assertEqual(
            member.logic.decide_role(role_uuid, "accepted").status, "ok",
        )
        sync(identity, member)
        self.assertTrue(identity.logic._is_current_member(
            identity.session.protocol.index[team_uuid], who,
        ))

        before = len(identity.logic.membership_records(
            identity.session.protocol.index[team_uuid], who,
        ))
        self.assertEqual(
            identity.logic.delete_membership_type(associate.uuid).status, "ok",
        )
        sync(identity, member)

        team = identity.session.protocol.index[team_uuid]
        self.assertFalse(identity.logic._is_current_member(team, who))
        self.assertIn(who, identity.logic.onboarding_pool_uuids(team))
        # Their roles go with the membership. The record of what they
        # answered is untouched - nothing is written into it, and taking a
        # membership up again brings the holding back - but a role is work a
        # *member* holds, so while the membership is gone it holds nothing.
        theirs = next(
            person for person in identity.logic.participants(team_uuid)
            if person["uuid"] == who
        )
        self.assertFalse(theirs["is_member"])
        self.assertEqual(theirs["membership"], "pool")
        self.assertEqual(theirs["roles"], [])
        # The answer is still on the record - read where it was written,
        # which is the only replica that can vouch for it - and that is what
        # lets the holding come back rather than being re-answered.
        self.assertTrue(any(
            child.data.get("actor_uuid") == who
            and child.data.get("decision") == "accepted"
            for child in member.logic._held(
                member.logic._node(role_uuid, "team_role"), "answers",
            )
        ))
        self.assertEqual(
            len(identity.logic.membership_records(team, who)), before,
        )

    def test_only_an_agreement_version_change_outdates_membership(self):
        """Identity marks substantial change by updating the version.

        The exact hash remains on the application and badge for audit, but
        same-version text edits neither invalidate an application nor make
        an issued badge outdated.
        """
        runtime = self.runtime(9696)
        team_uuid = runtime.logic.create_team("Living document").value
        who = runtime.session.identity.uuid
        team = runtime.session.protocol.index[team_uuid]
        self.assertEqual(runtime.logic.membership_status(team, who), "accepted")

        runtime.logic.rename_agreement(team_uuid, "Team Agreement")
        runtime.logic.set_agreement_version(team_uuid, "1")
        section = runtime.logic.create_section(team_uuid, "Purpose")
        runtime.logic.create_clause(section.value, "We do the work.")

        team = runtime.session.protocol.index[team_uuid]
        self.assertEqual(runtime.logic.membership_status(team, who), "outdated")
        # Still a member: outdated asks for renewal; it is not removal.
        self.assertTrue(runtime.logic._is_current_member(team, who))

        type_uuid = runtime.logic.membership_types(team)[0].uuid
        runtime.logic.set_membership_acceptance(
            type_uuid, "Confirm the revised Agreement.",
        )
        invitation = runtime.logic.open_membership_invitation(
            team_uuid, type_uuid, self.FAR_FUTURE,
        )
        application = runtime.logic.apply_for_membership(
            team_uuid, invitation.value.uuid,
            agreement_accepted=True, acceptance_text="Accepted again.",
        )
        self.assertEqual(application.status, "ok", application.reason)
        runtime.logic.create_clause(section.value, "This clarification is minor.")
        issued = runtime.logic.issue_membership_badge(
            team_uuid, application.value.uuid,
        )
        self.assertEqual(issued.status, "ok", issued.reason)
        team = runtime.session.protocol.index[team_uuid]
        self.assertEqual(runtime.logic.membership_status(team, who), "accepted")

        runtime.logic.create_clause(section.value, "Another minor clarification.")
        team = runtime.session.protocol.index[team_uuid]
        self.assertEqual(runtime.logic.membership_status(team, who), "accepted")

        runtime.logic.set_agreement_version(team_uuid, "2")
        team = runtime.session.protocol.index[team_uuid]
        self.assertEqual(runtime.logic.membership_status(team, who), "outdated")

    def test_a_member_of_one_type_moves_to_another_on_the_same_chain(self):
        """An Actor is on one membership type at a time, so taking a second
        continues the line rather than starting one beside it - which is what
        lets a second root keep meaning two replicas at once."""
        runtime = self.runtime(9697)
        team_uuid = runtime.logic.create_team("Two tiers").value
        who = runtime.session.identity.uuid
        runtime.logic.rename_agreement(team_uuid, "Team Agreement")
        runtime.logic.set_agreement_version(team_uuid, "1")
        runtime.logic.create_section(team_uuid, "Agreement terms")
        associate = runtime.logic.create_membership_type(
            team_uuid, "Associate", "Turns up",
            "I accept these membership conditions.",
        ).value.uuid
        invitation = runtime.logic.open_membership_invitation(
            team_uuid, associate, self.FAR_FUTURE,
        )

        moved = self.apply_and_issue(
            runtime, runtime, team_uuid, invitation.value.uuid,
            agreement_accepted=True, acceptance_text="Accepted.",
        )

        self.assertEqual(moved.status, "ok")
        team = runtime.session.protocol.index[team_uuid]
        projection = runtime.logic.membership_projection(team, who)
        self.assertEqual(projection["state"], "member")
        self.assertEqual(projection["membership_type_uuid"], associate)
        roots = [
            record for record in runtime.logic.membership_records(team, who)
            if not record.data.get("previous_membership_uuid")
        ]
        self.assertEqual(len(roots), 1)
        # And not twice onto the same one.
        self.assertEqual(runtime.logic.apply_for_membership(
            team_uuid, invitation.value.uuid, agreement_accepted=True,
            acceptance_text="Accepted.",
        ).status, "error")

    def test_concurrent_trustee_successors_expose_conflict_and_keep_incumbent(self):
        runtime = self.runtime(9625)
        team_uuid = runtime.logic.create_team("Concurrent authority").value
        actor_uuid = runtime.session.identity.uuid
        genesis_uuid = self.governance_basis(runtime, team_uuid)
        first = {
            "type": "team_trustee_state",
            "trust": "identity",
            "holder_actor_uuid": "",
            "previous_state_uuid": genesis_uuid,
            "cause": "resignation",
            "acted_by": actor_uuid,
            "acted_at": "2026-08-04T10:02:00+00:00",
            "authority_basis_uuid": genesis_uuid,
            "signals": "First concurrent signal",
            "consideration": "Resignation branch one",
            "expectation": "A successor will be elected",
        }
        second = dict(first)
        second["acted_at"] = "2026-08-04T10:02:01+00:00"
        second["signals"] = "Second concurrent signal"

        one = runtime.logic.append_governance_record(team_uuid, first)
        two = runtime.logic.append_governance_record(team_uuid, second)
        self.assertEqual((one.status, two.status), ("ok", "ok"))
        projection = runtime.logic.trustee_projection(
            runtime.session.protocol.index[team_uuid], "identity",
        )
        self.assertEqual(projection["state"], "contested")
        self.assertEqual(projection["current_state_uuid"], genesis_uuid)
        self.assertEqual(projection["holder_actor_uuid"], actor_uuid)
        self.assertCountEqual(
            projection["contenders"], [one.value.uuid, two.value.uuid],
        )

    def test_a_divergence_says_what_differs_not_only_that_it_does(self):
        # Core composes the divergence sentence from these records. Without
        # them it falls back to "Missing in <peer>", which tells the reader
        # something differs while withholding what - and names the peer by
        # its raw relay address for want of anything better.
        left, right = self.runtime(9603), self.runtime(9604)
        team_uuid = left.logic.create_team("Charter").value
        connect(left, right, team_uuid)
        right.logic.accept_team_invitation(
            right.session.protocol.index[team_uuid],
        )
        sync(left, right)
        section_uuid = left.logic.create_section(
            team_uuid, "Purpose",
        ).value
        sync(left, right)

        incoming = next(
            event
            for event in right.logic.transition_events(team_uuid)
            if event["node_uuid"] == section_uuid
        )
        change = incoming["changes"][0]
        self.assertEqual(change["node_label"], "Section")
        self.assertEqual(change["authored_act"], "created")

        # A text edit names the field rather than calling it "an item".
        left.logic.rename_section(section_uuid, "Why we are here")
        right.logic.accept_peer_node(left.peer_addr, section_uuid)
        sync(left, right)
        left.logic.rename_section(section_uuid, "What we are for")
        sync(left, right)
        edited = next(
            event
            for event in right.logic.transition_events(team_uuid)
            if event["node_uuid"] == section_uuid
        )
        self.assertEqual(
            [change["authored_detail"] for change in edited["changes"]],
            ["title changed"],
        )

    @staticmethod
    def relay_config(relay_root: str, identity: str, state_dir: str) -> dict:
        return {
            "relay_root": relay_root,
            "relay_identity": identity,
            "relay_state_file": str(Path(state_dir) / f"state-{identity}.json"),
        }

    def relay_root(self) -> str:
        """One folder for every client in a test. A client never polls a
        topic it was not given, so sharing the folder shares nothing."""
        if not getattr(self, "_relay_root", None):
            directory = tempfile.TemporaryDirectory()
            self.addCleanup(directory.cleanup)
            self._relay_root = directory.name
        return self._relay_root

    def runtime(self, port: int):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        config = app_server.load_config(None, "team", {
            "team": {
                "app_module": "s_team.application",
                "application_id": "team",
                "asset_package": "s_team.assets",
                "ui_file": "team.html",
                "css_file": "team.css",
            },
        })
        config["storage_file"] = str(Path(directory.name) / f"{port}.json")
        config["relay_state_directory"] = str(Path(directory.name) / "relay")
        runtime = app_server.create_runtime(port, config)
        runtime._test_tmp = directory
        created = runtime.relay_manager.create_target({
            "name": f"relay {port}", "backend": "local", "root": self.relay_root(),
        })
        if created.status != "ok":
            raise RuntimeError(created.reason)
        runtime.relay_target = created.value
        runtime.relay = runtime.relay_manager.connection_for_target(created.value)
        # How the other client's registries name this one: a relay peer is a
        # publication identity, not an address anybody can reach.
        runtime.peer_addr = f"relay:{runtime.relay.identity}"
        return runtime


if __name__ == "__main__":
    unittest.main()
