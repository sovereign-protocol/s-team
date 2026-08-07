# Design review ledger — S-Team

**Temporary.** This file is scaffolding for a review that rebuilds the S-Team
design documents element by element. It records, per element, what was
extracted from source, every contradiction found, how each was resolved, and
which old material the result supersedes.

When the review is finished, the supersession lists below *are* the delete
list, and this file goes with them. Nothing is deleted on a judgement call at
the end; it is deleted because we recorded, at the time, what replaced it.

## The two worlds

**New** — reviewed, decided, enforced:

- `DESIGN_TYPES.md` — what each type is and what it carries
- `DESIGN_RULES.md` — the rules over those types *(not yet created)*
- `tests/test_type_registry.py` — asserts the registry against source
- this ledger

**Old** — left untouched until the purge:

- `ARCHITECTURE.md`
- `DESIGN_ROLES_AND_ACTORS.md`
- `DESIGN_GENESIS_AND_GOVERNANCE_PLAN.md`

Nothing in the new world edits, references as authority, or depends on the
old world. Old documents are read as *evidence* during a review and quoted in
contradiction tables, never amended.

## Process, per element

1. **Extract** — what source actually says: types, fields, vocabularies, and
   the rules the code enforces.
2. **Contradict** — table every disagreement between source, old documents and
   the blueprint (`../Domain-Driven-Design.md`). No resolutions.
3. **Decide** — each row resolved explicitly. Source wins by default because
   it is the running system, but not automatically: some rows mean the code is
   wrong, and then the outcome is a code change.
4. **Document** — registry entry and rules encoding the decisions.
5. **Enforce** — a test asserts the document against source.

Standing constraints for this review: no back-compat paths for old record
shapes — if a decision invalidates stored data, validation fails loudly and the
ledger says so; no defaulting or exception-swallowing that turns a
contradiction into a silent fallback; no browser testing.

## Element status

| # | Element                        | Step |
| - | ------------------------------ | ---- |
| 1 | Trusteeship                    | **5 — done**, bar three blueprint-only rows |
| 2 | Membership                     | not started |
| 3 | Roles and holdings             | not started |
| 4 | Document (sections, clauses)   | not started |
| 5 | Pool onboarding                | not started |

---

# Element 1 — Trusteeship

## Step 1: extracted

Five node types, all flat children of the `team` topic, all declared in
`TeamLogic.GOVERNANCE_FIELDS`: `team_trustee_state`, `team_trustee_candidacy`,
`team_trustee_election`, `team_trustee_action`, `team_trustee_reality`.
Registered in `DESIGN_TYPES.md`, field for field, and enforced.

Three vocabularies: `TRUSTS`, `TRUSTEE_CAUSES`, `ACTION_KINDS`.

**Evidence quality of the old documents.** These differ sharply and the
difference is worth recording, because it tells us where review effort belongs:

| Document                                | On trusteeship                                                                                     |
| --------------------------------------- | -------------------------------------------------------------------------------------------------- |
| `DESIGN_GENESIS_AND_GOVERNANCE_PLAN.md` | **Accurate.** §3.1 matches `GOVERNANCE_FIELDS` exactly for all five types; §2.2 and §3.2 describe the append-only chain and authority matrix as built |
| `DESIGN_ROLES_AND_ACTORS.md`            | **Drifted.** §1.2, §1.3 and §5 each contradict source                                              |
| `ARCHITECTURE.md`                        | **Superseded.** Describes `agreement_identity`, a name absent from source                          |

So the genesis plan is largely a source for the new documents rather than a
target for replacement, and the roles document is the reverse.

## Step 2: contradictions

`S` = source, `G` = genesis plan, `R` = roles document, `A` = ARCHITECTURE.md,
`B` = blueprint.

### Stale documentation — no design decision, source is simply right

| #  | Question             | Positions                                                                      |
| -- | -------------------- | ------------------------------------------------------------------------------ |
| T1 | Name of the type     | `S`,`G`: `team_trustee_state` · `R` §1.2: `team_trustee` · `A`: `agreement_identity` |
| T2 | Rewritten or appended | `S`,`G` §2.2: append-only chain via `previous_state_uuid`; direct handover refused on purpose · `R` §1.3: "one node whose holder field is **rewritten**" |
| T4 | `held_since`         | `S`: no such field; the payload derives it · `R` §1.2: `data.held_since`        |

### Open — these need a decision

