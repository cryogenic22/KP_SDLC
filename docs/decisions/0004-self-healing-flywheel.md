# 0004 — Self-healing flywheel: measure before mining

**Status:** Accepted (Loop 1 landed). Loops 3–8 are intent-level only and are
expected to change once Loops 1–2 produce data.

## Context

The harness captures evidence about its own use and does almost nothing with it.
An inventory of this repo (2026-07-22) found:

| Stage | State |
|---|---|
| Collect traces | **Exists**, default-on, 1,821 events, schema `agent-observatory/event@1` |
| Aggregate / analyze | **Missing** — only "latest event per agent" and "set of distinct event types" |
| Mine into proposals | **Missing** — no such code |
| Evaluate proposals | Engine exists; **no corpus** (`.sdlc-core/` absent, so `ee run` has nothing to run) |
| Apply safely | **Exists, dormant, mis-fed** — `fix-engine` has the full safety envelope but consumes static findings, and its workflow is not installed |
| Scheduled trigger | **Missing** — no cron/schedule/dispatch in any workflow |
| Cost accounting | **Missing** — `duration_ms` captured and read by nothing |

Two facts set the sequence. The hard parts — schema'd capture, and a safe applier
with syntax gate, backup-restore, content-match precondition, confidence
threshold and human label gate — are **already built**. And the measurement that
would let us judge any of it was **entirely absent**, so every efficiency claim
about the harness, including the ones motivating this program, was unfalsifiable.

## Decision

Build the flywheel as eight independently revertible loops, and **measure before
mining**. Loop 1 makes cost exist as a number; nothing downstream is trusted
until it does.

| # | Loop | Proves | Exit gate |
|---|---|---|---|
| **A. Measure** ||||
| 1 | Meter — cost/step attribution as an Observatory consumer | cost is measurable at all | metered aggregates match an independent tally on a known transcript |
| 2 | Waste signatures — deterministic detectors over metered traces | waste is mechanically detectable, not merely narratable | each detector fires on a planted case, stays silent on a clean one |
| **B. Decide** ||||
| 3 | Proposal generator — signatures → typed proposals with evidence pointers | a detector can name a fix without applying it | every proposal carries a reproducible evidence link |
| 4 | Eval corpus — `.sdlc-core/corpus` + `ee run` in CI | proposals are scored *before* they act | corpus frozen and labeled before proposals exist |
| **C. Act** ||||
| 5 | Safe apply — re-point `fix-engine`'s envelope at trace proposals | nothing lands without human intent and rollback | refuses on missing evidence or failing before/after proof |
| 6 | Propagation — `sdlc update`, applying what `sdlc status` detects | fixes reach born repos at all | a stale born repo goes green without hand-editing its manifest |
| 7 | Automation + sanitized cross-repo export | the "from time to time" part | export passes a refuse-on-leak scan; schedule is revertible |
| 8 | Value ledger — tokens/steps per merged PR; signature-decline check | the flywheel earns its keep | a change that does not reduce its target signature is reverted |

Phase C is deliberately under-specified. Committing to its details before Phase B
produces data would repeat the mistake of fixing an experiment's shape before
observing any variance.

### The circularity hazard

If the same author mines the traces, generates the proposals, **and** writes the
eval that grades them, the result is unfalsifiable — the exact failure the CTX
dogfood substrate exists to avoid. Binding mitigations:

1. The Loop 4 corpus is **frozen and labeled before** any proposal is generated;
   Loop 3 output must not inform Loop 4 input.
2. Gold labels come from the repo owner or a blinded grader, never from the
   proposal generator.
3. A change counts as value only if the waste signature it targeted **measurably
   declines in later sessions** (Loop 8). Otherwise it is reverted.

### Loop discipline (binding)

One loop, one PR, branched off `main`, independently revertible — no bundling.
Every PR carries an anti-vacuous test (green cannot come from having looked at
nothing), an explicit anti-case, fail-closed behaviour, a green QG baseline
ratchet, and zero new CK high findings. Read the checker before chasing its
score. Verify with the command that answers the question, and say which command.
Stop at each phase boundary for review.

## Non-goals

- No auto-apply to `main`. Ever. A human label remains a precondition.
- No new agent capability — this makes the existing harness cheaper and more
  correct; it does not add product surface.
- No cross-machine aggregation until the sanitized export exists (Loop 7).
  `.observatory/` is gitignored and machine-local by design.

## Loop 1 as built

`observatory/cost.py`, surfaced as `python -m observatory cost`.

Token counts live only in the Claude Code session transcript — hook events carry
none (`events._SAFE_FIELDS` has neither a usage field nor `transcript_path`) — so
the meter locates transcripts itself via the path slug and reports three-state
when it cannot.

Invariants:

- **I1 content-blind by construction.** The extractor reads numeric usage fields,
  message role/type, and tool *names*. It never reads a `tool_use` block's
  `input`, never reads assistant text, and measures tool results by length only.
  Privacy is a property of what the code physically holds, not of filtering
  applied afterwards.
- **I2 three-state.** No transcripts → `available: false` with a reason. Absence
  must never render as zero, which would read as "this was cheap".
- **I3 fail closed.** A leak scan runs before any ledger write; a match refuses
  the write. This is I1's anti-case.
- **I4 deterministic.** Every emitted value derives from the inputs.
- **I5 self-metering.** This program's own sessions appear in the same ledger, so
  its cost is visible without anyone taking the author's word for it.

Metric contract `agent-observatory/cost@1`, per session: billed `steps`;
`input`/`output`/`cache_read`/`cache_write` and `total_input`; `cost_per_step`;
`tool_calls` total and per tool name; `text_only_steps`; `tool_result_bytes`;
first/last timestamps.

## Consequences

**What this buys.** The first measured finding is that spend tracks *step count*,
not tool output: across six sessions, ~903M input tokens against ~2.5MB of tool
results — roughly **0.07%** of input. At ~250k tokens per step, removing a step
is worth ~100× more than trimming a tool result. That inverts the intuitive
optimization target and is the basis for Loop 2's detectors.

**What it costs.** The meter reads session transcripts, which contain everything.
I1 constrains that to numbers and tool names, and I3 backs it with a refusal, but
the read itself is real and the trust boundary should be understood.

**Live-file caveat.** Transcripts are appended to while a session runs, so two
reads minutes apart legitimately differ. Any comparison must read the same bytes
at the same instant — the Loop 1 gate was verified that way.
