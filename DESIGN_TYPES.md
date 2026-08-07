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

The basis is judged **as the record it names**, not against the head of the
chain now. If the state it points at says this actor held that trusteeship,
the record stands — so decisions taken in office survive the holder leaving,
which is what an append-only trail is for.

It was the other way once: the basis had to *be* the current head. That made a
trustee's whole trail unauthorized the moment they resigned, and did it
invisibly, because records already adopted stayed put and only a replica that
received them afterwards refused them. Whether somebody counted as a member
depended on where a sync happened to fall.

The cost, taken deliberately: somebody who has left can still write new records
naming the state they used to hold. They are signed, attributed and visible,
and the signatures are here to say who did what rather than to prevent it.
What stops it in practice is the application, which will not compose such a
record — the same split as `settle_trusteeship` and a sitting holder.

## Where the blueprint's vocabulary lands

---

# Membership

**To be on a team, an Actor is a member of it.** Membership is its own
relationship, not a role and not a side effect of holding one. A member who has
taken nothing on is still on the team.

**`Member` is not a stored thing.** There is no member record with a name and a
type in it; there is a chain of `team_membership` records per Actor, and
"member" is the current state of that chain. The name comes from the identity,
the kind comes from the actor, and neither is copied into the membership — a
name copied at admission would be the name somebody had that day.

Identity decides membership, and that is the whole of what Identity decides
about a person. A member then takes any role by their own record.

**Vocabulary — `MEMBERSHIP_TRUST`:** `identity`

## `team_membership`

One chain per Actor, and only one. Somebody admitted, gone and admitted again
continues the chain rather than starting a second.

| Field                        | Requirement                                                              |
| ---------------------------- | -------------------------------------------------------------------------- |
| `actor_uuid`                 | required — whose standing this is                                           |
| `state`                      | required — `member` or `former`                                             |
| `previous_membership_uuid`   | required — empty only for an Actor who has never been on this team          |
| `cause`                      | required — from `MEMBERSHIP_CAUSES`                                         |
| `acted_by`                   | required                                                                    |
| `acted_at`                   | required                                                                    |
| `authority_basis_uuid`       | required — empty for `genesis` and `departure`, which rest on no authority   |
| `signals`                    | required — may be empty                                                     |
| `consideration`              | required — may be empty                                                     |
| `expectation`                | required — may be empty                                                     |
| `resolution_uuid`            | optional — required in practice for `admission`, which must name what it implements |

**Vocabulary — `MEMBERSHIP_CAUSES`:** `genesis`, `admission`, `departure`, `removal`

### How standing changes

| Cause       | Who                       | What it needs                                                                                 |
| ----------- | ------------------------- | ----------------------------------------------------------------------------------------------- |
| `genesis`   | the founder, for themself | No predecessor and no authority basis, and no other membership may exist on the team              |
| `admission` | Identity                  | A resolution naming the same actor with outcome `accepted`. A return also names the membership it resumes |
| `departure` | the member, for themself  | Names the current membership. Rests on **no** authority basis — naming one would claim it did      |
| `removal`   | Identity                  | Names the current membership, plus Identity's authority                                            |

Leaving is nobody's decision but the member's own, and it is the counterpart of
Identity's power to remove. That is why a departure may not name an authority
basis at all: it would be claiming the act rested on one.

## `team_member_opening`

Identity says the team is open to applications. One opening admits any number
of people; closing it is a second record naming the first.

| Field                     | Requirement                          |
| ------------------------- | ------------------------------------- |
| `previous_opening_uuid`   | required — empty for the initial record |
| `state`                   | required — `open` or `closed`          |
| `opened_by`               | required                              |
| `opened_at`               | required                              |
| `authority_basis_uuid`    | required                              |
| `closed_at`               | optional — required when `closed`      |

## `team_member_application`

The applicant's own record, and theirs alone to withdraw.

| Field                         | Requirement                          |
| ----------------------------- | ------------------------------------- |
| `opening_uuid`                | required                              |
| `previous_application_uuid`   | required — empty for the initial record |
| `actor_uuid`                  | required                              |
| `submitted_at`                | required                              |
| `state`                       | required — `submitted` or `withdrawn`  |
| `withdrawn_at`                | optional — required when `withdrawn`   |

