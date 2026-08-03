# Roles and Actors — design and implementation plan

Status tags follow the Core convention: **[DONE]** built and tested,
**[PROPOSED]** decided here but not built, **[OPEN]** unresolved.

Every step of §3 is now **[DONE]**, so the model in §1–2 describes what is
built rather than what is planned. What remains unbuilt is tagged **[OPEN]**
in §5.

**A note on two words.** A **Team** is the body: the actors in it, the roles
it defines, the seats it holds elsewhere. Its **Agreement** is the text those
actors consent to — the sections and clauses. The team is what holds; the
agreement is what is held to. Everything here says team except where the
document itself is meant, and the interface follows the same rule: one
disclosure is titled _Agreement_, and nothing else uses the word.

## 1. Model

### 1.1 Actor

An Actor is anything that can hold a role. Actor is `{Individual, Team}`.

| Kind       | Reference          | Stability                                                                                                                                                     |
| ---------- | ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Individual | identity node uuid | Stable per person. Siblings share one profile subtree — `adopt_pairing_identity` preserves `incoming.uuid` (session.py), so a person's clients are one Actor. |
| Team       | team node uuid     | Stable, shared across replicas.                                                                                                                               |

`account_key` (`DESIGN_MULTI_CLIENT_IDENTITY.md`) is **not** a prerequisite.
That doc is the road not taken; `DESIGN_MULTI_CLIENT_PAIRING.md` is **[DONE]**
and already gives one identity uuid per person.

**To be on a team, an Actor takes a role.** There is no membership
independent of role-holding — and that is what §2.4 extends upward: being on
a team below is being on the team above.

### 1.2 Node schema

```
team                          (topic)
├── team_section
│   └── team_clause
├── team_trustee              data.trust names which trusteeship;
│                             data.holder_actor_uuid, data.held_since
├── team_role                 data.name, data.purpose, data.order
│   ├── team_accountability   data.text, data.order
│   ├── team_domain           data.text, data.order
│   ├── team_role_offer       one per (role, actor); authored by the trustee
│   └── team_role_decision    one per (role, actor); by the actor
└── team_role_holding         this team's seat elsewhere:
                              data.parent_team_uuid, data.role_uuid,
                              data.order — the ordered parent list
```

Three levels for holdings, not two, because a role may have several holders
and revoking one must not revoke the others. Offers are per-(role, actor).

Accountabilities and domains are **nodes, not lists in `data`**. Same reason
clauses are nodes: reactions are per-node, and a JSON list collapses two
people editing different accountabilities into one undiffable divergence.

`agreement_link` is retired — a subteam is a Team actor holding a role in the
parent. `agreement_decision` is retired in favour of `team_role_decision` on
the default Participant role.

Which of these may be reacted to, and which are somebody else's fact rather
than a thing to agree with, is Core's question rather than this document's —
see `DESIGN_NODE_CLASSES.md` in s-core.

### 1.3 Cardinality, and trustee roles

- A role has 0..n holders. A **vacant role is not a problem** — it is defined
  work nobody has taken.
- **A trustee role has exactly one holder.** It is shaped differently from
  other roles because of cardinality, not privilege (§2.2).

**[DONE]** Identity is not a special node. It is the first instance of a
**trustee role** (German _Treuhänder_): a role held on behalf of the team
rather than for the holder's own part in it. One node type carries them all
and `trust` names which, so a second trusteeship inherits the encoding, the
resolution mechanism and the authority guard instead of arriving as a second
node type with its own copy of each. The class is defined by:

- exactly one holder;
- an authority carried _for_ the body — to speak for it, to commit it, to
  keep something of its on its behalf;
- one node whose holder field is rewritten, not an offer/answer pair (§2.2);
- vacated only by explicit resignation.

**[DONE]** Because a trusteeship _is_ a role, holding it is being on the
team, and `_has_current_acceptance` counts it. Anything else lets the
application tell the person who speaks for a team to take a role in it
before they may act — which is how this was found. The consequence is that
somebody cannot step out of their own team by refusing roles while still
holding Identity; they have to hand Identity on, or resign it (§2.2).

## 2. Rules

### 2.1 Authority

The Identity holder is the only actor whose role offers others adopt.

