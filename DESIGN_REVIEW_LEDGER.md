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
| 2 | Membership                     | **5 — done**, bar M4/M8/M12 carried forward |
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
| `DESIGN_ROLES_AND_ACTORS.md` | §1.1 from "To be on a team" to the end of the membership-chain paragraph | `DESIGN_TYPES.md` § Membership |
| `DESIGN_GENESIS_AND_GOVERNANCE_PLAN.md` | §3 "the existing offer/answer model… system Member role" paragraph; §3.1 the `system Member team_role`, `team_member_opening`, `team_member_application` and `team_member_resolution` rows; §3.2 the membership rows | `DESIGN_TYPES.md` § Membership — §3.1's opening row is wrong (`member_role_uuid` does not exist) and the §3 paragraph describes the reversed model |

---

# Element 2 — Membership

## Step 1: extracted

Four node types, flat children of `team`, all in `GOVERNANCE_FIELDS`:
`team_membership`, `team_member_opening`, `team_member_application`,
`team_member_resolution`. One vocabulary: `MEMBERSHIP_CAUSES` =
`genesis | admission | departure | removal`.

**Membership is a standing, not a decision.** The chain is per Actor, so
somebody admitted, gone and admitted again has one history. The admission
path is opening → application → resolution → membership, and the resolution
and the membership are deliberately two records: the resolution stays true
whatever happens later, the membership is where the person stands now.

Authority, per cause:

| Cause       | Who        | What it needs                                                                       |
| ----------- | ---------- | ------------------------------------------------------------------------------------ |
| `genesis`   | the founder, for themself | No predecessor, no authority basis, and no other membership may exist on the team |
| `admission` | Identity   | A resolution naming the same actor with outcome `accepted`, plus Identity authority   |
| `departure` | the member, for themself | Names the current membership. Rests on **no** authority basis — naming one would claim it did |
| `removal`   | Identity   | Names the current membership, plus Identity authority                                 |

**Probed, not inferred** (throwaway test, since deleted):

- A team **can reach zero members**. The founder leaving is enough.
- At zero members the departed founder still **holds both trusteeships** and
  can still open a member opening, so the team recovers — the Identity holder
  need not be a member to exercise Identity.
- Elections are blocked at zero members: `only a current Member may start an
  election`.
- **Terminal state.** Leave, resign Identity, resign Trust — three ordinary,
  individually-legitimate acts by one person — and the team is permanently
  dead: no opening (`the authority basis is not available`), no candidacy
  (`only a current Member may become a candidate`), no settlement
  (`only Trust may settle Identity`). Nothing can ever happen on it again.

## Step 2: contradictions

`S` = source, `G` = genesis plan, `R` = roles document, `B` = blueprint.

### Stale documentation — no design decision

| #  | Question | Positions |
| -- | -------- | --------- |
| M2 | `member_role_uuid` on `team_member_opening` | `G` §3.1 lists it as required · `S`: no such field |
| M3 | How Member standing is derived | `G` §3: "a live application plus an accepted resolution for the system Member role" · `S`,`R` §1.1: membership is its own record and the system Member role is gone |

### Open — these need a decision

| #   | Question | Positions | Consequence |
| --- | -------- | --------- | ----------- |
| M1  | **`_legacy_member_standing`** | `S`: a back-compat path reading three superseded ways of saying "member" — accepted application, Pool resolution, or a genesis offer on the system Member role. Not just a read: the **authority model consults it** when ending a membership that names no predecessor, and `current_member_uuids` consults it for the electorate | The review's standing constraints forbid back-compat paths. Deleting it un-members every team made under the old model — they become observers, unable to act, vote or be removed |
| M4  | **Is a seated Team a member of its parent?** | `R` §1.1: "a team in a role brings everybody on it into this one, so it is an admission — and admissions are Identity's" · `S`: `seat_team` writes only a `team_role_decision`; `current_member_uuids` never counts seated teams. Meanwhile a *person* cannot take a role without being a member | An asymmetry: teams hold roles without membership, people cannot |
| M5  | **Is `Member` an entity?** | `B` §4: `Member: 1 Name, 1 Type, 1 Actor` · `S`: a chain of records; "member" is a projection over it. Name comes from the identity, not the record | Already indicated as a projection; recorded here to be settled explicitly |
| M6  | **Identity as the membership authority** | `S`: `"identity"` passed as a literal at three sites in the assessment | Under five trusteeships, is "Identity decides membership" a rule of the model or today's default? Declared, or inlined? |
| M7  | **Concurrent admission of the same actor** | `S`: `membership_projection` takes `roots[-1]`, the newest root, with no contest check. `trustee_projection` treats more than one root as `contested` | Re-admission legitimately makes a second root, so multiple roots are *normal* here. But that makes two replicas concurrently admitting the same person indistinguishable from a re-admission, and it is resolved silently by sort order — which is exactly what T8 rejected for trusteeship |
| M8  | **`team_external_member_resolution`** | Grants membership, but belongs to Pool onboarding | Registered under element 2 or deferred to element 5 |
| M9  | **`Team: 1-n Members`** | `B` §4 requires at least one · `S`: zero is reachable and was observed | The blueprint's cardinality is not what is built |
| M10 | **The terminal state** | `S`: one person, acting alone and legitimately, can put a team beyond recovery | Accept as a consequence of nobody being trapped, or prevent it |

## Step 3: decisions

