# Type registry — S-Team

What each node type is, what it carries, and which rules govern it. One entry
per type, in one place, so a type is never described in three documents and
implemented in a fourth.

**This file is enforced.** `tests/test_type_registry.py` reads the field tables
below and asserts they equal the contracts declared in
`s_team.logic.TeamLogic`. A field added to the source and not to this file
fails in the pull request that adds it, and the same the other way round. That
is the whole point: the previous documents drifted because nothing could tell
that they had.

Enforcement is per-repository, like the boundary scans — S-Team's types are
asserted here, and each application repository asserts its own.

## How to read an entry

- Every governance record carries a `type` field. It is implied in every table
  and never listed.
- **required** — the field must be present. **optional** — it may be.
  Anything else is a schema error, and a record with a schema error is
  ignored by every projection rather than repaired.
- Governance records are **flat children of the `team` topic** and may not
  contain children.

Only reviewed and decided types appear here. What has not been reviewed yet is
absent rather than marked, and `DESIGN_REVIEW_LEDGER.md` tracks the progress.

---

# Trusteeship

A **trusteeship** is an authority held *for* the team rather than for the
holder's own part in it — to speak for it, to commit it, to keep something of
its on its behalf.

**A trusteeship is not a role**, and the difference is mechanical rather than
nominal. A role has 0..n holders and is taken by the holder's own decision; a
trusteeship has exactly one holder and is filled by election. No `team_role`
node is involved in one.

Membership is the prerequisite: only a current member may stand for a
trusteeship. It does not work in the other direction — **holding a trusteeship
does not make somebody a member.** A trustee is elected out of the members, so
the only case the reverse rule ever covered was somebody whose membership ended
while they still held a seat, and that is a state worth seeing rather than
papering over. The trail records it; the remedy is to fill the trusteeship.

Two exist, named by the `trust` field, created together at team genesis and
both held by whoever made the team.

**Vocabulary — `TRUSTS`:** `identity`, `trust`

Five are the target — Identity, Trust, Focus, Market and Equity. No third is
added before the facilitator rule below has a basis that means something for
more than two.

Authority is **append-only**. Nothing about a trusteeship is ever rewritten:
who holds it is the head of a chain of `team_trustee_state` records linked by
`previous_state_uuid`. Direct handover does not exist — `offer_identity`
refuses on purpose, because a handover would be a rewrite. The seat moves by
resignation, then election.

## `team_trustee_state`

Who holds a trusteeship, as a link in a chain. Standing, not the decision that
produced it — the same split as `team_trustee_election` (the decision) and
this (the seat), and as `team_member_resolution` and `team_membership`.

| Field                   | Requirement                                                                 |
| ----------------------- | --------------------------------------------------------------------------- |
| `trust`                 | required — which trusteeship, from `TRUSTS`                                  |
| `holder_actor_uuid`     | required — empty string means vacant                                         |
| `previous_state_uuid`   | required — empty only for the genesis link                                   |
| `cause`                 | required — from `TRUSTEE_CAUSES`                                             |
| `acted_by`              | required                                                                     |
| `acted_at`              | required                                                                     |
| `authority_basis_uuid`  | required — the record that grants the authority to write this one            |
| `signals`               | required — what was observed. May be empty                                   |
| `consideration`         | required — what was weighed. May be empty                                    |
| `expectation`           | required — what is expected to follow. May be empty                          |
| `process_uuid`          | optional — the S-Flow process, when `cause` is `election`                    |
| `process_result_hash`   | optional — what that process resolved to                                     |

**Vocabulary — `TRUSTEE_CAUSES`:** `genesis`, `election`, `resignation`, `resolution`

**Only an Individual may hold a trusteeship.** A Team in a role brings
everybody on it into the team below, which is why seating one is an admission;
a Team *holding* a trusteeship would go further, leaving admissions,
resignations and elections resting on an authority with no person answerable
for it. The check is at the authority layer rather than the schema, because
the answer is not in the record — it is whether the uuid names a Team — and a
check that reads the tree does not belong in a pure function of the record's
data. An actor the replica cannot place defers and retries, the same as an
unknown signing key: the absence of a Team node is not evidence of a person.

