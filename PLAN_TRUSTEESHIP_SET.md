# Implementation plan — a team's set of trusteeships

Today every team has exactly two trusteeships, because `TRUSTS` is a class
constant and "the counterpart" is what facilitation means at two.
`ROADMAP.md:41` and `:55` both defer Focus, Market and Equity until the
facilitation rule "means something for more than two".

This plan decides that rule and makes the set a property of the team.

Where it names a file, a function or a line, that is the thing as it stands
today, not as the design imagines it.

---

## 0. Where this starts

**The suite is green.** 213 passed, 32 subtests, 58.8s in `s-team`.

**The branch is shared.** `fix/node-classes-groundwork`, with `logic.py`,
`team.html`, `team.css`, `CHANGELOG.md`, `config/team.example.json` and two
test files already modified by the parallel agent. Re-check `git status`
before each phase, not only before the first — every phase here touches
`logic.py` and phase 5 touches `team.html`.

**Nothing outside this repository reads the identity accessors.**
`identity_holder`, `trust_holder`, `holds_identity`, `take_identity`,
`offer_identity` and `resign_identity` appear in no source file in
`s-cockpit`, `s-initiative`, `s-flow` or `s-core`. Generalising them is
contained to `logic.py`, `facade.py`, `controller.py` and `team.html`.

---

## The rule this plan implements

**Identity is the minimum.** It can be resigned, leaving it vacant; it can
never be dissolved. The other four are added one at a time and dissolved when
vacant. A team starts with Identity and Trust — decided in phase 4, and a
default rather than a constraint, since either can be established or (for
Trust) dissolved afterwards.

**Facilitation is derived, never stored:**

| Seat acted on            | Facilitated by                              |
| ------------------------ | ------------------------------------------- |
| Identity                 | Trust, if established — otherwise the members |
| Trust                    | Identity                                    |
| Focus, Market, Equity    | Trust, if established — otherwise Identity   |

**No seat supervises itself, and no member supervises a seat they hold.**
When the members facilitate Identity, the Identity holder is not among them.
That is the same invariant one level down, and it is what keeps the
one-trusteeship team from becoming a seat its holder can hand to a successor
of their choosing — the handover this model has no way to write.

**Supervision is Identity's and Trust's only.** Focus, Market and Equity are
held, never supervising. This is what makes the derived rule safe to check on
replay (§ D2).

---

## A refinement to the shape we agreed

We spoke of a `team_trusteeship` record carrying a seat's existence, beside
`team_trustee_state` carrying its occupancy. Writing the phases out, the same
semantics land in one chain instead of two, by adding two causes to
`TRUSTEE_CAUSES`:

- `establishment` — the seat begins, **vacant**, on the facilitator's
  authority. Chain root, so `previous_state_uuid` is empty.
- `dissolution` — the seat ends. Head of the chain, requires the seat to be
  **vacant** already, refused for Identity.

A seat is established when it has a chain root whose head is not a
`dissolution`. Nothing is rewritten, the whole life of a seat stays one
append-only line, and there is no second record type, container, dispatch row,
schema checker or projection to keep in step with the first. `genesis` stays
exactly as it is and becomes Identity's founding act only.

The cost, taken deliberately: a contest over dissolving a seat and a contest
over who sits in it are the same `contested` state on one chain. Both are a
fork in an append-only chain and the UI already shows contenders, so this
costs a sentence in `DESIGN_TYPES.md` rather than a mechanism.

---

## 1. Facilitation becomes a derived rule — **done**

**No behaviour change. Every existing test passes untouched** — that is this
phase's acceptance criterion. 218 passed, 38 subtests; the 213 that existed
before are unedited.

Two things landed differently from what is written below, both recorded here
rather than rewritten out of it:

- **`genesis` is now refused for Focus, Market and Equity.** Widening `TRUSTS`
  was not inert on its own: genesis answers to no facilitator, so the moment
  the three new seats could be named, any client could have founded itself
  into one. `_trustee_state_schema_error` restricts genesis to Identity and
  Trust, which is where it stayed: those two are what a team is founded with,
  and every other seat begins with an `establishment` that answers to a
  facilitator.
- **The replay regression test moves to phase 2.** It needs a Focus seat to
  establish Trust around, and nothing can establish Focus until phase 2. What
  phase 1 asserts instead is the property the test would exercise: the
  eligible set is drawn from Identity and Trust alone, for every seat.

