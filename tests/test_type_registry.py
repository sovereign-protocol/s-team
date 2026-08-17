"""DESIGN_TYPES.md is checked against the source it claims to describe.

The design corpus drifted because nothing could tell that it had: S-Team's
ARCHITECTURE.md went on describing ``agreement_*`` nodes for as long as it
took somebody to grep for them. A document nobody can verify is a document
that decays, so the registry is parsed here and compared to the contracts
declared in TeamLogic.

A source scan like the boundary tests, and per-repository for the same
reason: it fails in the pull request that breaks it.

The names in RETIRED are checked the way Core checks its own boundary: a
literal list in the test. They belonged to the schema this application used
before the review, and a document went on describing them for as long as it
took somebody to grep.
"""

import re
import unittest
from pathlib import Path

from s_team.logic import TeamLogic


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "DESIGN_TYPES.md"

# The schema this application carried before the review. `agreement_identity`
# became an append-only chain of `team_trustee_state`; the rest gained the
# `team_` prefix when the agreement became the team's rather than the team's
# name for itself.
RETIRED = frozenset({
    "agreement_identity", "agreement_role", "agreement_role_offer",
    "agreement_role_decision", "agreement_role_holding", "agreement_section",
    "agreement_clause", "agreement_accountability", "agreement_domain",
    "agreement_link", "agreement_decision",
    # The invitation. A role is taken, never handed out, so the record that
    # said somebody had been asked is gone and nothing writes one.
    "team_role_offer",
    # One member's whole list of what they hold of the team's work, as a
    # list field inside a single record. Each reference is its own
    # `topic_link` now, so offering an item is creating a node and taking it
    # off is deleting one - which is also why the set of items withdrawn
    # from a team is gone: it existed to stop a derived list from putting
    # back what somebody had removed.
    "team_item_list",
    # The waiting room, and the round of applications it fed. The pool is
    # derived now - whoever publishes on the channel without being on the
    # team - so there is no topic to be let into, nothing to apply for and
    # nobody to resolve an application. Identity opens a membership type and
    # the Actor answers for themselves.
    "team_pool", "team_pool_invitation", "team_pool_application",
    "team_pool_resolution", "team_external_member_resolution",
    "team_member_opening", "team_member_application",
    "team_member_resolution",
})

# Documented here because this application decides where they live and what
# they mean on a team, but declared by Core, so there is no contract in
# TeamLogic for them to agree with. A literal list for the same reason
# RETIRED is one: the alternative is a rule that silently stops checking a
# type the day somebody forgets to declare it.
BORROWED = frozenset({"topic_link"})

# Every governance record carries it; the registry says so once instead of
# repeating a row in each table.
IMPLICIT_FIELDS = frozenset({"type"})

HEADING = re.compile(r"^##\s+(.*?)\s*$")
TYPE_HEADING = re.compile(r"^`([a-z_]+)`$")
TABLE_ROW = re.compile(r"^\|\s*`([a-z_]+)`\s*\|\s*(\w+)")
VOCABULARY = re.compile(r"^\*\*Vocabulary\s+—\s+`([A-Z_]+)`:\*\*\s*(.*)$")
BACKTICKED = re.compile(r"`([a-z_]+)`")


def registry_text() -> str:
    return REGISTRY.read_text(encoding="utf-8")


def documented_contracts() -> dict[str, tuple[frozenset, frozenset]]:
    """Field tables, keyed by the node type whose section they sit under."""
    contracts: dict[str, tuple[set, set]] = {}
    current: str | None = None
    for line in registry_text().splitlines():
        heading = HEADING.match(line)
        if heading:
            # Reset on every h2, so tables under prose headings - the
            # projection states, the blueprint mapping - are not collected.
            match = TYPE_HEADING.match(heading.group(1))
            current = match.group(1) if match else None
            if current:
                contracts.setdefault(current, (set(), set()))
            continue
        if current is None:
            continue
        row = TABLE_ROW.match(line)
        if not row:
            continue
        field, requirement = row.group(1), row.group(2).lower()
        required, optional = contracts[current]
        if requirement == "required":
            required.add(field)
        elif requirement == "optional":
            optional.add(field)
    return {
        node_type: (frozenset(required | IMPLICIT_FIELDS), frozenset(optional))
        for node_type, (required, optional) in contracts.items()
    }


