"""Boundaries and packaging invariants for what S-Team ships.

Source scans rather than integration tests, so each assertion runs in the
repository owning the source it guards and fails in the pull request that
breaks it. Core, S-Initiative and S-Cockpit hold matching shares.

These matter more here than they did while S-Team lived inside Core.
Core's own suite scanned it as the shipped example; once it moved out, that
scan lost its subject and these took over.
"""

import ast
import importlib.metadata
import unittest
from importlib.resources import files
from pathlib import Path

import s_team
import sovereign


ROOT = Path(__file__).resolve().parents[1]
SOURCES = sorted((ROOT / "src").rglob("*.py"))
OTHER_APPLICATIONS = ("s_cockpit", "s_initiative")


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }


class PackagingTests(unittest.TestCase):
    def test_distribution_and_module_versions_agree(self):
        self.assertEqual(
            importlib.metadata.version("sovereign-team"), s_team.__version__,
        )

    def test_the_distribution_is_apache_licensed_like_every_application(self):
        # It carried Core's LGPL only because it lived inside Core's
        # repository, where NOTICE makes the repository licence the default
        # for examples. Moving out without this change would have shipped a
        # copyleft application while claiming the application licence.
        metadata = importlib.metadata.metadata("sovereign-team")
        declared = metadata.get("License-Expression") or metadata.get("License") or ""
        self.assertIn("Apache-2.0", declared)

    def test_installed_browser_assets_are_available(self):
        assets = files("s_team.assets")
        self.assertIn(
            "<!doctype html",
            assets.joinpath("team.html").read_text(encoding="utf-8"),
        )
        self.assertTrue(assets.joinpath("team.css").is_file())

    def test_package_sources_live_under_the_declared_src_root(self):
        # Asserting where the imported module loaded from only holds for an
        # editable install: CI installs a wheel, so __file__ points into
        # site-packages. The invariant is this repository's layout.
        self.assertTrue((ROOT / "src" / "s_team" / "__init__.py").is_file())
        self.assertFalse((ROOT / "s_team").exists())


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SOURCES, "no S-Team sources found")

    def test_imports_core_only_through_its_public_root(self):
        public_names = set(sovereign.__all__)
        for path in SOURCES:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            violations = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    violations.extend(
                        alias.name for alias in node.names
                        if alias.name == "sovereign"
                        or alias.name.startswith("sovereign.")
                    )
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if module.startswith("sovereign."):
                        violations.append(module)
                    elif module == "sovereign":
                        violations.extend(
                            f"sovereign.{alias.name}"
                            for alias in node.names
                            if alias.name == "*" or alias.name not in public_names
                        )
            self.assertEqual(violations, [], str(path))

    def test_does_not_import_another_application(self):
        for path in SOURCES:
            imports = imported_modules(path)
            self.assertFalse(any(
                name == package or name.startswith(f"{package}.")
                for name in imports
                for package in OTHER_APPLICATIONS
            ), str(path))

    def test_does_not_read_private_channel_services_from_config(self):
        for path in SOURCES:
            source = path.read_text(encoding="utf-8")
            self.assertNotIn('config.get("_channel_manager")', source, str(path))
            self.assertNotIn('config.get("_relay_manager")', source, str(path))
            self.assertNotIn("channel_manager", source, str(path))

    def test_does_not_read_mutable_session_registries(self):
        forbidden = {
            "peer_topic_sets", "peer_perspectives", "peer_identity_key",
            "active_topic_uuids", "app_metadata",
        }
        for path in SOURCES:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            used = {
                node.attr for node in ast.walk(tree)
                if isinstance(node, ast.Attribute)
            }
            self.assertFalse(used & forbidden, str(path))

    def test_reads_the_transition_ranking_rather_than_copying_it(self):
        # Kanban and Team had each copied Session's ranking and the
        # copies drifted: one ranked divergence 6, the other 5, so the same
        # conflict surfaced differently in each. Session owns the ranking.
        for path in SOURCES:
            source = path.read_text(encoding="utf-8")
            if "TRANSITION_PRIORITY" not in source:
                continue
            self.assertIn("Session.TRANSITION_PRIORITY", source, str(path))
            for literal in ('"divergence": 5', '"divergence": 6'):
                self.assertNotIn(literal, source, f"{path} re-declares the ranking")

    def test_domain_logic_does_not_depend_on_host_or_http_controllers(self):
        path = ROOT / "src" / "s_team" / "logic.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports = imported_modules(path)
        self.assertFalse(
            any(
                name == "starlette"
                or name.startswith("starlette.")
                or name.endswith(".controller")
                or name.endswith("_controller")
                or name == "sovereign.application"
                for name in imports
            ),
            str(path),
        )
        self.assertFalse(any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in {"build_routes", "create_application"}
            for node in tree.body
        ), str(path))
        self.assertFalse(any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and any(arg.arg == "runtime" for arg in node.args.args)
            for node in ast.walk(tree)
        ), str(path))

    def test_document_get_uses_the_composite_snapshot_boundary(self):
        source = (
            ROOT / "src" / "s_team" / "controller.py"
        ).read_text(encoding="utf-8")
        self.assertIn("runtime.composite_response(", source)
        self.assertIn("logic.document_snapshot", source)
        self.assertIn("logic.merge_document_observation", source)


