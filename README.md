# S-Team

S-Team is a local-first application for documents people have to agree to:
working agreements, terms, policies. It is built on Sovereign Core, so every
participant keeps an explicit local perspective and differences stay visible
rather than being silently overwritten by a central copy.

Where a Kanban board merges a peer's change and lets you react afterwards, a
team document does the opposite. A peer's node with no local counterpart arrives
as a **proposal** — accept it or withdraw it. A document is a thing people agree
to before it is true, so the adoption step is the point rather than an obstacle.
Records that carry authority are stricter still: a malformed or unauthorized one
is refused rather than offered to somebody to accept sight unseen.

## Quickstart

Requires Python 3.10+ and Sovereign Core `>=0.1.5,<0.2`.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\sovereign-host.exe 9307 config/team.example.json
```

Open <http://127.0.0.1:9307>. Direct HTTP is intended for LAN/VPN use. Local
folder and SFTP mailbox channels are configured through relay targets.

## Teams and organizations

**Being on a team is membership**, and it is its own thing rather than a
side-effect of holding a role. Identity admits and removes; leaving is your own
act. A member who has taken nothing on is still on the team.

**A member then takes any role by their own answer**, and nobody countersigns.
An invitation exists and any member may extend one, but it is a suggestion —
withdrawing it withdraws the suggestion and nothing else. A role carries its
accountabilities and domains, and a vacant role is not a problem: it is defined
work nobody has taken.

**A team can hold a role in another team**, which is what makes an
organization, and only while everybody on it is already a member of the team it
sits in. So a subteam is not a way into a team you have not joined:

- the parent side is an ordinary role, offered and answered like any other;
- the subteam's participants separately accept their own invitation;
- joining a parent never grants access to a child; and
- a child mounts only once you are a member of every ancestor.

A team may hold seats in more than one parent. The organization panel draws it
under the first seat that reaches a root, names the others on it, and marks
child teams that have separate membership.

Each answer is its own node recording the decision time, an optional expiry
(infinite by default), and a SHA-256 reference to the document body plus that
role's own definition. A content change makes older acceptances visibly
outdated until that participant renews them — scoped to the role, so editing one
role does not re-open everybody else's acceptance.

Answers, offers, seats and memberships are **appended, never rewritten**, so
when somebody took a role and when they stepped out of it are both readable.

## The documents

One question each, so there is one place to look and one place to change.

| File                | Answers                                    |
| ------------------- | ------------------------------------------- |
| `ARCHITECTURE.md`   | Who owns what, and what may depend on what  |
| `DESIGN_TYPES.md`   | What data exists — every node type, field for field, checked against the source by `tests/test_type_registry.py` |
| `DESIGN_RULES.md`   | What is true across all of it                |
| `DESIGN_UI.md`      | How it is presented                          |
| `ROADMAP.md`        | What is next, and what will never be built   |
| `CHANGELOG.md`      | What changed                                 |

## Desktop window

The same host can draw into its own window instead of a browser tab:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[desktop]"
.\.venv\Scripts\s-team-desktop.exe
```

The window picks a free port at start-up, so documents are kept in a per-user
directory (`%LOCALAPPDATA%\S-Team` on Windows) rather than beside the port
number. Pass a config file to override anything, including `storage_file`.

## History

S-Team began inside the Core repository as its conformance example —
the worked application proving Core's contract could be implemented by
something other than S-Initiative. It moved here once it became a product in its
own right. Commits before that point were made at `examples/s-team`.

## License

Application software and assets are Apache-2.0, as every Sovereign application
is. Documentation is CC-BY-4.0. Sovereign Core is a separately replaceable
LGPL-3.0-or-later dependency.
