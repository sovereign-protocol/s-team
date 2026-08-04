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

    def test_agenda_exposes_the_shared_move_route(self):
        self.assertIn("move: '/api/team/agenda/move'", self.team)
        self.assertIn(
            "displayedChildren(current, 'team_section')",
            self.team,
        )

    def test_polling_preserves_focused_form_fields(self):
        self.assertIn(
            "document.activeElement.matches('input, textarea, select')",
            self.team,
        )

    def test_participants_are_listed_by_the_roles_they_hold(self):
        for marker in (
            "acceptance-avatar",
            "SovereignUI.avatar(person",
            "role-chip",
            "holds no role here",
            "holds no role elsewhere",
            # Identity reads as a role like any other, told apart by a key.
            "role.identity ?",
            "Identity",
        ):
            self.assertIn(marker, self.team)

    def test_actor_rows_start_with_the_team_then_you_then_others(self):
        ordering = self.team.split("const people = participants || [];", 1)[1]
        ordering = ordering.split("return section;", 1)[0]
        own = ordering.index("section.append(own)")
        me = ordering.index("section.append(rowFor(me, interactive))")
        others = ordering.index("section.append(rowFor(person, false))")
        self.assertLess(own, me)
        self.assertLess(me, others)
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
        self.assertIn("Click to take it", self.team)

    def test_an_unreachable_answer_is_not_worded_as_an_unanswered_one(self):
        # "They have not answered" and "this session cannot see whether they
        # have" are different facts, and the interface has to say which.
        self.assertIn("offered, not yet decided", self.team)
        self.assertIn("answer not visible from here", self.team)
        self.assertIn(
            "you cannot see their answer", self.team,
        )

    def test_destructive_role_actions_state_their_consequence(self):
        for marker in (
            # Revoking says what survives it and what does not.
            "This withdraws the offer",
            "is theirs and stays",
            # Taking Identity says what it does to everyone else.
            "writes a competing holder into the same record",
            "confirmModalConfirmBtn",
        ):
            self.assertIn(marker, self.team)

    def test_inviting_and_withdrawing_belong_to_identity_alone(self):
        # Both live on the holder's badge, revealed on hover the way Delete
        # is, so a role reads as a line of people rather than of controls.
        self.assertIn("payloadState.holds_identity", self.team)
        self.assertIn("holder-action", self.team)
        self.assertIn("/api/team/roles/revoke", self.team)
        self.assertIn("/api/team/roles/offer", self.team)

    def test_who_holds_a_role_is_a_badge_and_the_rest_is_a_tooltip(self):
        # The line shows a face and a name; when they answered, against which
        # version and who offered it are one holder's details, so they belong
        # in the tooltip rather than in columns nobody reads across.
        self.assertIn("holder-badges", self.team)
        self.assertIn("const badge = SovereignUI.entityBadge({", self.team)
        self.assertIn("className: 'holder-badge'", self.team)
        self.assertIn("badge.title", self.team)

    def test_an_team_holds_roles_the_way_a_person_does(self):
        # A Team is a normal actor, so the roles it holds elsewhere are
        # badges on its own line in Actors - taken and left by clicking, as
        # yours are. There is no separate idea of a seat with a section of
        # its own.
        self.assertIn("payloadState.seat_offers", self.team)
        self.assertIn("/api/team/roles/decline_seat", self.team)
        self.assertIn("is-team", self.team)
        for gone in ("renderSeats", "renderSeatOffers", "seat-offer", "Seats held"):
            self.assertNotIn(gone, self.team)

    def test_the_three_team_parts_use_shared_disclosures(self):
        for title, key in (
            # "Agreement" and not "Team document": this section *is* the
            # agreement - the text the members consent to - and it is the
            # one place the word survives the move to Team.
            ("Agreement", "document"),
            ("Actors", "actors"),
            ("Roles", "roles"),
        ):
            self.assertIn(f"disclosure('{title}', '{key}')", self.team)
        # Who is here, open. The agreement is the longest section and the
        # least often changed, so it no longer greets whoever opens the team.
        self.assertIn("actors: true", self.team)
        self.assertIn("roles: false", self.team)
        self.assertIn("document: false", self.team)

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
            self.assertIn(f"noun: '{noun}'", self.team)
        self.assertIn("noun: kind", self.team)
        self.assertIn("kind: 'accountability'", self.team)
        self.assertIn("kind: 'domain'", self.team)
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
        self.assertIn("addControl: !proposed && currentInteractionAllowed", self.team)
        self.assertIn("className: 'element-add-control'", self.team)
        self.assertIn(".element-row:hover .element-add-control", css)
        # A section is added from the agreement's heading, which is not a row:
        # the agreement's title is a field on the team node, and giving it a
        # row would put a second lamp on the same node's divergence.
        self.assertIn("agreementHead.append(SovereignUI.addComposer", self.team)
        self.assertIn(".agreement-head .ui-add-trigger", css)
        self.assertNotIn("block.append(SovereignUI.addComposer", self.team)

    def test_the_team_is_named_apart_from_its_agreement(self):
        css = files("s_team.assets").joinpath(
            "team.css",
        ).read_text(encoding="utf-8")
        # One field used to serve both, so renaming the body silently
        # retitled the document its members had accepted.
        self.assertIn("/api/team/agreement/rename", self.team)
        self.assertIn("current.data.agreement_title", self.team)
        self.assertIn(".agreement-title:empty::before", css)
        # The team's name heads the page, outside every disclosure, and the
        # sections follow in the order the page now reads.
        self.assertIn("#document > .element-row", css)
        self.assertIn(
            "article.append(actorsPart.section, rolesPart.section,"
            " documentPart.section)",
            self.team,
        )

    def test_role_offer_picker_shares_the_held_by_heading_and_theme(self):
        css = files("s_team.assets").joinpath(
            "team.css",
        ).read_text(encoding="utf-8")
        self.assertIn("heldHeading.append(picker)", self.team)
        self.assertIn(".role-holders-heading", css)
        self.assertIn("background-color: var(--panel)", css)
        self.assertIn(".role-offer-picker option", css)

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