This is a **coordination rule, not a security boundary.** Core has no content
signing — every crypto path is SFTP transport key material, `identity_key` is
a bare `uuid4()`, and `revision_origin` is authorship bookkeeping. A peer can
write a node carrying another identity's origin and nothing downstream can
tell. This is already true of every node in the protocol; roles are only the
first content where forged data would confer authority.

Accepted deliberately: this software supports sovereign people who have
chosen to sync with each other. Recorded here so nobody later mistakes it for
a guarantee. Making it a boundary means keypairs in Core, not work here.

It applies in two independent layers:

- **Affordance** — the client does not offer trustee actions to someone who
  does not hold the trusteeship from their own perspective. Prevents
  accidents.
- **Adoption predicate** — a proposed offer node is not adopted unless its
  author holds Identity in the observed state. Prevents intent.

Plus one condition: **if the trustee node is diverged in my view, adopt no
internal offers and surface it.**

The predicate reads only replicated state, which is what makes every side
reach the same verdict. Any rule added here has to keep that property, or
two clients disagree about whether a node is adoptable at all.

### 2.2 A trusteeship is convergence, not protocol

`team_trustee` is a single node per team per trust, carrying the holder. It
needs no offer/accept protocol on top, because the protocol's own semantics
already express consent:

| Situation                     | My replica | Their replica | Event               |
| ----------------------------- | ---------- | ------------- | ------------------- |
| Alice holds it                | Alice      | Alice         | `in_agreement`      |
| Alice offers to Bob           | Bob        | Alice         | `peer_made_changes` |
| Bob accepts                   | Bob        | Bob           | `in_agreement`      |
| Bob self-installs, Alice idle | Alice      | Bob           | `peer_made_changes` |
| Alice steps out               | Alice      | (nobody)      | `peer_made_changes` |
| Both write at once            | Charlie    | Bob           | `divergence`        |

