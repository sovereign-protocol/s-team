# Interface — S-Team

How the team page presents roles, holders, trusteeships, actors and the
organization tree. Carried over unchanged from the roles-and-actors document
when that was retired: the design review rebuilt the model beneath this, and
deliberately did not touch the interface, so nothing here has been re-checked
against what the page now does.

Section numbers below are the originals.

### 4.1 The problem

A team has two faces: **its agreement** (what we agree) and **its structure**
(who is accountable for what). Roles are both — content you agree to _and_
the membership model. They must not be exiled to an admin panel, and they
must not be styled as prose.

Resolution: roles render as a **distinct region inside the document**, below
sections, as cards rather than paragraphs. Structured content, visibly
structured, but unmistakably part of the thing you are accepting.

The existing shell survives: `aside#organization` left, document pane right,
full re-render per payload.

### 4.2 Role card — definitions and invitations

```
┌─────────────────────────────────────────────────────┐
│ Treasurer                                    ⋯      │
│ Purpose: keep the books honest and current          │
│                                                     │
│ Accountabilities            Domains                 │
│ · Monthly reconciliation    · Bank accounts         │
│ · Filing annual accounts    · Payment approvals     │
│ + add                       + add                   │
│                                                     │
│ Held by  (A) Andre  (M) Maria  (👥) Team A          │
│ + offer to…                                         │
└─────────────────────────────────────────────────────┘
```

**[DONE]** The region is the definition rather than the doing.

**[DONE] The page reads: team name, Actors, Roles, Agreement.** An earlier
version put the agreement first and the roles last, reasoning that what we
agree comes before who is in it. In use it read the other way round: the
agreement is the longest section on the page and the least often changed, so
leading with it buried the team behind its own text. Who is here, then what
is expected of them, then the text they hold to — and the text arrives
collapsed, because it is reference rather than the working surface.

**[DONE] The team's name and the agreement's name are two fields.** They sat
on one — a team called "Finance" had an agreement called "Finance", and
renaming the body silently retitled the document everybody had accepted. The
team's name heads the page, outside every disclosure, and carries the team
node's lamp and reaction. The agreement's name sits inside its section, drawn
the way a role's purpose is: editable text, no row of its own, because the
status a second row would carry is already on the name above — they are one
node. It is stored as `agreement_title` beside `title` rather than under a new
agreement node, since sections already hang off the team directly. Left unset
rather than defaulted: an agreement nobody has named is a real state, and the
page prompts in its place. Both fields sit inside `team_reference_hash`, so
renaming either re-opens acceptances, which is right for the title of the
thing that was accepted. A copy takes a new team name and keeps the
agreement's — which is what makes a template a template.

The text collapses behind **a caret on the title itself**, and nothing more.
An earlier version put a labelled toggle above the sections; the label only
repeated what was directly beneath it, and it read as a heading for a region
rather than as a control on the title.

- Name and purpose use the existing `editable` in-place pattern — click,
  commit on blur or Enter, revert on Escape. No modal between reader and text.
- Accountabilities and domains reuse the clause affordances: add composer,
  delete, reorder.
- **Held by** is a line of badges — a face and a name each, the group mark
  for a team — and nothing else on the page. When somebody answered,
  against which version, who offered it and until when are questions you ask
  about _one_ holder, so they are in the badge's tooltip rather than in
  columns of small type read across a row. Status is carried by how the badge
  looks, in the same vocabulary as the participant chips (§4.3).
- Taking a role or stepping out of one is _not_ here — it is on your own line
  in Actors (§4.5), so one place answers "what is this role" and another
  answers "what am I doing about it".
- The only controls are the Identity holder's, because inviting and
  withdrawing are theirs alone and have nowhere else to live: an `Offer to…`
  picker, and one mark on the badge — **✓** to confirm a request, **×** to
  withdraw an offer — revealed on hover the way Delete is, so the line reads
  as people rather than as a row of controls.