## `team_member_resolution`

Identity's answer to one application. The decision, not the standing — it stays
true whatever happens later, which is what lets a membership be ended without
rewriting the decision that began it. The same split as an election and the
trusteeship it fills.

| Field                    | Requirement                        |
| ------------------------ | ----------------------------------- |
| `opening_uuid`           | required                            |
| `application_uuid`       | required                            |
| `actor_uuid`             | required                            |
| `outcome`                | required — `accepted` or `rejected`  |
| `resolved_by`            | required                            |
| `resolved_at`            | required                            |
| `authority_basis_uuid`   | required                            |
| `signals`                | required — may be empty              |
| `consideration`          | required — may be empty              |
| `expectation`            | required — may be empty              |

An accepted resolution is followed by a `team_membership` admission naming it.
Pool onboarding reaches the same place by a different resolution.

## Standing, and where it comes from

Membership records are the **only** source. Both admission paths end in one, so
there is nowhere else standing can come from, and an Actor with no record is an
observer.

There was a second source: teams made before membership was a record said
"member" three other ways — an accepted application, a Pool resolution, or a
genesis offer on a role marked `system_key: member` — and standing fell through
to those. It is gone. Teams that relied on it read as observers, visibly,
rather than being answered from a shape the model no longer produces.

`membership_projection` walks the chain and returns `observer`, `member`,
`former`, or `contested`.

**More than one root is a contest.** A return continues the chain it left, so a
second root can only mean two replicas admitting the same person at once, and
that is shown rather than settled by taking whichever sorts last — the same
answer as a contested trusteeship, for the same reason.

## A team may have no members at all

The blueprint asks for one or more. Zero is reachable and is accepted: the
founder leaving is enough.

Nothing bars the last person from going, and that is the point — the
alternative is refusing the final departure, which keeps a team alive by
trapping somebody in it. The Identity holder need not be a member to exercise
Identity, so a team at zero members can still be opened to applications and
recovered.

**Beyond recovery.** Leave, resign Identity, resign Trust — three ordinary acts,
each legitimate on its own — and nothing can happen on that team again: no
opening without Identity's authority, no candidacy without membership, no
settlement without Trust. This is a real end state, not an oversight. The record
survives, and a fork carries the work on.

## Where the blueprint's vocabulary lands

| Blueprint (`Domain-Driven-Design.md`) | Here                                                             |
| ------------------------------------- | ---------------------------------------------------------------- |
| `Member: 1 Name, 1 Type, 1 Actor`     | Not an entity. The current state of an Actor's `team_membership` chain; name and kind are read from the actor, never copied |
| `Team: 1-n Members`                   | `0-n`. Zero is reachable and accepted                             |

---

# The clause shape

A piece of text and where it sits among its siblings, whose children are the
same thing again:

```
<node>
├── text | title   the words
├── order          position among siblings
└── children       the same shape
```

Four types use it. `team_section` names itself with a `title` and holds
clauses; `team_clause`, `team_accountability` and `team_domain` carry `text`.

| Type                  | Under          | Names itself with |
| --------------------- | -------------- | ------------------ |
| `team_section`        | `team`         | `title`            |
| `team_clause`         | `team_section` | `text`             |
| `team_accountability` | `team_role`    | `text`             |
| `team_domain`         | `team_role`    | `text`             |

**Two levels, not arbitrary depth.** The shape permits nesting and this
document does not use it: a section holds clauses and a clause holds nothing.
Nothing is gained by leaving the depth open in a document people have to read
and agree to.

**Content, not record.** These are what people agree to, so they are edited in
place, and they are reactable per node — which is why an accountability is its
own node rather than an entry in a list on the role. Two people editing
different accountabilities have to be able to diverge separately; a list would
collapse both edits into one undiffable conflict.

Editable is not unchecked. Every one is validated against
`CONTENT_FIELDS` on adoption, and content may only contain content — a clause
carrying a role would be a document that owned its own participants.

## `team_section`

| Field   | Requirement                             |
| ------- | ---------------------------------------- |
| `title` | required — what the section is called     |
| `order` | required — a number, position among siblings |

## `team_clause`

