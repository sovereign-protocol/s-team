"""Versioned public query/command facade exposed by S-Team.

Mirrors S-Initiative's facade: a stable, explicitly versioned surface an
aggregator like S-Cockpit can consume without importing this package.
"""

from __future__ import annotations

from sovereign import ProtocolNode

from .logic import TeamLogic


TEAM_FACADE_API_VERSION = 2


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

    def membership(self, team: ProtocolNode) -> dict:
        return self._logic.membership_payload(team)

    def current_member_uuids(self, team: ProtocolNode) -> list[str]:
        """Who is on this team. The question other applications ask.

        `member_role` used to stand here, which handed out a node and left
        every caller to work out what holding it meant. Membership is a
        record now, so the answer is the answer.
        """
        return self._logic.current_member_uuids(team)

    def end_membership(
        self, team_uuid: str, actor_uuid: str, signals: str = "",
        consideration: str = "", expectation: str = "",
    ):
        return self._logic.end_membership(
            team_uuid, actor_uuid, signals, consideration, expectation,
        )

    def leave_team(self, team_uuid: str):
        return self._logic.leave_team(team_uuid)

    def start_trustee_election(
        self, team_uuid: str, trust: str, facilitator_actor_uuid: str = "",
    ):
        return self._logic.start_trustee_election(
            team_uuid, trust, facilitator_actor_uuid,
        )

    def settle_trusteeship(
        self, team_uuid: str, trust: str, holder_actor_uuid: str,
        process_uuid: str = "",
        signals: str = "", consideration: str = "", expectation: str = "",
    ):
        return self._logic.settle_trusteeship(
            team_uuid, trust, holder_actor_uuid, process_uuid,
            signals, consideration, expectation,
        )

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

    def onboarding_pool(self, team: ProtocolNode) -> list[str]:
        """Who is publishing on this team's channel without being on it."""
        return self._logic.onboarding_pool_uuids(team)

    def membership_types(self, team: ProtocolNode) -> list[ProtocolNode]:
        return self._logic.membership_types(team)

    def create_membership_type(
        self, team_uuid: str, name: str, requirements: str = "",
        acceptance: str = "",
    ):
        return self._logic.create_membership_type(
            team_uuid, name, requirements, acceptance,
        )

    def rename_membership_type(self, membership_type_uuid: str, name: str):
        return self._logic.rename_membership_type(membership_type_uuid, name)

    def set_membership_requirements(
        self, membership_type_uuid: str, requirements: str,
    ):
        return self._logic.set_membership_requirements(
            membership_type_uuid, requirements,
        )

    def set_membership_acceptance(
        self, membership_type_uuid: str, acceptance: str,
    ):
        return self._logic.set_membership_acceptance(
            membership_type_uuid, acceptance,
        )

    def delete_membership_type(self, membership_type_uuid: str):
        return self._logic.delete_membership_type(membership_type_uuid)

    def open_membership_invitation(
        self, team_uuid: str, membership_type_uuid: str, expires_at: str,
    ):
        return self._logic.open_membership_invitation(
            team_uuid, membership_type_uuid, expires_at,
        )

    def close_membership_invitation(
        self, team_uuid: str, membership_type_uuid: str,
    ):
        return self._logic.close_membership_invitation(
            team_uuid, membership_type_uuid,
        )

    def apply_for_membership(
        self, team_uuid: str, invitation_uuid: str,
        agreement_accepted: bool = False,
        acceptance_text: str = "",
    ):
        return self._logic.apply_for_membership(
            team_uuid, invitation_uuid, agreement_accepted, acceptance_text,
        )

    def issue_membership_badge(
        self, team_uuid: str, application_uuid: str,
    ):
        return self._logic.issue_membership_badge(
            team_uuid, application_uuid,
        )

    def accountabilities(self, role: ProtocolNode) -> list[ProtocolNode]:
        return self._logic.accountabilities(role)

    def domains(self, role: ProtocolNode) -> list[ProtocolNode]:
        return self._logic.domains(role)

    def role_holders(
        self, team: ProtocolNode, role: ProtocolNode,
    ) -> list[dict]:
        return self._logic.role_holders(team, role)

    def decide_role(
        self, role_uuid: str, decision: str, expires_at: str | None = None,
    ):
        return self._logic.decide_role(role_uuid, decision, expires_at)

    def resign_role(self, role_uuid: str):
        return self._logic.resign_role(role_uuid)

    def seat_team(self, role_uuid: str, team_uuid: str):
        return self._logic.seat_team(role_uuid, team_uuid)

    def unseat_team(self, role_uuid: str, team_uuid: str):
        return self._logic.unseat_team(role_uuid, team_uuid)

    def create_seated_team(self, role_uuid: str, title: str):
        return self._logic.create_seated_team(role_uuid, title)

    # What the team runs. Another application asking is asking what is on
    # this team's channel, which is where the answer lives - there is no
    # list of items to hand over, only the derivation.
    def items(self, team: ProtocolNode) -> list[dict]:
        return self._logic.team_items(team)

    def create_item(
        self, team_uuid: str, application_id: str, title: str,
        template: str = "",
    ):
        return self._logic.create_team_item(
            team_uuid, application_id, title, template,
        )

    def offer_item(self, team_uuid: str, topic_uuid: str):
        return self._logic.offer_team_item(team_uuid, topic_uuid)

    def connect_item(self, team_uuid: str, topic_uuid: str):
        return self._logic.connect_team_item(team_uuid, topic_uuid)

    def remove_item(self, team_uuid: str, topic_uuid: str):
        return self._logic.remove_team_item(team_uuid, topic_uuid)

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

    def update_agenda_item(self, item_uuid: str, text: str):
        return self._logic.update_agenda_item(item_uuid, text)

    def set_agenda_item_priority(
        self, item_uuid: str, priority: str | None,
    ):
        return self._logic.set_agenda_item_priority(item_uuid, priority)

    def move_agenda_item(self, item_uuid: str, index: int):
        return self._logic.move_agenda_item(item_uuid, index)