class AssetTests(unittest.TestCase):
    def setUp(self):
        self.team = files("s_team.assets").joinpath(
            "team.html",
        ).read_text(encoding="utf-8")

    def assertCodeContains(self, snippet: str):
        """Compare embedded JavaScript without coupling to formatter style."""
        normalize = lambda source: " ".join(source.replace("'", '"').split())
        self.assertIn(normalize(snippet), normalize(self.team))

    def test_peer_only_nodes_are_presented_as_proposals(self):
        self.assertIn("payloadState.proposed_nodes", self.team)
        # The reaction control and its wording are Core's, so a proposal here
        # offers the same acts, named the same way, as one on a board. This
        # page must not grow a second vocabulary for them again.
        self.assertIn("SovereignUI.reactionControl", self.team)
        self.assertNotIn("Accept proposal", self.team)
        self.assertNotIn("Withdraw proposal", self.team)
        # "Keep mine" is the Kanban reaction, offered after a merge. An
        # team never merges a peer's node first, so it must not appear.
        self.assertNotIn("Keep mine", self.team)

    def test_collaboration_pane_can_describe_displayed_nodes(self):
        helper = self.team.index("const findDisplayedNode =")
        use = self.team.index("const node = findDisplayedNode(uuid)")
        self.assertLess(helper, use)

    def test_team_text_uses_the_shared_editor_without_a_local_copy(self):
        self.assertIn("SovereignUI.editableText", self.team)
        self.assertNotIn("const editable =", self.team)
        self.assertCodeContains("multiline: field === 'text'")

    def test_ordered_team_content_uses_the_shared_reorder_control(self):
        self.assertIn("SovereignUI.reorderHandle", self.team)
        self.assertGreaterEqual(self.team.count("SovereignUI.reorderableList"), 4)
        for route in (
            "/api/team/sections/move", "/api/team/clauses/move",
            "/api/team/roles/move", "/api/team/roles/items/move",
        ):
            self.assertIn(route, self.team)
        self.assertNotIn("className = 'element-move'", self.team)

    def test_creation_names_use_hints_instead_of_prefilled_text(self):
        self.assertIn('placeholder="Untitled organization"', self.team)
        self.assertNotIn('value="Untitled organization"', self.team)
        self.assertCodeContains("document.querySelector('#newTeamName').value = '';")

    def test_a_proposal_is_answerable_by_the_side_it_is_made_to(self):
        # Editing a proposed element and answering it are different rights:
        # it is not ours to edit until we accept it, and accepting it is the
        # only thing the row is for. Conflating them left the receiving side
        # with "Proposed" and no way to accept.
        self.assertIn("reactable = true", self.team)
        self.assertIn("reactable: interactive", self.team)
        self.assertIn("reactable: reactable && !itemInherited", self.team)

    def test_topic_header_delegates_navigation_and_creation_to_the_shell(self):
        self.assertNotIn("onCreateTopic", self.team)
        self.assertIn("SovereignShell.setTopicSelector", self.team)

    def test_root_teams_are_worded_as_organizations(self):
        self.assertIn("<h2>New Organization</h2>", self.team)
        self.assertIn("+ Add organization", self.team)
        self.assertIn("No organizations yet", self.team)
        self.assertCodeContains(
            "label: payload.is_organization ? 'Organization' : 'Team'",
        )

    def test_agenda_exposes_the_shared_move_and_update_routes(self):
        self.assertIn("/api/team/agenda/move", self.team)
        self.assertIn("/api/team/agenda/update", self.team)
        # Sections hang off the agreement node, and the page reads through
        # the container it sits in rather than naming a type twice.
        self.assertCodeContains("displayedChildren(current, 'team_agreement')")
        self.assertCodeContains("displayedChildren(")

    def test_polling_preserves_focused_form_fields(self):
        self.assertCodeContains(
            "document.activeElement.matches('input, textarea, select')",
        )

    def test_participants_are_listed_by_the_roles_they_hold(self):
        for marker in (
            "acceptance-avatar",
            "SovereignUI.avatar(person",
            "role-chip",
            "on this team, holding no role yet",
            "in the onboarding pool",
            "holds no role elsewhere",
            # Identity reads as a role like any other, told apart by a key.
            "role.trustee ?",
            "Identity",
            "Trust",
        ):
            self.assertIn(marker, self.team)

    def test_member_rows_start_with_you_and_do_not_repeat_the_team(self):
        # The team is the page subject, not one of its own members. Its roles
        # and options are carried by the team-name row above this section.
        ordering = self.team.split("const people = participants || [];", 1)[1]
        ordering = ordering.split("return section;", 1)[0]
        me = ordering.index("section.append(rowFor(me, interactive))")
        others = ordering.index("section.append(rowFor(person, false))")
        self.assertLess(me, others)
        self.assertNotIn("section.append(ownRow())", self.team)
        self.assertIn("teamHeadingControls(currentInteractionAllowed)", self.team)
        self.assertNotIn(
            "if (!seats.length && !offers.length) return null",
            self.team,
        )

    def test_only_your_own_badges_act(self):
        # Somebody else's standing is a statement, not a control over
        # them, so those badges are inert.
        self.assertIn("rowFor(me, interactive)", self.team)
        self.assertIn("rowFor(person, false)", self.team)
        self.assertIn("Click to step out", self.team)
        # Taking a role is one control on your own line rather than a chip
        # per role, so there is no "click to take it" on anybody's badge.
        self.assertNotIn("Click to take it", self.team)
        self.assertIn("+ Add role", self.team)

    def test_every_holder_status_is_something_the_holder_said(self):
        # Nobody is invited to a role, so there is no state between being
        # asked and answering. "Invited, not yet taken up", "not on this
        # team" and "answer not visible from here" all described somebody
        # who had not answered, and there is no such person to draw.
        for status in ("holds this", "turned it down", "lapsed"):
            self.assertIn(status, self.team)
        for gone in (
            "invited, not yet taken up",
            "answer not visible from here",
            "you cannot see their answer",
        ):
            self.assertNotIn(gone, self.team)

    def test_destructive_role_actions_state_their_consequence(self):
        for marker in (
            # Leaving says what it costs and what getting back on takes.
            "You go back to the onboarding pool",
            "answering an invitation, which is Identity",
            # Trustee resignation says what happens next.
            "trusteeship stays vacant until a valid decision is implemented",
            "confirmModalConfirmBtn",
        ):
            self.assertIn(marker, self.team)

    def test_archiving_starts_from_the_team_heading_options(self):
        # Team-wide options belong beside the current team's name, while the
        # Organizations tree remains navigation.
        for marker in (
            'id="teamActionsModal"',
            "team-options",
            "openTeamActions(current.uuid, current.data.title)",
        ):
            self.assertIn(marker, self.team)
        self.assertNotIn("organization-gear", self.team)
        self.assertNotIn("archive-team", self.team)
        # The pane lists organizations, plural, and says so.
        self.assertIn("<h2>Organizations</h2>", self.team)
        self.assertCodeContains("textContent = 'Organizations'")

    def test_archiving_is_reachable_and_says_what_it_does_not_do(self):
        for marker in (
            "/api/team/teams/archive",
            "/api/team/teams/restore",
            "archive-shelf",
            # Archiving says what it does and, more to the point, what it
            # does not: nothing is sent, and nobody else loses anything.
            "everybody else keeps their copy",
            "the file carries",
        ):
            self.assertIn(marker, self.team)
        # An election is a flow the team runs, taken up without being asked
        # - so there is nothing to bring here, and no lifecycle to read.
        for gone in ("/api/team/elections/join", "Bring it here", "can_join"):
            self.assertNotIn(gone, self.team)

    def test_membership_is_operable_and_separate_from_roles(self):
        # Identity issues membership; a member takes any role. Both acts
        # have to be reachable, and neither may be dressed as the other.
        for marker in (
            "/api/team/membership/end",
            "/api/team/membership/leave",
            "/api/team/membership/apply",
            "/api/team/membership/issue",
            "on this team, holding no role yet",
        ):
            self.assertIn(marker, self.team)
        # Taking a role is not on the role card. The card is the definition;
        # what you are doing about it is on your own line.
        self.assertNotIn("Take this role", self.team)

    def test_membership_acceptance_is_an_explicit_gated_form(self):
        for marker in (
            'id="membershipAcceptanceModal"',
            'id="membershipAcceptanceInfo"',
            'id="membershipAcceptanceRequirement"',
            'id="membershipAcceptanceText"',
            "acceptanceField.oninput = update",
            'id="membershipAgreementAccepted"',
            "agreement.disabled = !agreementExists",
            "agreement.required = agreementExists",
            "membership.agreement",
            "acceptance_text: acceptance.acceptance_text",
            "agreement_accepted: acceptance.agreement_accepted",
        ):
            self.assertIn(marker, self.team)
        self.assertLess(
            self.team.index('id="membershipAcceptanceInfo"'),
            self.team.index('id="membershipAcceptanceRequirement"'),
        )
        self.assertLess(
            self.team.index('id="membershipAcceptanceRequirement"'),
            self.team.index('id="membershipAcceptanceText"'),
        )
        self.assertIn("This team has no Agreement yet.", self.team)
        self.assertNotIn("Membership cannot be accepted.", self.team)
        self.assertIn("Renew outdated membership", self.team)
        self.assertIn("Renew application for ${name}?", self.team)
        self.assertCodeContains("state.is_mine && membership.status === 'outdated'")
        # Every member is an actor and is already on the actor list, so the
        # two acts that change membership live on the actor's own line. A
        # roster beside it named the same people a second time.
        self.assertIn("participant-actions", self.team)
        self.assertIn("row.append(body, rowActions(person))", self.team)
        for gone in ("membership-roster", "membership-member", "Nobody is on this team."):
            self.assertNotIn(gone, self.team)
        # Nothing left that treats a role as the carrier of membership, or
        # an answer as a request awaiting Identity's confirmation.
        for gone in (
            "system_key === 'member'",
            "Apply for this role",
            "asked to take this",
        ):
            self.assertNotIn(gone, self.team)

    def test_vacancy_and_decision_trail_are_operable_in_the_page(self):
        for marker in (
            "Acting candidates",
            "/api/team/trusteeships/candidacy/enter",
            "/api/team/trusteeships/candidacy/withdraw",
            "Decision trail",
            "/api/team/trusteeships/actions/record",
            "/api/team/trusteeships/actions/reality",
            "signals_missing",
            "conflicting records",
            "requestDecisionContext",
            # The trail is a history of records, not a list of the actions
            # somebody typed in: every row says when, who, and how it came
            # out, and it is fed by the payload that carries all of them.
            "decision_trail",
            "decision-record",
            "decision-when",
            "decision-intent",
            "decision-result",
        ):
            self.assertIn(marker, self.team)

    def test_trustee_acts_start_from_the_trusteeship_they_belong_to(self):
        # Recording an action and filling the seat are both acts on one
        # trusteeship, so both start from its card. The five fields of a
        # record are a dialog, not a form parked under the trail, and none
        # of them is enforced - a partial record is still a record.
        for marker in (
            'id="trusteeActionModal"',
            "requestTrusteeAction(`Record ${label} action`)",
            "electionStartControl(trust, label)",
            "role-card-actions",
            # Standing for the seat, and the elections that fill it, are on
            # the same card - and instantiating a template is Identity's.
            "`Act for ${label}`",
            "/api/team/identity/take",
            # Who sits in the seat is a person's decision, and this is
            # where that person makes it.
            "/api/team/trusteeships/settle",
            "trustee-settle",
        ):
            self.assertIn(marker, self.team)
        # Nothing states any of this a second time in Actors: a warning line
        # about a vacancy, and a panel that said no election had been started
        # about seats it never named.
        for gone in (
            "trustee-action-form",
            "subject.required = true",
            "decision.required = true",
            "election-start-actions",
            "renderIdentity",
            "identity-line",
            "Trustee decisions",
            "No trustee election has been started.",
            # The election itself is read in S-Flow, from Initiatives and
            # Flows, so the card carries no state about it.
            "renderElection",
            "election-card",
            "Implement decision",
            "trustee_elections",
        ):
            self.assertNotIn(gone, self.team)

    def test_the_history_of_the_team_scrolls_inside_its_own_section(self):
        # A trail that grows without limit otherwise pushes the page it
        # belongs to out of reach.
        css = files("s_team.assets").joinpath(
            "team.css",
        ).read_text(encoding="utf-8")
        trail = css.split(".decision-trail {", 1)[1].split("}", 1)[0]
        self.assertIn("max-height", trail)
        self.assertIn("overflow-y: auto", trail)

    def test_the_work_a_team_runs_is_listed_and_taken_up(self):
        # An item is the team's because it is on the team's channel and
        # yours because you hold it. Nothing about it is recorded on the
        # team, so the page reads both facts from the payload and nothing
        # in it names a stored record.
        for marker in (
            "/api/team/items/create",
            "/api/team/items/connect",
            "/api/team/items/offer",
            "/api/team/items/remove",
            "Connect to…",
            "Offer one of mine…",
            'id="newItemModal"',
        ):
            self.assertIn(marker, self.team)
        # Only what you hold is a row: an offer is a name until you take it
        # up. Parentheses around a single arrow-function argument are a
        # formatter choice, not part of this contract.
        self.assertRegex(
            self.team,
            r"items\.filter\(\(?item\)?\s*=>\s*item\.active\)",
        )
        self.assertRegex(
            self.team,
            r"items\.filter\(\(?item\)?\s*=>\s*!item\.active\)",
        )
        # Removing says what it does not do, because the word is the same
        # one the Cockpit uses for deleting.
        self.assertIn("Everybody else keeps ", self.team)

    def test_the_onboarding_pool_is_derived_rather_than_a_second_topic(self):
        # The pool is whoever publishes on the channel without being on the
        # team. There is no waiting room to be let into, so the page has no
        # second view, no application to submit and nothing to resolve.
        for marker in (
            "onboarding pool",
            "renderMemberships",
            "/api/team/memberships/create",
            "/api/team/memberships/delete",
            "/api/team/membership/open",
            "/api/team/membership/close",
            "membership.pool",
        ):
            self.assertIn(marker, self.team)
        for gone in (
            "separate onboarding channel",
            "/api/team/pool/invitations/publish",
            "/api/team/pool/applications/submit",
            "/api/team/pool/applications/resolve",
            "/api/team/pool/team/mount",
            "Join Team channel",
            "active_invitations",
            "pool_uuid=",
            "renderPool",
            "openPool",
        ):
            self.assertNotIn(gone, self.team)

    def test_a_role_is_taken_rather_than_handed_out(self):
        # Nobody offers a role here any more. A member takes one, and a
        # sub-team takes one from its own heading - so the picker that
        # made an invitation is gone, and with it the list that fed it.
        for gone in (
            "role-offer-picker",
            "/api/team/roles/offer",
            "/api/team/roles/revoke",
            "offerable_actors",
            "Offer to\\u2026",
            "offered_by",
            "offered_at",
            "offered_elsewhere",
        ):
            self.assertNotIn(gone, self.team)
        # A holding is its holder's own record, so nothing on somebody
        # else's badge takes it back. Stepping out is theirs, and the one
        # mark left of that shape is the trustee's own.
        self.assertIn("Step out of ${label}", self.team)

    def test_a_team_takes_a_seat_from_its_own_page(self):
        # A team that could take a seat gets no row on the parent's page: a
        # seat nobody has taken is not a fact about anybody, and the only
        # person who could act on it holds that team's Identity and is
        # looking elsewhere. It acts from its own team-name row.
        for marker in (
            "const addTeamRoleControl = (seats)",
            "payloadState.seatable_roles",
            "payloadState.holds_identity",
            "/api/team/roles/seat",
            "/api/team/roles/unseat",
        ):
            self.assertIn(marker, self.team)
        for gone in ("const subteamRow = (person)", "const subteamChip = ("):
            self.assertNotIn(gone, self.team)

    def test_who_holds_a_role_is_a_badge_and_the_rest_is_a_tooltip(self):
        # The line shows a face and a name; when they answered, against which
        # version and who offered it are one holder's details, so they belong
        # in the tooltip rather than in columns nobody reads across.
        self.assertIn("holder-badges", self.team)
        self.assertIn("const badge = SovereignUI.entityBadge({", self.team)
        self.assertCodeContains("className: 'holder-badge'")
        self.assertIn("badge.title", self.team)

    def test_a_team_holds_roles_beside_its_name(self):
        # A Team is an actor elsewhere, so its held-role badges sit beside
        # its own heading, not among its members.
        self.assertIn("payloadState.parents", self.team)
        self.assertIn("team-heading-controls", self.team)
        for gone in (
            "renderSeats", "renderSeatOffers", "seat-offer", "Seats held",
            # A seat is taken and given up. There is nothing to decline,
            # because nothing was offered.
            "seat_offers", "/api/team/roles/decline_seat",
        ):
            self.assertNotIn(gone, self.team)

    def test_the_team_parts_use_shared_disclosures(self):
        for title, key in (
            # "Agreement" and not "Team document": this section *is* the
            # agreement - the text the members consent to - and it is the
            # one place the word survives the move to Team.
            ("Agreement", "document"),
            ("Members", "actors"),
            ("Roles", "roles"),
            # What the team is doing, which is what somebody opening it
            # came for.
            ("Initiatives and Flows", "work"),
            # What has already happened, named for the general case rather
            # than for the decision trail that is currently all of it.
            ("History", "history"),
        ):
            self.assertCodeContains(f"disclosure('{title}', '{key}')")
        # The work is open and everything else arrives closed. The agreement
        # is the longest section and the least often changed, and who is on
        # the team changes rarely enough not to greet you.
        self.assertIn("work: true", self.team)
        self.assertIn("actors: false", self.team)
        self.assertIn("roles: false", self.team)
        self.assertIn("document: false", self.team)
        self.assertIn("history: false", self.team)

    def test_copying_is_only_offered_while_making_a_new_team(self):
        # Starting a new team from this one is a choice made where a new
        # team is made. There is now such a flow on this page as well as in
        # the cockpit, so cloning may appear here - but only ever as the
        # "copy from" of the New Team modal, never as an action sitting on
        # the team you happen to be looking at.
        self.assertNotIn("state-duplicate", self.team)
        self.assertIn("newTeamTemplate", self.team)
        for line in self.team.split("\n"):
            if "teams/clone" in line:
                self.assertIn("template", line)

    def test_the_page_uses_shared_add_controls_and_has_no_state_line(self):
        css = files("s_team.assets").joinpath(
            "team.css",
        ).read_text(encoding="utf-8")
        self.assertIn("#document > .ui-disclosure", css)
        self.assertIn("SovereignUI.addComposer", self.team)
        for noun in ("section", "clause", "role"):
            self.assertCodeContains(f"noun: '{noun}'")
        self.assertCodeContains("noun: kind")
        self.assertCodeContains("kind: 'accountability'")
        self.assertCodeContains("kind: 'domain'")
        # How many actors are in it is not worth a line of its own: the
        # Identity line and every role already say it.
        self.assertNotIn("team-state", self.team)
        self.assertNotIn("One actor", self.team)

    def test_document_add_controls_live_on_their_headings(self):
        css = files("s_team.assets").joinpath(
            "team.css",
        ).read_text(encoding="utf-8")
        # A clause is added from its section's heading row, hover-revealed
        # like the other row controls.
        self.assertCodeContains("addControl: clauseComposer")
        self.assertCodeContains("className: 'element-add-control'")
        self.assertCodeContains("formHost: clauseComposerHost")
        self.assertIn(".element-row:hover .element-add-control", css)
        # A section is added from the agreement's heading, which is not a row:
        # the agreement's title is a field on the team node, and giving it a
        # row would put a second lamp on the same node's divergence.
        self.assertRegex(
            self.team,
            r"agreementHead\.append\(\s*SovereignUI\.addComposer",
        )
        self.assertCodeContains("formHost: sectionComposerHost")
        self.assertIn(".element-composer-row", css)
        self.assertIn(".agreement-head .ui-add-trigger", css)
        self.assertNotIn("block.append(SovereignUI.addComposer", self.team)

    def test_a_lone_reorderable_section_keeps_its_title_column(self):
        css = files("s_team.assets").joinpath(
            "team.css",
        ).read_text(encoding="utf-8")
        # Core hides the reorder handle until a sibling exists. Explicit grid
        # placement keeps the remaining cells from sliding into its column.
        self.assertIn(
            ".element-row.has-reorder > .element-label,\n"
            ".element-row.has-reorder > .element-heading { grid-column: 3; }",
            css,
        )
        self.assertIn(
            ".element-row.has-reorder > .element-actions { grid-column: 4; }",
            css,
        )

    def test_the_team_is_named_apart_from_its_agreement(self):
        css = files("s_team.assets").joinpath(
            "team.css",
        ).read_text(encoding="utf-8")
        # One field used to serve both, so renaming the body silently
        # retitled the document its members had accepted.
        self.assertIn("/api/team/agreement/rename", self.team)
        self.assertIn("agreementData(current).name", self.team)
        self.assertCodeContains("placeholder: 'Name this agreement'")
        self.assertNotIn(".agreement-title:empty::before", css)
        # The team's name heads the page, outside every disclosure, and the
        # sections follow in the order the page now reads.
        self.assertIn("#document > .element-row", css)
        start = self.team.index("article.append(", self.team.index("const historyPart"))
        appended = self.team[start:self.team.index(");", start)]
        positions = [
            appended.index(part)
            for part in (
                "workPart.section", "membersPart.section", "rolesPart.section",
                "documentPart.section", "membershipPart.section", "historyPart.section",
            )
        ]
        self.assertEqual(positions, sorted(positions))

    def test_one_rule_separates_the_name_from_the_sections(self):
        # Shared disclosures carry their own border-top and drop it only as a
        # first child, which the first section here is not - the team's name
        # is. Two rules ran directly under the title.
        css = files("s_team.assets").joinpath(
            "team.css",
        ).read_text(encoding="utf-8")
        self.assertIn(
            "#document > .element-row + .ui-disclosure { border-top: 0; }", css,
        )

    def test_assets_never_navigate_to_the_bare_root_with_a_query(self):
        # "/" serves whichever application is primary, so a root-relative link
        # lands somewhere that depends on host configuration.
        for number, line in enumerate(self.team.splitlines(), start=1):
            for pattern in ('href = `/?', 'href="/?', "href='/?"):
                self.assertNotIn(pattern, line, f"team.html:{number}")