| Field   | Requirement                             |
| ------- | ---------------------------------------- |
| `text`  | required                                 |
| `order` | required — a number, position among siblings |

## `team_accountability`

| Field   | Requirement                             |
| ------- | ---------------------------------------- |
| `text`  | required — what the role is answerable for |
| `order` | required — a number, position among siblings |

## `team_domain`

| Field   | Requirement                             |
| ------- | ---------------------------------------- |
| `text`  | required — what the role decides about    |
| `order` | required — a number, position among siblings |

## It is a shape, not a type

Deliberately. The machinery around ordered text already works without knowing
what the text is called: Core's `next_child_order` takes a type name from the
caller, and `_content_hash` takes a set of them.

So another application needing the same thing — an Initiative's expected
impact, a Trustee's mandate, a Flow's outcomes — declares **its own node type
names** against this shape rather than importing S-Team's or receiving them
from Core. Applications may not import one another, and Core's boundary scan
forbids application vocabulary in its source; sharing the shape rather than
the type satisfies both, and the rules are written once here instead of three
times.

What Core would host, if anything, is the type-agnostic helper it does not
have yet: content hashing over a caller-supplied set of type names. That is
not this repository's to make.

---

# Roles, and taking part in them

A **role** is defined work. It has 0..n holders, and a vacant role is not a
problem — it is work nobody has taken. A member takes one by their own record
and nobody else's; an invitation exists and any member may extend one, but it
is a suggestion, and withdrawing it withdraws the suggestion and nothing else.

The six types divide on a line that matters:

- **Content** — `team_role`, `team_accountability`, `team_domain`. Part of what
  people agree to, edited like any other text, and reactable per node so that
  two people editing different accountabilities diverge separately.
- **Records about it** — `team_role_offer`, `team_role_decision`,
  `team_role_holding`. Facts about who is doing what, and therefore
  **append-only**, with a declared contract, like every other record that
  carries authority.

That line was not held before. An offer was revived by rewriting the revoked
one, an answer was rewritten in place, and giving up a seat deleted the holding
outright — so who held a role, and when, was not recorded anywhere. A decision
alone is what holds a role, which makes it authority-bearing; it was stored
like content, and it had no contract at all, so a peer's answer was whatever
they sent and a person was asked to accept it sight unseen.

Each is one chain per actor per role, read by taking the end of it. **More than
one root, or more than one successor, holds nothing** — two answers about one
seat are two people to talk to, not a race to settle by sort order.

## `team_role_offer`

An invitation. Withdrawing one appends a `revoked` link rather than deleting
it, so the fact that there was an invitation survives.

| Field                  | Requirement                                     |
| ---------------------- | ------------------------------------------------ |
| `actor_uuid`           | required                                        |
| `actor_kind`           | required — `individual` or `team`                |
| `state`                | required — from `OFFER_STATES`                   |
| `previous_offer_uuid`  | required — empty for the first offer to an actor |
| `offered_by`           | required                                        |
| `offered_at`           | required                                        |
| `revoked_at`           | optional — required when `revoked`               |
| `revoked_by`           | optional                                        |

**Vocabulary — `OFFER_STATES`:** `offered`, `revoked`

## `team_role_decision`

The actor's own answer, and on its own enough to hold the role. Changing your
mind continues the chain, so when somebody took a role and when they stepped
out of it are both readable.

| Field                       | Requirement                                        |
| --------------------------- | --------------------------------------------------- |
| `actor_uuid`                | required                                            |
| `decision`                  | required — from `ROLE_DECISIONS`                     |
| `previous_decision_uuid`    | required — empty for a first answer                  |
| `decided_at`                | required                                            |
| `reference_hash`            | required — what this answer commits to               |
| `expires_at`                | optional — absent rather than null when there is none |
| `decided_by`                | optional — who answered for a Team, which cannot answer for itself |
| `seated_member_uuids`       | optional — who was on that Team when it took the seat |

**Vocabulary — `ROLE_DECISIONS`:** `accepted`, `refused`

## `team_role_holding`

The child side of a seat: which role in which parent this team holds. Both
sides must exist for a seat to be live, so a hierarchy is visible only once it
has been answered on both.

