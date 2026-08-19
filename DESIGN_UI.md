# Interface — S-Team

How the team page presents roles, holders, trusteeships, actors and the
organization tree. Carried over from the roles-and-actors document when that
was retired: the design review rebuilt the model beneath this and deliberately
did not touch the interface, so outside §4.5 nothing here has been re-checked
against what the page now does.

**§4.5 has been.** The Members area was rebuilt with the onboarding model under
it — memberships and their invitations in place of a waiting-room topic — and
that section describes what the page does today.

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

### 4.2 Role card — the definition, and who holds it

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
└─────────────────────────────────────────────────────┘
```

**[DONE]** The region is the definition rather than the doing.

**[DONE] The page reads: team name, Members, Roles, Agreement.** An earlier
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
agreement's — which is what makes a template a template. A human-readable
`agreement_version` is editable beside the Agreement name. It is ordinary
Agreement content; the displayed consolidated state comes from Identity-holder
perspective alignment, not from the label.

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
  against which version and until when are questions you ask about _one_
  holder, so they are in the badge's tooltip rather than in columns of small
  type read across a row. Status is carried by how the badge looks, in the
  same vocabulary as the participant chips (§4.3).
- Taking a role or stepping out of one is _not_ here — it is on your own line
  in Members (§4.5), so one place answers "what is this role" and another
  answers "what am I doing about it". **[DONE]** The card carries no button
  at all now: `Take this role` used to sit under every one of them, which put
  the same control in as many places as the team had roles and made the
  definition of the work read as an offer of it.
- **There are no controls on the badges at all.** There used to be an
  `Offer to…` picker and a **×** that withdrew what it had written, and both
  went with the invitation: a holding is its holder's own record, so there is
  nothing on somebody else's badge for you to take back. A member takes a
  role from their own line, and a sub-team from its line (§4.5).
- A vacant role is normal, not an error state — "Nobody holds this yet",
  neutral styling.

**[DONE] Identity is a role card like any other**, first in the region,
marked with a key and carrying no accountabilities or domains yet. It used to
be a line off to one side, which said in layout that it was a different kind
of thing — and left it the one holding on the page with no way out of it.

**[DONE] One card per trusteeship the team has**, in vocabulary order —
Identity, Trust, Focus, Market, Equity — read from the payload's `seats`
rather than drawn by name. Two calls stood here while there were two seats,
which made the set of trusteeships something the page knew rather than
something the team said.

Under the cards, and not on any of them, an **Add trusteeship** control
offering the seats this team could have and this Actor could decide — it is
about the set, not about a seat. **Dissolve** sits on a card, because that
one is about a seat: offered only where it stands empty, and never on
Identity. Both are the payload's answer (`can_establish`, `can_dissolve`)
rather than the page working out who may do what.

**The page holds no copy of the facilitation rule.** Which seat decides
another arrives as each seat's `facilitator_trust`. It used to be
`trust === "identity" ? "trust" : "identity"` in three places, which was the
rule written a second time, in a language that could not be tested against
the records.

### 4.3 Holder status

Four, and every one of them is something the holder said. A **membership**
badge carries two of the same four — `accepted` and `outdated` — and no
others (§4.5): a membership does not lapse, and refusing one is not taking it.

| Status   | Treatment                                               |
| -------- | -------------------------------------------------------- |
| accepted | solid dot, date and expiry                              |
| refused  | struck through, muted                                   |
| expired  | amber, "lapsed 12 Jun"                                  |
| outdated | amber, "accepted an earlier version" + re-accept action |

`pending`, `uninvited` and `unobserved` are gone with the invitation. All
three described somebody who had not answered — asked and silent, not asked
at all, or answering out of sight — and with nobody being asked there is no
such person to draw. An actor whose answer this session cannot read is simply
not on the line.

One note qualifies a status rather than replacing it: `outside_parent` —
accepted here, but holding nothing on a team above, so out of this one too
(§2.4a). Dimmed: their answer stands, it is their standing that does not.

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
> and **nothing you decide for the team will be adopted by others** until it
> is resolved.

### 4.5 Members, and Membership

Two sections, not one region inside another. **Members** is who is here.
**Membership** is what the team supports, and it sits **below the Agreement**,
because taking one up is accepting that text — the page reads: what the team
is doing, who is here, what is expected of them, the text they hold to, and
then what being on it means.

#### The Membership section

**[DONE] One row per membership type, and it stays for as long as the team
supports it** — open or closed, held by somebody or nobody. Each carries its
name, its **requirements**, the **acceptance** it asks for, whether it is open
and until when, and who is on it. Identity edits all three texts in place, the
way a role's purpose is edited; everybody else reads them.

The confirm presents the texts in their decision order: **Membership Info**
(`requirements`) first, then Identity's **Acceptance Requirement**
(`acceptance`). The Actor answers that requirement in a mandatory, editable
**Acceptance Text** field; that answer is stored on the membership record.

A separate checkbox says **I explicitly accept the Team Agreement as it stands
now**. It is required when an Agreement title or section exists. With no
Agreement it is disabled and grey, the form says only that none exists, and it
does not prevent membership acceptance.

**A membership somebody else has just declared shows as a proposal**, the way
a new role does, and is adopted the same way. It used to be drawn only from
what this replica had already adopted, so a new membership was invisible here
— and the invitation naming it deferred for good with nothing on the page to
say why. That is what a peer saw: no row, no control, and no explanation.

**Open and closed is one toggle over one chain**, so a membership never has
two live invitations and reopening continues the history rather than starting
beside it. Opening needs a date ahead of now — the window is what every
acceptance is judged against, so one behind us would draw an open door nobody
could walk through.

**The row does not list earlier invitations.** It said "1 earlier invitation"
about a thing nobody acts on, in the place where you decide whether to open
the door now. The chain keeps them and the History section reads them, which
is where past, closed things belong.

**`Stop supporting` says what it costs**: everybody on that membership goes
back to the pool and their roles here stop counting. Nothing is rewritten, and
the confirm says so.

**The pool is a count, not a list.** "3 in the onboarding pool" — because
everybody in it is already an actor in the region below, and whether they are
on the team is what their own row says. A second list of the same names under
a "Pool" heading was the page saying it twice.

There is no separate Pool view and no `Onboarding Pool` link. The waiting room
was its own topic with its own page; the pool is derived now, and a page for a
thing that is not stored has nothing to draw.

#### The actors

**[DONE]** Actor rows with their roles as badges, each carrying its own
status — somebody may hold three roles in three different states.

**Only held roles are badges.** Every unheld role used to be drawn on every
line as a grey chip you could click, which made a team with fifteen roles a
wall of controls and said nothing about the person. Taking work on is **one
control at the end of your own line, `+ Add role`**, and a pulldown rather
than a button because until you pick one there is nothing to say.

**And only a member's.** A role is work a member holds, so somebody in the
pool shows no badges at all — not even the ones they answered for before they
left or were removed. Their answers are untouched and come back with them; the
line just stops claiming they hold something.

**Two places act.** _Your member line_ comes first: a held badge is a control, click to
step out. **Refuse is not an action here** — the choice is holding or not
holding. Identity is one of those badges, and steps out the same way (§2.2).

_The team-name heading_ carries the other controls, because a Team is an Actor
and the roles it holds in other teams are roles. Same badges, answered by
whoever holds this team's Identity, and the same `+ Add role` — which is how a
team takes a seat now. The team is not repeated among its own Members.
One mark appears on hover for the thing that is not simply taking or leaving:
`↑` says draw the organisation under this one — home is the first holding in
order that works (§2.5), so badge order _is_ the control and there is no home
to set.

**A sub-team gets no line until it holds something.** It used to get one as
soon as it contained no strangers, drawn with an outline chip per role it
might take. The row stated nothing — a seat nobody has taken is not a fact
about anybody — and the only person who could act on it held that team's
Identity and was looking at a different page. **The act moved to where the
actor is**: a team takes a seat from its own team-name heading, choosing from
the roles in teams this client has. A team appears among these actors once it
_holds_ something, like everybody else.

What that costs is reach, and the pulldown says so rather than hiding it: a
team whose topic nobody has handed over cannot be offered, and one this team
holds strangers to is listed with the reason instead of being dropped.

#### The membership badge

**At the right end of every individual actor's row**, and only theirs: a Team
is not a member of anything — it holds a seat — and a badge under its name
saying it had accepted the Agreement would be somebody else's answer.

It names the membership and carries two states, because those are the only
two there are (§Membership in `DESIGN_TYPES.md`): `accepted`, or `outdated`
when Identity has declared a new Agreement version. A membership does not expire — an
invitation does — and refusing one is simply not taking it.

**On my own row it is the control for leaving.** The `×` leaves the team.
Renewal appears on the held membership type as **Renew outdated membership**
and opens **Renew application for [type]**; Identity then issues the new badge.

Everybody else's badges are inert. Where somebody else stands is a
statement of fact, not a control over them, and drawing it as a button
would say otherwise.

`Remove` is the one thing anybody does about another person, it is Identity's,
and it sits on that person's row beside their badge.

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

### 4.4a The trustee card

Four things are done to a trusteeship, and all four are on its card: stand
for it, elect somebody to it, settle it, act in it. Nothing on the card
reports an election's progress, because an election is a flow the team runs
and is read where the flows are — in Initiatives and Flows, and in S-Flow.

**Settle** is a picker of members, shown only to whoever holds or acts for
the counterpart trusteeship. It says plainly what it is: you are answering
for the seating, not the election. Nothing checks the name against the
result, and the record says you did it.

### 4.5a Initiatives and Flows

The first section, and the only one open by default: what the team is doing
is what somebody opening it came for, so Members now arrives closed.

A **row is something you hold** — click it and it opens in S-Initiative or
S-Flow — with `Remove`, which is the Cockpit's delete and nothing more: your
copy goes, everybody else keeps theirs.

Everything else the team runs is a name in **`Connect to…`**, because a name
is all anybody has of somebody else's copy until they take it up. Taking it
up is this client's own consent. It records both halves before the first copy
has to arrive: receive the item, and publish this replica back on the team's
channel. Otherwise the taker sees the creator while the creator still sees a
private item.

**`Offer one of mine…`** puts an item you already hold on the team's channel.
It is what makes a private team workable: with no channel there is nowhere to
publish, so the work is yours until there is somewhere, and then it is one
act. It also lets an existing board be brought into a team, which wanting it
in the first place was always going to mean.

Anybody who can see the team sees the list, because the lists it is derived
from are on the team's topic and reading the topic is what being on it means.
Only a Member gets the controls — presentation, not a boundary, and the page
does not pretend otherwise.

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

A team taking a role is what makes it a subteam, so "New subteam" is not a
separate button: structure is created the way the model actually works, by
filling a seat, instead of by a parallel affordance that happens to produce
the same nodes. An existing team fills one from **its own team-name heading**
(§4.5), on its own page; a new one is made from the seat's side, by **"fill
this role with a new team"**, because there is no team yet to have a line.

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
`setTopicName` both run _before_ the guard, unconditionally. This is why
the ordered parent list and its reorder control live on the team's own page
and not in the organization tree (§4.6), and why the new-team composer
(§4.7) is constructed once and re-attached rather than rebuilt: a rebuild on
the poll empties the box mid-word.

**What the guard does not cover** is ephemeral UI state that holds no focus:
open overflow menus, expanded cards, a half-typed composer. A 3s rebuild
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