| #   | Question | Positions | Consequence |
| --- | -------- | --------- | ----------- |
| T3  | **Is a trusteeship a role?** | `S`: no `team_role` node is involved; standing for one *requires* membership · `R` §1.3: "a trusteeship *is* a role", and holding it counts as being on the team · `B` §4: "a specialized Role" | Decides whether Trustee is a Role subtype or a distinct kind. Also decides whether holding a trusteeship can substitute for membership |
| T5  | **How many trusteeships** | `S`: two, `{identity, trust}`, both created at genesis · `R` §5: "[OPEN] the second trusteeship" (stale — it exists) · `B` §4: five — Identity, Trust, Focus, Market, Equity | Target state. Forces T12 |
| T6  | **Who may hold one** | `S`: `holder_actor_uuid` is an actor uuid; nothing forbids a Team · `B` §4: "requiring 1 Individual" · `G`,`R`: silent | Whether a team can hold a trusteeship in its parent |
| T7  | **`resolution` cause** | `S`,`G` §2.2 both declare it in the closed enum; no writer exists in source | Dead vocabulary to delete, or unimplemented intent to keep |
| T8  | **Concurrency class of a contested seat** | `S`,`G` §2.2: concurrent successors create a *visible contest*, both kept, humans resolve · `B` §2B: "Trustee assignments" are Objective Reality, strict alignment required | The blueprint's own taxonomy puts this in B; the implementation puts it in C |
| T9  | **Bet** | `B` §4: an entity under Trustee — Signals / Decision / Expected Impact / 0-n Assessed Impact · `S`: `team_trustee_action` (`signals`, `consideration`, `expectation`) plus 0-n `team_trustee_reality` (`reality`) | Same concept under two names, or two concepts |
| T10 | **Decision Point** | `B` §4: "1 Trustee, 1 Access to a python function" · `S`: `team_trustee_election` delegates to S-Flow by `process_definition_id` + version; no trustee-attached decision point exists | Whether to generalise the election mechanism, build something new, or drop it |
| T11 | **Mandate** | `B` §4: `1 Mandate [C-Text]` on Trustee · `S`: absent | In or out of the to-be state; if in, a build item |
| T12 | **Which trusteeship facilitates an observation** | `S`: hardcoded as the other of two — `"trust" if action.trust == "identity" else "identity"` · `G` §3.2: "facilitating trustee", which one unspecified for observations; specified for elections (Identity↔Trust) · `B`: five trusteeships make "the other one" undefined | Blocks T5. With more than two, the rule needs a basis |

## Step 3: decisions