| Field                      | Requirement                                |
| -------------------------- | ------------------------------------------- |
| `parent_team_uuid`         | required                                    |
| `role_uuid`                | required                                    |
| `order`                    | required — a number, the declared parent order |
| `state`                    | required — from `HOLDING_STATES`             |
| `previous_holding_uuid`    | required — empty for a first claim on a seat  |

**Vocabulary — `HOLDING_STATES`:** `held`, `given_up`

## A Team in a seat

A Team may hold a role in another team, which is what a subteam is. Two
conditions, both checked when the seat is taken:

- the seated team has **at least one member** — containment is vacuously true
  of an empty team, and an abandoned one would otherwise be seatable anywhere;
- **every one of its members is already a member of the team it sits in.**

Membership of a team by a team is *inferred, not assigned*: nobody grants it,
the team either contains no strangers or it does not. **Seating admits
nobody.** It was described the other way once — a team in a role brought
everybody on it into the parent — which made a subteam a way into a team you
had never been admitted to. Containment is the precondition now, and the people
come first.

Checked at the moment of the act, with the member set recorded on the decision
as `seated_member_uuids`. Not re-derived on every read: each team is an
independently shared topic and a parent replica need not have the subteam
mounted at all, so a rule evaluated continuously would leave a team unable to
tell whether its own role was held — and would let the subteam's Identity
revoke the seat by admitting one person. Later drift is a divergence to be
seen, not a silent revocation.

Seats form a DAG, and it is *drawn* as a tree by projecting through home, the
first holding in order that reaches a root.

## What an acceptance covers, and the cost of that

`role_reference_hash` is the document body plus that one role's definition.
Scoped that way, editing the Treasurer's accountabilities does not re-open the
Secretary's acceptance.

Editing the **body** still re-opens everyone's, at every level below. That is
accepted rather than worked around: if the document people agreed to has
changed, their agreement to it is genuinely stale, and being asked again is the
honest answer. A grace period was considered and rejected — it would make
whether somebody holds a role depend on the clock and on local settings, and
two replicas would disagree.

## Where the blueprint's vocabulary lands

| Blueprint (`Domain-Driven-Design.md`) | Here                                                             |
| ------------------------------------- | ---------------------------------------------------------------- |
| `Role: 1 Team, 1 Name, 0-1 Purpose, 0-n Domains, 0-n Accountabilities, 0-n Actors` | Right, except that "Actors" is two different facts — who was invited (`team_role_offer`) and who holds it (`team_role_decision`) — and only the second is holding |
| The Pull Principle                    | Built. A member takes a role by their own answer; nobody countersigns |
| *(nothing)*                           | `team_role_holding` — the blueprint has no way to express a subteam as built |

---

# The Pool

A **Pool** is a separate shared topic that holds no Team document — a waiting
room. It exists so somebody can ask to join a team they cannot yet see:
accepting a Team's invitation is how you get the Team, and there has to be a
way to ask for one without already having it.

The way in:

1. Identity opens a Member opening on the Team.
2. Identity publishes a **Pool invitation** naming that opening, with an expiry.
3. An outsider, invited into the Pool topic, submits an **application**.
4. Identity **resolves** it. On acceptance, a `team_external_member_resolution`
   is written on the *Team* and a membership admission follows it, and the Pool
   resolution carries the Team's connection coordinates so the applicant can
   reach it.

Both sides are append-only, and both are validated. A rejected resolution is
**forbidden** from carrying coordinates; an accepted one is required to.

## `team_pool`

The waiting room itself. A topic, and so the one thing here with children.

| Field         | Requirement                     |
| ------------- | -------------------------------- |
| `team_uuid`   | required — the Team it is for     |
| `team_title`  | required                        |
| `title`       | required                        |
| `created_by`  | required                        |
| `created_at`  | required                        |

## `team_pool_invitation`

| Field                  | Requirement                          |
| ---------------------- | ------------------------------------- |
| `team_uuid`            | required                             |
| `team_title`           | required — must match the Pool's       |
| `opening_uuid`         | required — the Member opening it is for |
| `published_by`         | required                             |
| `published_at`         | required                             |
| `expires_at`           | required — must be after `published_at` |
| `authority_basis_uuid` | required — Identity's                  |