class ThemeTests(unittest.TestCase):
    """U4 was "dark everywhere" with one documented exception: the document
    surface stayed light, reasoned as paper inside a dark frame. Using the
    desktop build showed that exception reads as a bug rather than a design,
    so it is gone - amendment recorded in DESIGN_UI_CONSISTENCY.md alongside
    U4. These hold the line against it quietly coming back.
    """

    def setUp(self):
        self.css = files("s_team.assets").joinpath(
            "team.css",
        ).read_text(encoding="utf-8")

    def test_declares_a_dark_colour_scheme(self):
        self.assertIn("color-scheme: dark", self.css)

    def test_the_document_panel_is_not_painted_light(self):
        # The exact former declarations, so a revert is caught even if it
        # arrives through a different rule. Matched as declarations rather
        # than a bare substring so the history note in this file's own
        # opening comment - which names the old colour deliberately - is
        # not itself a false positive.
        self.assertNotIn("background: #f9fafb", self.css)
        self.assertNotIn("background:#f9fafb", self.css)

    def test_text_colours_are_not_the_ones_calibrated_for_a_light_panel(self):
        # #111827 was the panel's near-black text - unreadable if the panel
        # underneath it were ever made dark again without also moving this.
        self.assertNotIn("color: #111827", self.css)
        self.assertNotIn("color:#111827", self.css)

    def test_actor_lines_share_a_background_and_aligned_value_column(self):
        participant = self.css.split(".participant {", 1)[1].split("}", 1)[0]
        body = self.css.split(".acceptance-body {", 1)[1].split("}", 1)[0]
        self.assertIn("display: grid", participant)
        self.assertIn("background: var(--hover)", participant)
        self.assertIn("display: grid", body)
        self.assertIn("grid-template-columns: 150px minmax(0, 1fr)", body)


if __name__ == "__main__":
    unittest.main()
