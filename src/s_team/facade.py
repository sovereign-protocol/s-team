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

    def take_identity(self, team_uuid: str):
        return self._logic.take_identity(team_uuid)

    def offer_identity(self, team_uuid: str, actor_uuid: str):
        return self._logic.offer_identity(team_uuid, actor_uuid)

    def resign_identity(self, team_uuid: str):
        return self._logic.resign_identity(team_uuid)

    def roles(self, team: ProtocolNode) -> list[ProtocolNode]:
        return self._logic.roles(team)

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