### Source

- `logic.py:116` — `TRUSTS` grows to five: `identity`, `trust`, `focus`,
  `market`, `equity`.
- `logic.py:126` — add `SUPERVISORY_TRUST = "trust"` beside
  `MEMBERSHIP_TRUST`, named for the same reason: so "supervision defaults to
  Trust" is something the model says once.
- New `established_trusts(team) -> frozenset[str]` — seats with a chain root
  whose head is not a dissolution. Until phase 2 there are no dissolutions, so
  this reads as "has a chain root", which is what makes phase 1 inert and what
  makes every team already on disk read correctly.
- `logic.py:3282` — `_sole_facilitating_trust(trust)` is replaced by two
  functions on the team:
  - `facilitating_trust(team, trust) -> str` — the rule table above. `""`
    means the members facilitate.
  - `eligible_facilitating_trusts(team, trust) -> frozenset[str]` —
    `({SUPERVISORY_TRUST, MEMBERSHIP_TRUST} & established_trusts(team)) - {trust}`.
- New `_facilitation_refusal(team, trust, actor_uuid, basis_uuid)`. It reads
  the basis rather than the rule: a `team_trustee_state` whose own `trust` is
  in `eligible_facilitating_trusts` and whose holder is the actor, or a
  `team_trustee_candidacy` on the same terms as `_trust_authority:4110` allows
  today for acting candidates. It replaces the re-derivation at **both**
  replay-time sites — `_assess_trustee_state:4335` and
  `_assess_trustee_reality:4607`.
- `logic.py:3295` `_authority_basis_for_actor` and `logic.py:2110`
  `can_settle` keep using `facilitating_trust` — the rule decides what is
  *offered*, the eligible set decides what is *accepted*.
- Four write-time sites take the facilitator from `facilitating_trust`:
  `start_trustee_election:3390`, `settle_trusteeship:3583`,
  `append_trustee_reality:4949` and the actions payload at `:4996`. The last
  two are the observation path — a reality about an Identity action is written
  under Trust's authority — so the rule governs who may observe as well as who
  may settle, and both follow the table without a second statement of it.
- `logic.py:3549` — the election-adoption loop iterates
  `established_trusts(team)`, not `self.TRUSTS`.
- `logic.py:7526` — containment counts holders of every established seat, not
  Identity and Trust by name.
- `logic.py:7036` — the `trusteeships` payload is keyed by established seat.

Schema validation at `logic.py:2293`, `:3315`, `:3380`, `:3581`, `:4512` and
`:4908` keeps checking against `TRUSTS`, the **vocabulary**. A record naming a
seat this replica has not yet seen established is not malformed; it is
unresolved, and it must stay readable so it can resolve when the establishment
arrives.

### Tests

- The rule table, one case per row, at each set size.
- A settlement whose basis names an ineligible seat is refused — including
  Identity's own state as the basis for settling Identity.
- Genesis founds Identity and Trust and nothing else.
- **The replay regression** — moved to phase 2, where a Focus seat exists to
  write it about. A Focus settlement authorised under Identity's facilitation
  must stay authorised after Trust is established. This is the case that made
  the old re-derivation unsafe, and the reason `_facilitation_refusal` reads
  the basis.

### Documentation

`DESIGN_TYPES.md:55` — the `TRUSTS` vocabulary line, and the paragraph above
it that says two exist. `DESIGN_TYPES.md:227` — "The facilitating trusteeship"
is rewritten around the rule table. Add the `SUPERVISORY_TRUST` vocabulary
line; `test_type_registry.py:173` accepts a one-member vocabulary declared as a
plain string, which is how `MEMBERSHIP_TRUST` already passes.

---

## 2. `establishment` and `dissolution` — **done**

226 passed, 39 subtests. Two things landed differently:

- **A second establishment root is a contest, not a refusal.** Written as
  "refuse it" below, after the genesis and membership-invitation precedent.
  Both of those have one possible author, so a competing root is junk. This one
  has two, and refusing the later arrival settles a real concurrency by arrival
  order — each replica settling it differently, with no way back together. The
  projection shows the fork instead.
- **`establishable_trusts` and `TRUST_ORDER`** were not in the plan. The face
  needs to know which seats a team could add and in what order to offer them,
  and vocabulary order is not alphabetical — Equity first would put the rarest
  seat at the top of every list.

