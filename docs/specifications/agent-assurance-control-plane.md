# Agent Assurance Control Plane

**Status:** Proposed for owner ratification (revision 6)  
**Version:** 0.6  
**Date:** 2026-09-12  
**Supersedes:** v0.1 (2026-09-06), v0.2, v0.3, v0.4 and v0.5. Revised against
five rounds of independent review; §21 records the disposition of every finding
from all five.  
**Working name:** Keel  
**Repository:** KP_SDLC  

## 1. Purpose

Build a harness-independent assurance control plane for agentic software delivery.
It must show what coding agents are doing in real time, determine whether claims
about their work are backed by current and non-vacuous evidence, preserve useful
context across sessions, and demonstrate whether the engineering system improves
because teams use it.

The control plane is not another source-code scanner. Existing tools continue to
inspect code, architecture, security, data and runtime behaviour. KP_SDLC governs
how those results become trusted decisions:

- which repository and artifact were inspected;
- which policy and configuration were applied;
- which checks actually executed;
- which surfaces were not inspected;
- whether the evidence was capable of failure;
- whether the observer was independent of the authoring agent;
- whether a waiver is owned and unexpired;
- whether the evidence is fresh enough for the decision being made.

The visual experience may be playful, but every displayed fact must come from a
stable evidence contract. Theme packs never change capture, evidence or verdict
semantics.

## 2. Product outcome

A developer should be able to run:

```text
sdlc init
sdlc check
sdlc status
sdlc explain <finding-or-decision>
sdlc observatory
```

and answer, without reading agent transcripts:

1. Which agents and tasks are active, waiting, failing or complete?
2. Which files, worktrees and tools are involved, and where is coordination risk?
3. Is context pressure rising, was compaction captured, and can the next session
   recover from structured memory?
4. Which quality, architecture, contract, runtime, evaluation, security and
   production surfaces were inspected?
5. Which claims are blocked, inconclusive, waived or supported by adequate
   evidence?
6. Who or what produced the evidence, and was it independent of the authoring
   agent?
7. What is the next useful action, who owns it, and when does it expire?
8. Has adoption reduced escapes, rework, uncertainty or developer waiting time?

## 3. Non-goals

- Do not replace Sonar, Ruff, ESLint, Semgrep, CodeQL, dbt, Soda, Great
  Expectations, promptfoo, DeepEval, OpenTelemetry or similar specialist tools.
- Do not invent a proprietary signature format or transparency log.
- Do not capture complete prompts, transcripts, tool inputs or tool outputs by
  default.
- Do not claim that an attestation proves correctness. It proves origin, process
  and an identified verifier's decision under an identified policy.
- Do not use event volume, token spend, lines of code or agent count as maturity.
- Do not rank individual developers or agents by productivity.
- Do not let an agent weaken its own success criteria, approve its own exception,
  or sign a human gate.
- Do not require every repository to use KP_SDLC's gate numbering or lifecycle.
- Do not implement external side effects, agent control or automatic worktree
  deletion in Observatory — for the whole of this programme, not merely its first
  increment.
- Do not let any self-healing or remediation action apply itself. Every such
  action is proposed, approved by a human, and recorded as its own evidence.

## 4. Existing assets and required reuse

This specification extends rather than replaces the current implementation:

