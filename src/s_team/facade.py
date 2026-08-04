"""Versioned public query/command facade exposed by S-Team.

Mirrors S-Initiative's facade: a stable, explicitly versioned surface an
aggregator like S-Cockpit can consume without importing this package.
"""

from __future__ import annotations

from sovereign import ProtocolNode

from .logic import TeamLogic


TEAM_FACADE_API_VERSION = 1


class TeamFacade:
    """Stable facade returning detached node snapshots and command results."""

    def __init__(self, logic: TeamLogic):
        self._logic = logic

    def teams(self) -> list[ProtocolNode]:
        return self._logic.teams()

    def sections(self, team: ProtocolNode) -> list[ProtocolNode]:
        return self._logic.sections(team)

    def clauses(self, section: ProtocolNode) -> list[ProtocolNode]:
        return self._logic.clauses(section)

    def parent_holdings(self, team: ProtocolNode) -> list[ProtocolNode]:
        return self._logic.parent_holdings(team)

    def child_teams(
        self, team: ProtocolNode,
    ) -> list[tuple[str, ProtocolNode]]:
        return self._logic.child_teams(team)

    def identity_holder(self, team: ProtocolNode) -> str:
        return self._logic.identity_holder(team)

    def identity(self, team: ProtocolNode) -> dict:
        return self._logic.identity_payload(team)

    def trust_holder(self, team: ProtocolNode) -> str:
        return self._logic.trust_holder(team)

    def trust(self, team: ProtocolNode) -> dict:
        return self._logic.trust_payload(team)

    def take_identity(self, team_uuid: str):
        return self._logic.take_identity(team_uuid)

    def offer_identity(self, team_uuid: str, actor_uuid: str):
        return self._logic.offer_identity(team_uuid, actor_uuid)

    def resign_identity(self, team_uuid: str):
        return self._logic.resign_identity(team_uuid)

    def roles(self, team: ProtocolNode) -> list[ProtocolNode]:
        return self._logic.roles(team)

    def member_role(self, team: ProtocolNode) -> ProtocolNode | None:
        return self._logic.member_role(team)

    def membership(self, team: ProtocolNode) -> dict:
        return self._logic.membership_payload(team)

    def verify_flow_decision_result(
        self,
        process_uuid: str,
        expected_result_hash: str | None = None,
        expected_definition_id: str = "integrative-election",
        expected_definition_version: str | None = None,
    ) -> dict:
        return self._logic.verify_flow_decision_result(
            process_uuid,
            expected_result_hash,
            expected_definition_id,
            expected_definition_version,
        )

    def start_trustee_election(
        self, team_uuid: str, trust: str, facilitator_actor_uuid: str = "",
    ):
        return self._logic.start_trustee_election(
            team_uuid, trust, facilitator_actor_uuid,
        )

    def implement_trustee_election(
        self, team_uuid: str, election_uuid: str,
        signals: str = "", consideration: str = "", expectation: str = "",
    ):
        return self._logic.implement_trustee_election(
            team_uuid, election_uuid, signals, consideration, expectation,
        )

    def trustee_elections(self, team: ProtocolNode) -> list[dict]:
        return self._logic.trustee_elections_payload(team)

    def enter_trustee_candidacy(self, team_uuid: str, trust: str):
        return self._logic.enter_trustee_candidacy(team_uuid, trust)

    def withdraw_trustee_candidacy(
        self, team_uuid: str, candidacy_uuid: str,
    ):
        return self._logic.withdraw_trustee_candidacy(
            team_uuid, candidacy_uuid,
        )

    def record_trustee_action(
        self, team_uuid: str, trust: str, subject_uuid: str,
        payload: dict | None = None, signals: str = "",
        consideration: str = "", expectation: str = "",
        action_kind: str = "domain_action",
    ):
        return self._logic.record_trustee_action(
            team_uuid, trust, subject_uuid, payload, signals,
            consideration, expectation, action_kind,
        )

    def append_trustee_reality(
        self, team_uuid: str, action_uuid: str, reality: str,
    ):
        return self._logic.append_trustee_reality(
            team_uuid, action_uuid, reality,
        )

    def trustee_actions(self, team: ProtocolNode) -> list[dict]:
        return self._logic.trustee_actions_payload(team)

    def pools(self) -> list[ProtocolNode]:
        return self._logic.pools()

    def pool(self, pool: ProtocolNode) -> dict:
        return self._logic.pool_payload(pool)

    def publish_pool_invitation(
        self, team_uuid: str, opening_uuid: str, expires_at: str = "",
    ):
        return self._logic.publish_pool_invitation(
            team_uuid, opening_uuid, expires_at,
        )

    def submit_pool_application(
        self, pool_uuid: str, invitation_uuid: str,
    ):
        return self._logic.submit_pool_application(
            pool_uuid, invitation_uuid,
        )

    def withdraw_pool_application(
        self, pool_uuid: str, application_uuid: str,
    ):
        return self._logic.withdraw_pool_application(
            pool_uuid, application_uuid,
        )

    def resolve_pool_application(
        self, pool_uuid: str, application_uuid: str, outcome: str,
        signals: str = "", consideration: str = "", expectation: str = "",
    ):
        return self._logic.resolve_pool_application(
            pool_uuid, application_uuid, outcome,
            signals, consideration, expectation,
        )

    def mount_accepted_team(
        self, pool_uuid: str, application_uuid: str,
    ):
        return self._logic.mount_accepted_team(
            pool_uuid, application_uuid,
        )

    def open_member_opening(self, team_uuid: str):
        return self._logic.open_member_opening(team_uuid)

    def close_member_opening(self, team_uuid: str, opening_uuid: str):
        return self._logic.close_member_opening(team_uuid, opening_uuid)

    def submit_member_application(self, team_uuid: str, opening_uuid: str):
        return self._logic.submit_member_application(team_uuid, opening_uuid)

    def withdraw_member_application(
        self, team_uuid: str, application_uuid: str,
    ):
        return self._logic.withdraw_member_application(
            team_uuid, application_uuid,
        )

    def resolve_member_application(
        self, team_uuid: str, application_uuid: str, outcome: str,
        signals: str = "", consideration: str = "", expectation: str = "",
    ):
        return self._logic.resolve_member_application(
            team_uuid, application_uuid, outcome,
            signals, consideration, expectation,
        )

    def accountabilities(self, role: ProtocolNode) -> list[ProtocolNode]:
        return self._logic.accountabilities(role)

    def domains(self, role: ProtocolNode) -> list[ProtocolNode]:
        return self._logic.domains(role)

    def role_offers(self, role: ProtocolNode) -> list[ProtocolNode]:
        return self._logic.role_offers(role)

    def role_holders(
        self, team: ProtocolNode, role: ProtocolNode,
    ) -> list[dict]:
        return self._logic.role_holders(team, role)

    def offer_role(self, role_uuid: str, actor_uuid: str):
        return self._logic.offer_role(role_uuid, actor_uuid)

    def revoke_role_offer(self, role_uuid: str, actor_uuid: str):
        return self._logic.revoke_role_offer(role_uuid, actor_uuid)

    def decide_role(
        self, role_uuid: str, decision: str, expires_at: str | None = None,
    ):
        return self._logic.decide_role(role_uuid, decision, expires_at)

    def resign_role(self, role_uuid: str):
        return self._logic.resign_role(role_uuid)

    def seat_team(self, role_uuid: str, team_uuid: str):
        return self._logic.seat_team(role_uuid, team_uuid)

    def decline_seat(self, role_uuid: str, team_uuid: str):
        return self._logic.decline_seat(role_uuid, team_uuid)

    def unseat_team(self, role_uuid: str, team_uuid: str):
        return self._logic.unseat_team(role_uuid, team_uuid)

    def seat_offers(self, team: ProtocolNode) -> list[dict]:
        return self._logic.seat_offers(team)

    def create_seated_team(self, role_uuid: str, title: str):
        return self._logic.create_seated_team(role_uuid, title)

    def parents(self, team: ProtocolNode) -> list[dict]:
        return self._logic.parent_payload(team)

    def home_parent_uuid(self, team: ProtocolNode) -> str:
        return self._logic.home_parent_uuid(team)

    def is_organization(self, team: ProtocolNode) -> bool:
        return self._logic.is_organization(team)

    def organization(self) -> dict:
        return self._logic.organization_payload()

    def participants(self, team_uuid: str) -> list[dict]:
        return self._logic.participants(team_uuid)

    def transition_events(
        self, team_uuid: str, network: dict | None = None,
    ) -> list[dict]:
        return self._logic.transition_events(team_uuid, network)

    def transition_by_node(self, events: list[dict]) -> dict:
        return self._logic.transition_by_node(events)

    def collaboration_context(
        self, topic_uuid: str, network: dict | None = None,
    ) -> dict:
        return self._logic.collaboration_context(topic_uuid, network)

    def create_team(self, title: str):
        return self._logic.create_team(title)

    def create_subteam(self, parent_team_uuid: str, title: str):
        return self._logic.create_subteam(parent_team_uuid, title)

    def clone_team(self, team_uuid: str, title: str | None = None):
        return self._logic.clone_team(team_uuid, title)

    def actor_uuids(self, team: ProtocolNode) -> set[str]:
        return self._logic.actor_uuids(team)

    def team_state(self, team: ProtocolNode) -> str:
        return self._logic.team_state(team)

    def delete_team(self, team_uuid: str):
        return self._logic.delete_team(team_uuid)

    def create_agenda_item(
        self, team_uuid: str, text: str, priority: str | None = None,
    ):
        return self._logic.create_agenda_item(
            team_uuid, text, priority,
        )

    def delete_agenda_item(self, item_uuid: str):
        return self._logic.delete_agenda_item(item_uuid)

    def set_agenda_item_priority(
        self, item_uuid: str, priority: str | None,
    ):
        return self._logic.set_agenda_item_priority(item_uuid, priority)

    def move_agenda_item(self, item_uuid: str, index: int):
        return self._logic.move_agenda_item(item_uuid, index)
