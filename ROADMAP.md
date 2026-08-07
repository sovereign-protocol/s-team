# Roadmap

What is ahead, and what will not be built. What exists is described in
`DESIGN_TYPES.md` and `DESIGN_RULES.md`; what changed is in `CHANGELOG.md`.

## Ahead

### The Hard Fork — organic mitosis

Deferred; nothing else depends on it. The right to leave with the work.

- Keep the existing copy allowlist: structure and text, no records of anybody
  taking part.
- An explicit fork flow for a current Member.
- Copy into a new root Organization with fresh uuids.
- Bootstrap the initiator into a new genesis state — new state, not copied
  membership.
- Every other person joins through the ordinary Member gate.
- Copy no operational or audit records.

**Done when** the fork carries equivalent governance structure and no source
history, members, authority, seats or conflicts.

### Owed by Sovereign Core

Neither is S-Team's to make, and both came out of the design review.

- **Type-agnostic content hashing.** The clause shape is shared as a shape
  rather than a type, so another application declares its own node names
  against it. Core already takes type names from the caller for ordering; it
  has no equivalent for hashing, so until it does, an application adopting the
  shape writes its own copy.
- **Per-actor topic invitations.** An accepted Pool resolution carries a
  general Team invitation, readable by everyone in the Pool. Scoping the
  coordinates to the accepted applicant would close that, and Core composes
  them.

### Smaller

- **A third trusteeship.** The class generalises and the encoding is ready,
  but the rule saying which trusteeship facilitates another means nothing
  beyond two, so nothing is added until it does.
- **Versioned releases of a document**, distinct from the node history
  underneath it.
- **Roles as actors in their own right** — a role, rather than the person in
  it, holding a seat in a subteam, so the seat survives personnel change. The
  actor reference is a discriminated union, so this stays additive.

## Not goals

Deliberate, and not on the list because they were forgotten.

- Global ordering, or first-come-first-served arbitration. Concurrency is
  shown, not settled by a machine.
- Focus, Market and Equity trusteeships, until the facilitation rule above is
  decided.
- Asset or budget copying and division.
- Automatic parent funding or escalation.
- Copying decision or protocol history into a fork.
- Treating a Team's parent position as authority over that Team. Position is
  never authority.
- Preventing invalid Actors from writing or transmitting records. Theirs are
  verified, disregarded where unauthorised, and left visible — cryptography
  here is for attribution, not control.

Executable distribution follows only after the focused LGPL packaging review.