### Source

- `logic.py:127` — `TRUSTEE_CAUSES` gains `establishment` and `dissolution`.
- `logic.py:2301` `_trustee_state_schema_error` — `establishment` is a root,
  so it is the second cause permitted an empty `previous_state_uuid`;
  `dissolution` and `establishment` both require an empty
  `holder_actor_uuid`; `genesis` is now permitted only for
  `MEMBERSHIP_TRUST`.
- `logic.py:4287` `_assess_trustee_state` — two branches beside
  `_assess_resignation`:
  - `establishment`: no live chain for this seat already, and
    `_facilitation_refusal` against the seat being established.
  - `dissolution`: the head is vacant, the seat is not `MEMBERSHIP_TRUST`, and
    `_facilitation_refusal` again.
- `logic.py:2413` `trustee_projection` returns `dissolved` when the head is a
  dissolution. The four states become five.
- New `establish_trusteeship(team_uuid, trust)` and
  `dissolve_trusteeship(team_uuid, trust)` beside `resign_trusteeship:1550`.
- `facade.py` passthrough; `controller.py:503` neighbourhood gains
  `/api/team/trusteeships/establish` and `/dissolve`.
- `trusteeship_payload:2048` gains `can_establish` and `can_dissolve`; the
  team payload at `logic.py:7033` gains the unestablished seats so the UI can
  offer them.

### Tests

- Establish Focus under Trust's authority; refuse it under Focus's own.
- Establish Focus under Identity when Trust is not established.
- Dissolve refused while the seat is held; accepted once vacant.
- Identity dissolution refused, whoever asks.
- Two clients establishing Focus concurrently produce `contested`, not a
  silent winner.
- A `team_trustee_state` naming a dissolved seat is unauthorised.

---

## 3. The members facilitate Identity — **done**

229 passed, 39 subtests. One thing landed differently: a membership named as
the basis where a trusteeship *does* facilitate is refused, not deferred.
Deferring left the record waiting on a question already answered the other
way, which is a record that never resolves.

`facilitating_basis_for_actor` turned out to be the better seam than the two
listed below — the write paths ask one question and get a seat's state or a
membership back, without knowing which case they are in. Four write paths use
it: establish/dissolve, settle, observe, and the election's facilitator.

This is what makes a one-trusteeship team live rather than bricked.

### Source

- `_facilitation_refusal` accepts a `team_membership` basis **only** when
  `eligible_facilitating_trusts(team, trust)` is empty — which, Identity being
  mandatory, happens for Identity alone. The actor must be a current member by
  `_is_current_member`, and must not be the seat's own holder.
- `logic.py:3295` `_authority_basis_for_actor` returns the actor's current
  membership uuid in that case, so `can_settle` lights up for members and the
  election path names them as facilitator.
- `logic.py:4110` `_trust_authority` keeps returning `deferred` for a seat it
  cannot resolve — an unknown establishment is not evidence of absence, the
  same stance it already takes for an unknown signing key.

### Tests

- With Trust dissolved and Identity vacant, a member settles Identity.
- With Trust dissolved and Identity held, a member facilitates an election
  that replaces the holder.
- The Identity holder cannot facilitate Identity — the "except Identity" rule,
  and the one that keeps handover impossible.
- With Trust established, a membership basis for Identity is refused.
- A member observes an Identity action when there is no Trust, and the
  Identity holder cannot observe their own.

### Documentation

`DESIGN_TYPES.md:537` "A team may have no members at all" — the **Beyond
recovery** paragraph changes materially. Leave, resign Identity, resign Trust
is no longer terminal: dissolve Trust and the members can refill Identity.
Say so, and say what remains terminal — zero members and a vacant Identity,
because there is nobody left to facilitate.

---

## 4. Identity as the explicit minimum — **done**

Done: the named accessors are gone — `identity_payload`, `trust_payload`,
`trust_holder`, `holds_trust`, the payload's `identity` / `trust` /
`holds_trust` keys, and `offer_identity` with its route, which existed only to
refuse. `seats`, `establishable_trusts` and per-seat `facilitator_trust` stand
in their place. Identity is the explicit minimum in the model: the only seat
`genesis` may found alongside Trust, and the only one that cannot be
dissolved.

