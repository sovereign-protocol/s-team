# Team Genesis and Governance - delivery plan

Status: proposed for review before implementation.

This plan replaces the earlier two-phase split. The delivery order is driven
by trust and data dependencies: verified authorship must exist before trustee
actions can be adopted automatically, and a stable S-Flow result contract must
exist before S-Team can implement election outcomes.

## 1. Agreed semantics

### Team and Organization

- **Team** remains the stored node type and the Actor kind.
- A root Team - one with no live parent holding - is presented as an
  **Organization**.
- Organization is derived, not stored. A Team becomes an Organization when it
  loses its last parent and stops being one when it takes a parent role.
- Organization is not a third Actor kind.

### Genesis

A newly created Team starts with three roles held by its creator:

1. **Member**, an ordinary role;
2. **Identity**, a trustee role; and
3. **Trust**, a trustee role.

Identity controls membership. Trust facilitates decisions about Identity;
Identity facilitates decisions about Trust.

### Membership

- Identity opens a Member opening.
- One opening may receive and admit several applications.
- An applicant authors their own application and may withdraw it.
- Identity explicitly accepts or rejects each application.
- Closing an opening prevents new applications but does not undo accepted
  memberships. Applications already pending remain resolvable.
- Rejection ends one application. The actor may submit a new application while
  an opening remains open.
- In the first delivery, applicants are already observers on the Team channel.
  External applications arrive later through the Pool.

### Decisions and trustee authority

- A decision process defines how a decision is reached.
- The facilitating trustee is the only Actor authorised to represent,
  interpret and implement that outcome for the Team.
- The decision process never changes a trusteeship directly.
- The incumbent remains in authority until a valid implementation is adopted.
- For an Identity election, Trust implements the result. For a Trust election,
  Identity implements the result.
- The Integrative Election process in S-Flow remains responsible for its own
  nomination, ranking, objection and tie-resolution rules.
- Any current Member may trigger a trustee election.

### Vacancies and concurrency

- Explicit resignation creates a vacancy.
- Any current Member may become a candidate for a vacant trusteeship.
- Every active candidate receives acting authority for that trustee domain.
- Candidate actions do not make the candidate the trustee.
- Concurrent valid actions are allowed. Compatible actions coexist;
  incompatible actions are exposed as conflicts.
- There is no global first-come-first-served claim. Offline peers cannot share a
  truthful global arrival order without a sequencer.
- When a trusteeship is contested, the last settled incumbent remains effective
  until the conflict is resolved. When it was already vacant, it remains vacant
  and its active candidates retain acting authority.

### Trustee decisions and observations

Every authoritative trustee action carries:

- **Signals** - input collected and considered;
- **Consideration** - examination of possible consequences; and
- **Expectation** - expected benefits and issues, for whom and when.

These values may be empty: the system exposes failure to signal rather than
blocking action. A later **Reality** observation is a separate append-only
record authored by the facilitating trustee. There may be several Reality
observations over time; none rewrites the original action.

### Forking

Governance DNA remains the existing clone allowlist:

- agreement sections and clauses;
- roles;
- accountabilities; and
- domains.

A fork receives fresh UUIDs and copies no trustees, members, offers,
applications, decisions, observations, conflicts, parent holdings or history.
The initiator then creates a new genesis state in the fork. The original Team
is unchanged. Parent relationships are not copied.

Focus, Market, asset division, budgets and parent funding decisions are out of
scope for this plan.

## 2. Architectural rules

### 2.1 Signed authorship precedes automatic authority

Current `revision_origin` is bookkeeping and can be forged. It is not a safe
basis for silently accepting an incoming trustee action. Therefore:

- signed authorship is implemented before trustee auto-adoption is enabled;
- transport still carries invalid or unauthorised records so attempts remain
  observable;
- cryptography proves which key authored a record; S-Team governance determines
  whether that author had authority; and
- unsigned legacy content remains readable, but it never qualifies for the new
  authoritative auto-adoption path.

This uses cryptography for attributable truth. It does not prevent a person
from writing or transmitting a record.

### 2.2 Operational authority is append-only

New governance actions are immutable records. Prefer one replicated record per
decision so adoption cannot apply half of a multi-node command.

Trusteeship state becomes an append-only chain. Each state record names:

- the trusteeship (`identity` or `trust`);
- the holder, or an empty holder for vacancy;
- the previous settled state record;
- the cause (`genesis`, `election`, `resignation` or `resolution`);
- the implementing authority and its authority basis;
- an optional S-Flow decision reference and result hash; and
- the standard trustee-decision fields.

