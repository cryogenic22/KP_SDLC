# CTX dogfood-value evaluation — protocol (v1)

**Question:** does CTX materially improve development in the repositories already
using it — fewer mistakes, faster continuation, less re-derivation — or does it
only prove that memory artifacts get written?

**Status:** measurement substrate built (this doc + `eval_engine.ctx_baseline` +
`schemas/eval/ctx-dogfood-baseline.schema.json` + a sanitized baseline under
`eval-engine/results/`). No paid experiment arms have been run. **Stop for
review before running any.**

---

## 0. What the dogfood does and does not show

The four live ledgers prove **capture health**: high identifier fidelity, hundreds
of decisions/literals, thousands of turns packed. They do **not** show that any
agent made fewer mistakes *because* the memory existed — there is no counterfactual
in historical sessions. Capture ≠ value. Everything below exists to close that gap
honestly, and constraints + supersessions are currently underexercised across all
four repos (a product-adoption gap, not just an evaluation gap).

## 1. Reproducible baseline (built)

`eval_engine.ctx_baseline` freezes, per repo: split Git dirty state
(code/ledger/config separately — a single flag conflates them), ledger file
hashes, **runtime provenance** (resolved ctxpack module + source hash, Python
identity, package version, per-repo hook/MCP launch hashes + which servers set
`PYTHONPATH`), and the sanitized `session stats` aggregates.

Two correctness properties are enforced and tested:

- **No torn read.** Aggregates are computed from a *frozen copy* of the exact
  bytes that were hashed, then the live files are re-verified; a mid-capture change
  retries and finally marks the entry `torn` (fail closed). The ledger churns
  live, so hashing files and then invoking live `session stats` could observe two
  different states — that is explicitly avoided.
- **Privacy by construction.** Hashes/counts/opaque labels only; the tool refuses
  to emit if `scan_forbidden` finds an absolute path, session UUID, or the like.
  The label→repo map stays in the uncommitted `--repos-config`.

## 2. Retrospective audit = FIDELITY, not value

For the ~9 existing cross-session transitions, check whether CTX's gist + recall
recover the prior session's current decision, an exact literal, a constraint (and
its negation), and a failed-approach warning — with provenance to the origin turn,
and flagging any already-stale recalled fact. This establishes **trust** (accuracy,
provenance, staleness). It **cannot** establish value: every historical session
already ran with CTX, so there is no control. Label it a fidelity audit.

## 3. Four-handoff calibration probe (NOT a go/no-go gate)

One clean cross-session handoff per repo. Two frozen-start, **planning-only** arms:

- **A — CTX intended workflow:** SessionStart gist injected + **one bounded,
  task-conditioned** structured recall at the first substantive task. Raw grep only
  as fallback.
- **B — strong control:** same model, commit, instructions, and token/tool budget;
  no CTX artifacts; repo + Git history + raw-transcript search available.

Graders blinded to arm. Gold handoff prepared from the prior transcript first.

**Continuity score (0–6, one point each, graded separately then summed):**
objective+next-step · current decision · required constraint (incl. negation) ·
exact literal · failed approach not recommended · evidence/provenance valid.
Partial credit is deliberate — a binary pass/fail wastes information at this N.

**Critical-failure flags (recorded separately):** resurrected a superseded
decision · violated a negated constraint · invented an unsupported fact ·
recommended a known failed approach.

**Endpoints:** co-primary = continuity score + context-acquisition effort (tool
calls + tokens to accepted plan); secondary = transcript greps, repo searches,
wall-clock, unsupported assertions, human corrections.

**Read-path instrumentation (both arms) — closes the passive/explicit gap:** log
startup-gist-injected + gist SHA + tokens, explicit recall issued + returned fact
IDs + provenance turns, fallback/repo searches, and whether retrieved info
influenced the plan. *"0 explicit reads" ≠ "memory not consulted"* — passive gist
injection is itself a read path; undercounting it biases against CTX.

**What the probe decides:** harness works · graders agree · control is genuinely
strong · metrics discriminate · no CTX mechanical regression · an effect-size +
variance estimate to power the real study. It may kill the study **only** on a
mechanical failure (stale facts, uniformly worse plans, unusable retrieval) —
**never** on a win count at n=4.

## 4. Power the real study from the pilot

Do not pre-commit to 32 transitions. Use the observed paired-score variance +
control performance to size it. The independent unit is the **session/handoff**;
the six components are repeated measurements within a handoff, not six samples.

## 5. Authoring discipline is a separate 2×2

`Decision:` / `Supersedes:` discipline may carry much of the value. Isolate it
later with a factorial (CTX enabled/disabled × structured/natural authoring) — out
of scope for the calibration probe.

## Guardrails

- **No behavior change yet.** The startup gist is already default-on. Task-
  conditioned recall (arm A) is the *specific policy under test*; implement it as a
  default only if it improves continuity or effort. Do not build an unrestricted
  "recall more often" feature off read-count correlation.
- **No paid arms until approved** (budget + a blinded grader named).
- **Stop for review** after building the gold sheets.