**Decided: a new team starts with Identity and Trust**, as it always has.
Creation writing Identity alone was written, run and reverted — it costs 26
test conversions, all of them tests assuming a new team has Trust, none
structural.

The decision rests on this being a *default* rather than a capability: both
shapes are reachable either way, because a team can dissolve Trust or
establish it whenever it wants to. What changed is that the pair is now where
a team starts rather than what it is stuck with, and `genesis` is the only
cause that founds them — every other seat begins with an `establishment` that
answers to a facilitator.

### What phase 4 was written as

### Source

- `logic.py:832` `create_team` and `logic.py:878` `create_seated_team` stop
  writing trusteeships. They write the founder's membership; the founder's own
  next act establishes Identity.
- `logic.py:1508` `take_identity` becomes that act, unchanged in mechanism —
  it already writes a `genesis` state and already refuses when a chain exists.
  It stops creating Trust alongside.
- `create_seated_team:894` requires `holds_identity(parent)`; a parent that
  has not set Identity cannot seat a subteam. Correct, and worth a test.
- The named accessors go, replaced rather than aliased:
  `identity_holder:1475`, `trust_holder:1484`, `holds_identity:1490`,
  `holds_trust:1496`, `identity_payload:2042`, `trust_payload:2045`,
  `resign_identity:1546`, `offer_identity:1532` in `logic.py`, and
  `facade.py:39-58`. `holder(team, trust)` and `holds(team, trust)` cover the
  four call sites at `logic.py:894`, `:5489`, `:5676`, `:5752`.
  `offer_identity` refuses unconditionally and its route can go with it.

### Tests

Roughly 102 lines across `test_team_logic.py` and `test_ownership_guards.py`
name these. Most are a signature change; the ones that assert a new team has
Trust are the real edit, and they become assertions that it has neither seat
until the founder sets Identity.

**Cost, stated plainly:** a new team takes one more act before it can invite
anybody. That is what "every team explicitly names and sets Identity" means,
and it puts the founding act in the trail instead of leaving it implied by
genesis.

---

## 5. The face — **done**

- `team.html:2463` renders one card per established seat in vocabulary order —
  Identity, Trust, Focus, Market, Equity — instead of two by name.
  `renderTrusteeRoleCard(trust)` at `:2173` is already generic.
- `team.html:1860` derives the facilitator client-side
  (`trust === "identity" ? "trust" : "identity"`). It comes from the payload
  now; the browser does not get to hold a second copy of the rule.
- `team.html:1047` iterates the payload's seats rather than the literal pair;
  `:1054`, `:2174`, `:2197`, `:2328` carry the two-way label expression, and
  `logic.py:1566`, `:3409`, `:3437`, `:5095` carry `.title()` — one label map
  for the five, in one place.
- An **Add trusteeship** affordance offering the unestablished seats, and
  **Dissolve** on a vacant seat that is not Identity.
- The empty-team card at `:2325` becomes "Set Identity" — the phase 4 act.

`DESIGN_UI.md` follows. Both the full-render and the DOM-patch path for each
node type change together; a render function updated without its patch
counterpart is the failure mode this file has produced before.

---

## 6. Registry and roadmap — **done**

- `DESIGN_TYPES.md` — the `TRUSTS` and `TRUSTEE_CAUSES` vocabularies, the
  `SUPERVISORY_TRUST` line, the rewritten facilitation section, two new rows in
  **How a seat moves**, the fifth projection state, and the revised **Beyond
  recovery** paragraph. `test_type_registry.py` fails the change that forgets
  any of them, which is the point of it.
- `ROADMAP.md:41` and `:55` — both entries come off. The rule means something
  beyond two now.
- `CHANGELOG.md`.

---

## Order, and what each phase is worth on its own

| Phase | Ships                                                        |
| ----- | ------------------------------------------------------------ |
| 1     | Nothing visible. The rule exists and is tested; suite green   |
| 2     | Focus, Market and Equity can be added and removed             |
| 3     | A team can drop to Identity alone and still replace it        |
| 4     | Identity is set rather than assumed; new teams start at one   |
| 5     | The face for all of it                                        |
| 6     | The documents that are enforced                               |

Phases 1 and 2 together are the whole of "add the trustees the team wants".
Phase 3 is what makes phase 4 safe, and phase 4 is what makes the minimum a
decision rather than a default. Stopping after 2 leaves a working system with
Identity and Trust always present — which is today's shape, plus three
optional seats.