One valid successor advances the state. Concurrent valid successors create a
visible contest rather than being ordered by timestamps. Existing mutable
`team_trustee` records require a compatibility projection or a one-time local
migration; they must not be silently reinterpreted.

Other authoritative records - openings, membership resolutions and acting
trustee actions - follow the same append-only rule. Withdrawal or reversal is
a counter-record, never deletion or mutation of another Actor's record.

### 2.3 Authority basis

Every authoritative action references the governance fact that grants its
authority:

- current trustee state for a normal trustee action;
- active candidacy plus vacant trustee state for an acting action; or
- facilitating trustee state for an election implementation.

An incoming action is handled as follows:

1. Invalid signature: do not adopt; expose as invalid authorship.
2. Valid signature but missing prerequisite state: defer and retry later.
3. Valid signature but no applicable authority: do not adopt; expose as an
   unauthorised attempt.
4. Valid signature and authority: auto-adopt.
5. Valid concurrent authoritative revisions: retain and expose the conflict.

Agreement text, role definitions, accountabilities and domains remain on the
normal proposal/consent path.

## 3. Data additions

Names are provisional but their separation is required.

| Record | Purpose |
| --- | --- |
| `team_trustee_state` | Append-only holder/vacancy chain for one trusteeship |
| `team_role` with `system_key: member` | Identifies the constitutional Member role without relying on its editable name |
| `team_member_opening` | Identity-authored, multi-admission opening |
| `team_member_application` | Applicant-authored request referencing an opening |
| `team_member_resolution` | Identity-authored acceptance or rejection of one application |
| `team_trustee_election` | S-Team reference to the S-Flow process and snapshotted electorate |
| `team_trustee_candidacy` | Member-authored application for acting authority during vacancy |
| `team_trustee_action` | Authoritative action where no more specific record is the action itself |
| `team_trustee_reality` | Facilitator-authored observation about an earlier action |

The existing offer/answer model remains for ordinary non-Member roles. Member
standing is derived from a live application plus an accepted resolution for
the system Member role. Identity and Trust standing are derived from their
settled trustee states.

## 4. Delivery sequence

Each increment must leave the application usable and must be tested before the
next increment starts.

### Increment 0 - contract and compatibility baseline

- Add the final schemas and authority matrix to the design documentation.
- Mark the existing default role with `system_key: member` for new data.
- Define legacy recognition conservatively: only the untouched default
  Participant role may be inferred as Member. A customised legacy role requires
  explicit user selection; its name is never silently overwritten.
- Define Organization as a derived root-Team projection across S-Team and
  S-Cockpit.
- Freeze fixtures for current teams so migration remains testable.

**Gate:** current files open without mutation and existing tests remain green.

### Increment 1 - signed authorship in S-Core

- Create and persist a local identity signing keypair.
- Publish the public-key binding with the Core identity.
- Canonically sign new protocol revisions and verify incoming ones.
- Surface verification as `valid`, `unknown`, `legacy_unsigned` or `invalid`.
- Define key rotation and compromised-key revocation before enabling silent
  adoption.
- Preserve invalid records in peer observations rather than dropping them.

**Gate:** two clients verify each other's actions; forged content is detected;
restart, sibling-client pairing and relay transport preserve verification.

### Increment 2 - governance authority and selective auto-adoption

- Add append-only governance-record support and authority-basis validation to
  S-Team.
- Register an S-Team peer-update hook using Core's existing per-node selective
  reconciliation.
- Auto-adopt only valid, authorised operational records.
- Keep unauthorised and invalid attempts visible with an explicit reason.
- Never auto-resolve divergence.
- Keep every agreement-content record on manual proposal/consent behaviour.

**Gate:** an authorised action propagates without a peer click; the same signed
action from a non-authority has no effect but remains visible; concurrent valid
actions surface a conflict.

### Increment 3 - Organization and three-role genesis

- Render root Teams as Organizations without changing stored Actor kind.
- Generalise the current Identity-only code and UI to Identity and Trust.
- Create the system Member role.
- On ordinary Team creation, assign Member, Identity and Trust to the creator.
- Distinguish ordinary creation from template cloning: a template remains
  empty until instantiated.
- Project legacy mutable trustee records through the compatibility path agreed
  in Increment 0.

**Gate:** an N=1 Organization is fully usable and its creator holds exactly the
three base roles.

### Increment 4 - Member openings and applications

- Identity can open and close a multi-admission Member opening.
- Observers can submit and withdraw their own applications.
- Identity can accept or reject each pending application.
- Accepted applicants become current Members; rejected applicants do not.
- Acceptance, rejection and closure auto-adopt as Identity actions.
- Direct role offers cannot bypass the Member gate.

