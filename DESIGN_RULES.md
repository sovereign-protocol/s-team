# Rules — S-Team

What is true of the domain regardless of which type it is written in. What each
type is and carries lives in `DESIGN_TYPES.md`; where the boundaries are is in
`ARCHITECTURE.md`.

## 1. Organization is derived, not stored

- **Team** is the stored node type and the Actor kind.
- A root Team — one with no live parent seat — is presented as an
  **Organization**.
- A Team becomes one when it loses its last parent, and stops being one when it
  takes a seat in another. Nothing records it.
- Organization is not a third Actor kind. It is contextual wording, and
  S-Cockpit uses the same word for the same reason.

## 2. Peers and actors are two populations

- **Peers** — who you sync this topic with. A transport fact.
- **Actors** — who is on the team and what they have taken on. A governance
  fact.

Neither contains the other: a member who has taken no role is a member who is
idle, and somebody on the team you no longer sync with is a member you cannot
see.

An answer is credible only when read from the actor's own replica. A peer's
copy of a third party's answer is hearsay — it is signed, so you can tell who
wrote it, but a peer holding a copy is not the actor saying it — and it is not
counted.

The statuses are `{refused, expired, outdated, accepted}` and there is no
fifth. There used to be two more, and both belonged to invitations: `pending`
said somebody had been asked and had not answered, and `unobserved` said the
invitation was here but the answer was on a replica you do not sync with.
Nobody is asked now, so an actor whose answer this session cannot read is not
a holder in an unknown state — there is no record of them here at all, which
is the honest reading and the one the page shows.

Consequence worth stating plainly: **a team can only be as large as the group
that fully syncs on it.** Subteams are not only a governance device, they are
the replication scaling mechanism — the load-bearing reason the structure is
recursive rather than one large membership list.

## 3. Agreement truth comes from Identity perspectives

- Every Actor may edit their local Agreement copy.
- The consolidated Agreement is the name, version, sections and clauses on
  which all current or acting Identity holders' perspectives agree.
- If those perspectives differ or are unavailable, no consolidated Agreement
  exists and no membership invitation can be opened.
- `agreement_version` is Identity's declaration of substantial change. Badge
  freshness follows it; the stored exact Agreement hash remains audit and
  divergence evidence rather than a validity condition.
- Agreement alignment is not Agreement consent. Consent is explicit in an
  Actor's membership application and preserved on the Identity-issued badge.

## 4. Templates are a state, not a type

| Members | State                 |
| ------- | --------------------- |
| 0       | Template              |
| 1       | Instantiated template |
| 2 or more | Working team        |

No flag, no separate node type, no clone-and-strip mode. Copying is "the
structure with fresh uuids and no records of anybody taking part", which lands
at zero by construction. Role uuids are regenerated too, because acceptance is
uuid-keyed and a copy sharing them would let an answer given in the original
count in the copy.

A team with nobody on it is **inert as an actor**: no members means no
trusteeships, so it cannot answer, resign or take a seat. Its seats can
only be released from the parent's side. That is a derived property, not a
rule — and it is the same state a working team reaches if everybody leaves it.

Its *text* stays writable, which falls out of the same guards: a template
holds no seats, so the ancestry walk finds nothing to fault. That is the
behaviour you want, since editing is what a template is for, and it needed no
exception to get.

Taking Identity in an empty template is the same write as anywhere else, with
nobody to diverge against.

## 5. Cycles are rejected best-effort, per replica

Cycles among Team actors are refused when a seat is taken, by walking the
parents already known. Enforcement is **per replica and best-effort**: you can
only detect a cycle among teams you have joined, so one may exist globally that
no single peer can see.

This is the same shape as everything else here — a replica answers from what it
has, and is honest about the difference between "no" and "I cannot tell".

## 6. Names are made distinct, not refused

A name is the whole of how a role or a team is referred to — a badge, a seat
in a parent, a line in the organization tree. Two of them called the same
thing are two different things that read as one.

Refusing the write would throw away what somebody typed, so the name is kept
and numbered: a second "Lead" becomes "Lead (2)", and a second "Lead (2)"
becomes "Lead (3)" rather than stacking suffixes. It applies to creation and to
renaming, and renaming a thing to the name it already has is not a collision
with itself.