### How a seat moves

Each cause is a different authority, and that is the whole of what the four
mean:

| Cause         | Who writes it            | What it needs                                                                                     |
| ------------- | ------------------------ | -------------------------------------------------------------------------------------------------- |
| `genesis`     | the holder, for themself | Nothing precedes it, so `previous_state_uuid` and `authority_basis_uuid` are both empty, and no other state for this trusteeship may exist |
| `resignation` | the incumbent only       | Their own current state as the basis — the authority to give a seat up is the authority of holding it. Must leave the seat vacant |
| `election`    | the facilitating trustee | A `team_trustee_election` naming the same `process_uuid`, a target predecessor that is still current, and a terminal S-Flow result electing exactly the named holder |
| `resolution`  | the facilitating trustee | Process evidence (`process_uuid`, `process_result_hash`) and facilitating authority — but **no election record**. A seat settled by a decision that was not a formal election |

There is no direct handover. Giving a seat to somebody else is resignation
followed by an election or a settlement, because a handover would be a rewrite
and authority here is append-only.

`resolution` is reached through `settle_trusteeship`, which requires the seat
to be **vacant**.

The authority model is wider than that on purpose: it also accepts a
`resolution` written over a *sitting* holder, because it asks only that the
predecessor be the current head. One trustee can therefore replace the other.
That is deliberate and is not narrowed. Cryptography here is for attribution,
not control — the act is signed, attributable and visible in the trail, and the
remedy for it is the team's, not a validation rule's. What the application
offers and what the model accepts are two different questions, and only the
first is a matter of convenience.

## `team_trustee_candidacy`

Standing for a vacant trusteeship. Writable only by a current member, only
while the projection reads `vacant`, and only once per actor at a time.
Withdrawal appends a second record naming the first in
`previous_candidacy_uuid`, so a candidacy is its own small chain.

| Field                      | Requirement                                        |
| -------------------------- | -------------------------------------------------- |
| `trust`                    | required                                           |
| `actor_uuid`               | required                                           |
| `vacant_state_uuid`        | required — which vacancy this answers               |
| `previous_candidacy_uuid`  | required — empty for the first record               |
| `submitted_at`             | required                                           |
| `state`                    | required — `active` or `withdrawn`                  |
| `withdrawn_at`             | optional                                           |

## `team_trustee_election`

The decision process that fills a vacancy. It does not fill it — implementing
it writes a `team_trustee_state` with `cause: election`.

| Field                                | Requirement                                          |
| ------------------------------------ | ---------------------------------------------------- |
| `trust`                              | required                                             |
| `process_uuid`                       | required — the S-Flow process carrying the decision   |
| `process_definition_id`              | required                                             |
| `process_definition_version`         | required                                             |
| `electorate_actor_uuids`             | required                                             |
| `triggered_by`                       | required                                             |
| `triggered_at`                       | required                                             |
| `target_state_uuid`                  | required — the vacancy this election is aimed at      |
| `facilitator_trust`                  | required                                             |
| `facilitator_actor_uuid`             | required                                             |
| `facilitator_authority_basis_uuid`   | required                                             |

An election counts as under way only while **all** of these hold: no state
record already implements its `process_uuid`; its `target_state_uuid` is still
the current head; and its Flow result is visible to this session and not void.

The last condition is a liveness guard, not a detail. A client that cannot see
the Flow process cannot tell whether it is running, so an election it can never
resolve is ignored rather than allowed to freeze the seat indefinitely.

## `team_trustee_action`

What a trustee did, with the reasoning that stands behind it.

| Field                   | Requirement                                       |
| ----------------------- | ------------------------------------------------- |
| `trust`                 | required                                          |
| `action_kind`           | required — from `ACTION_KINDS`                     |
| `subject_uuid`          | required — what was acted on                       |
| `acted_by`              | required                                          |
| `acted_at`              | required                                          |
| `authority_basis_uuid`  | required                                          |
| `signals`               | required — what was observed. May be empty         |
| `consideration`         | required — what was weighed. May be empty          |
| `expectation`           | required — what is expected to follow. May be empty |
| `payload`               | required — an object; kind-specific detail         |