| Existing asset | Role in the target system |
|---|---|
| Quality Gate | Static quality evidence provider |
| Cathedral Keeper | Architecture and repository-structure evidence provider |
| Input Gate (G1) | Definition-of-ready evidence provider |
| Contract Gate (G2) | Contract-completeness evidence provider |
| Runtime Verify (G4) | Runtime assertion evidence provider |
| Eval Engine (G5) | Behavioural and trajectory evaluation provider |
| NFR Gate (G6 — closed prototype, PR #23) | Non-functional budget evidence provider, to be rebuilt on §6.2.1 |
| `sdlc-init` | Installation, manifest and born-gated proof executor |
| Observatory | Read-only live projection and operator experience |
| CtxPack | System of record for context capture, recall and compaction |
| Structural Floor | Protection for policy and success-definition surfaces |
| Shared finding shape | Human- and machine-readable diagnostic boundary |

No work package may introduce a second implementation of one of these concerns
without an ADR explaining why an adapter cannot be used.

## 5. Architectural decision

Use a stable core with evolving adapters and multiple read models.

```text
Harness telemetry                         Repository/tool evidence
Claude · Codex · others                   QG · CK · gates · CI · scanners
        |                                              |
        v                                              v
TelemetryAdapter -> EventEnvelope       EvidenceAdapter -> EvidenceEnvelope
        |                                              |
        +----------------------+-----------------------+
                               v
                    Assurance decision engine
                  policy · freshness · coverage
                  adequacy · independence · waiver
                               |
              +----------------+----------------+
              |                                 |
              v                                 v
       Decision + findings              Attestation exporters
              |                         in-toto · DSSE · Sigstore
              v
    Observatory read models <--------- CtxPackMemoryAdapter
    live scene · queue · graph          health + checkpoint digests
    library · maturity · history
```

### 5.1 Component ownership

**Telemetry adapters** translate harness-specific events into canonical
capabilities and events. Unknown vendor events remain observable; they do not
become trusted semantics until an adapter version maps them.

**Evidence adapters** translate existing tool artifacts into a common evidence
shape. They never reinterpret a missing or malformed artifact as a pass.

**The assurance engine** evaluates policy over evidence. It owns verdict
precedence, freshness, coverage, waiver and independence rules. It does not run
specialist analysis that an adapter can delegate to an existing tool.

**Attestation exporters** serialize decisions and their evidence references into
standard formats. The internal decision model remains usable offline and without
Sigstore.

**Observatory** is a read-only projection for the duration of this programme. It
may recommend an action but cannot approve, waive, merge, deploy, delete or
mutate an external system. Making it read-write is a separate ratification with
its own threat model, not a later increment of this one. Self-healing proposals
surface here as ranked recommendations; a human applies them, and the
application produces its own evidence record naming the approver.

**CtxPack** owns memory content and recall. The control plane consumes a health
assessment and content digests, never a second copy of the memory ledger.

## 6. Canonical contracts

All contracts are versioned, reject unknown required semantics, tolerate unknown
optional extension fields, and have positive and negative fixtures.

### 6.1 `sdlc/event@1`

Minimum fields:

```yaml
schema: sdlc/event@1
id: evt_...
observed_at: RFC3339 timestamp
source:
  adapter: claude-code/hooks@1
  harness: claude-code
  harness_version: optional
repository:
  id: stable local or remote identity
  commit: optional full SHA
  worktree: optional stable identifier
session:
  id: opaque identifier
  parent_id: optional
actor:
  id: opaque identifier
  kind: human | agent | service
type: canonical event type
capability: session_lifecycle | tool_lifecycle | permissions | subagents |
            compaction | context_utilization | cost | unknown
operation:
  name: bounded tool or lifecycle name
  phase: start | progress | finish | error | deny
correlation:
  task_id: optional
  tool_call_id: optional
execution:
  workflow_id: optional stable workflow identity
  workflow_run_id: optional identity of the concrete run
  step_id: optional identity of the step within the workflow
  call_id: unique identity for this invocation
  attempt: integer >= 1
  idempotency_key: stable key for the intended effect
  status: executed | replayed | resumed | deduplicated
  retry_of: call_id of the previous attempt when attempt > 1
  replay_of: call_id of the original invocation when status != executed
  recorded_at: RFC3339 ingestion timestamp, distinct from observed_at
privacy:
  content_captured: false
  redactions: []
integrity:
  observer: self_reported | harness_hook | runner | protected_ci | isolated
```

Rules:

- Event IDs are unique and append-only.
- Harness payloads are untrusted input.
- Tool inputs and outputs are excluded by default.
- Malformed events are counted and surfaced, not allowed to stop the projection.
- Event timestamps never alone establish freshness; ingestion time and source
  monotonicity are also recorded.
- A session with no terminal event becomes stale after a configurable TTL. It is
  not shown as actively waiting forever.
- `call_id` is unique per invocation and never reused across attempts. A retry
  is a genuine re-execution: `status: executed`, a new `call_id`, `attempt > 1`,
  and `retry_of` naming the previous attempt. `replay_of` is never used for a
  retry, and `retried` is not a status — the distinction the model needs is
  between work that ran again and a record that was replayed.
- A replayed or deduplicated event reports the original observation time in
  `observed_at` and the replay time in `recorded_at`. Replay never refreshes
  freshness.
- Two events sharing an `idempotency_key` count once toward any executed or
  coverage total. A shared key with divergent outcomes is a `CONTENDED` finding,
  not a silent last-writer-wins.

### 6.2 `sdlc/evidence@1`

Minimum fields:

```yaml
schema: sdlc/evidence@1
id: evd_...
result_digest: sha256 over the normalized tool result alone (§6.3.1);
               recognizes "the same tool said the same thing", never gates
evidence_digest: sha256 over this document's canonical payload (§6.3.1), which
                 contains result_digest plus every verdict-driving field;
                 the field is excluded from the bytes it digests, and this is
                 the digest a decision references
subject:
  kind: git_commit | file | artifact | dataset | deployment | agent_session
  name: stable subject name
  digests: {algorithm: value}
producer:
  tool: quality-gate
  version: semver-or-digest
observer:
  actor_identity:            # who authored the subject under inspection
    id: opaque identity
    kind: human | agent | service
    verification: unverified | token | oidc | signed_commit | attested
  observer_identity:         # who produced this evidence
    id: opaque identity
    kind: human | agent | service
    verification: unverified | token | oidc | signed_commit | attested
  execution_identity:        # where it ran, and who could change that
    runner: local | self_hosted_ci | protected_ci | isolated
    actor_can_mutate_config: boolean
    oidc_issuer: optional
    oidc_subject: optional
  workload_identity:         # what was actually applied
    policy_digest: digest of the policy that ran
    config_digests: []
    fixture_digest: optional proof-of-fire fixture identity
  claimed_level: 0..4        # adapter self-report; recorded, never gates
  independence:              # DERIVED by the engine; never authored
    level: 0..4
    derivation: rule-set id and version
    inputs: [references to the four identities above and their proofs]
    constrained_by: [reason codes that capped the level]
policy:
  id: stable policy id
  version: version or digest
  config_digests: []
execution:
  started_at: RFC3339 timestamp
  finished_at: RFC3339 timestamp
  recorded_at: RFC3339 ingestion timestamp
  latency_ms: integer
  executed_count: integer
  skipped_count: integer
  workflow_id: optional
  workflow_run_id: optional
  step_id: optional
  call_id: unique identity for this production run
  attempt: integer >= 1
  idempotency_key: stable key for the intended effect
  status: executed | replayed | resumed | deduplicated
  retry_of: call_id of the previous attempt when attempt > 1
  replay_of: call_id of the original run when status != executed
measurements: []             # typed quantities; see 6.2.1
coverage:
  declared_surfaces: []
  inspected_surfaces: []
  uninspected_surfaces: []
outcome: pass | fail | unavailable | inconclusive
findings: []
references: []
```

Rules:

- `pass` requires `executed_count > 0` unless the policy explicitly defines a
  different non-vacuous positive control.
- Every declared surface is inspected, named as uninspected, or explicitly
  declared not applicable with a reason.
- Evidence is immutable, and it carries **two** digests because it answers two
  different questions (§6.3.1). `result_digest` covers the normalized tool
  result only, so two runs that found exactly the same thing share it and stay
  recognizable as the same finding set. `evidence_digest` covers the canonical
  evidence payload — `result_digest` plus every field that can change a
  verdict, including `status`, `finished_at`, `idempotency_key` and retry or
  replay lineage — so two runs that found the same thing at different times, or
  under different execution status, do **not** share it.
- A decision references `evidence_digest`, never `result_digest`. Referencing
  the result digest alone would let a record whose occurrence facts differ be
  substituted for the one that was actually evaluated.
- Evidence must bind to an `evidence_digest` and to a full commit SHA or subject
  digest before it can support a merge or release decision.
- Evidence older than its policy freshness window cannot support a fresh pass.
- A tool's own `passed: true` field is an observation, not the control-plane
  verdict.
- `observer.independence.level` is derived by the engine (§7). Evidence that
  arrives with a level already filled in has it moved to `claimed_level`; a
  claimed level above the derived level is a named finding.
- A quantity that a policy compares against a threshold must appear in
  `measurements` in the typed shape of §6.2.1. A bare number in `findings`
  cannot support a budget decision.

#### 6.2.1 Typed measurement

Non-functional decisions compare quantities. A quantity without its unit,
statistic, workload, window and environment is not comparable to a budget, and a
comparison made anyway is a fabricated verdict. Each entry of `measurements`
therefore carries:

```yaml
- metric_id: stable metric identity (e.g. http.server.request.duration)
  value: number
  unit: unit token (ms, s, By, 1, %, /s) — UCUM or OpenTelemetry vocabulary
  statistic: p50 | p95 | p99 | mean | median | max | min | count | rate | ratio
  direction: lower_is_better | higher_is_better
  workload:
    id: named scenario the measurement was taken under
    digest: digest of the workload definition
    concurrency: optional integer
  window:
    started_at: RFC3339 timestamp
    finished_at: RFC3339 timestamp
    sample_count: integer
    excluded_count: integer (warmup or discarded samples)
  environment:
    id: named environment profile
    digest: digest of the resolved environment description
    class: local | ci_shared | ci_dedicated | staging | production
  measurement_source: benchmark_harness | load_generator | apm | ci_runner_timer
                      | harness_timer | synthetic | vendor_report
  uncertainty:                      # optional but required by strict profiles
    kind: stddev | ci95 | iqr
    value: number
```

Rules:

- All of `metric_id`, `value`, `unit`, `statistic`, `workload`, `window`,
  `environment` and `measurement_source` are required. A measurement missing any
  of them is `INCONCLUSIVE` for budget purposes and can never derive `PASS`.
- Two measurements are comparable only when `metric_id`, `unit`, `statistic`,
  `workload.digest` and `environment.class` all match. A budget evaluated across
  a mismatch is `INCONCLUSIVE` with an explicit incomparability reason code.
- `sample_count` below the policy or profile floor yields `INCONCLUSIVE`, not a
  pass on one sample.
- `measurement_source: synthetic` and `vendor_report` are inadmissible for
  blocking decisions unless the policy or profile names them admissible.
- Unit conversion is explicit and recorded. The engine never guesses that `s`
  and `ms` were meant to be the same scale.
- A budget comparison records the observed value, the limit, the margin and the
  comparison direction, so `sdlc explain` can reproduce the arithmetic.

G6 (NFR budget) is rebuilt on this shape. The closed PR #23 compared a bare
number against a bare limit, which is why its interface was not salvaged.

#### 6.2.2 Durable execution and replay

Evidence is produced by runs that retry, resume and replay. Provenance that
cannot tell a fresh execution from a replayed record will eventually launder a
stale result into a fresh pass. The `execution` block therefore carries
`workflow_id`, `workflow_run_id`, `step_id`, `call_id`, `attempt`,
`idempotency_key`, `status`, `retry_of` and `replay_of`.

The model has exactly two states, and the whole point is that they are not
confusable. Either the work ran — `status: executed`, whether this is the first
attempt or the fourth — or a previously recorded result was reproduced, which
is `replayed`, `resumed` or `deduplicated`. A retry is the first kind, not the
second; it is not a distinct status, and it does not use `replay_of`.

Rules:

- `status: executed` establishes freshness, including a genuine re-execution
  with `attempt > 1`. `replayed`, `resumed` and `deduplicated` carry the
  original run's timestamps forward, are evaluated against the original
  `finished_at`, and never refresh freshness.
- `attempt > 1` requires `retry_of` to name a `call_id` already recorded for the
  same **logical effect**: the same `idempotency_key`, the same subject digest
  and the same producer. Where a `step_id` is present both records must also
  share it; where there is no workflow context and `step_id` is absent, the
  `idempotency_key` alone identifies the effect. A retry carrying no
  `idempotency_key` has no lineage to check and is malformed, so it derives
  `INCONCLUSIVE` rather than being accepted on the strength of its `attempt`
  number. `replay_of` is required for, and only for, the reproduced statuses.
- `call_id` is unique per production run, and lineage is resolved through it, so
  two evidence records claiming one `call_id` with different `evidence_digest`s
  are a contradiction about a single run rather than two runs. That derives
  `INCONCLUSIVE` with a lineage-collision reason code; the engine does not pick
  one. Because `call_id` is bound (§6.3.1), producing such a pair requires
  changing a digest rather than editing a record in place.
- Evidence sharing an `idempotency_key` counts once toward `executed_count`.
- Divergent outcomes under one `idempotency_key` produce a `CONTENDED` modifier
  and block promotion until adjudicated. **ACP-0 admits no exception**: there is
  no retry-to-green allowance, so a step that failed and then passed under the
  same key is contended rather than green. A profile-level relaxation would
  need its own ratification and is out of scope for the pilot.

The word "replay" carries three distinct meanings in this design, and collapsing
them produces requirements that cannot be met. They are named separately and
used only as named:

| Term | What it is | Where it is specified |
|---|---|---|
| **Step replay** | a durable-execution engine reproducing a recorded *tool* result instead of re-running the step: `status: replayed`, `resumed` or `deduplicated` | this section |
| **Verification replay** | recomputing a recorded *decision's* canonical payload from its recorded inputs and asserting byte equality — a check, not a new decision | §6.3.3 |
| **Re-evaluation** | deciding again over the same evidence under `mode: replay`, `historical` or `test` — a new decision with a new payload and digest, which can never promote | §6.3.3 |

Step replay never refreshes freshness; that rule is stated above. Verification
replay and re-evaluation are decision-level operations and are specified in
§6.3.3, which also states why exact reproduction and re-deciding cannot be the
same operation.

### 6.3 `sdlc/decision@1`

Verdicts:

| Verdict | Meaning |
|---|---|
| `PASS` | Required, fresh, non-vacuous evidence held |
| `PASS_WITH_DEBT` | Pass held; owned and dated non-blocking debt remains |
| `BLOCKED` | A bound check failed or required policy condition was not met |
| `SKIPPED_NAMED` | A surface or adapter is unbound; omission is named and charged to coverage |
| `INCONCLUSIVE` | Evidence was unavailable, stale, malformed, inadmissible or incapable of failure |
| `VOID` | The underlying mechanism reported success while its guard or inspected set was empty/unbound |

Verdict precedence is:

```text
VOID > BLOCKED > INCONCLUSIVE > SKIPPED_NAMED > PASS_WITH_DEBT > PASS
```

Lifecycle and modifiers are separate from verdicts. Initial lifecycle values are
`DRAFTED`, `ACTIVE`, `HELD`, `EXPIRED`, `SUPERSEDED`; modifiers include
`PROVISIONAL`, `EXPIRING`, `DRIFT`, `WAIVED`, `NO_APPROVER`, `UNSIGNED` and
`CONTENDED`.

A decision includes `content_digest` — sha256 over its own canonical payload,
excluded from the bytes it digests — plus the subject digest, policy digest,
config digests, the referenced **`evidence_digest`s**, derived verdict, reason
codes, uninspected surfaces, owner, the `evaluation` block (§6.3.2) together
with any `claimed_source` or `claimed_skew_bound_s` a request supplied, the
expiry window, and its generation time. Which of these sit inside the digested
payload and which are occurrence-only is settled by the tables in §6.3.1, not by
the order of this sentence. No agent-authored boolean such as `approved: true`
is accepted as a decision.

#### 6.3.1 Field classification, the two evidence digests and determinism

This section governs both digested contracts — `sdlc/evidence@1` and
`sdlc/decision@1`. (`sdlc/event@1` is telemetry, is not a decision input, and
ships no earlier than ACP-6; nothing here applies to it.)

Evidence and decisions both carry two kinds of field, and conflating them makes
determinism unstatable. A new run legitimately produces a new evidence ID, a new
`call_id` and new timestamps — that is what makes the record auditable. If every
such field sits inside the thing required to be reproducible, then no two runs
can ever match and the requirement is impossible to satisfy rather than merely
hard.

The earlier split sorted fields by whether they *vary between runs*. That is the
wrong test, and it is how `finished_at`, `status`, `idempotency_key` and retry
lineage came to sit outside the digest while normative rules elsewhere made each
of them decisive. The correct test is semantic:

> **Classification rule.** A field is **bound** if its value can change a
> verdict, freshness, deduplication, contention, the derived independence level,
> or whether a verification replay succeeds. Otherwise it is
> **occurrence-only**. Varying between runs is not a reason to exclude a field
> from the digest; it is a reason to stop requiring those runs to share one.

Two conformance requirements follow, and both are testable:

- Every field of both schemas carries a declared class. A field present in a
  document with no declared class is a schema defect and the document derives
  `INCONCLUSIVE`; it is never evaluated on the assumption that an unclassified
  field is harmless. This is the fail-closed rule that would have caught
  `status` and `idempotency_key` belonging to neither partition.
- A field that any rule later reads to reach a verdict moves into the bound set
  in the same change that introduces the rule. The tables below are normative
  and are the only place the partition is stated.

##### The two evidence digests

One digest was being asked to answer two questions at once: *did the same tool
find the same thing?* and *is this the record that was evaluated?* Those have
different answers, so they get different digests.

- **`result_digest`** — sha256 over the **result subset**: subject digest,
  producer tool and version, policy digest, resolved config digests, `outcome`,
  `executed_count`, `skipped_count`, the coverage sets, findings in canonically
  ordered form, and each measurement's comparability and value fields
  (`metric_id`, `value`, `unit`, `statistic`, `direction`, `workload`,
  `environment`, `measurement_source`, `uncertainty`, `sample_count`,
  `excluded_count`). It excludes `window.started_at` and `window.finished_at`,
  which are facts about when sampling happened rather than about what was
  measured. Two runs that genuinely found the same thing share this digest.
  It **never gates** and a decision never references it.
- **`evidence_digest`** — sha256 over the **canonical evidence payload**, which
  is `result_digest` together with every remaining bound field: the four
  identities and the derived independence block, `claimed_level`, the schema
  version, `finished_at`, `step_id`, `call_id`, `attempt`, `idempotency_key`,
  `status`, `retry_of`, `replay_of`, and the measurement windows. Two runs that
  found the same thing at different moments, or under different execution
  status, do **not** share this digest. Decisions reference this one.

Layering them this way means `evidence_digest` transitively covers the result
subset without duplicating its bytes, and that substituting any occurrence fact
— a later `finished_at`, an `executed` status over a `replayed` one, a rewritten
retry parent — changes `evidence_digest` even when the tool output is preserved
byte for byte.

##### Evidence field classification

| Field | Class | Why |
|---|---|---|
| `schema` | bound | a version change changes semantics |
| `id` | occurrence-only | record identity, read by nothing |
| `result_digest` | bound | anchors the result subset into the payload |
| `evidence_digest` | computed | excluded from the bytes it digests |
| `subject.*` | bound | what the evidence is about |
| `producer.tool`, `producer.version` | bound | pin drift is a named finding |
| `observer.actor_identity`, `observer_identity`, `execution_identity`, `workload_identity` | bound | the four inputs the independence derivation consumes (§7) |
| `observer.claimed_level` | bound | a claim above the derived level is a named finding |
| `observer.independence.*` | bound | derived level and the caps that bound it |
| `policy.id`, `policy.version`, `policy.config_digests` | bound | what was actually applied |
| `execution.finished_at` | **bound** | freshness is evaluated against it, and promotion requires `evaluation.as_of >= finished_at` |
| `execution.executed_count`, `skipped_count` | bound | vacuity guard and coverage |
| `execution.status` | **bound** | only `executed` establishes freshness |
| `execution.idempotency_key` | **bound** | deduplication, `executed_count` counting, and `CONTENDED` |
| `execution.call_id` | **bound** | the identity `retry_of` and `replay_of` point at; unbound, the lineage graph is rewritable |
| `execution.attempt`, `retry_of`, `replay_of` | **bound** | malformed lineage derives `INCONCLUSIVE` (§6.2.2) |
| `execution.step_id` | bound | part of the same-logical-effect test for a retry |
| `measurements[].*` | bound | every field is a comparability or budget input (§6.2.1) |
| `coverage.*` | bound | uninspected surfaces are charged to the verdict |
| `outcome`, `findings` | bound | the result itself |
| `references` | bound | no rule reads them, but an auditor follows them, and nothing is gained by leaving the links a decision was built on mutable |
| `execution.started_at`, `recorded_at`, `latency_ms` | occurrence-only | no rule reads them. A latency *budget* is not an exception: §6.2.1 requires any quantity compared against a threshold to appear in `measurements`, which is bound |
| `execution.workflow_id`, `workflow_run_id` | occurrence-only | audit context; the same-effect test uses `idempotency_key` and `step_id` |
| emitting process identity | occurrence-only | recorded for audit; the evaluator's own context is derived, not read from the record (§6.3.2) |

##### Decision field classification

| Field | Class | Why |
|---|---|---|
| `schema` | bound | as above |
| `id` | occurrence-only | record identity |
| `content_digest` | computed | excluded from the bytes it digests |
| subject digest, policy digest, config digests | bound | what was decided about, under what |
| referenced `evidence_digest`s, sorted | bound | the evidence actually evaluated |
| derived verdict, reason codes (sorted), uninspected surfaces | bound | the decision |
| derived independence level and its caps | bound | eligibility |
| `owner` | bound | who the decision is charged to |
| freshness and expiry *policy window* | bound | the absolute expiry instant is derived from this window and `as_of`, so it is not stored separately |
| `evaluation.*` (§6.3.2) | bound | the semantic time input |
| `claimed_source`, `claimed_skew_bound_s` | bound | recorded claims; a claim disagreeing with the derivation is a named finding |
| modifiers derived at evaluation (`CONTENDED`, `WAIVED`, `NO_APPROVER`, `UNSIGNED`, `DRIFT`, `PROVISIONAL`, `EXPIRING`) | bound | they change whether the decision gates |
| lifecycle (`DRAFTED`, `ACTIVE`, `HELD`, `EXPIRED`, `SUPERSEDED`) | **outside the payload** | mutable state recorded beside the decision. Superseding a decision must not alter the bytes it was verified under |
| generation time, emitting process identity, request ID | occurrence-only | what happened when it was produced |

##### Counterexample matrix

The partition is only defensible if it survives the cases that broke the last
one. Each row is two records differing in exactly one respect.

| Two records differ in | `result_digest` | `evidence_digest` | Consequence |
|---|---|---|---|
| nothing but record `id`, `recorded_at` and `latency_ms` — one run, ingested twice | same | same | recognized as the same evidence; either record may be referenced |
| `finished_at`, at one fixed `evaluation.as_of` | same | **differs** | one is fresh and one is stale, and the decision names which record it evaluated. The two can no longer collide behind one digest |
| `status: executed` vs `replayed` | same | **differs** | only the executed record establishes freshness |
| `idempotency_key` | same | **differs** | two intended effects, each counted once |
| `attempt: 1` vs `attempt: 2` with valid `retry_of` | same | **differs** | one idempotency key still counts once toward `executed_count` |
| `outcome`, under one `idempotency_key` | differs | differs | `CONTENDED`; promotion blocked until adjudicated, with no retry-to-green allowance |
| `retry_of` repointed to another call | same | **differs** | lineage is bound, so the parent cannot be swapped silently |
| `evaluation.as_of` moved by one second | n/a | n/a (decision) | different decision payload, different `content_digest`, verification replay fails |
| tool re-run over an unchanged tree at a later time | same | **differs** | this is the honest case, and it is now statable: the tool found the same thing at a different moment |

The last row is the one the old model could not express. It required two such
runs to share a digest while also admitting they could yield different freshness
verdicts — a contradiction. Splitting the digests resolves it without weakening
either property.

##### Canonical serialization and the determinism requirement

**Canonical serialization is RFC 8785 (JSON Canonicalization Scheme).** The
earlier wording — UTF-8 JSON, sorted keys, no insignificant whitespace — left
string escaping and number formatting ambiguous, so `{"n":1.0,"text":"é"}` and
its escaped, integer-valued equivalent both satisfied it and hashed differently.
JCS fixes key ordering, string escaping and number serialization exactly.

One JCS property is worth stating plainly rather than assuming the opposite: it
performs **no Unicode normalization**. Parsed string data is preserved as-is, so
two spellings of the same text differing only in normalization form remain
different bytes and produce different digests. Canonicalization is not
normalization. Producers are responsible for emitting consistent Unicode; the
engine will not silently reconcile NFC and NFD on their behalf.

Three additions on top of JCS: arrays are ordered by a rule stated in the schema rather than by discovery
order; non-finite numbers (`NaN`, `±Infinity`) are prohibited in a canonical
payload, consistent with §6.2.1's domain guard; and every digest field —
`content_digest`, `evidence_digest`, `result_digest` — is `sha256` over the
canonical bytes of the set it covers *excluding that digest field itself*, since
a field cannot contain a digest of itself.

**The determinism requirement, stated so it can be met:** for the same evidence
set identified by `evidence_digest`, the same policy digest, the same resolved
config digests, the same subject digest and the same `evaluation` block, the
canonical decision payload — and therefore its `content_digest` — is
byte-identical across runs, machines and processes. Occurrence-only fields
differ on every run by design, and a difference confined to them is not a
determinism failure. A difference in the payload is, and it is a defect in the
engine rather than an acceptable variation.

Determinism is a property of **deciding**, not of producing evidence. Re-running
an adapter over an unchanged tree is a new execution: it yields the same
`result_digest` and a different `evidence_digest`, because the second run
genuinely happened later. That is not a determinism failure either, and the two
statements are tested separately (§18.1).

One consequence is worth stating outright. Both the freshness *outcome* and the
`evaluation` block it was computed from live in the payload, so the same
evidence evaluated at two different instants yields two payloads that differ —
correctly, because the decision genuinely differs; reproducibly, because the
difference is driven by a recorded input rather than by when someone happened to
run the command; and detectably, because that input is digested rather than
asserted beside the digest.

#### 6.3.2 The evaluation context and time authority

```yaml
evaluation:
  as_of: RFC3339 instant that freshness and expiry are computed against
  source: protected_runner_clock | engine_clock | recorded_replay | caller_override
  mode: promotion | replay | historical | test
  skew_bound_s: the clock-skew tolerance resolved from the bound policy
```

Freshness is computed against `evaluation.as_of` rather than against the clock
at the moment of evaluation, because without a stable input the engine is not a
function at all: the same evidence, policy, config and subject would yield one
payload before an expiry boundary and another after it.

But a stable input that an arbitrary caller supplies is worse than no input. If
the instant governing freshness sits outside the digested bytes, a caller can
backdate it until stale evidence falls inside its window, or edit it afterwards,
and the decision's `content_digest` still verifies — forging precisely the
property the field was added to establish. The whole `evaluation` block is
therefore **inside the canonical payload**: moving `as_of` by one second changes
the payload, changes `content_digest`, and fails verification. Backdating stops
being undetectable and becomes a different decision.

##### Binding is not enough: the block is derived, not accepted

Putting a field inside a digest proves only that its text was not altered after
the fact. It does not make the claim true. An attacker who edits a stored
decision and recomputes every digest consistently produces a perfectly
self-consistent document; if `source` were accepted as written, that document
would label itself `engine_clock`, set `skew_bound_s` to a year, and verify.

So the evaluation context follows the same trust boundary §7 draws between
`claimed_level` and derived independence, applied to time. **The engine derives
every field of `evaluation`. It accepts none of them.**

A decision request may carry at most two things about time: the `mode` it is
asking for, and — in `replay`, `historical` or `test` mode only — a
`requested_as_of`. A request that supplies `source` or `skew_bound_s` has the
value recorded as `claimed_source` or `claimed_skew_bound_s`, which never gates;
a claim that disagrees with the derivation is a named finding, exactly as a
claimed independence level above the derived level is.

| Field | Derived from | Never |
|---|---|---|
| `source` | the evaluator's own execution context at evaluation time | read from the request or from the stored document |
| `as_of` | the instant that derived `source` supplies | supplied by a caller in `promotion` mode |
| `mode` | the requested mode, admitted only if the derived `source` supports it | escalated to `promotion` by the request alone, and never silently demoted — a `promotion` request that cannot derive a promoting source derives `INCONCLUSIVE` with a named reason rather than quietly becoming a `historical` decision |
| `skew_bound_s` | resolution of the policy and config already bound by the payload's own policy digest | taken from the request or from the document being evaluated |

Each `source` value is derivable only under one condition:

- **`protected_runner_clock`** — the evaluator's own `execution_identity`
  verifies as `protected_ci` or `isolated` with a verified `oidc_issuer` and
  `oidc_subject`, and the instant is attested by *that* runner. The clock proof
  is bound to the runner identity; an unverified or unbound claim is not this
  value.
- **`engine_clock`** — the engine itself read the clock in-process during this
  evaluation.
- **`recorded_replay`** — the instant was read from a recorded payload being
  re-evaluated (§6.3.3).
- **`caller_override`** — anything a caller supplied, whatever the caller called
  it. This is the derivation's floor: an unprovable claim does not fail to a
  higher value.

The remaining rules:

- A **promotion** decision — anything gating a merge or release — requires a
  *derived* `source` of `protected_runner_clock` or `engine_clock`. Because the
  value is derived from where the evaluation actually ran, an evaluation run
  anywhere else cannot produce it, no matter what the request or the stored
  document asserts.
- `as_of` must sit within `skew_bound_s` of the producing runner's clock, and
  must not precede the `finished_at` of the evidence it evaluates, since
  evidence cannot be evaluated before it existed. `finished_at` is bound
  (§6.3.1), so that comparison cannot be moved by editing the evidence record.
- `skew_bound_s` in the payload must equal the value resolved from the policy
  digest in the same payload. A mismatch derives `INCONCLUSIVE` with a
  policy-mismatch reason code. Inflating the tolerance therefore requires
  changing the policy itself, which changes the policy digest, which changes the
  payload and voids the claim that the decision enforced the policy it names.
- `caller_override` is admissible **only** in `replay`, `historical` or `test`
  mode, and a decision in any of those modes can never authorize a current
  promotion. `mode` is in the payload, so a test-mode decision cannot later be
  presented as a production one without changing its digest.

A decision whose evaluation context fails any of these conditions is
`INCONCLUSIVE`. It is never `PASS`, and the failure is named rather than
silently corrected to the current time.

`engine_clock` deserves one clarification, because on its own it looks weaker
than it is. It records that the engine read its own clock in-process. It is not
a claim that the clock is *accurate*, and on a developer machine it plainly is
not a trusted reading — but an attacker who controls that machine controls the
engine too, so no time field could help there. Time authority does not carry
promotion eligibility by itself: a locally produced decision is capped at
independence level 2 by §7 regardless of its clock, so where policy requires
level 3 or above, `engine_clock` cannot satisfy it. The two controls compose,
and neither is written assuming the other will cover it.

The property that matters is that these are **refusals to derive, not digest
checks**. A digest catches a value changed after the fact. Only derivation
catches a value that was never true. The planted negatives of §15.1 are written
to exercise the second case specifically: the attacker is permitted to recompute
every digest consistently, and the engine must still refuse.

#### 6.3.3 Verification replay versus re-evaluation

v0.5 required a replay to reproduce the original payload digest exactly *and* to
carry `mode: replay` with `source: recorded_replay`. Since `mode` and `source`
are payload fields, those requirements contradict each other: the replay payload
necessarily differs, so the equality could never hold. The error was treating
two operations as one. They are two, and only one of them is an equality claim.

**Verification replay is not a decision.** It is a check. `sdlc verify
<decision-id>` loads a recorded decision, loads the evidence records its
`evidence_digest`s name, recomputes the canonical decision payload from those
inputs using the recorded `evaluation` block **verbatim — its original `mode`,
`source`, `as_of` and `skew_bound_s`** — and asserts byte equality with the
recorded payload and its `content_digest`. It authors no evaluation context of
its own, so no `mode: replay` value ever enters the bytes under comparison. That
a verification is running is a property of the operation, recorded in the
verification's own result, not in the payload being tested. Verification never
reads a clock, never re-runs an adapter and never emits a decision. Its outcomes
are `verified`, `digest_mismatch` or `inputs_unavailable`, and a recorded
decision that does not verify is `INCONCLUSIVE` for any onward use.

What verification proves is bounded, and the boundary is worth stating so it is
not over-read. `verified` means *this decision's payload is exactly what these
recorded inputs produce*. It does not re-run the derivations of §6.3.2: it does
not re-resolve `skew_bound_s` against the policy, and it cannot re-derive
`source`, because the execution context that derived it no longer exists. Those
are decision-time controls and verification is not a substitute for them. The
division is deliberate — derivation establishes that a claim was true when it
was made, verification establishes that nothing has moved since.

**Re-evaluation is a decision.** Deciding again over the same evidence — under
`mode: replay`, `historical` or `test` — produces a new decision with its own
payload, its own evaluation context and its own `content_digest`. It makes no
equality claim and is not compared against the original. It can never authorize
a promotion.

The two answer different questions. Verification asks *was this decision
computed honestly from these inputs?* Re-evaluation asks *what would we decide
about this evidence now, or under these stated conditions?* Only the first is an
equality claim; only the second produces a new record. Step replay (§6.2.2) is a
third thing again, at the evidence layer, and never refreshes freshness.

### 6.4 `sdlc/lane-profile@1`

A profile describes a repository or work type without hard-coding a universal
G1-to-G6 sequence:

- profile ID, version and owner;
- repository/work-type selectors;
- declared assurance surfaces;
- required and optional adapters;
- a gate DAG with prerequisites and enforcement points;
- per-check latency and freshness budgets;
- required independence levels;
- role and signer eligibility rules;
- waiver policy;
- maturity evidence requirements;
- theme pack selection, which is presentation-only.

**No lane profile is required for the ACP-0 pilot.** ACP-0 resolves a single
hard-wired policy against one repository; profile resolution, the gate DAG and
waiver logic begin at ACP-2, and this section describes the shape they take when
they arrive. `foundation` and `application` are the first two to build then, and
`service`, `data`, `agentic` and `regulated` follow as real repositories demand
them.

## 7. Independence model

Independence is derived, never declared. An adapter may state what it believes
its independence to be; that statement is recorded as `claimed_level` and has no
gating effect. The engine computes `observer.independence.level` from four
verified inputs, and the level is the minimum of what those inputs support.

| Level | Required actor identity | Required observer identity | Required execution identity | Required workload identity |
|---|---|---|---|---|
| 0 | any | any, or same as actor | any | any |
| 1 | any | distinct from actor | harness hook outside the observed tool call | policy digest recorded |
| 2 | verified (token or better) | distinct, verified | separate runner identity; `actor_can_mutate_config: false` | policy + config digests recorded; if this change edits the success-definition surface, rule 4 governs |
| 3 | verified (`signed_commit` or `oidc`) | `oidc`, protected CI | `runner: protected_ci` with OIDC issuer and subject | policy digest commit-bound; the workload was not authored by this change, or was and carries a distinct CODEOWNER approval (rule 4); fixture digest with current proof-of-fire |
| 4 | `attested` | `attested` | `runner: isolated` with environment attestation | all of level 3, with the workload **not** authored by this change — approval does not substitute at this level — plus an attested workload digest |

The derivation is a floor test, evaluated in order, and the result is capped by
whichever rule bites first:

1. Observer identity equal to actor identity caps the level at 0.
2. `verification: unverified` on the observer caps at 1.
3. `actor_can_mutate_config: true` caps at 1 — an observer whose configuration
   the author can rewrite is not independent of the author.
4. A change that also edits the **success-definition surface** — tests, policy,
   configuration, thresholds, baselines, adapters, fixtures, or the CI workflow
   the check runs under — caps the level at 2. A distinct CODEOWNER approval of
   that same change lifts the cap to 3, and no further. Segregation of duties is
   the control that levels up to 3 rest on, so an independent human ratifying
   the new goalposts restores eligibility there; level 4 asserts an attested
   workload, which no human approval can stand in for. This rule is the only
   place the question is decided.
5. Absent or expired proof-of-fire on the producing adapter caps at 2.
6. Missing OIDC issuer/subject caps at 2; `runner: local` or `self_hosted_ci`
   caps at 2.
7. Missing environment attestation caps at 3.

Every cap that fired is recorded in `constrained_by` with a reason code, so a
level is always explainable as "level N because rules X and Y capped it."

Rules:

- An agent identity is never eligible to sign a human approval gate.
- The author of a change cannot be the sole verifier where the profile requires
  segregation of duties.
- Changes to the success-definition surface are governed by cap rule 4 above,
  which names the full surface and the one approval that lifts it. This list
  states no separate condition, so the single source of truth stays single.
- The verifier records how it observed process, file and network behaviour.
  Claude/Codex hooks alone must not be described as OS-level runtime evidence.
- A gate with no eligible approver is `HELD + NO_APPROVER`; it never auto-clears.
- A derived level is recomputed on every evaluation. It is never cached across a
  policy, config or identity change.
- Adapters do not implement the derivation. One engine rule set computes it, so
  a new adapter cannot mint its own independence.
- **Current repository ceiling.** KP_SDLC has one usable GitHub identity, so
  `required_approving_review_count` is 0 and `require_code_owner_reviews` is
  false on `main`. Review-based gates in this repository therefore derive at
  most level 2 (rule 1: no observer identity distinct from the actor), regardless
  of how the review was conducted. ACP-3's exit criteria cannot be honestly
  demonstrated here until MR-1 lands.
- **Protected CI is necessary for level 3, not sufficient.** That a check ran on
  a protected runner says where it executed, not whether it was independent of
  the author. If the same change also modified the policy, configuration,
  workflow or fixture the check runs under, rule 4 governs: the level is capped
  at 2, and only a distinct CODEOWNER approval of that change lifts it to 3.
  Otherwise the author moves the goalposts and a trusted machine clears them.
  This bullet states no condition of its own — it points at rule 4, so there is
  exactly one place the workload question is answered.

## 8. Adapter contract

Every telemetry or evidence adapter declares:

- adapter ID and version;
- supported canonical capabilities or evidence surfaces;
- discovery/probe method;
- required configuration and permissions;
- output schema version;
- freshness rule;
- the identity and proof inputs the engine's derivation consumes — actor,
  observer, execution and workload identities, each with the evidence for its
  `verification` word — and optionally a `claimed_level`, which is recorded and
  never gates. An adapter does not declare its own independence: it declares
  what the engine needs in order to derive it (§7);
- nothing about evaluation time. An adapter reports `finished_at` for the run it
  observed; it never supplies `evaluation.source`, `evaluation.as_of` or
  `skew_bound_s`, which the engine derives at evaluation time (§6.3.2). An
  adapter that emits them has them recorded as claims that never gate;
- privacy classification;
- clean fixture and planted failing fixture;
- last proof-of-fire result;
- failure behaviour;
- optional upstream tool/version pin.

An adapter is `bound` only after its planted fixture has been caught. Missing or
expired proof-of-fire makes the adapter inconclusive. Pin drift is a named
finding and cannot retain a new passing decision until revalidated.

**ACP-0 ships exactly two adapters: Quality Gate and Cathedral Keeper.** Both
are evidence adapters. No telemetry adapter ships in the pilot, so nothing in
this section authorizes one.

The list below is ACP-1's target set — what the registry is expected to cover
once the protocol has been extracted from the two adapters that already exist,
rather than designed ahead of them:

- G1, G2, G4, G5 and G6 artifacts;
- Git worktrees and repository state;
- GitHub Actions artifacts and protected-check state.

CtxPack is deliberately **not** in that set. Its adapter, its sanitization
contract and its health projection all belong to ACP-7, behind the §10 gap; no
part of CtxPack is an ACP-1 deliverable.

Telemetry adapters — Claude Code hooks, Codex, and a generic OpenTelemetry
ingestion option — belong to ACP-6 and follow the `sdlc/event@1` implementation,
which the pilot defers entirely. When they arrive, unknown harness events remain
visible as `unknown`, and adding a mapping must not require a dashboard schema
change. The pilot that unlocks any of this is the ACP-0 **evidence** pilot of
§18; there is no Claude telemetry pilot in the authorized scope.

## 9. Attestation mapping

The internal decision is authoritative inside KP_SDLC. Exporters provide
interoperability:

| Information | Preferred external representation |
|---|---|
| Generic verification decision | in-toto Simple Verification Result v0.2 |
| Per-check execution and configuration | in-toto Test Result v0.1 |
| Sufficiently observed process/network/file trace | in-toto Runtime Trace v0.1 |
| SLSA-level verification | SLSA Verification Summary v1, only when a SLSA level is actually asserted |
| Claims, evidence and conformance | CycloneDX Attestations where the semantics fit |
| Authentication | DSSE envelope; optional Sigstore keyless signing in protected CI |

Attestations are stored beside the artifact or in the repository's configured
attestation store. The receipt records whether a transparency log was used.
Signature verification and policy-semantic verification are separate results.
Using a standard envelope does not make KP_SDLC's adequacy semantics standard.

The first exporter may emit unsigned in-toto Statements for deterministic local
tests. It must not claim cryptographic integrity. Signing becomes available only
under an identity and trust-root configuration.

## 10. CtxPack and context management

CtxPack remains the sole system of record for memory. The control plane records:

- checkpoint and per-session archive availability;
- pre-compaction capture;
- session-start gist injection;
- stop/session-end finalization;
- structured recall availability and usage;
- conflicts, lint state and exact-literal fidelity;
- structured ledger reads versus transcript fallbacks;
- context activity pressure and checkpoint history;
- exact provider context utilization only when the harness exposes it.

The decision or attestation may reference a sanitized checkpoint digest and
lifecycle state. It must not embed raw memory, prompts or transcripts.

Memory scopes are explicit:

- `local`: may contain machine/session identifiers; gitignored;
- `team`: sanitized, access-controlled operational memory;
- `public`: explicitly exported, leak-scanned, no personal identifiers, absolute
  paths, secrets or raw conversation content.

Scope is declared, not inferred from file location. An artifact's scope is a
property of its content and its sanitization guarantee; being inside or outside
the repository proves nothing about either.

This repository is currently a live exception worth naming rather than
overwriting. `.gitignore` deliberately un-ignores `.claude/ctx/`, so the CtxPack
ledger is committed by design — it is `team`-scope by location while its content
carries no sanitization guarantee, which is `local`-scope content. That gap is
ACP-7's first concrete task: give the committed ledger a `team`-scope
sanitization contract with privacy canaries, or move it behind an ignore rule.
Until one of those happens, the control plane must not describe the committed
ledger as sanitized team memory.

The installer creates ignore rules for any artifact whose declared scope is
`local` before the first capture.

## 11. Observatory and Keel experience

Observatory exposes read models, not a second domain model:

### 11.1 Live scene

- Agents and subagents mapped to tasks, sessions and worktrees.
- Canonical actions mapped to theme animations.
- Explicit distinction between observed, supported-but-not-observed and
  unavailable capabilities.
- Stale sessions visibly expire rather than remaining active.
- Fun reactions such as mistakes or loop detection are downstream of a named
  finding and confidence classification.

### 11.2 Attention queue

Rank initially by:

1. `NO_APPROVER` or policy-owner concentration;
2. `VOID` harness faults;
3. `BLOCKED` findings with concrete evidence;
4. `INCONCLUSIVE`, drift or stale evidence;
5. person-held actions;
6. agent-held actions.

Every queue row opens the decision, proof, provenance and allowed exits. At
least one self-serve exit remains available, but a self-serve exit never writes
a pass or waiver.

### 11.3 Work graph

Show task dependencies, agent ownership, declared and observed write sets,
contention, receipts and completion evidence. Overlapping write sets create a
coordination finding; they do not automatically delete or move a worktree.

### 11.4 Library

Show lane profiles, packs, adapters, pins, proof-of-fire status, owners, expiry,
gate eligibility and current coverage.

### 11.5 Theme boundary

The default product ships an original professional theme and at least one
original playful theme. Third-party or copyrighted character themes are external
theme packs and are not required for product operation. Theme packs consume only
documented view-model fields.

## 12. Operational measurement and maturity

Maturity remains multidimensional. Initial dimensions are:

- observability;
- memory discipline;
- quality governance;
- behavioural evaluation;
- parallel coordination;
- evidence adequacy;
- verifier independence;
- security readiness;
- production readiness.

Each level requires named evidence. A dimension cannot increase because more
events, agents, code or tokens were observed. History records only a changed
evidence fingerprint, with explicit positive and negative deltas.

Operational measures:

- declared and inspected surface coverage;
- checks executed and skipped;
- p50/p95 check latency and developer wait time by check class;
- freshness failures and pin drift;
- adjudicated true/false positives with corpus size and protocol;
- findings per engagement/week and action rate;
- escaped-defect recurrence;
- catch and reach rates on a frozen internal escape corpus, with intervals and
  work-type stratification;
- rework hours associated with actual escapes;
- waiver count, age, owner and expiry;
- eligible-signer concentration and waiting time;
- compaction/handoff completeness and structured-recall usage.

The default false-positive target and latency SLO are policy settings, not
universal facts. `not useful` is collected separately from `false positive`.
A mandatory control that exceeds its budget becomes degraded/inconclusive and
requires owner action; it does not silently switch itself off.

## 13. Security and privacy requirements

- Local event and maturity ledgers use append-only writes and restrictive file
  permissions where the platform supports them.
- Raw tool input/output, prompts and transcripts are opt-in and prohibited from
  standard attestations.
- Adapter inputs are untrusted and size-bounded.
- Paths, session IDs and usernames are removed from team/public exports.
- Signing keys are never stored in the repository. Protected CI uses short-lived
  identity where available.
- Policy, configuration and adapter digests are included in evidence.
- Missing attestations fail closed where policy requires them; signatures cannot
  prove that a required attestation was not omitted.
- The Structural Floor protects the full success-definition surface: gate
  engines, rules, schemas, policies, baselines, adapter bindings, lane profiles,
  assurance code and CI workflows.
- Today `protected-surface.txt` covers the QG engine and config, the ratchet
  baseline and its runtime overrides, the CK config, the floor mechanism itself,
  `.github/workflows/`, the shipped CI templates and the agent-session machinery.
  Each remaining surface joins it in the PR that first creates it, under the
  package that owns it: schemas at ACP-0, adapter bindings at ACP-1, lane
  profiles at ACP-2. This specification does not pre-register paths that do not
  exist, because an unresolvable CODEOWNERS entry is a floor that protects
  nothing.
- Branch protection, CODEOWNERS approval and stale-approval dismissal are owner
  controls. No prompt substitutes for them.

## 14. CLI and machine interfaces

### 14.1 CLI

```text
sdlc init [--profile ID] [--dry-run]
sdlc check [--profile ID] [--changed|--all] [--json]
sdlc status [--upstream ENGINE_ROOT] [--json]
sdlc explain <object-id> [--evidence|--provenance|--coverage]
sdlc verify <decision-id> [--json]
sdlc observatory [--bind 127.0.0.1] [--port PORT]
sdlc maturity [--record] [--json]
sdlc receipt export <decision-id> [--format in-toto] [--sign]
sdlc adapter list|probe|prove <adapter-id>
```

Only `init`, `bootstrap` and `status` exist today; `status` landed with PR #28.
The rest of the surface above is target design, and this specification does not
document it as shipped:

| Command | State |
|---|---|
| `sdlc init`, `sdlc bootstrap`, `sdlc status` | shipped on `main` |
| `sdlc check`, `sdlc explain`, `sdlc verify` | ACP-0 — the first slice |
| `sdlc adapter list\|probe\|prove` | ACP-1 |
| `sdlc observatory` | ACP-5 |
| `sdlc maturity`, `sdlc receipt export` | ACP-8 / ACP-4 |

Existing component CLIs remain available during migration. The unified CLI
delegates to them; it does not duplicate gate logic.

### 14.2 Local API

Read-only endpoints:

- `GET /api/snapshot`
- `GET /api/events?after=<cursor>`
- `GET /api/queue`
- `GET /api/objects/<id>`
- `GET /api/graph/<id>`
- `GET /api/library`
- `GET /api/maturity`

The initial server binds only to localhost. Remote deployment requires a separate
authentication, tenancy and authorization design.

## 15. Testing strategy

Every work package includes:

1. contract/schema positive and negative fixtures;
2. a clean fixture and a planted failing fixture;
3. an anti-vacuous assertion proving something was inspected;
4. the planted-negative matrix below, in full;
5. privacy canaries proving sensitive content cannot enter standard output;
6. deterministic verdict derivation, and verification replay (§6.3.3) over a
   recorded decision;
7. exact subject/config/policy digest binding, plus a conformance test that
   every schema field's declared class matches the tables of §6.3.1;
8. a test that an agent/self-reported identity cannot satisfy an independent
   gate, and that a self-reported time authority cannot satisfy a promotion;
9. targeted component tests, then the full blocking CI suite;
10. a fresh-context adversarial review before merge.

### 15.1 Planted-negative matrix

Every adapter and every gate is tested against all ten planted conditions, and
each must derive the stated verdict. A test suite that omits a row does not
qualify the component for an enforcement claim.

The last three rows share a rule that makes them harder than they look: **the
attacker is allowed to recompute every digest.** Each of those fixtures is
internally consistent — `result_digest`, `evidence_digest` and `content_digest`
all recompute correctly over the tampered content. A test that passes only
because a digest failed to match has not exercised the control; the engine must
refuse because the claim cannot be *derived* or *resolved*, not because the
bytes disagree. The `tampered record` row above them is the opposite case and is
kept deliberately: there, the digest mismatch itself is the control under test.

| Planted condition | Fixture | Required verdict | Must never derive |
|---|---|---|---|
| Missing evidence | required artifact absent | `INCONCLUSIVE`, uninspected surface named | `PASS`, `SKIPPED_NAMED` |
| Malformed evidence | truncated/invalid artifact, wrong schema version | `INCONCLUSIVE` with a parse reason code | `PASS`, silent skip, crash |
| Zero execution | artifact reports `passed: true` with `executed_count: 0` | `VOID` | `PASS`, `PASS_WITH_DEBT` |
| Stale evidence | valid artifact bound to a prior commit or outside the freshness window | `INCONCLUSIVE` with a staleness reason code | `PASS` |
| Inadmissible observer | valid, fresh artifact whose derived independence is below the policy or profile requirement | `INCONCLUSIVE` with an independence reason code | `PASS` |
| Backdated evaluation | stale evidence plus an `evaluation.as_of` moved backwards to bring it inside its window; and a promotion presented with `source: caller_override` or a non-`promotion` mode | `INCONCLUSIVE` with an evaluation-time reason code | `PASS` — a caller-supplied instant can never freshen evidence |
| Tampered record | a recorded `content_digest` that does not recompute over the canonical payload, and an occurrence-only field edited to disagree with the payload it echoes | `INCONCLUSIVE` with a tamper reason code | `PASS`, silent repair to the current time |
| Mutated occurrence fact | four fixtures, each preserving the tool result byte for byte so `result_digest` is unchanged, while mutating one of `finished_at`, `status`, `idempotency_key`, or retry/replay lineage; all digests recomputed | `INCONCLUSIVE` — the decision that referenced the original `evidence_digest` no longer resolves, and a promotion rebuilt on the mutated record fails its own checks | `PASS` on the strength of an unchanged `result_digest` |
| Forged time authority | a request and a stored decision asserting `source: engine_clock` or `protected_runner_clock`, evaluated outside that execution context, with every digest recomputed consistently | `INCONCLUSIVE` with an underivable-source reason code; the assertion is recorded as `claimed_source` | `PASS`, or derivation of any source above `caller_override` |
| Inflated skew bound | `skew_bound_s` in the payload exceeding the value the payload's own policy digest resolves to, with every digest recomputed | `INCONCLUSIVE` with a policy-mismatch reason code | `PASS`, evaluation against the inflated tolerance |

Four properties are asserted alongside the matrix. A malformed artifact never
crashes the run — it is counted and surfaced. The planted failing fixture is
caught with a non-zero execution count, so the negative test is itself
non-vacuous. Altering a recorded `evaluation.as_of` by any amount changes the
payload digest and fails verification, which is asserted directly rather than
inferred from the field's position in the schema: the backdating test moves the
instant, recomputes, and requires both the digest mismatch and the refusal. And
the last three rows are asserted to fail on **derivation or resolution**, not on
digest comparison — each test proves the document verified cleanly and was
refused anyway.

For adapter proof-of-fire, CI must run both the clean and planted fixtures. A
test that merely inspects source text is insufficient for an enforcement claim.

## 16. Delivery backlog

### MR-0 — Restore a trustworthy main branch — **COMPLETE (2026-09-07)**

**Priority:** P0  
**Outcome:** achieved. At completion `main` was `afa2210` with fresh passing
`quality` and `structural-floor` runs and no pull request open. Both are
mutable facts stated as of 2026-09-07; this specification's own PR opened
immediately afterwards, and the current head is whatever `main` says it is.

The v0.1 merge sequence is superseded. What actually happened:

| PR | Disposition | Commit |
|---|---|---|
| #26 | Merged after fixing non-vacuous pytest command enforcement | `d7f4d9b` |
| #28 | Merged after fixing malformed-manifest crashes and correcting integrity claims | `ebb32c7` |
| #31 | Merged — reviewer and CI operations hardening | `afa2210` |
| #23 | Closed — G6 compared untyped quantities; superseded by §6.2.1 | — |
| #27 | Closed — measurement substrate ahead of a decided protocol | — |
| #29 | Closed — cost meter conceptually incomplete (pricing provenance) | — |
| #30 | Closed — external-framework ADR, not on the critical path | — |
| #25 | Remains closed — #26 superseded its no-op-test half | — |

Closure was a judgement about interfaces, not about effort. The tests inside
#23, #27 and #29 are salvageable and should be recovered when the contracts they
were written against exist; their current interfaces should not be revived.

Hardening delivered with #31:

- synchronized root `AGENTS.md` / `CLAUDE.md` reviewer contracts, with a
  blocking drift test so the two cannot diverge;
- reduced workflow permissions and explicit job timeouts;
- reviewer PR comments made marker-based updates rather than repeated posts;
- branch protection on `main`: strict required checks (`Mechanical guardrails`,
  `Process guardrails`, `protected-surface-sync`), stale-approval dismissal,
  admin enforcement, force-push and deletion disabled, conversation resolution
  required, merge commits standardized and branches auto-deleted.

**Residual limitation — carried to MR-1, not closed.** The repository has one
usable GitHub identity, so `required_approving_review_count` is 0 and
`require_code_owner_reviews` is false. Independent review is currently enforced
by process (the operating contract in `AGENTS.md`/`CLAUDE.md`) and not by
identity. No part of this specification may describe the current arrangement as
identity-enforced segregation of duties.

### MR-1 — Identity-enforced independent review

**Priority:** P0  
**Depends on:** MR-0  
**Deliverables:** a second reviewer account or team; CODEOWNERS approval
required on `main`; `require_last_push_approval` enabled;
`required_approving_review_count` raised to at least 1.

**Exit:** a merge to `main` is impossible without an approval from an identity
other than the author's, verified by the hosting platform rather than asserted
in a document. Until this lands, §7's derivation caps review-based gates in this
repository at level 2, and ACP-3 cannot demonstrate its exit criteria here.

### ACP-0 — Contracts plus one deterministic decision on one repository

**Priority:** P0  
**Depends on:** MR-0  
**Scope:** this is the whole first slice. It is the only work package authorized
before the pilot in §18 succeeds.

**Deliverables:**

- `sdlc/evidence@1` and `sdlc/decision@1` schemas, including typed measurement
  (§6.2.1), durable execution identity (§6.2.2), the per-field classification
  and two evidence digests (§6.3.1) and derived independence (§7), with positive
  and negative fixtures;
- the independence derivation rule set as engine code with its own unit tests;
- the evaluation-context derivation (§6.3.2) in the same rule-set style: the
  engine derives `source`, `as_of`, `mode` and `skew_bound_s`, demotes any
  supplied value to a `claimed_*` field, and resolves `skew_bound_s` from the
  bound policy digest;
- evidence adapters for Quality Gate and Cathedral Keeper only;
- `sdlc check` and `sdlc explain`, producing a deterministic decision bound to
  one repository at one full commit SHA;
- `sdlc verify <decision-id>` — recompute the recorded payload from the recorded
  inputs and compare (§6.3.3). It is deliberately the smallest possible command:
  no clock, no adapter run, no new decision;
- the planted-negative matrix of §15.1 wired into blocking CI;
- migration notes recording what each adapter drops from its native artifact.

**Explicitly out of scope:** `sdlc/event@1` implementation, telemetry adapters,
Codex, eval and gate adapters beyond QG/CK, lane-profile resolution, the gate
DAG, waivers, Observatory read models, themes, attestation and signing, maturity
scoring.

**Exit:** deciding twice over the same recorded evidence set, subject digest,
policy digest, resolved config digests and `evaluation` block yields a
byte-identical canonical decision payload and `content_digest` (§6.3.1), with
differences confined to occurrence-only fields; re-running an adapter over an
unchanged tree yields the same `result_digest` and a different
`evidence_digest`; `sdlc verify` returns `verified` for a recorded decision and
`digest_mismatch` once any bound field is mutated; QG and CK artifacts are
represented without losing details a reviewer needs; every row of the
planted-negative matrix derives its required verdict, with the derivation rows
proven to refuse a fully self-consistent document; `sdlc explain` reproduces the
arithmetic behind each verdict.

> **Authorization gate.** Everything from ACP-1 onward is a sketch of intent, not
> approved work. None of it starts until the §18 pilot passes and the owner
> re-reads this backlog against what the pilot actually taught. Treating
> ACP-0..ACP-9 as a linear build programme is the specific failure mode this
> revision exists to prevent.

### ACP-1 — Evidence adapter registry

**Priority:** P1  
**Depends on:** ACP-0 **and a successful §18 pilot**  
**Deliverables:** adapter protocol, filesystem-defined discovery registry,
`sdlc adapter list|probe|prove`, adapters for G1/G2/G4/G5/G6 and GitHub Actions,
proof-of-fire metadata. QG and CK adapters ship in ACP-0 and are the reference
implementations the protocol is extracted from, not designed ahead of.

**Exit:** `sdlc adapter probe` names supported, observed, stale and unavailable
surfaces; every bound adapter catches its planted fixture.

### ACP-2 — Decision engine and unified check

**Priority:** P1  
**Depends on:** ACP-1  
**Deliverables:** lane-profile resolver, gate DAG, coverage/freshness/waiver
logic. `sdlc check` and `sdlc explain` already exist from ACP-0; this package
generalizes them from a single hard-wired policy to resolved profiles.

**Exit:** one application profile produces a deterministic decision bound to the
current commit and policy digests; an uninspected required surface cannot pass.

### ACP-3 — Independence and identity

**Priority:** P1  
**Depends on:** ACP-0, ACP-2, MR-1  
**Deliverables — the delta over ACP-0 only.** ACP-0 already ships the four
identities, the derivation rule set and the derived level; this package does not
rebuild them. It adds: approval-gate eligibility (which identities may sign
what), the author-versus-verifier comparison across a change rather than a
single evidence record, `NO_APPROVER` and signer-concentration findings, and
identity resolution against the hosting platform rather than the local
environment.

**Exit:** a self-reported agent receipt cannot satisfy a level-3 gate; protected
CI can; no eligible signer produces `HELD + NO_APPROVER`. The review-based half
of this exit cannot be demonstrated in KP_SDLC until MR-1 lands.

### ACP-4 — Standard attestation export

**Priority:** P1  
**Depends on:** ACP-2, ACP-3  
**Deliverables:** in-toto Statement/SVR exporter, Test Result references,
conditional Runtime Trace exporter, DSSE/Sigstore protected-CI integration,
offline verification test.

**Exit:** a third-party verifier validates signature, identity and subject; a KP
policy test separately validates decision semantics; deleting a required
attestation cannot yield pass.

### ACP-5 — Observatory read models and Keel UX

**Priority:** P1  
**Depends on:** ACP-0, ACP-2  
**Deliverables:** attention queue, object proof/provenance views, work graph,
library, stale-session TTL, original theme-pack interface.

**Exit:** the UI renders only canonical read models; swapping themes changes no
snapshot or verdict; every visible verdict opens its evidence and provenance.

### ACP-6 — Multi-harness and coordination telemetry

**Priority:** P1  
**Depends on:** ACP-0, ACP-5  
**Deliverables:** Codex adapter, generic OpenTelemetry ingestion option,
task-agent-worktree correlation, observed write sets, overlap/merge-risk
findings.

**Exit:** Claude and Codex sessions produce the same canonical event shape and
the same UI semantics; unknown vendor events remain visible and harmless.

### ACP-7 — Memory governance

**Priority:** P1  
**Depends on:** ACP-0  
**Deliverables:** explicit local/team/public memory scopes, CtxPack ignore and
sanitization guarantees, checkpoint digest references, handoff-completeness
evaluation, structured-recall measurement.

**Exit:** no raw memory is captured in decisions or attestations; a sanitized
export passes privacy canaries; missing compaction/finalization becomes a named
finding rather than a guessed context percentage.

### ACP-8 — Escaped-defect learning and operational measurement

**Priority:** P1  
**Depends on:** ACP-2, Eval Engine  
**Deliverables:** escaped-defect registry, RED-to-GREEN receipt, frozen internal
back-test corpus protocol, adjudicated precision/recall, reach, latency,
recurrence and rework-hour reporting.

**Exit:** at least one real escaped defect becomes a protected regression; the
system reports corpus size, method and uncertainty; no synthetic prototype
number appears as measured product evidence.

### ACP-9 — Maturity and pilot

**Priority:** P2  
**Depends on:** ACP-3, ACP-5, ACP-7, ACP-8  
**Deliverables:** expanded evidence-backed maturity dimensions, before/after
checkpoints, one application pilot, one data/analytics pilot, published failure
criteria.

**Exit:** the team can demonstrate at least one evidence-backed improvement and
one honestly reported non-improvement or regression; no composite productivity
score is produced.

## 17. Rollout gates

### Stage A — Shadow

- Read-only capture and decisions.
- No newly introduced control blocks a merge.
- Measure coverage, latency, alert volume, precision and developer action rate.
- Publish the adjudication protocol before publishing a false-positive rate.

### Stage B — Advisory

- Only checks with current proof-of-fire and acceptable operational evidence may
  become advisory.
- Developers can dispute findings; disputes are data, not automatic false
  positives.

### Stage C — Blocking

- Deterministic checks only unless a separately ratified judged-gate policy
  exists.
- Subject, policy and configuration are digest-bound.
- Required independence level is met.
- Branch protection actually requires the status.
- Rollback/waiver procedure has owner and expiry.

### Stage D — Fleet

- Only after single-repository behaviour is stable.
- Sanitized central evidence; raw events and memory remain local by default.
- Tenant isolation and authorization receive their own threat model.

## 18. Definition of done for the first product slice

The v0.1 version of this section combined live Claude observation, Codex replay,
three evidence engines, CtxPack health, attestation export, an Observatory UI,
two theme packs and maturity scoring. That is a release, not a slice, and a slice
that large cannot fail informatively — it can only be late.

The first slice is one repository, one commit, two evidence engines, one
deterministic decision.

### 18.1 The pilot

Subject: this repository, at one full commit SHA on `main`.

Done when all of the following hold:

1. `sdlc check` normalizes Quality Gate and Cathedral Keeper output for that SHA
   into `sdlc/evidence@1`, recording both `result_digest` and `evidence_digest`
   (§6.3.1) and what each adapter dropped.
2. It emits one `sdlc/decision@1` bound to that SHA, the QG/CK policy digests,
   the resolved config digests and the `evidence_digest`s it evaluated.
3. **Decision determinism.** Deciding twice over the *same recorded evidence
   set*, the same subject, policy and resolved config digests and the same
   `evaluation` block produces a byte-identical canonical decision payload and
   `content_digest`. The two-run test pins `evaluation.as_of` to a fixed value
   under `mode: test` rather than reading the clock, so an expiry boundary
   falling between the runs cannot make it flaky. Decision IDs and generation
   times still differ, and the test asserts both facts: the payloads match and
   the occurrence-only fields do not.
4. **Adapter re-run.** Running an adapter twice over an unchanged tree yields
   the same `result_digest` and a **different** `evidence_digest`, and the test
   asserts both. This is the honest case the previous contract could not state.
5. **Verification replay.** `sdlc verify <decision-id>` recomputes a recorded
   decision's payload from its recorded inputs, using its recorded `evaluation`
   block verbatim, and returns `verified`. Mutating any bound field of a
   referenced evidence record — including one that leaves `result_digest`
   unchanged — makes the same command return `digest_mismatch`, and the mutated
   record cannot support a promotion (§6.3.3).
6. Every row of the planted-negative matrix (§15.1) derives its required
   verdict: missing, malformed, zero-execution, stale, inadmissible-observer,
   backdated evaluation, tampered record, mutated occurrence fact, forged time
   authority and inflated skew bound. In particular a QG result reporting
   `passed: true` with `executed_count: 0` derives `VOID`, and the last three
   rows are proven to fail on derivation or resolution with every digest
   recomputed.
7. **Field classification is enforced.** Both schemas declare a class for every
   field, a fixture carrying an undeclared field derives `INCONCLUSIVE`, and a
   conformance test asserts that the declared classes match the normative tables
   of §6.3.1 — so the partition cannot drift out of the specification silently.
8. Independence is derived, not read: evidence arriving with `independence_level`
   pre-filled has it demoted to `claimed_level`, and a claimed level above the
   derived level is a named finding.
9. Time authority is derived, not read: a request supplying `source` or
   `skew_bound_s` has it demoted to `claimed_source` / `claimed_skew_bound_s`,
   `skew_bound_s` is resolved from the bound policy digest, and a promotion
   evaluated outside a protected runner or the engine itself cannot derive a
   promoting source (§6.3.2).
10. A locally produced decision derives at most level 2, and the reason codes
    that capped it are printed.
11. `sdlc explain <decision-id>` reproduces each verdict from the recorded
    evidence — including the arithmetic of any threshold comparison — without
    re-running QG or CK.
12. `make check` and the full blocking CI suite pass on the branch with non-zero
    execution counts.

### 18.2 Not in this slice

Deferred until the pilot has succeeded and taught us something:

| Deferred | Returns in | What would pull it forward |
|---|---|---|
| `sdlc/event@1` implementation, live Claude observation | ACP-6 | a decision that cannot be made without session telemetry |
| Codex fixture replay, multi-harness | ACP-6 | a second harness in real use |
| Eval, G1/G2/G4/G5/G6 adapters | ACP-1 | a gate whose evidence a reviewer actually needs normalized |
| G6 / NFR budgets | ACP-1 | §6.2.1 proven on a real measurement |
| Lane profiles, gate DAG, waivers | ACP-2 | a second repository with different surfaces |
| Attestation export, DSSE, Sigstore | ACP-4 | an external verifier who has asked for one |
| Observatory read models, Keel UX, themes | ACP-5 | an operator who cannot answer a question from the CLI |
| CtxPack health projection | ACP-7 | the §10 sanitization gap being closed first |
| Maturity scoring, fleet aggregation | ACP-8/9 | a second pilot repository |

Shipping any of these inside the first slice is a scope regression, not
progress.

## 19. Open owner decisions

1. Ratify or reject this specification. It is a proposal; nothing in it is
   policy until it is merged and an owner says so.
2. Ratify, reject or defer the controlled self-healing loop. Its draft ADR is
   untracked and unnumbered — trunk holds ADR 0001-0003 only, so it should be
   submitted as ADR 0004. Whatever it becomes, self-healing stays
   human-approved: §11's read-only boundary is not conditional on it.
3. Confirm `Keel` as the product name, a prototype name, or replace it.
4. Authorize MR-1, and decide whether the second reviewer identity is a person,
   a bot account or a GitHub team. Until this is settled, every independence
   claim in this repository is capped at level 2.
5. Choose the pilot repository for §18. The default is KP_SDLC itself, which is
   honest — but a control plane that has only ever been run on its own source is
   untested against a repository it did not co-evolve with.
6. Decide whether tracked specifications plus GitHub Issues become the backlog,
   retiring local-only `docs/plans/`.
7. Decide the disposition of the tests inside closed PRs #23, #27 and #29 —
   recovered against the new contracts, or written fresh.

## 20. Acceptance principle

The control plane succeeds only if it makes engineering decisions more truthful
and less expensive to understand. A beautiful dashboard over stale, self-reported
or vacuous evidence is a product failure.

## 21. Disposition of the independent reviews

Recorded so the next reader can tell which parts of v0.1 were wrong and why,
rather than inferring it from a diff.

| # | Finding | Disposition |
|---|---|---|
| 1 | BLOCKER — the first product slice is not a slice | §18 rewritten to one repository, one commit, QG/CK normalization and one deterministic decision CLI. Everything else moved to §18.2 with the demand signal that would pull it forward. |
| 2 | MAJOR — the evidence contract cannot support defensible NFRs | §6.2.1 adds typed measurement: metric ID, value, unit, statistic, workload, statistical window, environment and measurement source, with comparability and sample-floor rules. |
| 3 | MAJOR — durable execution semantics are missing | §6.2.2 and the `execution` blocks of both contracts add workflow/run/step IDs, call ID, attempt, idempotency key, and replay-versus-execution status. Replay never refreshes freshness; one idempotency key counts once. |
| 4 | MAJOR — independence cannot be self-declared | §7 rewritten as a derivation over four verified identities, with ordered cap rules and recorded reason codes. An adapter-supplied level becomes `claimed_level` and never gates. |
| 5 | MAJOR — MR-0 is superseded | MR-0 replaced with the actual disposition of #23 and #26-#31, the hardening delivered, and the residual single-identity limitation, which is carried openly into the new MR-1. |

Two further corrections were found while applying the above, both cases of the
specification asserting something trunk contradicts:

- §10 claimed no local CtxPack artifact is committed. `.gitignore` deliberately
  un-ignores `.claude/ctx/`, so the ledger is committed by design. The section
  now names the real gap — committed location, unsanitized content — and makes
  closing it ACP-7's first task.
- §13 implied the Structural Floor already protects schemas, adapter bindings and
  lane profiles. It protects the surfaces that exist today; the rest join
  `protected-surface.txt` in the PR that creates them, because a CODEOWNERS entry
  for a nonexistent path protects nothing.

### 21.1 Second round — review of `c6f3206`

The v0.2 revision was reviewed at its immutable head and blocked on five
findings. All five were localized documentation corrections; none required a
change of direction, and no new scope was added while fixing them.

| # | Finding | Disposition |
|---|---|---|
| 1 | BLOCKER — the determinism requirement was internally impossible: evidence takes a new ID and new timestamps per run, yet two runs were required to be byte-identical | §6.3.1 splits both documents into a canonical payload and an invocation envelope, defines canonical serialization and `content_digest`, and restates determinism over the payload. ACP-0's exit and §18.1 item 3 now require payload equality *and* envelope difference, so the requirement is testable in both directions. |
| 2 | MAJOR — retry and replay states disagreed: `retried` was a status, only `executed` established freshness, and a retry-to-green allowance contradicted the `CONTENDED` rule | Adopted the recommended model. `retried` is removed from both status enums; a real retry is `status: executed` with `attempt > 1` and a new `retry_of` field; `replay_of` is reserved for reproduced statuses, which never refresh freshness. The retry-to-green allowance is deleted outright — ACP-0 admits no exception. |
| 3 | MAJOR — pre-narrowing scope leaked back into the pilot via §6.4, §8 and ACP-3 | §6.4 states that no lane profile is required for ACP-0. §8 states that ACP-0 ships exactly two evidence adapters and recasts its list as ACP-1's target set, with telemetry moved to ACP-6 and the "Claude pilot" replaced by the ACP-0 evidence pilot. ACP-3 is restated as the delta over ACP-0 and demoted to P1 behind MR-1. |
| 4 | MAJOR — wording still let provenance be overstated: adapters were asked to declare an "independence level and its proof", and protected CI read as sufficient | The adapter contract now asks for the derivation's identity and proof *inputs* plus an optional `claimed_level` that never gates. §7 gains an explicit rule that protected CI is necessary but not sufficient: if the same change authored the policy, config, workflow or fixture the check ran under, rules 3 and 4 cap the level regardless of runner. |
| 5 | MINOR — mutable repository facts were stale inside the proposed source of truth | G6 is described as a closed prototype (PR #23) rather than an open PR, and MR-0's "no open pull requests" is qualified as the state at completion on 2026-09-07, with the note that this specification's own PR opened immediately afterwards. |

The reviewer's instruction not to fold the controlled self-healing feature into
ACP-0 while fixing these was followed: nothing about that loop changed here, and
it remains a separate proposal (§19.2).

### 21.2 Third round — review of `9262480`

The v0.3 revision was reviewed at its immutable head. The five earlier findings
were accepted as resolved; four contradictions remained in the revised normative
text, plus a retry-lineage gap and stale PR metadata. All corrections are
documentation-only.

| # | Finding | Disposition |
|---|---|---|
| 1 | BLOCKER — determinism was still not a well-defined function: the same inputs were required to produce an identical payload, yet were said to correctly produce a different one across a freshness boundary | Freshness now has an explicit stable input. `evaluated_as_of` is a caller-supplied instant recorded in the envelope; freshness and expiry are computed against it, never against the clock, and replay reuses the recorded value. The determinism precondition and both pilot statements name every input: subject digest, policy digest, **resolved config digests** and `evaluated_as_of`. §18.1 item 3 pins it in the two-run test so an expiry boundary between runs cannot make it flaky. **Superseded in round 4:** a caller-supplied, envelope-resident instant is forgeable, and §21.3 records the correction. |
| 2 | MAJOR — the encoding did not guarantee canonical bytes; escaping, Unicode and number formatting were open | Canonical serialization is now **RFC 8785 (JCS)**, which fixes key ordering, escaping and number serialization exactly; the cited `1.0` / `é` counter-example is closed. Three additions: schema-stated array ordering, non-finite numbers prohibited (consistent with §6.2.1), and `content_digest` computed over the payload *excluding the `content_digest` field itself*. The field is now named in both minimum document shapes. |
| 3 | MAJOR — the level-3 workload cap had conflicting escape rules across rule 4, the new protected-CI rule and the level table | Decided and encoded once: a distinct CODEOWNER approval of the same change **lifts the cap to 3 and no further**, because segregation of duties is the control levels up to 3 rest on while level 4 asserts an attested workload no approval substitutes for. Rule 4 now names configuration and the CI workflow alongside tests, policy, baselines, thresholds, adapters and fixtures. The level table rows 2-4 defer to rule 4, and the protected-CI bullet states no condition of its own. |
| 4 | MAJOR — ACP ownership was still inconsistent | One owner per surface. CtxPack is removed from §8's ACP-1 set and assigned wholly to ACP-7. §13 sequences the floor by owning package: schemas at ACP-0, adapter bindings at ACP-1, lane profiles at ACP-2. Every place the hard-wired ACP-0 policy is valid now reads "policy or profile" — the §15.1 inadmissible-observer row, the §6.2.1 sample floor, and the measurement-source admissibility rule. |
| 5 | MINOR — PR metadata stale | Title and body updated to v0.4 at the new head, with the current suite count and completed CI. No document change. |
| — | Retry lineage under-specified: `attempt > 1` required only a shared optional `step_id` | `retry_of` must now name a call recorded for the same **logical effect** — same `idempotency_key`, subject digest and producer — sharing `step_id` where one exists. The non-workflow case is defined: with no `step_id`, the `idempotency_key` alone identifies the effect, and a retry carrying none is malformed and derives `INCONCLUSIVE`. |

### 21.3 Fourth round — review of `7a6f496`

Round 3's corrections were accepted. One trust-boundary blocker remained, and it
was introduced by round 3's own fix — worth recording plainly, because it is the
characteristic failure of this kind of work: a field added to make something
deterministic became a field an attacker could set.

| # | Finding | Disposition |
|---|---|---|
| 1 | BLOCKER — freshness was forgeable. `evaluated_as_of` governed freshness and expiry while being caller-supplied and held only in the invocation envelope, which `content_digest` does not cover. A caller could backdate it so stale evidence passed, or edit it afterwards, and the digest still verified | Fixed on both dimensions. The instant is now part of an `evaluation` block — `as_of`, `source`, `mode`, `skew_bound_s` — that sits **inside the canonical payload**, so moving `as_of` by one second changes the payload, changes `content_digest` and breaks replay. Admissible sources are bounded by mode: a promotion decision requires `protected_runner_clock` or `engine_clock`, within `skew_bound_s` of the producing runner and never preceding the evidence's `finished_at`; `caller_override` is admissible only in `replay`, `historical` or `test` mode and can never authorize a current promotion; replay uses `recorded_replay` and the bound value. Failing any condition derives `INCONCLUSIVE`, never `PASS`, and is named rather than silently corrected to the current time. |
| — | Two planted negatives required | §15.1 grows from five rows to seven. **Backdated evaluation** covers both the moved instant and a promotion presented with an untrusted source or non-promotion mode. **Tampered record** covers a `content_digest` that does not recompute and an envelope field edited to disagree with the payload it echoes. A third asserted property requires the backdating test to move the instant, recompute, and demand both the digest mismatch and the refusal — so the binding is proven, not assumed from the field's position in the schema. §18.1 item 4 names both. |
| — | RFC 8785 does not normalize Unicode | The JCS paragraph no longer implies it does. It now says the earlier scheme left escaping and number formatting ambiguous, and states the preserve-as-is rule outright: canonicalization is not normalization, two normalization forms of the same text produce different digests, and producers are responsible for emitting consistent Unicode. |
| — | §7's rule list partially restated cap rule 4 with the older, shorter surface list | The duplicate is removed and replaced by a pointer to rule 4, so the single source of truth stays single. |

Round 4's own fix is **partly superseded in round 5**: binding the `evaluation`
block into the payload was necessary and is kept, but binding a field does not
make its content true, and requiring a replay to carry `mode: replay` while also
reproducing the original payload digest was impossible. §21.4 records both.

### 21.4 Fifth round — review of `fd04d6a`

The round-4 binding was accepted. Two linked contract defects remained, and the
reviewer classified them as a **reviewer escape** rather than an implementation
miss: the canonical/envelope split was applied as directed, but no round had
enumerated every verdict-driving input, and none had separated exact replay
verification from re-deciding. That reading is accepted here. The fix is one
consolidated correction to the field partition and the replay model, not another
localized patch.

| # | Finding | Disposition |
|---|---|---|
| 1 | BLOCKER — the payload/envelope partition still left verdict-driving fields outside the digest. `finished_at` drove freshness and the `as_of >= finished_at` rule, `attempt`/`retry_of`/`replay_of` drove lineage validity, and `status`/`idempotency_key` were classified nowhere at all — while §6.3.1 claimed the envelope held nothing that changes a verdict | The partition is re-derived from a **semantic** test rather than a varies-between-runs test, and §6.3.1 now states it once in two normative tables covering every field of both contracts. `finished_at`, `status`, `idempotency_key`, `call_id`, `attempt`, `retry_of`, `replay_of` and `step_id` are bound. Two fail-closed conformance rules ride with it: an undeclared field derives `INCONCLUSIVE`, and a field a new rule reads moves into the bound set in the same change. |
| 2 | BLOCKER — identical tool results were required to share one digest while their occurrence facts could produce different freshness verdicts | Evidence carries **two** digests. `result_digest` covers the normalized tool result and answers "the same tool found the same thing"; `evidence_digest` covers the canonical payload — `result_digest` plus every bound field — and is the only digest a decision references. The reviewer's counterexample (same results, different `finished_at`, one fixed `as_of`) is now expressible: same `result_digest`, different `evidence_digest`, and the decision names which record it evaluated. A nine-row counterexample matrix is carried in §6.3.1 so the next reader can check the partition against the cases that broke the last one. |
| 3 | BLOCKER — replay was impossible under its own rules: a promotion payload carries `mode: promotion`, replay was required to carry `mode: replay` and `source: recorded_replay`, and both were payload fields, yet replay had to reproduce the original digest exactly | One operation was being asked to be two. §6.3.3 splits them. **Verification replay** is a check, not a decision: it recomputes the recorded payload from the recorded inputs using the recorded `evaluation` block verbatim and asserts byte equality, authoring no evaluation context of its own, so no `mode: replay` value ever enters the compared bytes. **Re-evaluation** under `mode: replay`/`historical`/`test` is a new decision with a new payload and digest that makes no equality claim and can never promote. §6.2.2 adds a three-term table distinguishing both from evidence-layer **step replay**. `sdlc verify` is the ACP-0 command, deliberately minimal. |
| 4 | MAJOR — time authority was stated but not derived: `source` and `skew_bound_s` were bound claims, so a caller could label itself `engine_clock` or inflate the tolerance, and the round-4 negative only rejected the honest `caller_override` label | §6.3.2 applies §7's claimed-versus-derived boundary to time. The engine derives all four `evaluation` fields and accepts none; a supplied value becomes `claimed_source` / `claimed_skew_bound_s` and never gates. Each `source` value has one derivation condition, `caller_override` is the floor an unprovable claim falls to, `protected_runner_clock` requires the evaluator's own verified OIDC-bound runner identity, and `skew_bound_s` must equal the value resolved from the policy digest in the same payload — so inflating it changes the policy digest and voids the claim to enforce that policy. |
| — | Negatives required for all of the above | §15.1 grows from seven rows to ten: **mutated occurrence fact** (four fixtures mutating `finished_at`, `status`, `idempotency_key` and lineage while preserving the tool result byte for byte), **forged time authority**, and **inflated skew bound**. The last three rows carry an explicit rule that the attacker may recompute every digest: the fixture verifies cleanly and must still be refused, so the test exercises derivation rather than digest comparison. §18.1 grows to twelve items, adding adapter re-run digest behaviour, verification replay, and field-classification conformance. |

Three gaps surfaced while applying the above and are closed here rather than
left for a sixth round:

- Lineage resolves through `call_id`, so two evidence records claiming one
  `call_id` with different `evidence_digest`s had no defined handling. §6.2.2
  now derives `INCONCLUSIVE` with a lineage-collision reason code; the engine
  does not pick one.
- `engine_clock` read as sufficient for promotion on its own, which would admit
  a developer laptop's clock. §6.3.2 states what it does and does not claim, and
  names the control that actually caps a local decision — §7's independence
  derivation, at level 2 — so the two controls visibly compose instead of each
  assuming the other covers it.
- Verification's scope was implicit. §6.3.3 now bounds it: `verified` means the
  payload is what those inputs produce, not that the §6.3.2 derivations were
  re-run. Derivation establishes a claim was true when made; verification
  establishes nothing has moved since.

Both blockers were introduced by accepted fixes from earlier rounds, which is
worth recording plainly: a partition drawn on the wrong axis, and a determinism
requirement extended to an operation that could not satisfy it. Neither was
visible without enumerating the fields, which is why the classification now lives
in a table that a conformance test checks rather than in prose.

## Appendix A — External reference designs

External systems inform this design; none becomes a dependency. A construct
qualifies only if it can be made deterministic, fail-closed, zero-dependency and
per-repository. Anything that arrives as a framework is studied and reimplemented
in-doctrine, or dropped.

The 2026-09-07 review identified five constructs from Eve worth studying. They
are recorded here **second-hand** — this revision did not inspect Eve directly,
and each must be verified against the source before it shapes an interface.

| Construct | Where it lands | Doctrine note |
|---|---|---|
| Filesystem-defined discovery plus an `info`/`doctor` command reporting configured, discovered, observed, stale and missing capabilities | ACP-1 `sdlc adapter probe` | Already close to doctrine: naming what is *missing* is the anti-vacuous move. `stale` is the field this specification lacked. |
| Trusted orchestration separated from untrusted model-controlled execution, credentials outside the sandbox | §7 execution identity; a threat model before any read-write surface | Sharpens `actor_can_mutate_config` from a boolean into an architectural boundary. |
| Durable step replay and retry identities carried into provenance | §6.2.2 — already adopted | Independently arrived at as review finding 3. |
| Proof-of-fire tests exercising real sessions and tool behaviour rather than inspecting source text | §15, §15.1 | Matches the existing rule that source-text inspection cannot support an enforcement claim. |
| Parent/child/session/sandbox lineage for subagents | ACP-6, alongside `sdlc/event@1` | Deferred with the rest of the telemetry contract; recorded so the event schema reserves room for it. |

Verifying these against Eve's source, and deciding which survive the doctrine
filter, is a research task to be scheduled after the §18 pilot — not a
prerequisite for it.
