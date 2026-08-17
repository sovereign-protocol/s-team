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

Every node type S-Team declares is here. `DESIGN_RULES.md` holds what applies
across them, and `DESIGN_UI.md` how they are presented.

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
this (the seat), and as `team_membership_invitation` (the door being opened)
and `team_membership` (somebody standing inside it).

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
| `process_uuid`          | optional — the S-Flow process that informed it, when `cause` is `election`   |

**Vocabulary — `TRUSTEE_CAUSES`:** `genesis`, `election`, `resignation`, `resolution`

**Only an Individual may hold a trusteeship.** A Team *holding* one would leave
invitations, removals, resignations and elections resting on an authority with
no person answerable for it. The check is at the authority layer rather than the schema, because
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
| `election`    | the facilitating trustee | A `team_trustee_election` naming the same `process_uuid`. **The result is not checked against the holder** — see below |
| `resolution`  | the facilitating trustee | Facilitating authority, and a **vacant** seat. No process, no election record: a seat filled where nobody ran one |

There is no direct handover. Giving a seat to somebody else is resignation
followed by an election or a settlement, because a handover would be a rewrite
and authority here is append-only.

Both are reached through `settle_trusteeship`. Naming an election lets it
replace a sitting holder, because replacing one is what an election is for;
without an election it may only fill a **vacant** seat, since the way out of an
occupied one is the holder's own resignation.

**Nothing checks the holder against the result.** It could — the result is
verifiable, and this application used to do it, implementing the outcome
automatically once the hash matched. It does not any more. A decision nobody
takes is a decision nobody can be answerable for, so a person reads the
process and puts somebody in the seat, and the record says who did that, on
what authority, and which process they were reading. A facilitator can seat
somebody the election did not choose; the trail will say so, and that is the
remedy — the same one every other act here has.

The authority model is wider still on purpose: it also accepts a `resolution`
written over a *sitting* holder, because it asks only that the predecessor be
the current head. `settle_trusteeship` will not write one, but the model does
not forbid the record. That is deliberate and is not narrowed. Cryptography
here is for attribution,
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

Which flow is an election, and for which seat. That is all it is: an election
is **a flow the team runs**, differing from any other only in that every
member is a required participant, and this record is what says so.

| Field            | Requirement                                          |
| ---------------- | ---------------------------------------------------- |
| `trust`          | required — the seat it is about                       |
| `process_uuid`   | required — the S-Flow process carrying the decision   |
| `triggered_by`   | required                                             |
| `triggered_at`   | required                                             |

It used to carry the electorate, the target seat, the facilitator and their
authority, because implementing it was automatic and all of that had to be
checked first. Nothing is implemented automatically now, so none of it is
evidence for anything: who takes part is the flow's own business, and who
settles the seat is judged when they settle it.

**Under way means unsettled.** An election counts until some
`team_trustee_state` names its `process_uuid` — read from this team's own
records, with no question put to S-Flow. The old rule asked whether the
process had ended, which a client that could not see the process could not
answer, and a record it could never resolve froze the seat for good.

**Members take one up without being asked.** Every other item the team runs
waits to be connected to, because nobody has to care about it; taking part in
an election is what being a member means here, so a member's client asks for
the process itself. It is asked once — a client that has held the process and
put it down again has said what it wanted.

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
| `value`                 | required — the decision in words. May be empty      |
| `signals`               | required — what was observed. May be empty         |
| `consideration`         | required — what was weighed. May be empty          |
| `expectation`           | required — what is expected to follow. May be empty |
| `payload`               | required — an object; kind-specific detail         |

**Vocabulary — `ACTION_KINDS`:** `membership_invitation`, `membership_removal`, `trustee_resignation`, `election_implementation`, `domain_action`

## `team_trustee_reality`

What actually happened, observed against an action. Zero or more per action —
one person's observation does not close the question, and divergent
observations are kept rather than reconciled.

**A child of the action it observes**, and the only record whose place is
another record rather than a container. Which decision an observation is about
is a fact about where it sits, not a uuid it carries and could carry wrongly.
An action holds nothing else, so it needs no container between them — and one
there could not exist before the action itself had been adopted.