| #   | Decision | Costs |
| --- | -------- | ----- |
| M1  | **`_legacy_member_standing` is deleted**, with `MEMBER_ROLE_SYSTEM_KEY` and the two other sites that consulted it. Standing comes from membership records and nowhere else; both admission paths end in one, so the fallback answered only for teams predating them. | **Applied.** Teams whose standing was written only the old way now read as observers, loudly. Ending a membership always names the one it ends — the exception for standing that had nothing to name is gone. The test that pinned the old behaviour now pins the new. |
| M2  | `team_member_opening` has no `member_role_uuid`. | Documentation only. |
| M3  | Membership is its own record. The system Member role is not how standing is derived. | Documentation only. |
| M5  | **`Member` is a projection**, not a stored entity — the current state of an Actor's chain. The name comes from the identity, not the record. | Documentation only. |
| M9  | A team may have **zero members**. The blueprint's `1-n` is not what is built. | `../Domain-Driven-Design.md` changes. |
| M10 | **A team can be put beyond recovery, and that is accepted.** Leave, resign Identity, resign Trust — each legitimate alone — and nothing can happen on it again. The alternative is refusing to let the last person go, which traps somebody in a team to keep it alive. The record survives and a fork can carry the work on. | Must be documented and tested, so it stays a known state rather than a discovery. |
| M4  | Deferred to element 3 — whether seating a Team admits it depends on how roles and holdings are modelled. | Carried forward. |
| M6  | Declare the membership authority rather than inlining `"identity"` at three sites. | Not yet applied. |
| M7  | **Concurrent admission becomes a visible contest.** A re-admission names the ended membership it follows, so a second *root* can only mean two replicas admitting the same person at once, and that is shown rather than resolved by sort order. | Not yet applied. Needs `_admit` to name the predecessor and `membership_projection` to treat multiple roots as contested. |
| M8  | `team_external_member_resolution` is registered with element 5, noted here as an admission source. | Carried forward. |

### M11 — new, open, and the reason M1 mattered

Deleting the legacy path exposed a defect it had been masking.

`_trust_authority` requires `authority_basis_uuid` to equal the **current head**
of that trusteeship's chain. So a decision is authorised against the state of
the world *now*, not the state when it was written — and **every past decision
by a trustee becomes unauthorized the moment they resign.**

Probed directly (throwaway test, since deleted): an admission written by
Identity, re-assessed after that Identity resigned, returns
`unauthorized: the trusteeship authority basis is stale`. Records already
adopted survive locally, so the damage is invisible until a replica receives
the record *after* the resignation — then it refuses it, and the admitted
person never lands there at all.

It is therefore **order-dependent**: whether somebody is a member on a peer
replica depends on whether a sync happened between their admission and the
admitting trustee's resignation. `test_concurrent_acting_decisions_and_reality_remain_visible`
syncs at that exact point now, with a comment saying why; it is about
concurrent acting decisions, not this.

The tension: the staleness check exists to stop a *former* trustee writing new
decisions against their old basis. Removing it fixes history but permits that.

**Decided: judge against the basis state itself.** A record is authorized if
the state it names says this actor held that trusteeship. Decisions taken in
office stand. The cost is accepted on the same reasoning as T13 — a departed
trustee writing new records against their old state is signed, attributed and
visible, and what stops it in practice is the application, which will not
compose one.

Applied to the **state** branch of `_trust_authority` only, which is what was
decided and what the probe demonstrated. `test_a_trustees_decisions_survive_their_resignation`
pins it, and `test_concurrent_acting_decisions_and_reality_remain_visible` now
passes without the sync that was papering over it.

### T12 correction — six sites, not four

Element 1 recorded four hardcodes of "the other of two". Two more surfaced
while grepping for M6, both missed because the earlier pattern looked for
`facilitator_trust` and these did not use that name:

- the authority assessment for `team_trustee_reality`, which used a local
  called `facilitator`;
- the decision-trail payload, which derived it from a tuple element.

Both now call `_sole_facilitating_trust`. The assessment refuses when the
answer is ambiguous; the payload carries nothing, which is honest.

### M12 — new, open

M11 was applied to the state branch of `_trust_authority`. Two other places
judge a past record against the present in the same way, and were left alone
rather than changed on inference:

- **Ending a membership** checks that the named predecessor *is the current*
  membership. Once superseded, re-assessing that ending fails.
- **Acting authority** (the candidacy branch) requires the trusteeship to be
  vacant *now* and the candidacy to be active *now*, so an acting trustee's
  past decisions stop being authorized once the seat is filled.

The second is arguably intended — acting authority is explicitly temporary —
but the order-dependence is the same, and write-time refusal already comes from
`_authority_basis_for_actor` returning nothing, so the assessment need not
carry it.

## Step 5: enforcement

Six tests added, each failing if its decision is reverted:

| Test | Encodes |
| ---- | ------- |
| `test_standing_written_only_the_old_way_no_longer_counts` | M1 — legacy standing reads as observer, and there is no membership left to end |
| `test_a_trustees_decisions_survive_their_resignation` | M11 — an admission and the admitting Identity's resignation in one sync, and the member still lands |
| `test_a_return_continues_the_membership_chain` | M7 — admitted, left, admitted again: three records, one chain |
| `test_two_membership_roots_for_one_actor_are_a_contest` | M7 — a second root is shown, not settled by sort order |
| `test_a_team_can_be_left_beyond_recovery` | M10 — the terminal state, and that all four ways back are refused |

`tests/test_type_registry.py` now covers the four membership types field for
field, `MEMBERSHIP_CAUSES`, and `MEMBERSHIP_TRUST` — declared as a plain string
because a vocabulary of one names a rule rather than offering a choice.
Suite: **186 tests, green** (was 180).

## Element 2 — remaining

- **M4** deferred to element 3, **M8** to element 5, **M12** open.
- **M9** changes `../Domain-Driven-Design.md`, not s-team.

## Retired names

The left column appears in no source file. Checked by
`tests/test_type_registry.py`.

| Retired              | Became                |
| -------------------- | --------------------- |
| `agreement_identity` | `team_trustee_state`  |