**Gate:** several applicants use one opening and receive independent outcomes;
only Identity or an authorised acting Identity candidate can resolve them.

### Increment 5 - stable S-Flow decision-result contract

- Add a versioned S-Flow facade result containing at least process UUID,
  definition ID/version, lifecycle, terminal outcome, selected candidate,
  participant snapshot, facilitator and canonical result hash.
- Do not let S-Team inspect S-Flow's internal node layout.
- Make the existing Integrative Election template produce this contract.
- Add cross-application contract tests.

**Gate:** S-Team can independently verify a terminal election result through
the facade and detect a changed or incomplete result.

### Increment 6 - trustee elections and implementation

- Allow any current Member to start an election for Identity or Trust.
- Snapshot current Members as required participants.
- Assign the counterpart trustee as S-Flow facilitator.
- Show process progress to everyone.
- Show **Implement decision** only to the facilitating trustee or an authorised
  acting candidate for that facilitating trust.
- Implementation references the terminal result and advances the target
  trusteeship state.
- Keep the incumbent effective until that implementation is valid and adopted.
- Treat competing valid implementations as a visible trusteeship contest.

**Gate:** normal and tied elections complete; a non-facilitator cannot implement
the result; an unimplemented result changes no authority.

### Increment 7 - vacancy, acting authority and decision trail

- Implement explicit trustee resignation.
- Allow every current Member to enter or withdraw candidacy while vacant.
- Derive acting authority from vacancy plus active candidacy.
- Expose all active candidates in the UI.
- Include Signals, Consideration and Expectation on authoritative actions.
- Allow the facilitating trustee to append Reality observations.
- Highlight missing signals without blocking execution.
- Exercise concurrent acting decisions and their counter-processes.

**Gate:** a vacant domain remains operable; multiple candidates can act;
conflicting actions remain visible and recoverable; filling the trusteeship
ends acting authority.

### Increment 8 - Hard Fork / organic mitosis

- Keep the existing governance-DNA copy allowlist.
- Introduce an explicit Hard Fork flow for a current Member.
- Copy into a new root Organization with fresh UUIDs.
- Bootstrap the initiator into the new genesis state; this is new state, not
  copied membership.
- Require every additional person to join through the normal Member gate.
- Copy no operational or audit records.

**Gate:** the fork contains equivalent governance DNA and no source history,
actors, authority, holdings or conflicts.

### Increment 9 - Pool / DMZ onboarding

- Introduce the Pool as a separate shared topic/channel.
- Publish signed invitations referencing a Member opening and expiry.
- Publish signed external applications without granting Team-channel access.
- Let Identity resolve Pool applications and publish the minimum coordinates
  needed for an accepted applicant to mount the Team topic.
- Expired invitations remain historical records but are hidden from active
  discovery by local validation.
- Keep Team internal state out of the Pool.

**Gate:** an unknown external Actor can apply, be rejected without Team access,
or be accepted and then mount the Team topic; expired invitations cannot be
used by the normal client flow.

## 5. Test matrix required throughout

- N=1 genesis and restart.
- Two peers over direct and mailbox/relay channels.
- Same identity on sibling clients.
- Offline delivery in both orders.
- Invalid signature, unknown key and revoked key.
- Authorised, unauthorised, stale-authority and deferred actions.
- Concurrent compatible actions and true divergence.
- Trustee resignation during an election.
- Facilitating trusteeship vacant during another trusteeship's election.
- Member expiry or departure during a snapshotted S-Flow process.
- Legacy Participant and mutable Identity records.
- Clone and Hard Fork exclusion of all new operational/history node types.

## 6. Explicit non-goals

- Global ordering or first-come-first-served arbitration.
- Focus and Market trusteeships.
- Asset or budget copying/division.
- Automatic parent funding or escalation.
- Copying decision or protocol history into a fork.
- Treating a Team's parent position as authority over that Team.
- Preventing invalid Actors from writing or transmitting records; their records
  are verified, disregarded where unauthorised, and exposed.

## 7. Implementation boundary

Expected ownership by repository:

- **S-Core:** signatures, verification state and transport-preserving evidence.
- **S-Team:** governance records, authority evaluation, projections, UI and
  migrations.
- **S-Flow:** stable terminal decision-result facade and election execution.
- **S-Cockpit:** contextual Organization wording and cross-application entry
  points only.

No implementation should begin until the append-only trusteeship model, legacy
migration rule and signed-key lifecycle in this plan are accepted.
