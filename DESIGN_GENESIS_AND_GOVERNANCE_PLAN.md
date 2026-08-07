# Team Governance — what is left to build

Increments 0-7 and 9 of the original delivery plan are complete. What that
plan described about node types, fields and authority has been rebuilt and is
now in `DESIGN_TYPES.md`, checked against the source; the semantics that
outlived it are in `DESIGN_RULES.md`. This file keeps only what is still
ahead, and the boundaries that decide who builds it.

## Team and Organization

- **Team** is the stored node type and the Actor kind.
- A root Team — one with no live parent seat — is presented as an
  **Organization**.
- Organization is derived, not stored. A Team becomes one when it loses its
  last parent and stops being one when it takes a seat in another.
- Organization is not a third Actor kind. It is contextual wording.

## Signed authorship precedes automatic authority

`revision_origin` is bookkeeping and can be forged, so it is not a safe basis
for silently accepting an incoming record. Therefore:

- cryptography proves which key authored a record; S-Team governance decides
  whether that author had the authority;
- transport still carries invalid and unauthorised records, so attempts stay
  observable rather than disappearing;
- unsigned content does not satisfy the protocol schema.

This uses cryptography for attributable truth. It does not prevent anybody
from writing or transmitting a record, and nothing here should be built as
though it does.

Each client has its own Ed25519 private key. The Core profile carries an
append-only key-event chain: the bootstrap activation is self-signed, later
device or rotation activations are signed by an active key, and revocation
must be signed by a *different* active key. A received chain may only extend
the last trusted prefix, so a stale or competing profile stays observable but
cannot roll back a trusted revocation. A sole compromised key cannot revoke
itself; without another active sibling the identity must be replaced.

Private keys live only in the local session envelope. Pairing first authorises
a distinct sibling key, then carries that private-key bundle in the bearer
pairing token, which makes session files and pairing tokens sensitive.

## Still ahead

### The Hard Fork — organic mitosis

**Deferred.** Nothing else depends on it.

- Keep the existing copy allowlist: structure and text, no records of anybody
  taking part.
- An explicit Hard Fork flow for a current Member.
- Copy into a new root Organization with fresh uuids.
- Bootstrap the initiator into a new genesis state — new state, not copied
  membership.
- Every other person joins through the ordinary Member gate.
- Copy no operational or audit records.

**Gate:** the fork carries equivalent governance structure and no source
history, members, authority, seats or conflicts.

### Owed by other repositories

Both came out of the design review and neither is S-Team's to make:

- **Type-agnostic content hashing in Core.** The clause shape is shared as a
  shape rather than a type, so another application declares its own node names
  against it. Core already takes type names from the caller for ordering; it
  has no equivalent for hashing, so until it does, an application adopting the
  shape writes its own copy.
- **Per-actor topic invitations in Core.** An accepted Pool resolution carries
  a general Team invitation, readable by everyone in the Pool. Scoping the
  coordinates to the accepted applicant would close that, and the Core
  composes them.

## Explicit non-goals

- Global ordering, or first-come-first-served arbitration.
- Focus, Market and Equity trusteeships, until the rule saying which
  trusteeship facilitates another means something beyond two.
- Asset or budget copying and division.
- Automatic parent funding or escalation.
- Copying decision or protocol history into a fork.
- Treating a Team's parent position as authority over that Team.
- Preventing invalid Actors from writing or transmitting records. Their
  records are verified, disregarded where unauthorised, and exposed.

## Implementation boundary

- **S-Core:** signatures, verification state, and transport that preserves
  evidence.
- **S-Team:** governance records, authority evaluation, projections and UI.
- **S-Flow:** the stable terminal decision-result facade, and running
  elections.
- **S-Cockpit:** contextual Organization wording and cross-application entry
  points only.