| Field                   | Requirement                        |
| ----------------------- | ---------------------------------- |
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

The places that *derive* a facilitator ask for the single eligible one and
refuse when there is more than one, so adding a third trusteeship fails loudly
at the point of use instead of quietly resolving to Identity, which is what an
`else` branch would have done.

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
walk backs membership, candidacies and membership invitations via
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

The Agreement has ordinary `agreement_title` and `agreement_version` fields on
the Team beside its sections. There is no publication record. Its consolidated
truth is derived from perspectives: every current Identity holder must expose
the same name, version, sections and clauses. If they differ, no consolidated
Agreement exists and Identity cannot open a membership. A badge stores both
the human-readable version and exact content hash. Identity owns badge
validity: matching the declared version keeps the badge current, while the
hash preserves exactly what the Actor reviewed for audit and divergence.

**To be on a team, an Actor is a member of it.** Membership is its own
relationship, not a role and not a side effect of holding one. A member who has
taken nothing on is still on the team.

**`Member` is not a stored thing.** There is no member record with a name and a
type in it; there is a chain of `team_membership` records per Actor, and
"member" is the current state of that chain. The name comes from the identity,
the kind comes from the actor, and neither is copied into the membership — a
name copied when they joined would be the name somebody had that day.

**Identity declares the class and issues the badge.** Identity declares which
memberships this team supports and when each accepts applications. The Actor
writes the application and its answers; Identity accepts it by issuing the
membership badge. The Actor may invalidate their own badge, and Identity may
invalidate it through `removal`.

**Vocabulary — `MEMBERSHIP_TRUST`:** `identity`

## The Onboarding Pool

**Derived, not recorded.** The pool is every Actor publishing on the team's
channel who is not a current member. There is no pool record, no pool topic and
no way to join one: being on the channel *is* being in the pool, and it is
reached the way every other topic is, by being given it.

That is the whole definition, and it replaces a waiting room built from five
node types and a second shared topic. What the waiting room existed for was
asking to join a team you could not see — and that requirement is gone, because
membership now requires answering the visible membership requirement and, when
one exists, explicitly accepting the Agreement. The pool has to read the team.
Onboarding is therefore bounded by topic access: whoever hands out the topic
decides who may ever ask, and everyone who has it reads everything on it.

## Membership types

A `team_membership_type` is a membership this team supports — a **name**, a
description of its **requirements**, the **acceptance requirement** Identity
asks the Actor to answer, and an **order** among its siblings.

**Two supplied texts, followed by one answer.** `requirements` is Membership
Info read while deciding. `acceptance` is Identity's requirement shown at the
moment of accepting. The Actor's answer is not written back into the type; it
is stored as `acceptance_text` on their membership record.
Content rather than a record, exactly like `team_role`: edited in place, part
of what people read before accepting, and no append-only chain, because
deleting one is how a team stops supporting a membership. Identity creates and
deletes it; that is the one way it differs from a role, which anybody on the
team may define.

It carries no enforced field table for the same reason `team_role` carries
none — the enforcement dicts cover records with authority contracts, and this
is document content.

**Deleting one needs no cascade.** A membership names its type by uuid. Delete
the type and every membership on it stops resolving, so those Actors read as
non-members and are back in the pool — without a single record being rewritten.
The append-only trail survives intact and still says what everybody was.

**And their roles go with it.** A role is work a *member* holds, so an answer
given by somebody who is no longer on the team holds nothing: `role_holders`
reads standing beside the answer and leaves them off. Nothing is written into
the role — their `team_role_decision` stands exactly as they left it — which
is what lets the holding come back when they take a membership up again,
without anybody re-answering. The same applies to leaving and to `removal`.

**Individuals only.** A seated Team has no membership of its own to read: its
standing is containment, checked when it took the seat (§A Team in a seat), so
asking this question of one would unseat every subteam.

Every team is created with one, so the founder's `genesis` membership has a
type to name.

## `team_membership_invitation`

Identity opening one membership type to the pool, for a window. One chain per
type, and **only one invitation per type at a time** — reopening continues the
chain rather than starting a second, so the history is one line.

