"""Starlette controller for the minimal S-Team view."""

from __future__ import annotations

from sovereign import application_json_response
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route


def build_routes(logic, runtime) -> list[Route]:
    async def api_document(request: Request):
        requested = request.query_params.get("team_uuid")
        # Taking part in an election is what being a member means here, so
        # a member's client asks for the process rather than waiting to be
        # told to. Before the read and not inside it: following a topic
        # takes a lock that may not be held under Session's.
        logic.adopt_live_elections()
        # Identity-owned membership definitions also reconcile on the read
        # cycle. A non-Identity local rewrite produces no new inbound packet
        # from Identity, so relying only on peer-update callbacks would leave
        # that unauthorized copy visible indefinitely.
        logic.reconcile_governance_updates()
        return runtime.composite_response(
            lambda: logic.document_snapshot(requested),
            lambda snapshot: runtime.collaboration.network_info(
                snapshot.get("topic_uuid"),
            ),
            logic.merge_document_observation,
        )

    async def api_create_team(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.create_team(data.get("title", "")))

    async def api_create_subteam(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.create_subteam(
            data["parent_team_uuid"], data.get("title", ""),
        ))

    async def api_clone_team(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.clone_team(
            data["team_uuid"], data.get("title"),
        ))

    async def api_select_team(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.select_team(data["team_uuid"]))

    async def api_delete_team(request: Request):
        data = await request.json()
        return await _json_result(
            runtime, logic.delete_team(data["team_uuid"]),
        )

    async def api_archive_team(request: Request):
        data = await request.json()
        return await _json_result(
            runtime, logic.archive_team(data["team_uuid"]),
        )

    async def api_restore_team(request: Request):
        data = await request.json()
        return await _json_result(
            runtime, logic.restore_team(data.get("file", "")),
        )

    async def api_create_section(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.create_section(
            data["team_uuid"], data.get("title", ""),
        ))

    async def api_create_clause(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.create_clause(
            data["section_uuid"], data.get("text", ""),
        ))

    async def api_update_clause(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.update_clause(
            data["clause_uuid"], data.get("text", ""),
        ))

    async def api_rename_team(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.rename_team(
            data["team_uuid"], data.get("title", ""),
        ))

    async def api_rename_agreement(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.rename_agreement(
            data["team_uuid"], data.get("title", ""),
        ))

    async def api_set_agreement_version(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.set_agreement_version(
            data["team_uuid"], data.get("version", ""),
        ))

    async def api_rename_section(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.rename_section(
            data["section_uuid"], data.get("title", ""),
        ))

    async def api_delete_section(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.delete_section(data["section_uuid"]))

    async def api_move_section(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.move_section(
            data["section_uuid"], int(data.get("index", 0)),
        ))

    async def api_move_clause(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.move_clause(
            data["clause_uuid"], int(data.get("index", 0)),
        ))

    async def api_delete_clause(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.delete_clause(data["clause_uuid"]))

    async def api_take_identity(request: Request):
        data = await request.json()
        return await _json_result(
            runtime, logic.take_identity(data["team_uuid"]),
        )

    async def api_offer_identity(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.offer_identity(
            data["team_uuid"], data.get("actor_uuid", ""),
        ))

    async def api_resign_identity(request: Request):
        data = await request.json()
        return await _json_result(
            runtime, logic.resign_identity(data["team_uuid"]),
        )

    async def api_resign_trusteeship(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.resign_trusteeship(
            data["team_uuid"], data.get("trust", ""),
            data.get("signals", ""), data.get("consideration", ""),
            data.get("expectation", ""),
        ))

    async def api_enter_trustee_candidacy(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.enter_trustee_candidacy(
            data["team_uuid"], data.get("trust", ""),
        ))

    async def api_withdraw_trustee_candidacy(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.withdraw_trustee_candidacy(
            data["team_uuid"], data["candidacy_uuid"],
        ))

    async def api_record_trustee_action(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.record_trustee_action(
            data["team_uuid"], data.get("trust", ""),
            data.get("subject_uuid", ""), data.get("payload"),
            data.get("signals", ""), data.get("consideration", ""),
            data.get("expectation", ""),
            data.get("action_kind", "domain_action"),
        ))

    async def api_append_trustee_reality(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.append_trustee_reality(
            data["team_uuid"], data["action_uuid"],
            data.get("reality", ""),
        ))

    async def api_create_membership_type(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.create_membership_type(
            data["team_uuid"], data.get("name", ""),
            data.get("requirements", ""), data.get("acceptance", ""),
        ))

    async def api_rename_membership_type(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.rename_membership_type(
            data["membership_type_uuid"], data.get("name", ""),
        ))

    async def api_set_membership_requirements(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.set_membership_requirements(
            data["membership_type_uuid"], data.get("requirements", ""),
        ))

    async def api_set_membership_acceptance(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.set_membership_acceptance(
            data["membership_type_uuid"], data.get("acceptance", ""),
        ))

    async def api_delete_membership_type(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.delete_membership_type(
            data["membership_type_uuid"],
        ))

    async def api_open_membership(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.open_membership_invitation(
            data["team_uuid"], data["membership_type_uuid"],
            data.get("expires_at", ""),
        ))

    async def api_close_membership(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.close_membership_invitation(
            data["team_uuid"], data["membership_type_uuid"],
        ))

    async def api_apply_for_membership(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.apply_for_membership(
            data["team_uuid"], data["invitation_uuid"],
            data.get("agreement_accepted") is True,
            data.get("acceptance_text", ""),
        ))

    async def api_issue_membership_badge(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.issue_membership_badge(
            data["team_uuid"], data["application_uuid"],
        ))

    async def api_end_membership(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.end_membership(
            data["team_uuid"], data.get("actor_uuid", ""),
            data.get("signals", ""), data.get("consideration", ""),
            data.get("expectation", ""),
        ))

    async def api_leave_team(request: Request):
        data = await request.json()
        return await _json_result(
            runtime, logic.leave_team(data["team_uuid"]),
        )

    async def api_start_trustee_election(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.start_trustee_election(
            data["team_uuid"], data.get("trust", ""),
            data.get("facilitator_actor_uuid", ""),
        ))

    async def api_settle_trusteeship(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.settle_trusteeship(
            data["team_uuid"], data.get("trust", ""),
            data.get("holder_actor_uuid", ""),
            data.get("process_uuid", ""),
            data.get("signals", ""), data.get("consideration", ""),
            data.get("expectation", ""),
        ))

    async def api_create_role(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.create_role(
            data["team_uuid"], data.get("name", ""),
        ))

    async def api_rename_role(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.rename_role(
            data["role_uuid"], data.get("name", ""),
        ))

    async def api_role_purpose(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.set_role_purpose(
            data["role_uuid"], data.get("purpose", ""),
        ))

    async def api_delete_role(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.delete_role(data["role_uuid"]))

    async def api_move_role(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.move_role(
            data["role_uuid"], int(data.get("index", 0)),
        ))

    async def api_decide_role(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.decide_role(
            data["role_uuid"],
            data.get("decision", ""),
            data.get("expires_at"),
        ))

    async def api_resign_role(request: Request):
        data = await request.json()
        return await _json_result(
            runtime, logic.resign_role(data["role_uuid"]),
        )

    async def api_seat_team(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.seat_team(
            data["role_uuid"], data.get("team_uuid", ""),
        ))

    async def api_create_item(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.create_team_item(
            data["team_uuid"],
            data.get("application_id", ""),
            data.get("title", ""),
            data.get("template", ""),
        ))

    async def api_offer_item(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.offer_team_item(
            data["team_uuid"], data.get("topic_uuid", ""),
        ))

    async def api_connect_item(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.connect_team_item(
            data["team_uuid"], data.get("topic_uuid", ""),
        ))

    async def api_remove_item(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.remove_team_item(
            data["team_uuid"], data.get("topic_uuid", ""),
        ))

    async def api_unseat_team(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.unseat_team(
            data["role_uuid"], data.get("team_uuid", ""),
        ))

    async def api_create_seated_team(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.create_seated_team(
            data["role_uuid"], data.get("title", ""),
        ))

    async def api_move_parent(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.move_parent_holding(
            data["holding_uuid"], int(data.get("index", 0)),
        ))

    async def api_create_role_item(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.create_role_item(
            data["role_uuid"], data.get("kind", ""), data.get("text", ""),
        ))

    async def api_update_role_item(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.update_role_item(
            data["item_uuid"], data.get("text", ""),
        ))

    async def api_delete_role_item(request: Request):
        data = await request.json()
        return await _json_result(
            runtime, logic.delete_role_item(data["item_uuid"]),
        )

    async def api_move_role_item(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.move_role_item(
            data["item_uuid"], int(data.get("index", 0)),
        ))

    async def api_agenda_create(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.create_agenda_item(
            data["team_uuid"], data.get("text", ""), data.get("priority"),
        ))

    async def api_agenda_delete(request: Request):
        data = await request.json()
        return await _json_result(
            runtime, logic.delete_agenda_item(data["item_uuid"]),
        )

    async def api_agenda_priority(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.set_agenda_item_priority(
            data["item_uuid"], data.get("priority"),
        ))

    async def api_agenda_move(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.move_agenda_item(
            data["item_uuid"], int(data.get("index", 0)),
        ))

    async def api_react(request: Request):
        data = await request.json()
        reaction = data.get("reaction", "adopt")
        node_uuid = data["node_uuid"]
        source_addr = data["source_addr"]
        absent = bool(data.get("absent"))
        if reaction == "rollback":
            result = logic.rollback_peer_node(source_addr, node_uuid, absent)
        else:
            result = logic.accept_peer_node(source_addr, node_uuid, absent)
        return await _json_result(runtime, result)

    async def api_adopt(request: Request):
        data = await request.json()
        return await _json_result(runtime, logic.adopt_peer_changes(
            data["source_addr"], data["team_uuid"],
        ))

    return [
        Route("/api/team/document", api_document),
        Route("/api/team/teams/create", api_create_team, methods=["POST"]),
        Route(
            "/api/team/teams/create_subteam",
            api_create_subteam,
            methods=["POST"],
        ),
        Route(
            "/api/team/teams/clone",
            api_clone_team,
            methods=["POST"],
        ),
        Route("/api/team/teams/select", api_select_team, methods=["POST"]),
        Route("/api/team/teams/rename", api_rename_team, methods=["POST"]),
        Route("/api/team/teams/delete", api_delete_team, methods=["POST"]),
        Route("/api/team/teams/archive", api_archive_team, methods=["POST"]),
        Route("/api/team/teams/restore", api_restore_team, methods=["POST"]),
        Route(
            "/api/team/agreement/rename",
            api_rename_agreement,
            methods=["POST"],
        ),
        Route(
            "/api/team/agreement/version",
            api_set_agreement_version,
            methods=["POST"],
        ),
        Route("/api/team/sections/create", api_create_section, methods=["POST"]),
        Route("/api/team/sections/rename", api_rename_section, methods=["POST"]),
        Route("/api/team/sections/delete", api_delete_section, methods=["POST"]),
        Route("/api/team/sections/move", api_move_section, methods=["POST"]),
        Route("/api/team/clauses/move", api_move_clause, methods=["POST"]),
        Route("/api/team/clauses/create", api_create_clause, methods=["POST"]),
        Route("/api/team/clauses/update", api_update_clause, methods=["POST"]),
        Route("/api/team/clauses/delete", api_delete_clause, methods=["POST"]),
        Route(
            "/api/team/identity/take", api_take_identity, methods=["POST"],
        ),
        Route(
            "/api/team/identity/offer",
            api_offer_identity,
            methods=["POST"],
        ),
        Route(
            "/api/team/identity/resign",
            api_resign_identity,
            methods=["POST"],
        ),
        Route(
            "/api/team/trusteeships/resign",
            api_resign_trusteeship,
            methods=["POST"],
        ),
        Route(
            "/api/team/trusteeships/candidacy/enter",
            api_enter_trustee_candidacy,
            methods=["POST"],
        ),
        Route(
            "/api/team/trusteeships/candidacy/withdraw",
            api_withdraw_trustee_candidacy,
            methods=["POST"],
        ),
        Route(
            "/api/team/trusteeships/actions/record",
            api_record_trustee_action,
            methods=["POST"],
        ),
        Route(
            "/api/team/trusteeships/actions/reality",
            api_append_trustee_reality,
            methods=["POST"],
        ),
        Route(
            "/api/team/memberships/create", api_create_membership_type,
            methods=["POST"],
        ),
        Route(
            "/api/team/memberships/rename", api_rename_membership_type,
            methods=["POST"],
        ),
        Route(
            "/api/team/memberships/requirements",
            api_set_membership_requirements,
            methods=["POST"],
        ),
        Route(
            "/api/team/memberships/acceptance", api_set_membership_acceptance,
            methods=["POST"],
        ),
        Route(
            "/api/team/memberships/delete", api_delete_membership_type,
            methods=["POST"],
        ),
        Route(
            "/api/team/membership/open", api_open_membership,
            methods=["POST"],
        ),
        Route(
            "/api/team/membership/close", api_close_membership,
            methods=["POST"],
        ),
        Route(
            "/api/team/membership/apply", api_apply_for_membership,
            methods=["POST"],
        ),
        Route(
            "/api/team/membership/issue", api_issue_membership_badge,
            methods=["POST"],
        ),
        Route(
            "/api/team/membership/end", api_end_membership,
            methods=["POST"],
        ),
        Route(
            "/api/team/membership/leave", api_leave_team,
            methods=["POST"],
        ),
        Route(
            "/api/team/elections/start", api_start_trustee_election,
            methods=["POST"],
        ),
        Route(
            "/api/team/trusteeships/settle", api_settle_trusteeship,
            methods=["POST"],
        ),
        Route("/api/team/roles/create", api_create_role, methods=["POST"]),
        Route("/api/team/roles/rename", api_rename_role, methods=["POST"]),
        Route(
            "/api/team/roles/set_purpose",
            api_role_purpose,
            methods=["POST"],
        ),
        Route("/api/team/roles/delete", api_delete_role, methods=["POST"]),
        Route("/api/team/roles/move", api_move_role, methods=["POST"]),
        Route("/api/team/roles/seat", api_seat_team, methods=["POST"]),
        Route(
            "/api/team/roles/unseat",
            api_unseat_team,
            methods=["POST"],
        ),
        Route(
            "/api/team/roles/seat_new",
            api_create_seated_team,
            methods=["POST"],
        ),
        Route("/api/team/items/create", api_create_item, methods=["POST"]),
        Route("/api/team/items/offer", api_offer_item, methods=["POST"]),
        Route("/api/team/items/connect", api_connect_item, methods=["POST"]),
        Route("/api/team/items/remove", api_remove_item, methods=["POST"]),
        Route("/api/team/parents/move", api_move_parent, methods=["POST"]),
        Route("/api/team/roles/decide", api_decide_role, methods=["POST"]),
        Route("/api/team/roles/resign", api_resign_role, methods=["POST"]),
        Route(
            "/api/team/roles/items/create",
            api_create_role_item,
            methods=["POST"],
        ),
        Route(
            "/api/team/roles/items/update",
            api_update_role_item,
            methods=["POST"],
        ),
        Route(
            "/api/team/roles/items/delete",
            api_delete_role_item,
            methods=["POST"],
        ),
        Route(
            "/api/team/roles/items/move",
            api_move_role_item,
            methods=["POST"],
        ),
        Route("/api/team/agenda/create", api_agenda_create, methods=["POST"]),
        Route("/api/team/agenda/delete", api_agenda_delete, methods=["POST"]),
        Route("/api/team/agenda/set_priority", api_agenda_priority, methods=["POST"]),
        Route("/api/team/agenda/move", api_agenda_move, methods=["POST"]),
        Route("/api/team/react", api_react, methods=["POST"]),
        Route("/api/team/adopt", api_adopt, methods=["POST"]),
    ]


async def _json_result(runtime, result) -> JSONResponse:
    return await application_json_response(runtime, result)