## `team_pool_application`

| Field                         | Requirement                          |
| ----------------------------- | ------------------------------------- |
| `invitation_uuid`             | required                             |
| `team_uuid`                   | required — must match the invitation's |
| `opening_uuid`                | required — must match the invitation's |
| `actor_uuid`                  | required                             |
| `submitted_at`                | required                             |
| `state`                       | required — `submitted` or `withdrawn`  |
| `previous_application_uuid`   | required — empty for the initial record |
| `withdrawn_at`                | optional — required when `withdrawn`   |

## `team_pool_resolution`

| Field                    | Requirement                                     |
| ------------------------ | ------------------------------------------------ |
| `invitation_uuid`        | required                                        |
| `application_uuid`       | required                                        |
| `team_uuid`              | required                                        |
| `opening_uuid`           | required                                        |
| `actor_uuid`             | required                                        |
| `outcome`                | required — `accepted` or `rejected`              |
| `resolved_by`            | required                                        |
| `resolved_at`            | required                                        |
| `authority_basis_uuid`   | required — Identity's                            |
| `signals`                | required — may be empty                          |
| `consideration`          | required — may be empty                          |
| `expectation`            | required — may be empty                          |
| `team_invitation_token`  | optional — an object. **Required** when accepted, and **forbidden** when rejected |

## `team_external_member_resolution`

The Team's own record of an acceptance that happened in a Pool. A governance
record, so it lives on the Team beside memberships rather than in the Pool, and
it is what the admission names as the resolution it implements.

| Field                        | Requirement                              |
| ---------------------------- | ----------------------------------------- |
| `pool_uuid`                  | required                                 |
| `pool_invitation_uuid`       | required                                 |
| `pool_application_uuid`      | required                                 |
| `opening_uuid`               | required                                 |
| `actor_uuid`                 | required                                 |
| `outcome`                    | required — **`accepted` only**            |
| `resolved_by`                | required                                 |
| `resolved_at`                | required                                 |
| `authority_basis_uuid`       | required                                 |
| `application_evidence_hash`  | required — the state hash of the application it answers |
| `signals`                    | required — may be empty                   |
| `consideration`              | required — may be empty                   |
| `expectation`                | required — may be empty                   |

Only accepted, because a rejection changes nothing about the Team and there is
nothing for the Team to record. The refusal lives in the Pool, where it
happened.

## Two properties that are chosen, not overlooked

**Expiry is checked against the application, not the clock.** Whether an
invitation was live is decided by comparing the applicant's `submitted_at` with
the invitation's own `published_at` and `expires_at` — all recorded values — so
an application that was valid when made stays valid however long it takes to
reach anybody. The consequence is that `submitted_at` is the applicant's own
claim and backdating into a closed window cannot be detected. Accepted: the
claim is signed and attributable, Identity still has to resolve the application
before anything happens, and an expiry is a signal to whoever resolves rather
than a gate the applicant is held behind by force.

**The coordinates in an accepted resolution are readable by the whole Pool.**
The token is a general Team invitation, and it sits in a topic every Pool
participant syncs — so anybody Identity has admitted to the waiting room can
read somebody else's acceptance and reach the Team with it. What they get is
*topic access, not membership*: only the named applicant is admitted, so an
interloper reads the Team and remains an observer. Recorded here as a known
property. Scoping the token to the applicant would need Core to compose a
per-actor invitation, which is not this repository's to add.

---

# Trusteeship — blueprint mapping

| Blueprint (`Domain-Driven-Design.md`) | Here                                                             |
| ------------------------------------- | ---------------------------------------------------------------- |
| Trustee                               | `team_trustee_state`. **Not** a specialized Role — no role node is involved |
| Bet — Signals / Decision / Expected Impact / Assessed Impact | `team_trustee_action` (`signals`, `consideration`, `expectation`) plus 0-n `team_trustee_reality` (`reality`) — **already built under another name** |
| Decision Point — "access to a python function" | `team_trustee_election` delegating to an S-Flow process by `process_definition_id` and version. A named, versioned, replicated definition rather than a function reference |
| Agile State / Divergence Warning      | `contested` in the projection above                              |
| Mandate [C-Text]                      | not built                                                        |