| Field                      | Requirement                                     |
| -------------------------- | ----------------------------------------------- |
| `membership_type_uuid`     | required — which membership this opens           |
| `previous_invitation_uuid` | required — empty for the first record            |
| `state`                    | required — `open` or `closed`                    |
| `opened_by`                | required                                        |
| `opened_at`                | required                                        |
| `expires_at`               | required — must be after `opened_at`             |
| `authority_basis_uuid`     | required — Identity's                            |
| `closed_at`                | optional — required when `closed`                |

**The window is checked against the application, not the clock.** Whether an
invitation was live is decided by comparing the application's own `applied_at`
with the invitation's `opened_at` and `expires_at` — all recorded values — so
two replicas reading the same records always agree, and an acceptance that was
valid when made stays valid however long it takes to arrive. The open/closed
toggle is a control over the record; it is not what anybody reads to decide
whether somebody is a member.

The cost is the same one the model already accepts elsewhere: `applied_at` is the
applicant's own claim and backdating into a closed window cannot be detected. It
is signed and attributable, and the remedy is `removal`.

## `team_membership_application`

The Actor's signed application for one open membership. It snapshots both the
request and response so the later badge states exactly what was asked and
answered.

| Field                        | Requirement |
| ---------------------------- | ----------- |
| `actor_uuid`                 | required |
| `membership_type_uuid`       | required |
| `invitation_uuid`            | required |
| `previous_membership_uuid`   | required — empty when first joining |
| `applied_at`                 | required — inside the invitation window |
| `membership_info`            | required — may be empty |
| `acceptance_requirement`     | required |
| `acceptance_text`            | required |
| `agreement_accepted`         | required boolean |
| `agreement_version`          | required — empty when no Agreement exists |
| `reference_hash`             | required — exact consolidated Agreement hash |

## `team_membership`

One chain per Actor, and only one. Somebody who took a membership, left and
took one again continues the chain rather than starting a second — and so does
somebody moving between types, because **an Actor is on one membership type at
a time**. Which one is whatever the head of their chain names.

| Field                        | Requirement                                                              |
| ---------------------------- | -------------------------------------------------------------------------- |
| `actor_uuid`                 | required — whose standing this is                                           |
| `state`                      | required — `member` or `former`                                             |
| `membership_type_uuid`       | required — which membership this places them on, or the one they left       |
| `previous_membership_uuid`   | required — empty only for an Actor who has never been on this team          |
| `cause`                      | required — from `MEMBERSHIP_CAUSES`                                         |
| `reference_hash`             | required — the Team text version present when this answer was made           |
| `acted_by`                   | required                                                                    |
| `acted_at`                   | required                                                                    |
| `authority_basis_uuid`       | required — Identity's for badge issuance/removal; empty for `genesis` and `departure` |
| `acceptance_text`            | required — the Actor's non-empty answer for `acceptance`; empty for other causes |
| `agreement_accepted`         | required boolean — true when this act explicitly accepts an existing Agreement; false when none exists or the cause is not an acceptance |
| `agreement_version`          | required — human-readable version accepted; may be empty |
| `membership_info`            | required — Membership Info copied from the application; may be empty |
| `acceptance_requirement`     | required — Identity's requirement copied from the application; may be empty outside acceptance |
| `signals`                    | required — may be empty                                                     |
| `consideration`              | required — may be empty                                                     |
| `expectation`                | required — may be empty                                                     |
| `invitation_uuid`            | optional — required for `acceptance`, which must name the window it answers  |
| `application_uuid`           | optional — required for `acceptance`, which must name the Actor's application |

**Vocabulary — `MEMBERSHIP_CAUSES`:** `genesis`, `acceptance`, `departure`, `removal`

### How standing changes

| Cause        | Who                        | What it needs                                                                                     |
| ------------ | -------------------------- | ------------------------------------------------------------------------------------------------- |
| `genesis`    | the founder, for themself  | No predecessor and no authority basis, and no other membership may exist on the team                |
| `acceptance` | Identity                   | The Actor's application copied exactly into a badge, plus Identity's authority basis |
| `departure`  | the member, for themself   | Names the current membership. Rests on **no** authority basis — naming one would claim it did        |
| `removal`    | Identity                   | Names the current membership, plus Identity's authority                                             |

