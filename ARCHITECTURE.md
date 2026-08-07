# Architecture

Who owns what, and what may depend on what. The node types themselves are in
`DESIGN_TYPES.md`; what holds across them is in `DESIGN_RULES.md`.

## Ownership

S-Team owns the team node schemas — the document, the roles and their items,
and the records of who takes part in them: membership, trusteeship, openings
and Pool onboarding. It imports only the documented `sovereign` package root.

Sovereign Core owns protocol, Session, channels, hosting, identity and blob
mechanics, and contains no team node-type knowledge — a rule Core enforces in
its own suite by scanning its source. Applications never import one another.

Expected ownership across the repositories:

- **S-Core** — signatures, verification state, and transport that preserves
  evidence.
- **S-Team** — governance records, authority evaluation, projections and UI.
- **S-Flow** — the stable terminal decision-result facade, and running
  elections.
- **S-Cockpit** — contextual Organization wording and cross-application entry
  points only.

## Content and records

Two kinds of node, and the difference decides how each behaves.

**Content** — the document and the role definitions — is what people agree to,
so it is edited in place and presented for adoption.

**Records** — offers, answers, seats, memberships, trusteeships and their
decisions — are facts about who is doing what, so they are appended and never
rewritten. Authority is judged against the record a write *names*, not against
the state of the world when it is read, so a decision taken in office survives
the holder leaving.

`DESIGN_TYPES.md` draws that division per type.

## Trust

Cryptography is for attributable truth, not for control. It does not prevent
anybody from writing or transmitting a record, and nothing here should be built
as though it does.

- Cryptography proves which key authored a record; S-Team governance decides
  whether that author had the authority.
- Transport still carries invalid and unauthorised records, so attempts stay
  observable rather than disappearing.
- Unsigned content does not satisfy the protocol schema.

`revision_origin` alone is bookkeeping and can be forged, so it is never a safe
basis for silently accepting an incoming record.

Each client has its own Ed25519 private key. The Core profile carries an
append-only key-event chain: the bootstrap activation is self-signed, later
device or rotation activations are signed by an active key, and revocation must
be signed by a *different* active key. A received chain may only extend the last
trusted prefix, so a stale or competing profile stays observable but cannot roll
back a trusted revocation. A sole compromised key cannot revoke itself; without
another active sibling the identity must be replaced.

Private keys live only in the local session envelope. Pairing first authorises a
distinct sibling key, then carries that private-key bundle in the bearer pairing
token — which is what makes session files and pairing tokens sensitive.

## Structure

Organizational structure is a Team holding a role in another Team. Each side
keeps its own record and a seat is live only while both stand, so accepting a
parent never grants access to its children, and a hierarchy is visible only once
it has been answered on both sides. The child remains beside the parent under
the application container rather than inside its protocol subtree, which
preserves independent invitations, channels, membership and deletion.

A child topic mounts only when the local participant is a current member of
every ancestor.

## Adoption

Where it differs from S-Initiative: a peer's node that has no local counterpart
is presented as a *proposal* to accept or withdraw, rather than merged and then
reconciled. A document is a thing people agree to before it is true, so the
adoption step is the point rather than an obstacle.

Records carrying authority go further and are assessed before adoption — a
malformed or unauthorized one is refused rather than offered to somebody to
accept sight unseen.
