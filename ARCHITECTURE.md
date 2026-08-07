# Architecture

S-Team owns the team node schemas — the document, the roles and their items,
and the records of who takes part in them: membership, trusteeship, openings
and Pool onboarding. `DESIGN_TYPES.md` registers every one of them field for
field and is checked against the source, so it is the place to look rather
than this file. It imports only the documented `sovereign` package root.
Sovereign Core owns protocol, Session, channels, hosting, identity and blob
mechanics, and contains no team node-type knowledge — a rule Core enforces in
its own suite by scanning its source.

Two lines run through the whole application. **Content** — the document and
the role definitions — is what people agree to, so it is edited in place.
**Records** — offers, answers, seats, memberships, trusteeships and their
decisions — are facts about who is doing what, so they are appended and never
rewritten, and authority is judged against the record a write names rather
than against the state of the world when it is read. `DESIGN_TYPES.md` is
where that division is drawn per type, and `DESIGN_RULES.md` holds what
applies across them.

Organizational structure is a Team holding a role in another Team. Each side
keeps its own record and a seat is live only while both stand, so accepting a
parent never grants access to its children, and a hierarchy is visible only
once it has been answered on both sides. The child remains beside the parent
under the application container rather than inside its protocol subtree, which
preserves independent invitations, channels, membership and deletion.

A child topic mounts only when the local participant is a current member of
every ancestor.

Where it differs from S-Initiative: a peer's node that has no local counterpart
is presented as a *proposal* to accept or withdraw, rather than merged and then
reconciled. A document is a thing people agree to before it is true, so the
adoption step is the point rather than an obstacle. Records carrying authority
go further and are assessed before adoption — a malformed or unauthorized one
is refused rather than offered to somebody to accept sight unseen.