The application and departure are the Actor's own signed acts. Badge issuance
and removal are Identity's signed acts and carry Identity's authority basis.

**An acceptance records distinct answers.** `acceptance_text` answers
Identity's membership requirement. When an Agreement exists,
`agreement_accepted` records the separate explicit consent and
`reference_hash` identifies the exact text read. With no Agreement, the boolean
is false and its absence does not close the membership invitation.

The command is refused unless the membership type has a non-empty Acceptance
Requirement and the Actor supplies non-empty Acceptance Text. If the team has
an Agreement (a title or section), explicit Agreement consent is also required;
without one, consent is false and membership may still be accepted. Both the
answer and the consent boolean are stored on the record.

### The membership badge, and what makes it stale

`reference_hash` is the exact Agreement snapshot the Actor reviewed. It is
evidence for inspecting content divergence, not the validity clock. Identity's
human-readable `agreement_version` determines freshness, so the badge has two
states and no more:

| Status     | When                                                        |
| ---------- | ----------------------------------------------------------- |
| `accepted` | the badge version equals Identity's consolidated Agreement version |
| `outdated` | it does not — Identity declared a substantial new version       |

Editing the Agreement without changing its version is Identity's declaration
that the change is non-substantial. Members retain current badges, see the
content divergence, and may inspect, adopt, or leave. Changing the Agreement
version declares a substantial change: existing badges become `outdated`, and
the member re-answers through a renewal application before Identity issues a
new badge. Standing never depends on the clock or local grace-period settings.

There is no `expired` and no `refused`. An invitation expires; a membership does
not, and refusing one is simply not taking it.

**An acceptance is public and adoptable like any other record.** It is written
on the team's topic and reaches the others through the ordinary peer-adoption
path, `auto_adopt_mode` included. Nothing new carries it.

## Standing, and where it comes from

Membership records are the **only** source. There is one way in and it ends in
one, so there is nowhere else standing can come from, and an Actor with no
record is in the pool.

One more thing can end it without any record being written: **the membership
type going away.** Standing is read as the pair (chain head says `member`, the
type it names still exists), so deleting a type returns everybody on it to the
pool. That is the only place standing depends on something outside the chain,
and it is deliberate — the alternative is a cascade that rewrites other people's
records.

`membership_projection` walks the chain and returns `pool`, `member`, `former`,
or `contested`.

**More than one root is a contest.** A return continues the chain it left, and
so does a move between types, so a second root can only mean two replicas
writing a first membership for the same person at once — shown rather than
settled by taking whichever sorts last, the same answer as a contested
trusteeship, for the same reason.

## A team may have no members at all

The blueprint asks for one or more. Zero is reachable and is accepted: the
founder leaving is enough.

Nothing bars the last person from going, and that is the point — the
alternative is refusing the final departure, which keeps a team alive by
trapping somebody in it. The Identity holder need not be a member to exercise
Identity, so a team at zero members can still be opened to the pool and
recovered.

**Beyond recovery.** Leave, resign Identity, resign Trust — three ordinary acts,
each legitimate on its own — and nothing can happen on that team again: no
invitation without Identity's authority, no candidacy without membership, no
settlement without Trust. This is a real end state, not an oversight. The record
survives, and a fork carries the work on.

## Where the blueprint's vocabulary lands

| Blueprint (`Domain-Driven-Design.md`) | Here                                                             |
| ------------------------------------- | ---------------------------------------------------------------- |
| `Member: 1 Name, 1 Type, 1 Actor`     | Not an entity. The current state of an Actor's `team_membership` chain. The *Type* is `team_membership_type`, named by uuid; the name and kind are read from the actor, never copied |
| `Team: 1-n Members`                   | `0-n`. Zero is reachable and accepted                             |
| The Pull Principle                    | Now membership too, not only roles. Identity opens a type; the Actor takes it |

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

Five types use it. `team_agreement` names itself with a `name` and holds
sections; `team_section` names itself with a `title` and holds clauses;
`team_clause`, `team_accountability` and `team_domain` carry `text`.

A container sits between a parent and its children only where the parent
holds more than one kind. An agreement holds sections and a section holds
clauses, so there the parent is already the predicate.