def documented_vocabularies() -> dict[str, frozenset]:
    return {
        match.group(1): frozenset(BACKTICKED.findall(match.group(2)))
        for match in (
            VOCABULARY.match(line) for line in registry_text().splitlines()
        )
        if match
    }


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(REGISTRY.exists(), "DESIGN_TYPES.md is missing")
        self.documented = documented_contracts()
        self.declared = {
            **TeamLogic.GOVERNANCE_FIELDS,
            **TeamLogic.ROLE_RECORD_FIELDS,
            **TeamLogic.CONTENT_FIELDS,
        }

    def test_the_registry_documents_every_reviewed_area(self):
        # The registry is deliberately partial - it is being built one
        # element at a time - but an area it claims is registered may not
        # quietly lose an entry.
        reviewed = {
            name for name in self.declared
            if name.startswith("team_trustee_")
            or name in TeamLogic.ROLE_RECORD_TYPES
            or name in TeamLogic.CONTENT_TYPES
            or name in {
                "team_membership", "team_membership_invitation",
            }
        }
        self.assertTrue(reviewed, "no reviewed types declared in source")
        self.assertEqual(reviewed - set(self.documented), set())

    def test_every_documented_type_exists_in_source(self):
        unknown = sorted(
            set(self.documented) - set(self.declared) - BORROWED,
        )
        self.assertEqual(unknown, [], f"documented but not declared: {unknown}")

    def test_documented_fields_match_the_declared_contract(self):
        for node_type, (required, optional) in sorted(self.documented.items()):
            if node_type in BORROWED:
                continue
            with self.subTest(node_type=node_type):
                self.assertEqual(
                    (required, optional),
                    self.declared[node_type],
                    f"{node_type} in DESIGN_TYPES.md disagrees with TeamLogic",
                )

    def test_documented_vocabularies_match_the_declared_ones(self):
        documented = documented_vocabularies()
        self.assertTrue(documented, "no vocabularies parsed from the registry")
        for name, values in sorted(documented.items()):
            with self.subTest(vocabulary=name):
                self.assertTrue(
                    hasattr(TeamLogic, name), f"TeamLogic has no {name}",
                )
                declared = getattr(TeamLogic, name)
                # A vocabulary of one is declared as a plain string, because
                # nothing chooses between its members. MEMBERSHIP_TRUST is
                # the name of a rule rather than a set of options.
                self.assertEqual(
                    values,
                    frozenset({declared}) if isinstance(declared, str)
                    else declared,
                )

    def test_the_membership_authority_is_itself_a_trusteeship(self):
        self.assertIn(TeamLogic.MEMBERSHIP_TRUST, TeamLogic.TRUSTS)

    def test_the_membership_vocabularies_are_all_registered(self):
        documented = documented_vocabularies()
        for name in ("MEMBERSHIP_CAUSES", "MEMBERSHIP_TRUST"):
            self.assertIn(name, documented)

    def test_the_participation_vocabularies_are_all_registered(self):
        documented = documented_vocabularies()
        for name in ("ROLE_DECISIONS", "HOLDING_STATES"):
            self.assertIn(name, documented)

    def test_the_trusteeship_vocabularies_are_all_registered(self):
        for name in ("TRUSTS", "TRUSTEE_CAUSES", "ACTION_KINDS"):
            self.assertIn(name, documented_vocabularies())

    def test_every_governance_record_type_has_a_row(self):
        # The dispatch table and the type list are two statements of the same
        # thing. A type in one and not the other is a KeyError raised while
        # assessing somebody else's record, which is the worst place for one.
        self.assertEqual(
            set(TeamLogic.GOVERNANCE_RECORDS),
            set(TeamLogic.GOVERNANCE_RECORD_TYPES),
        )

    def test_each_row_names_methods_that_exist_and_a_declared_author(self):
        for node_type, (author, checker, assessor) in sorted(
            TeamLogic.GOVERNANCE_RECORDS.items(),
        ):
            with self.subTest(node_type=node_type):
                required, _ = TeamLogic.GOVERNANCE_FIELDS[node_type]
                self.assertIn(author, required)
                self.assertTrue(
                    callable(getattr(TeamLogic, assessor, None)), assessor,
                )
                if checker:
                    self.assertTrue(
                        callable(getattr(TeamLogic, checker, None)), checker,
                    )

    def test_the_membership_type_is_not_a_governance_record(self):
        # It is content: named, edited in place and deletable, the way a role
        # is. Declaring it as a record would mean an append-only chain, and
        # deleting one is exactly how a team stops supporting a membership.
        self.assertNotIn(
            TeamLogic.MEMBERSHIP_TYPE_TYPE, TeamLogic.GOVERNANCE_RECORD_TYPES,
        )
        self.assertNotIn(
            TeamLogic.MEMBERSHIP_TYPE_TYPE, TeamLogic.GOVERNANCE_FIELDS,
        )

    def test_retired_names_appear_in_no_source_file(self):
        for path in sorted((ROOT / "src").rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            for name in sorted(RETIRED):
                self.assertNotIn(name, source, f"{path} names retired {name}")

    def test_retired_names_appear_in_no_current_design_document(self):
        # The failure that started the review: a document went on describing
        # a schema the source had renamed away from, and nothing noticed.
        # The changelog is exempt, being a record of what happened.
        paths = sorted(ROOT.glob("DESIGN_*.md")) + [ROOT / "ARCHITECTURE.md"]
        self.assertGreater(len(paths), 1, "no design documents found to scan")
        for path in paths:
            text = path.read_text(encoding="utf-8")
            for name in sorted(RETIRED):
                self.assertNotIn(name, text, f"{path.name} names retired {name}")


if __name__ == "__main__":
    unittest.main()