| #  | Decision | Costs |
| -- | -------- | ----- |
| T1 | The type is `team_trustee_state`. | Documentation only. |
| T2 | Authority is **append-only**. Who holds a trusteeship is the head of a chain linked by `previous_state_uuid`; nothing is ever rewritten and direct handover does not exist. | Documentation only. Source and the genesis plan already agree. |
| T3 | **A trusteeship is not a role.** A role has 0..n holders and is taken by the holder's own decision; a trusteeship has exactly one holder and is filled by election. Holding one does **not** make somebody a member — a trustee is elected out of the members, so the only case the shortcut ever served was a person whose membership ended while they still held a seat, and that state is worth seeing rather than papering over. | No code change: `_has_current_acceptance` already delegates to membership alone. **But nothing tests it** — the rule exists only in a docstring. A behavioural test is required in step 5. |
| T4 | There is no `held_since` field. The payload derives it. | Documentation only. |
| T5 | Two are built, `identity` and `trust`. **Five are the target** — Identity, Trust, Focus, Market, Equity. No third is added until T12 is resolved, because the facilitator rule does not generalise past two and would otherwise make Identity facilitate everything by accident. | Registry states built and target separately. Adding a third is a later element. |
| T8 | A contested trusteeship is a **visible contest**, not automatic resolution. Concurrent valid successors are both kept and the divergence is shown. Category B is rejected for this type: it needs an automatic tie-break, and the only candidates are relay timestamp (unsigned and forgeable) or hash ordering (which hands a governance seat to whoever's uuid sorts lower). An arbitrary winner is worse than a visible contest. | Documentation only. The blueprint's §2B list loses "Trustee assignments". |

| T6 | Only an **Individual** may hold a trusteeship. A team holding Identity would mean admission decisions with no accountable person behind them. | A validation rule that does not exist yet. How it is expressed is still open — see below. |
| T12 | The facilitating trusteeship is **any trusteeship but the subject**. The invariant is that no trusteeship supervises itself; "the counterpart" was only ever a description of what that means when there are exactly two. | **Applied.** Four sites, not the three first found — the fourth was a local named `facilitator` rather than `facilitator_trust`. The validator now rejects `facilitator_trust == trust`; the three derivation sites call `_sole_facilitating_trust`, which returns nothing above two so the caller refuses instead of silently picking Identity. |

Still open: **T6** (how to express), **T7** (reopened, below), **T9**, **T10**, **T11**.

### T7 reopened — the premise was wrong

T7 was decided on my claim that nothing writes the `resolution` cause. That
claim came from grepping for production writers, and it missed that
`append_governance_record` is a generic path any code or peer can write
through, and that the authority assessment treats the cause *differently*:

- `cause: election` requires a matching `team_trustee_election` record naming
  the same `process_uuid`, a valid target predecessor, and a terminal S-Flow
  result electing exactly the named holder.
- `cause: resolution` requires none of that. It requires process evidence
  (`process_uuid`, `process_result_hash`) and the facilitating trusteeship's
  authority, and settles the seat directly.

So `resolution` is a real capability with no facade method: **fill a
trusteeship without an election, on the facilitating trustee's authority.**
Deleting it removes that path rather than tidying an unused name. The change
was reverted and the decision is open again.

Found because deleting it broke `test_filling_trusteeship_ends_all_acting_authority`,
which uses that cause precisely to fill a seat with no election record.

**T7 re-decided: keep and surface it.** `settle_trusteeship` now reaches it —
facilitating authority plus process evidence, no election record — and requires
the seat to be **vacant**.

### T13 — decided: no narrowing

Surfacing `resolution` exposed that the authority model permits more than the
facade offers: a facilitating trustee may write a `resolution` state over a
**sitting** holder, because the assessment requires only that the predecessor
be the current head, never that it be vacant. That is a unilateral replacement
of a serving trustee by the other trustee.

**Decision: the model is not narrowed.** Cryptography here is for attribution
rather than control; the act is signed, attributable and visible in the trail,
and the remedy is the team's rather than a validation rule's. Narrowing it
would make the model a cage, which is the one thing the architecture says it is
not.

The asymmetry is kept and stated: `settle_trusteeship` requires a vacancy, the
assessment does not. What the application offers and what the model accepts are
different questions. `test_the_model_allows_settling_over_a_sitting_trustee`
pins both halves, so the wider behaviour cannot later be "fixed" as a bug.

## Step 5: enforcement

Four tests added to `tests/test_team_logic.py`, all of which fail if the
decision they encode is reverted:

| Test | Encodes |
| ---- | ------- |
| `test_holding_a_trusteeship_is_not_being_on_the_team` | T3 — a founder who leaves keeps the seat and is not a member |
| `test_a_team_cannot_hold_a_trusteeship` | T6 — a Team actor named as holder is refused, seat stays vacant |
| `test_settling_fills_a_vacancy_without_an_election` | T7 — `resolution` reachable; an occupied seat refuses |
| `test_settling_needs_the_facilitating_trusteeship` | T7/T12 — somebody holding neither trusteeship cannot settle |
| `test_the_model_allows_settling_over_a_sitting_trustee` | T13 — the facade refuses, the model accepts, and both halves are deliberate |

`tests/test_type_registry.py` asserts the registry against source: five types
field for field, and all three vocabularies. Suite: **180 tests, green**
(was 175).

F3 is closed by the first of these.

## Element 1 — remaining

- **T9, T10, T11** — blueprint vocabulary (Bet, Decision Point, Mandate). No
  s-team code consequence; they change `../Domain-Driven-Design.md`.
- `settle_trusteeship` has no controller route or UI. Reachable through logic
  only.

## Findings for later elements

Recorded here so they are not lost, and deliberately not acted on:

| #  | Finding | Element |
| -- | ------- | ------- |
| F1 | `_legacy_member_standing` reads three superseded ways of saying "member" for teams made under the old model. A back-compat path, which this review's standing constraints forbid. | 2 — membership |
| F2 | The payload key `holds_role` now means "is a member", and its comment still reads "Taking a role is the only way to be part of a team" — reasoning that §1.1 of the roles document reversed. Stale claims in source, not only in documents. | 3 — roles |
| F3 | No behavioural test asserts that a trusteeship holder whose membership has ended is not a member. Required by T3. | 1 — step 5 |

## Supersedes

Delete at the purge, once every element is through step 5. Trusteeship content
only — these documents cover more, so the *sections* are listed, not the files.

| Document | Section | Replaced by |
| -------- | ------- | ----------- |
| `ARCHITECTURE.md` | the `agreement_identity` sentence in ¶2, and `agreement_identity` in the ¶1 type list | `DESIGN_TYPES.md` § Trusteeship |
| `DESIGN_ROLES_AND_ACTORS.md` | §1.2 `team_trustee` schema line; §1.3 entire; §5 "[OPEN] The second trusteeship" | `DESIGN_TYPES.md` § Trusteeship |
| `DESIGN_GENESIS_AND_GOVERNANCE_PLAN.md` | §2.2 trusteeship paragraphs; §3.1 the five `team_trustee_*` rows; §3.2 the trusteeship rows | `DESIGN_TYPES.md` § Trusteeship — accurate, so this is deduplication rather than correction |

## Retired names

The left column appears in no source file. Checked by
`tests/test_type_registry.py`.

| Retired              | Became                |
| -------------------- | --------------------- |
| `agreement_identity` | `team_trustee_state`  |