| Type                  | In container      | Under            | Names itself with |
| --------------------- | ----------------- | ---------------- | ------------------ |
| `team_agreement`      | `agreements`      | `team`           | `name`             |
| `team_section`        | —                 | `team_agreement` | `title`            |
| `team_clause`         | —                 | `team_section`   | `text`             |
| `team_accountability` | `accountabilities`| `team_role`      | `text`             |
| `team_domain`         | `domains`         | `team_role`      | `text`             |

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

## `team_acceptance`

An Actor's acceptance of one agreement, at the text it had when they accepted.
Appended, never rewritten: accepting an updated agreement continues the
Actor's chain, so what somebody accepted and when stays readable.

Distinct from the acceptance fields on `team_membership`, which snapshot what
was asked and answered at *admission*. That is evidence of an event and stays
with the event. This is the standing fact, renewed when the agreement changes
without anybody being admitted again.

`reference_hash` is what makes it mean anything. A version label is a sentence
somebody typed; the hash is the agreement as it actually read, so "who
accepted this exact text" is answerable from the tree.

| Field                       | Requirement                                    |
| --------------------------- | ---------------------------------------------- |
| `actor_uuid`                | required — who accepted; must be the author     |
| `agreement_uuid`            | required — must name this Team's agreement      |
| `reference_hash`            | required — the agreement as it read then        |
| `text`                      | required — the acceptance sentence, may be empty |
| `previous_acceptance_uuid`  | required — the acceptance this continues, or empty |
| `accepted_at`               | required — when                                 |

## `team_agreement`

The text a team holds to, which is not the team itself: a team is a body of
people. An acceptance names an agreement, which is why it is a node rather
than a pair of fields on the team.

Its uuid is derived from the team's, so every client reaches the same
agreement without adopting a shell. Only what is written in it is negotiated.

| Field     | Requirement                                  |
| --------- | -------------------------------------------- |
| `name`    | required — what the agreement is called       |
| `version` | required — its human-readable version label   |
| `order`   | required — a number, position among siblings  |

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
and nobody else's. **Nobody is invited to a role.** There was once a third
record, an invitation written by somebody else and revocable by them; it made
taking on work an act with two authors and gave every holding a half its holder
did not control. What replaced it for a Team actor is containment — a team
holding nobody who is not already a member here is entitled to a seat without
being asked — and for a person, nothing at all: membership is the entitlement,
and a role is taken.

A `team_membership_invitation` is not a counter-example. It names a **type**
and is addressed to the pool at large, never to a person; nobody's name appears
on one, and it grants nothing until somebody answers it for themself.

The five types divide on a line that matters:

- **Content** — `team_role`, `team_accountability`, `team_domain`. Part of what
  people agree to, edited like any other text, and reactable per node so that
  two people editing different accountabilities diverge separately.
- **Records about it** — `team_role_decision`, `team_role_holding`. Facts
  about who is doing what, and therefore **append-only**, with a declared
  contract, like every other record that carries authority.

That line was not held before. An answer was rewritten in place, and giving up
a seat deleted the holding outright — so who held a role, and when, was not
recorded anywhere. A decision alone is what holds a role, which makes it
authority-bearing; it was stored like content, and it had no contract at all,
so a peer's answer was whatever they sent and a person was asked to accept it
sight unseen.

Each is one chain per actor per role, read by taking the end of it. **More than
one root, or more than one successor, holds nothing** — two answers about one
seat are two people to talk to, not a race to settle by sort order.

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

**The child takes the seat, from its own page.** Whoever holds the seated
team's Identity answers for it, so the act happens where that team is — the
same rule as every other actor, whose own line is the only one that acts. The
parent's page draws no line for a team that might qualify: a seat nobody has
taken is not a fact about anybody, and a row for one invited a click from the
one person who could not make it.

What that costs is reach. Both sides of a seat have to be written, and the
containment check reads the parent's memberships, so a team can only take a
seat in a team **this client already has**. A topic nobody has given you is
unreachable, not merely unread — the same property that makes a reference to
what the team runs necessary.

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
| `Role: 1 Team, 1 Name, 0-1 Purpose, 0-n Domains, 0-n Accountabilities, 0-n Actors` | Right, and "Actors" is one fact: who holds it (`team_role_decision`). Nobody is invited to a role |
| The Pull Principle                    | Built. A member takes a role by their own answer; nobody countersigns |
| *(nothing)*                           | `team_role_holding` — the blueprint has no way to express a subteam as built |