- A vacant role is normal, not an error state — "Nobody invited yet",
  neutral styling.

Confirm cannot be dropped in favour of the picker alone: the picker
excludes anybody already listed under _Held by_, and a requester is listed
there. Without it a request is unanswerable.

**[DONE] Identity is a role card like any other**, first in the region,
marked with a key and carrying no accountabilities or domains yet. It used to
be a line off to one side, which said in layout that it was a different kind
of thing — and left it the one holding on the page with no way out of it.

### 4.3 Holder status

Visually distinct, and `unobserved` must not read as `pending`:

| Status         | Treatment                                                                                  |
| -------------- | -------------------------------------------------------------------------------------------- |
| accepted       | solid dot, date and expiry                                                                 |
| pending        | hollow dot, "offered, not yet decided"                                                     |
| refused        | struck through, muted                                                                      |
| expired        | amber, "lapsed 12 Jun"                                                                     |
| outdated       | amber, "accepted an earlier version" + re-accept action                                    |
| uninvited      | _not invited to this team yet_ — actionable, and not the same as the next one              |
| unobserved     | greyed italic, tooltip: _you don't sync with this person, so you can't see their decision_ |

Plus two notes that qualify a status rather than replace it:

- `offered_elsewhere` — the offer for this one exists only on the author's
  replica, and answering it takes it up (§2.3).
- `outside_parent` — accepted here, but holding nothing on a team above, so
  out of this one too (§2.4a). Dimmed: their answer stands, it is their
  standing that does not.

### 4.4 Identity

**[DONE]** The line only appears when Identity needs attention —
contested, recorded twice, vacant, or held by somebody else and therefore
takeable. When you hold it cleanly it is already visible as your own badge
(§4.5) and as its role card (§4.2), and the line would be repeating itself.

Three sentences, one per situation:

```
🔑 Identity: Andre                                    ⋯
⚠ Identity contested — you see Andre, Bob sees Bob
⚠ Identity: Andre has stepped out; your copy still has them holding it
  [Accept the empty seat]  [Keep Andre]
```

Reuses the existing divergence rendering and the `accept_peer_node` /
`rollback_peer_node` buttons. Handover, contest and vacancy are the same
event distinguished by _who is asserting what_: if the peer asserting
`holder = Bob` is Bob it is a handover awaiting your acceptance; if it names
somebody else it is a contested claim; if it names nobody the holder has
resigned (§2.2). Same event, three renderings — presentation only.

**Take Identity** lives in the overflow menu, never as a primary button, and
goes through the existing `#confirmModal`. The warning states the consequence,
not the mechanism:

> Andre currently holds Identity. Taking it will create a competing record,
> and **your role offers will not be adopted by others** until it is resolved.

### 4.5 Actors — two lines act, everybody else's states

**[DONE]** Actor rows with their roles as badges, each carrying its own
status — somebody may hold three roles in three different states.

**Two lines act.** _Yours_ comes first: a badge is a control, click to take
the role, click again to step out, and it changes on the spot. **Refuse is
not an action here** — the choice is holding or not holding. Identity is one
of those badges, and steps out the same way (§2.2).

_This team's_ comes second, because a Team is an Actor and the roles it holds
in other teams are roles. Same badges, same two clicks, answered by whoever
holds this team's Identity. Two marks appear on hover for the things that are
not simply taking or leaving: `×` declines an invitation, and `↑` says draw
the organisation under this one — home is the first holding in order that
works (§2.5), so badge order _is_ the control and there is no home to set.

Everybody else's badges are inert. Where somebody else stands is a
statement of fact, not a control over them, and drawing it as a button
would say otherwise.

**Nothing states how many actors there are.** A line reading "One actor —
nothing is agreed between anybody yet" was tried and removed: the Identity
line and every role already say who is and is not in it, so it was a third
statement of the same fact. Template is marked in the tree only (§4.6),
where it distinguishes one row among many.