**Vocabulary — `ACTION_KINDS`:** `member_opening`, `member_resolution`, `trustee_resignation`, `election_implementation`, `domain_action`

## `team_trustee_reality`

What actually happened, observed against an action. Zero or more per action —
one person's observation does not close the question, and divergent
observations are kept rather than reconciled.

| Field                   | Requirement                        |
| ----------------------- | ---------------------------------- |
| `action_uuid`           | required — the action observed      |
| `observed_by`           | required                           |
| `observed_at`           | required                           |
| `reality`               | required — non-empty                |
| `authority_basis_uuid`  | required                           |

**Observation is cross-trusteeship.** A reality about an Identity action is
written under **Trust**'s authority, and one about a Trust action under
**Identity**'s. Neither trusteeship assesses its own outcomes.

## The facilitating trusteeship

Elections, settlements and observations all rest on a trusteeship *other than*
the one being acted on. The invariant is that **no trusteeship supervises
itself**; "the counterpart" is only what that means when there happen to be
two.

The validator says exactly that — `facilitator_trust` must name a trusteeship
and must not be the subject. The three places that *derive* a facilitator ask
for the single eligible one and refuse when there is more than one, so adding a
third trusteeship fails loudly at the point of use instead of quietly resolving
to Identity, which is what an `else` branch would have done.

## The projection, and divergence

`trustee_projection` walks the `previous_state_uuid` chain from the record with
an empty predecessor and returns one of four states:

| State           | When                                                       |
| --------------- | ---------------------------------------------------------- |
| `unconfigured`  | no valid root record                                        |
| `held`          | the chain ends at a record with a holder                    |
| `vacant`        | the chain ends at a record with an empty holder             |
| `contested`     | more than one root, or more than one successor to the head  |

`contested` is a **fork in the chain**, carrying the contending record uuids.
Nothing resolves it automatically. Both writes are kept; the UI shows the
divergence; it collapses when a human withdraws.

This is a decision, not an omission. Resolving a contested seat automatically
needs a tie-break, and the only two available are the relay's timestamp — which
is unsigned and forgeable, so it would let anyone win a seat by touching a file
— and hash ordering, which would hand a governance seat to whichever uuid sorts
lower. For a scarce authority an arbitrary winner is worse than a visible
contest, so the contest is the answer.

That is the blueprint's **Agile State / Divergence Warning** already built, and
it is worth naming precisely, because the mechanism generalises: the same
walk backs membership, candidacies and member openings via
`_record_chain_projection`. Divergence detection in this codebase is
*fork-in-an-append-only-chain*, not a separate conflict subsystem.

Records with a schema error are excluded from the walk before it starts, so a
malformed write can neither hold a seat nor manufacture a contest.

## Authority basis

`authority_basis_uuid` points at the record that grants the right to write
this one. It is a pointer, not a flag, and it is checked at write time and
again on every read of a peer's record.

- Holder of the trusteeship → their current `team_trustee_state`.
- Trusteeship vacant, actor has an active candidacy → that candidacy.
- Otherwise → empty, and the write is refused.

A basis that names a state which is no longer the head is **stale**, and the
record it supports is unauthorized. This is what makes the append-only chain
do real work: authority expires by being superseded, without anything being
rewritten.

## Where the blueprint's vocabulary lands

| Blueprint (`Domain-Driven-Design.md`) | Here                                                             |
| ------------------------------------- | ---------------------------------------------------------------- |
| Trustee                               | `team_trustee_state`. **Not** a specialized Role — no role node is involved |
| Bet — Signals / Decision / Expected Impact / Assessed Impact | `team_trustee_action` (`signals`, `consideration`, `expectation`) plus 0-n `team_trustee_reality` (`reality`) — **already built under another name** |
| Decision Point — "access to a python function" | `team_trustee_election` delegating to an S-Flow process by `process_definition_id` and version. A named, versioned, replicated definition rather than a function reference |
| Agile State / Divergence Warning      | `contested` in the projection above                              |
| Mandate [C-Text]                      | not built                                                        |