(`in_agreement` is Core's word for two replicas holding the same version. It
is not this document's noun.)

**[DONE]** The event is `divergence` only when _both_ sides wrote since
their last common state. One side writing while the other sits still is an
ordinary peer change — measured, not assumed: `test_identity_handover_
converges_and_a_claim_diverges` and `test_two_sides_naming_different_holders_
at_once_diverge`.

That distinction changes nothing structurally, because both event types carry
`peer_addr` and both are settled by the same `accept_peer_node` /
`rollback_peer_node`. It does change wording: a self-install cannot be
promised to "create a divergence", so the interface warns about a competing
record the other side must settle, which is true in both cases. The view
keys off the holder each replica names, never off the event type.

Handover is not a new verb: Alice writing `holder = Bob` is a proposal, Bob
accepting it is `accept_peer_node`. A contested claim is the same shape and
the response is `accept_peer_node` or `rollback_peer_node`. Both already
exist.

This deletes three things that would otherwise need building: a vacancy rule,
a claim-legality predicate, and ambiguity-freeze machinery.

**Ordinary roles cannot use this encoding**, because absence conflates _has
not seen it yet_ with _said no_. Refusal is a first-class act in a
consent-based system, so ordinary roles keep an explicit decision node — which
also carries expiry and the reference hash.

**[DONE] Resignation empties the record; it does not delete it.**
`resign_identity` writes an empty holder, and `identity_payload` reads that
back as vacant. Deleting the node instead would make "nobody holds this" and
"I have not been told who holds this" the same observation, and it is the
node both sides compare when somebody takes the seat.

A peer's emptied record is reported as a **vacancy claim** — its own kind,
beside handover and contest. It used to be dropped for having no name to
report, which left the other side looking at a holder who had already left
with nothing on screen to answer.

**Expired is not vacant.** The holder is expected to hand over to a
successor; expiry marks the norm, it does not release the seat. A trusteeship
becomes vacant only by explicit resignation or in a template.

### 2.3 Withdrawal — one principle, two verbs

> **You may withdraw what you authored. You may never delete what someone
> else wrote.**

- Identity authored the offer → Identity may withdraw it. That is
  **revocation**.
- The actor authored the decision → the actor may delete it. That is
  **resignation**.

**[DONE]** Revocation _marks_ the offer `revoked_at` rather than deleting it.
Deleting was the original design and is wrong: with §2.4b's request mechanism,
an answer with no offer beside it means somebody asking for the role, so a
deleted offer would leave the actor's surviving answer reading as a fresh
request — and the Identity holder would immediately be prompted to re-offer
exactly what they had just taken back, making revocation useless. Marking is
still a withdrawal of what Identity itself wrote, so the rule holds; it just
keeps the fact that an offer existed. Offering again revives the same record.
A withdrawn offer with no answer left beside it is not shown at all.

This was caught in the running application, not by the tests: the first fix
recorded on the _actor's_ node whether it was answering an offer, which is
correct at the moment it is written and wrong forever after, because
confirmation changes the situation and cannot rewrite somebody else's node.

A holding is live only when both nodes are present, so neither party needs
the other's consent and neither can rewrite the other's record. Mechanically
free: deletions propagate as absences, and `adopt_absence` /
`rollback_absence` are already parameters of `accept_peer_node` /
`rollback_peer_node`.

**[DONE]** This is why offer and decision are **siblings under the role, not
nested**. Deleting a container prunes its descendants rather than tombstoning
them — measured in step 1 on a role's accountabilities — so nesting the
decision inside the offer would make revocation delete the actor's own
record, which is precisely what this rule forbids. Both are keyed on
`actor_uuid` under the role instead, leaving each author's node independent.

**[DONE]** Answering an offer adopts it first. This application never merges
a peer's new node automatically — it presents it as a proposal — so an offer
reaches the person it names as a proposal, not as state. `decide_role`
therefore adopts the offer before recording the answer, keeping it one
gesture for the person while still passing through `accept_peer_node`, so the
authority check in §2.1 is not bypassed.

**[DONE]** And it has to be _shown_ to them while it is still only a
proposal. `role_holders` was built from merged content alone, which made an
offer invisible to the one person who could answer it: their screen was
identical whether or not they had been offered anything, and the offering
side meanwhile read `awaiting_peer` as though an answer were pending. Such an
offer is now listed as `pending` and marked `offered_elsewhere`.

The leftover is harmless. After revocation the actor's decision node survives
pointing at nothing, and is inert. No cleanup pass.

### 2.4 Validity — ALL paths, per holding

**[DONE]** A team is writable when **every** holding chain reaches a root
with every link valid. Roots — teams holding no role anywhere — are
self-standing.

**This reverses the original rule, and the reversal is the point.** The first
version took ANY path: holding seats in two teams meant either could carry
the body, so one parent going invalid suspended that relationship rather than
paralysing a body the other still supported. That reads well until you say it
in terms of membership. You are on a team only by holding a role on it, and a
body sits _inside_ each of its parents — so taking part in it is taking part
in all of them. Under ANY, somebody could keep working in a team through a
parent they were still in, inside a parent they had left. **A second parent
is a second commitment, not a spare route around the first.**

The consequence to accept explicitly is the mirror of the one the old rule
accepted: _"invalidating a parent invalidates all children"_ is now
unconditionally true, including for children with several parents.

Validity is **derived, never written**. This deletes the descendant-refusal
cascade that would otherwise overwrite your own acceptance on every
descendant and never un-cascade when the parent is re-accepted.

A path counts as valid only if every team on it is joined locally, which is
what the guard means by _"Read-only until every parent team is joined."_

#### 2.4a Membership is contained

**[DONE]** Every member of a team is a member of each of its parents. Not by
convention — by the guard above, which is the same statement read from the
other end. Three things follow, all built:

- **A team may take a seat only if everybody already on it holds a role in
  the parent.** Otherwise accepting the seat carries them into a team they
  never took a role in, and shuts the team for them — including for the
  trustee who accepted the seat on its behalf. `create_seated_team` always
  checked the parent chain; `seat_team` on an existing team checked nothing
  beyond holding the child's Identity, so its trustee could lock themselves
  out of their own team by accepting an invitation. The refusal names the
  people who are not yet in the parent, because that is the work to do
  first.
- **Losing a role above is losing the team below**, for that person, derived
  and never recorded, so it reverses itself when the role above is taken up
  again.
- **The roster has to say so.** Invalidity above was derived only for
  whoever was reading, so everybody else went on being shown as `accepted`
  and a team's own member list stated something untrue about them. Holders
  carry `outside_parent`, and `actor_uuids` stops counting them — without
  which the containment could be satisfied one level down by somebody the
  level above had already lost.

The role above may be the smallest "member" role there is; what matters is
that it exists. The default Participant role is exactly that.

Computing it reads strictly **upward**. Asking a team who is on it, in order
to decide who is on it, is circular; the question goes to the parents alone,
and each answers it of its own parents in turn, terminating at a root. That
is also what makes the containment transitive for free.

The constraint is **observable, not enforceable**: a role held on a replica
this session cannot reach reads as unheld. The seat check therefore refuses
and names the people it cannot place, rather than guessing.

#### 2.4b A request is a decision with no offer

**[DONE]** Only Identity may offer (§2.1), so somebody who has just accepted
a topic invitation holds nothing and cannot be let in by anyone else. Asking
is the move available to them; confirming is the move available to Identity.

This needs **no new node type**. A holding is live only while both records
exist, so the two halves already mean something on their own:

| Offer   | Decision | Meaning                       |
| ------- | -------- | ----------------------------- |
| yes     | no       | an unfilled seat — _pending_  |
| no      | yes      | somebody asking — _requested_ |
| yes     | yes      | held                          |
| revoked | yes      | withdrawn — _revoked_ (§2.3)  |

Confirming a request is an ordinary `offer_role`. The asker's answer is
already on file, so the holding goes live the moment both records exist and
the newcomer is never asked to answer twice. Neither side writes the other's
record at any point, so §2.3 is untouched.

Consent to a seat works the same way, and is worth saying plainly because
all three seat records are one-author facts rather than things anybody
adopts: the offer is the trustee's own record, the decision is the actor's
own, and the holding is exactly the overlap. **Consent is expressed by
authoring your own record**, not by adopting somebody else's.

### 2.5 Home — derived, not declared

Holdings are an **ordered list**. Home is the **first holding in order whose
chain validates**. That is a pure function of (order, validity):

- no `home` field, no declaration step, no stale-home migration
- reverses itself automatically when the original parent recovers
- home edges ⊆ holding edges, one per team, over a DAG ⇒ the projection is a
  spanning forest for free, needing no separate cycle check
- a team with no valid holding has no home and renders as a local root

Ordering reuses the existing `order` convention read by `_ordered()` and
written by `session.move_child_to_index` — the same primitive behind
`move_section` and `move_clause`. Later ordering policy (activity level, etc.)
is a reorder over the same list and needs no new design.

**Home is display and navigation only, and under §2.4 it decides nothing
about writability at all.** Every parent has to validate, so which one a team
is _drawn_ under is a question about the tree and nothing else. This was a
sharper constraint under ANY, where confusing the two would have turned
"reachable by any path" into "reachable through home"; it is now simply true
by construction.

**Non-home holdings stay visible** as annotations on the team's own page,
never hidden. A hidden second parent is a trap for whoever deletes the first
— and now also a hidden second commitment.

### 2.6 Peers and actors are two populations

- **Peers** — who you sync this topic with. Transport fact.
- **Actors** — who has accepted a role. Governance fact.

Neither contains the other: someone invited but holding no role is an
observer; someone holding a role you no longer sync with is a member you
cannot see.

Acceptance is credible only when read from the actor's own replica. A peer's
copy of a third party's answer is hearsay, and nothing signs content, so it
is not counted.

That adds a status. Today: `{pending, refused, expired, outdated, accepted}`.
Add **`unobserved`** — you know the offer exists but do not sync with the
actor, so you cannot know their answer. It _is_ distinguishable from
`pending`, because you know your own peer set. Collapsing them would be a lie
the UI tells.

Consequence worth stating: **a team can only be as large as the group that
fully syncs on it.** Subteams are not only a governance device, they are the
replication scaling mechanism — the load-bearing reason the structure is
recursive rather than one large membership list.

### 2.7 Acceptance scope

The reference hash covers **the agreement body plus the definitions of the
roles this actor holds** — not the whole team.

Whole-document hashing means editing the Treasurer's accountabilities
re-opens the CFO's acceptance and every subteam's. Under the scoped hash:
editing an unrelated role touches nobody, editing the agreement text
correctly stales everyone, adding a new role stales nobody.

**It does not span ancestors, and should not.** Extending it up the chain was
tried and reverted: under §2.4a a member of a subteam already holds a role in
each parent, so the parent's text is already covered by their acceptance
_there_. Putting it in the child's hash as well makes them consent to the
same text twice — after re-accepting above they would still read `outdated`
below, and that second click carries no information. The gap it was meant to
close ("party to a body without having committed to its basis") cannot occur
once membership is contained.

Validity is `min(offer validity, decision validity)`. The offer may bound the
seat ("until Dec 31"); the decision may bound the commitment ("until Sep 30").
Both are meaningful and different.

### 2.8 Templates are a state, not a type

| Actors | State                 |
| ------ | --------------------- |
| 0      | Template              |
| 1      | Instantiated template |
| ≥2     | Working team          |

No flag, no separate node type, no clone-and-strip mode. Cloning is "copy
structure with fresh uuids, zero decisions", which lands at 0 actors by
construction. Role uuids must be regenerated too — acceptance lookup is
uuid-keyed.

A 0-actor team is **inert as an actor**: no actors means no Identity, so it
cannot offer, accept, resign, or take a seat. Its holdings can only be
removed from the parent side, by ordinary revocation (§2.3). That is a derived
property, not a rule.

Its _text_ is a different matter and stays writable, which falls out of the
same guards: a template holds no seats, so `_interaction_guard` finds no
ancestry to fault. That is the behaviour you want — editing is what a template
is for — and it needed no exception to get.

Taking Identity in a 0-actor template is the same write as anywhere else,
with nobody to diverge against.

### 2.9 DAG enforcement

Cycles among Team actors are rejected at the application layer, using the
existing `_creates_cycle` walk generalised to multiple parents.

Enforcement is **best-effort per replica**: you can only detect a cycle among
teams you have joined. A cycle may exist globally that no single peer sees.

### 2.10 Names are made distinct, not refused

**[DONE]** A name is the whole of how a role or a team is referred to — a
badge, an offer, a seat in a parent, a line in the organization tree. Two of
them called the same thing are two different things that read as one.
Refusing the write would throw away what somebody typed, so the name is kept
and numbered: a second "Lead" becomes "Lead (2)", and a second "Lead (2)"
becomes "Lead (3)" rather than stacking suffixes. Applies to creation and to
rename; renaming a thing to the name it already has is not a collision with
itself.

## 3. Staging

Each step ships a working application. The risky graph rewrite is last, after
roles are proven as content.

### Step 0 — Baseline **[DONE]**

Commit the in-flight tree/subteam/badge work on its own branch before
anything is layered on it.

### Step 1 — Roles as content **[DONE]**

Roles, accountabilities and domains as document nodes. CRUD, ordering,
reactions. No offers, no holdings, no Identity. Purely additive — the existing
acceptance model keeps working, and describing roles is useful on its own.

| Area            | Work                                                                                                                                            |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `logic.py`      | `team_role` / `team_accountability` / `team_domain` node types; create/rename/delete/move for each; add all three to the reactable set          |
| `logic.py`      | Scoped reference hash (§2.7). At this step nobody holds roles, so role edits stale nobody — correct once step 2 lands                            |
| `controller.py` | 9 routes following the existing `sections/*` and `clauses/*` shape                                                                               |
| `facade.py`     | `roles()`, `accountabilities()`, `domains()` readers                                                                                             |
| UI              | Role cards (§4.2)                                                                                                                                |

**Done when** a role with accountabilities and domains can be authored,
reordered, diverged and reconciled exactly as clauses can.

### Step 2 — Identity, offers, decisions **[DONE]**

Including the retirement of `agreement_decision`: being on a team is holding
a role in it, so that is what `_has_current_acceptance` now reads, and the
descendant-refusal cascade is gone with it (§2.4).

Actor is still Individual only.

**2a — Identity.** The trustee node; creator takes it at team creation;
adoption predicate (§2.1); divergence rendering; warned self-install.

**2b — Offers and decisions.** `team_role_offer` and `team_role_decision`;
default Participant role on every new team; revocation and resignation as
authored-node deletion (§2.3); membership becomes explicit; badges switch
from peers to actors and gain `unobserved`.

**Done when** two sessions can offer, accept, refuse, revoke and resign a
role, and both see consistent badges; and when an Identity handover and a
contested claim both render correctly and resolve through existing
adopt/rollback.

### Step 3a — Team as Actor **[DONE]**

The representation, with single-parent behaviour preserved so the existing
suite polices it. `agreement_link` is gone: a subteam is an ordinary role in
the parent offered to a Team actor, and a `team_role_holding` in the child
naming that seat. Both sides must name the same seat before the relationship
exists anywhere.

Three things this surfaced:

- **Adding a subunit no longer re-opens anybody's acceptance.** The seat is
  a role, and roles are outside the agreement body hash, so the parent's
  text is unchanged by gaining a subteam. The `agreement_link` it replaces
  _was_ document content, which forced everyone to re-accept the parent
  whenever the organisation grew. This also deleted the `_reaffirm_holdings`
  call that existed only to paper over that.
- **The two guards are not the same walk.** `_check_parent_chain` includes
  the team being hung from — hanging something below a team means taking
  part in it — while `_interaction_guard` excludes the team being written
  to, which is why a root is always writable. Collapsing them into one walk
  silently let anybody seat a subteam under a team they held nothing in.
- **A holding has to be checkable before it is mounted**, so
  `_holding_is_live` takes the holder rather than looking it up: the
  invited subtree is not in the local index yet, which is the entire point
  of checking it.

### Step 3b — Multiple parents **[DONE]**

A team may hold seats in several others. `_ancestry_problem` is a DFS over
the holding graph, cycle-safe; home is the first holding in order whose path
validates, derived on read; `seat_team` and `create_seated_team` fill a seat
with an existing or a new team, both refusing anything that would close a
loop.

Shipped first as an ANY-path walk and later reversed to ALL (§2.4). The DFS
itself is unchanged by that; only what it does with a clean path is — it used
to return success on the first one, and now requires all of them.

**The org view stayed a tree.** An earlier draft of this plan called that the
biggest UI change of the whole thing, which was written before home existed
and was wrong afterwards: home edges are a subset of holding edges with at
most one per team over a DAG, so the projection is a forest and
`renderOrganization` needed no restructuring at all (§2.5). The DAG never
reaches the tree renderer. What it did need is the two markers that keep the
projection honest — `also in:` on a row whose other seats home leaves out,
and the team's own badges on its page, whose order sets home (§4.5).

**Done when** a team holding roles in two parents renders once under its
derived home, annotates the other, and closes when either parent goes
invalid.

### Step 4 — Templates **[DONE]**

`clone_team` copies the text and the roles into a new team with fresh uuids
and nobody in it; `team_state` counts actors and returns template /
instantiated / working; both payloads carry it and the view badges the first
two.

The parts worth recording:

- **Nothing is stripped.** The copy walks `CLONED_TYPES` — sections, clauses,
  roles, accountabilities, domains — and simply never visits the trustee,
  offers, answers or holdings. A clone-then-strip pass would have had to know
  the same list inverted, and would have been a second place to forget a node
  type when one is added.
- **The default Participant travels**, because it is content. A template that
  arrived with no role at all would make its first user invent one before
  taking part, which is the thing §2.8 says a template should spare them.
- **Copying is not gated on standing in the original.** It reads that team
  and writes only a new one of this session's own, so a team you can see
  read-only is one you can fork. That is a feature, not a leak: you could
  already read it.
- **State is derived from `role_holders`, not from a second reading of the
  same facts.** Writing a leaner actor scan would have put "what counts as
  accepted" in two places. Making `role_holders` memoized per read scope
  instead made the shared path cheap enough that the org payload can ask it
  for every team, which is what makes the badge affordable at all.
- **A request is not an actor.** An answer with no offer behind it is somebody
  asking to join (§2.4b), so it leaves the count where it was — which is what
  keeps a template from being promoted by a stranger.
- **Copying lives in the flow that makes a new team**, not on an existing
  one's page. An action whose result is a different team has no business
  sitting on this one's page. It also puts the choice where it is actually
  made: you decide where a team starts when you start it.

### Step 5 — Answering for a team **[DONE]**

Not in the original staging, and needed once a team really was an actor: a
team could be offered a seat, but nothing showed it the offer.

- **An invitation is written on the parent's page and answered on the
  child's.** Those are two different people's pages — the parent's Identity
  holder writes the offer, the child's answers it, and they need not be the
  same person or even joined to the same topics. `seat_offers` collects the
  offers naming this team so the answer is made where the authority to make
  it lives. Invitations reaching this session only as proposals are included,
  since answering one adopts it, exactly as for a person (§2.1).
- **There is no "seat" in the interface.** A first cut gave holdings and
  invitations two sections of their own, titled _Seats held_ and _Invited
  to_ — which invented a second vocabulary for something the model already
  has a word for. A Team is an Actor (§1.1), so the roles it holds elsewhere
  are roles, drawn as badges on the team's own line in _Actors_, read and
  acted on exactly as a person's are: click to take, click to step out. A
  badge names the role and where it is — "Operations in Cooperative" —
  because that is the whole of what distinguishes it from a role held here.
  _Seat_ survives only in the storage type and the function names, where it
  names an edge in the graph rather than a thing the reader has to learn.
- **`decline_seat` completes the pair.** Without it an unwanted invitation
  sits forever: the offer belongs to the parent and only its author may
  withdraw it (§2.3), so the child needs a refusal of its own. A declined seat
  stays listed, because turning something down is an answer that can change.
- **One answer per actor per role.** `_record_role_decision` rewrites an
  actor's existing decision instead of adding a second, and `seat_team` goes
  through it. Reconsidering a refusal used to leave two decision nodes for
  one actor, with which of them counted decided by iteration order.
- **A Team actor's answer is vouched for by whoever gave it.** The
  credibility rule (§2.6) reads an answer only from the replica of the person
  it belongs to — but a team has no replica and cannot answer for itself, so
  every seated subteam was reported `unobserved`, including ones this very
  session had just seated. The rule now applies to the person named in
  `decided_by`, which is the same rule pointed at the actor who actually
  acted. `role_holders` also stops routing Team actors through the
  not-a-topic-member branch, which had called every one of them a stranger.
  Found by looking at the badges, not by a test.

### Step 6 — Containment **[DONE]**

§2.4 reversed to ALL paths; `seat_team` gained the members check; the roster
gained `outside_parent`. See §2.4a — the whole of it postdates the original
plan and came out of asking what "membership" means once the word for the
body became _team_.

## 4. UI

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

**[DONE]** The region is the definition rather than the doing. It sits last:
the team's agreement comes first, then who is in it — you, this team,
everybody else — then what it expects of them.

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

**Two rules on the page**, and no more: one between what the agreement says
and who is in it, one between who is in it and what it expects of them.
A blanket rule on every `<section>` drew a line between each pair of
paragraphs instead.

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

## 5. Open

- **[DONE]** Reads memoise inside a scope. Building one payload asked
  Session for the same identity, member lists, node lookups and content
  hashes hundreds of times — `Session.identity` alone was read 349 times, and
  each read snapshots the whole protocol tree — which cost **1125 ms per
  build** against a 3-second poll. Scoped to a single read it is **67 ms**.
  The scope is the read and nothing outside one caches, so a mutation can
  never be served a stale entry; keying it on the view revision instead was
  tried first and was wrong, because logic-level mutations do not advance it.
- **[OPEN]** Whether two roles claiming the same domain in one team should be
  detected as a conflict. Out of scope for the first cut; named so it is not
  later mistaken for a bug.
- **[OPEN]** The second trusteeship. The class exists (§1.3) and the encoding
  is ready for it, but Identity is still the only member, so nothing has yet
  tested that the guards generalise as intended.
- **[OPEN]** The cost of depth. Every member needs a role at every level, and
  any edit to a root's agreement invalidates the acceptance at every level
  for everybody below. Accepted deliberately — the minimal member role makes
  it conceptually cheap — but whether it wants a mechanism (a member role
  offered automatically on joining a child) is not decided.
- **[OPEN]** Role as a third Actor kind (a role holding a seat in a subteam,
  so the seat survives personnel change). Deliberately deferred — the actor
  reference is a discriminated union so this stays additive.
- **[RESOLVED]** Whether a background payload refresh can destroy an
  in-progress inline edit. It cannot — see §4.8.
- **[DONE]** How a newly invited person gets their first role — resolved in
  §2.4b: a request is a decision with no offer, so it needed no new node type.
  `agreement_decision` is retired with it; `_interaction_guard` reads role
  holdings and nothing else.