**One rule on the page**, and no more: under the team's name, separating the
subject of the page from the three sections that describe it. The sections
carry none of their own — their disclosure headings already separate them,
and a blanket rule on every `<section>` drew a line between each pair of
paragraphs instead. The earlier arrangement needed two, because the sections
had no headings above them to do the separating.

Actor kinds are drawn differently, so "a person holds this" and "a body
holds this" do not read alike.

Somebody present holding nothing shows as _holds no role here_: visible,
and visibly outside.

### 4.6 Organization tree

`renderOrganization` mostly survives, since the tree renders through derived
home. Additions:

- a team with extra holdings shows an `also in: Foundation` marker
- a row whose home fell back shows `home via Foundation` subtly
- a template badge from §2.8, on its own line under the row, the same shape
  the tree already uses for its other extra facts. **Only** the template
  case: instantiated was badged here first and marked every row in a solo
  user's tree, which distinguishes nothing — one actor is the ordinary state
  of anything you have just made. It stays on the team's own page, where it
  is about that team rather than about all of them
- the ordered parent list, with reorder, lives on the team's own page —
  not in the tree

### 4.7 Creating a subteam becomes filling a seat

The actor picker groups candidates as **Individuals | Teams**. Offering a
role to a team is what makes it a subteam, so "New subteam" stops being a
separate button and becomes **"fill this role with a new team"**.

Structure is then created the way the model actually works — by filling a
seat — instead of by a parallel affordance that happens to produce the same
nodes.

**[DONE] A team is creatable from the page that shows teams.** The empty
state named the two ways in — create one, or accept an invitation — and
offered neither, so a client with no team had no way to get one at all. The
control sits beside the topic name and in the empty state, and creating
selects, so you land in the new team's own empty agreement rather than back
where you started.

### 4.8 Rendering — keep the full re-render

The document re-renders fully on every payload, polled every 3s. That stays.

`render()` already refuses to rebuild while the document is being edited
(team.html): it returns early when `document.activeElement` is inside
`#document` and is a contenteditable, input, textarea or select. Role cards
inherit this for free.

**Constraint that follows:** no editable surface may live outside
`#document` — or, if one must, it has to be built once rather than per
render. `renderOrganization` (`tree.replaceChildren()`) and
`setTopicSelector` both run _before_ the guard, unconditionally. This is why
the ordered parent list and its reorder control live on the team's own page
and not in the organization tree (§4.6), and why the new-team composer
(§4.7) is constructed once and re-attached rather than rebuilt: a rebuild on
the poll empties the box mid-word.

**What the guard does not cover** is ephemeral UI state that holds no focus:
open overflow menus, expanded cards, a half-filled offer picker. A 3s rebuild
closes them. The fix is not DOM patching but **holding that state in JS rather
than in the DOM** — an object keyed by role uuid, reapplied on render. Full
re-render then stays viable by construction.

Plus one skip: every payload already carries `"revision"`, but do **not**
gate on it. It is a Session revision, and `merge_document_observation`
decorates the snapshot with peer liveness _after_ `read_snapshot`, so
transport changes may not advance it and the network indicators would freeze.
Compare a JSON string of the last payload instead and skip `render()` when
identical — one stringify per poll at this document size, and no dependence
on every mutation path advancing the revision correctly.

**The payload is a contract with the page, and its keys are not the node
types.** They were renamed together once, in lockstep with the tests, which
is exactly why nothing failed: `document_payload` returned the selected team
under a different key, the page read `undefined`, and drew an empty document
with the rename control switched off beside a team that was there the whole
time. The suite now asserts the keys from the page's side.

**Rejected for now:** the keyed reconcile helper s-initiative already has
(`reconcileDOM(parent, dataItems, keyFn, createFn, updateFn)`). Copyable and
proven, but it needs a `createFn`/`updateFn` pair per node type — five new
pairs here — and a pair falling out of step is a silent bug class this
codebase has already met. Revisit only if role cards grow state that genuinely
cannot live outside the DOM.