---

# What a team runs

An **initiative** or a **flow** a team runs is another application's topic,
published on the team's channel. The team owns no copy of it and stores
nothing about its contents — only who says they have it.

## `topic_link`

**Core's node type, not this application's** — the fields it carries, and what
following one does, are in `s-core/DESIGN_TOPIC_LINKS.md` and `PUBLIC_API.md`.
S-Team owns only where they live, which is as direct children of the team, and
what they mean here: one member's word that this team's work includes one
topic.

It replaced a chain of per-actor snapshots, each carrying a *list field* of
items — the only list field in the codebase, safe solely because a single
author replaced their own wholesale. As separate nodes there is nothing to
replace: **offering an item is creating one and taking it off is deleting
one**, so the decision is the record. The stored set of items withdrawn from a
team went with it, having existed only to stop a derived list from putting
back what somebody had taken off.

**An item is the team's while at least one member's reference names it.** When
the last of them takes theirs off, it is gone from the team.

**Only a current Member's reference counts, and that is derived on every
read.** It used to be gated when the record arrived, and the difference shows
when somebody leaves: a stored answer would go on naming their items until
something rewrote it, while a derived one stops the moment their standing
does. Arrival is judged too — a stranger's reference is refused rather than
merely ignored — but the two answer different questions and neither stands in
for the other.

**A reference is not a claim to hold a copy.** It says the team's work
includes this; whether this client currently has one is read from the tree on
every read and reported as `active`. So deleting your copy from the Cockpit
leaves the item on the team shown as not held, rather than quietly taking it
off — taking it off is somebody's act. *This is a change of meaning from the
lists, which said "I hold this" and were recomputed when that stopped being
true.*

**Adoption:** `auto` and `same-origin` once held, so its author's removal
travels as their offer did and nobody else may write it. Deliberately not
`never` like a governance record — a record is appended and stands for good,
while a reference is put up and taken down, and freezing one would need a
second record saying it had been withdrawn, which is the shape the withdrawal
set had.

**Why this cannot be read off the channel instead.** An explicit relay target
polls only the topics this client has assigned to it and the ones it has
already consented to receive. A topic nobody has told you about is not
unread, it is unreachable — so the reference is what carries the uuid, and
publishing an item beside the team tells nobody anything.

**Nothing keeps an item alive but the people who want it.** A member who takes
their reference off is not deleting the team's work, and a member who keeps
theirs is the whole of why it still exists. That is the sovereign shape of it:
you can hold what you care about, and you cannot oblige anybody to hold what
you care about for you.

**One thing still has to remember a refusal.** An election is the only item a
member takes up without being asked, so removing one is recorded locally as
declined — otherwise the next poll puts it straight back. That is not the
withdrawal set returning: the old one stopped a *derived list* from
resurrecting a decision, and there is no derived list now; this stops an
*automatic adopter*, which is still there.

Taking up an offered item is bidirectional. Core records both `desired` and
the item's home-channel assignment even when its first local replica has not
arrived yet. Once mounted, that assignment publishes the taker's replica, so
every existing holder sees the taker as a peer on the item.

---

# Trusteeship — blueprint mapping

| Blueprint (`Domain-Driven-Design.md`) | Here                                                             |
| ------------------------------------- | ---------------------------------------------------------------- |
| Trustee                               | `team_trustee_state`. **Not** a specialized Role — no role node is involved |
| Bet — Signals / Decision / Expected Impact / Assessed Impact | `team_trustee_action` (`signals`, `consideration`, `expectation`) plus 0-n `team_trustee_reality` (`reality`) — **already built under another name** |
| Decision Point — "access to a python function" | `team_trustee_election` naming an S-Flow process. A replicated decision anybody can read, rather than a function reference |
| Agile State / Divergence Warning      | `contested` in the projection above                              |
| Mandate [C-Text]                      | not built                                                        |

