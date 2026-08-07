"""DESIGN_TYPES.md is checked against the source it claims to describe.

The design corpus drifted because nothing could tell that it had: S-Team's
ARCHITECTURE.md went on describing ``agreement_*`` nodes for as long as it
took somebody to grep for them. A document nobody can verify is a document
that decays, so the registry is parsed here and compared to the contracts
declared in TeamLogic.

A source scan like the boundary tests, and per-repository for the same
reason: it fails in the pull request that breaks it.

Scoped to the new world - the registry, the ledger and src/. Documents the
review has not reached yet are evidence, not subjects: this suite never fails
because an old document is wrong, because that would make old-world edits a
running tax instead of a single purge at the end. DESIGN_REVIEW_LEDGER.md
names which documents those are.
"""

import re
import unittest
from pathlib import Path

from s_team.logic import TeamLogic


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "DESIGN_TYPES.md"
LEDGER = ROOT / "DESIGN_REVIEW_LEDGER.md"

# Every governance record carries it; the registry says so once instead of
# repeating a row in each table.
IMPLICIT_FIELDS = frozenset({"type"})

HEADING = re.compile(r"^##\s+(.*?)\s*$")
TYPE_HEADING = re.compile(r"^`([a-z_]+)`$")
TABLE_ROW = re.compile(r"^\|\s*`([a-z_]+)`\s*\|\s*(\w+)")
VOCABULARY = re.compile(r"^\*\*Vocabulary\s+—\s+`([A-Z_]+)`:\*\*\s*(.*)$")
BACKTICKED = re.compile(r"`([a-z_]+)`")
RETIRED_SECTION = re.compile(r"^##\s+Retired names\s*$")
# Only the first column. The second names what the type became, which is a
# live name and must not be swept up as a retired one.
RETIRED_ROW = re.compile(r"^\|\s*`([a-z_]+)`\s*\|")


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


def retired_names() -> set[str]:
    """Read from the ledger: supersession is review bookkeeping, not registry."""
    names: set[str] = set()
    in_section = False
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        if RETIRED_SECTION.match(line):
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        row = RETIRED_ROW.match(line) if in_section else None
        if row:
            names.add(row.group(1))
    return names


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(REGISTRY.exists(), "DESIGN_TYPES.md is missing")
        self.documented = documented_contracts()
        self.declared = {
            **TeamLogic.GOVERNANCE_FIELDS,
            **TeamLogic.POOL_FIELDS,
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
            or name in TeamLogic.POOL_FIELDS
            or name in {
                "team_membership", "team_member_opening",
                "team_member_application", "team_member_resolution",
                "team_external_member_resolution",
            }
        }
        self.assertTrue(reviewed, "no reviewed types declared in source")
        self.assertEqual(reviewed - set(self.documented), set())

    def test_every_documented_type_exists_in_source(self):
        unknown = sorted(set(self.documented) - set(self.declared))
        self.assertEqual(unknown, [], f"documented but not declared: {unknown}")

    def test_documented_fields_match_the_declared_contract(self):
        for node_type, (required, optional) in sorted(self.documented.items()):
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
        for name in ("OFFER_STATES", "ROLE_DECISIONS", "HOLDING_STATES"):
            self.assertIn(name, documented)

    def test_the_trusteeship_vocabularies_are_all_registered(self):
        for name in ("TRUSTS", "TRUSTEE_CAUSES", "ACTION_KINDS"):
            self.assertIn(name, documented_vocabularies())

    def test_retired_names_appear_in_no_source_file(self):
        retired = retired_names()
        self.assertTrue(retired, "the retired-names section parsed as empty")
        for path in sorted((ROOT / "src").rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            for name in sorted(retired):
                self.assertNotIn(name, source, f"{path} names retired {name}")

    def test_the_registry_does_not_depend_on_the_documents_being_replaced(self):
        # The new world must stand on its own, or the purge cannot happen.
        superseded = ("ARCHITECTURE.md", "DESIGN_ROLES_AND_ACTORS.md",
                      "DESIGN_GENESIS_AND_GOVERNANCE_PLAN.md")
        text = registry_text()
        for name in superseded:
            self.assertNotIn(name, text, f"DESIGN_TYPES.md refers to {name}")


if __name__ == "__main__":
    unittest.main()
