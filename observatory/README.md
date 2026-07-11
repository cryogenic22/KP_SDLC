# Agent Observatory — vertical-slice specification

Agent Observatory is a local, evidence-first view of coding-agent activity and
repository readiness. The first increment proves the full path:

```text
Claude Code hook -> normalized append-only event -> repository health snapshot
                 -> localhost JSON API -> animated dashboard
```

The visual theme is deliberately downstream of the snapshot contract. A pixel
office, spacecraft, or professional control room can render the same facts
without changing capture, health, or evidence semantics.

## Product contract

The default view answers:

1. Which agents are working, waiting, failing, or finished?
2. Is a long-running context approaching a sensible handoff/compaction point?
3. Which repository signals need human attention now?
4. Are quality, architecture, and behavioural evaluation claims backed by
   non-vacuous evidence?
5. How many Claude worktrees exist, and which have recent observed activity?

Every health item distinguishes:

- `observed`: a direct fact from an event or artifact;
- `rule-based concern`: a deterministic rule over observed facts;
- `heuristic`: a probabilistic interpretation that must carry confidence;
- `evaluation`: a verdict produced by an explicit eval contract.

This increment emits the first two only. Overengineering, scope drift, loop
detection, security readiness, and production readiness remain future
detectors until their evidence contracts and positive controls are defined.

## Architecture

### Capture

`claude_hook.py` accepts Claude Code hook JSON on stdin. It records event type,
session/agent identity, timing, tool name, errors, notifications, and other
bounded metadata. Tool inputs are excluded by default because shell commands
and MCP arguments can contain credentials or proprietary content. Setting
`OBSERVATORY_CAPTURE_INPUTS=1` opts into bounded, key-redacted inputs.

Events are appended to `.observatory/events.jsonl` using
`agent-observatory/event@1`. The runtime directory is ignored by Git.

### Projection

`SnapshotBuilder` creates `agent-observatory/snapshot@1` from:

- normalized Claude hook events;
- CtxPack `.claude/ctx/checkpoints.jsonl` context checkpoints;
- `.claude/worktrees/` inventory;
- the latest root Quality Gate report;
- the Cathedral Keeper report;
- an Eval Engine `latest.json` scorecard when present.

The context meter is intentionally named **activity pressure**. CtxPack exposes
turns, errors, files changed, decisions, and checkpoint history; it does not
prove provider context-window utilization. The UI must not relabel the estimate
as an exact token percentage.

### Presentation

The standard-library HTTP server binds to localhost only. `/api/snapshot`
returns the current projection and `/` serves the dashboard. The browser polls
every three seconds; the server caches the expensive projection for two
seconds. The dashboard uses DOM text nodes for data and does not inject event
content as HTML.

## Run the experiment

From the repository root:

```bash
python -m observatory install-hooks
python -m observatory serve
```

Then open `http://127.0.0.1:8765` and start a new Claude Code session in the
repository. Hook installation is idempotent and adds commands alongside the
existing CtxPack and reuse-injector hooks.

Useful diagnostics:

```bash
python -m observatory snapshot
python -m observatory record-maturity
python -m pytest observatory/tests -q
```

`install-hooks`, `snapshot`, `record-maturity`, and `serve` are the whole public
CLI — one entry point (`python -m observatory`, or the packaged
`kp-observatory` console script), backed by the adaptive projection.

## Disable, uninstall, and overhead

Capture is designed to be safe to leave on and trivial to turn off:

- **Disable for a session (no file edits):** set `OBSERVATORY_DISABLE=1`. The
  hook then exits 0 immediately as a no-op — nothing is captured.
- **Uninstall:** remove the `python observatory/claude_hook.py` entries from
  `.claude/settings.json` (they are additive, one per hook event). The CtxPack
  and reuse-injector hooks are independent and are never touched by install or
  uninstall.
- **Fail-safe:** a capture error exits non-zero *without* the exit code 2 that
  would block a tool call, and each hook has a 5-second timeout, so a broken or
  slow hook can never block or hang a Claude Code session.
- **Overhead:** one hook invocation is ~0.2 s on this machine, dominated by
  Python process start-up (the capture itself is a bounded append). That cost is
  paid out-of-band per hook event, not on the model's critical path.
- **Privacy:** events are written only to the local `.observatory/` directory
  (git-ignored); tool inputs are excluded unless `OBSERVATORY_CAPTURE_INPUTS=1`,
  and even then sensitive-looking keys are redacted and values are bounded.

## First-increment health rules

| Rule | Classification | Behaviour |
|---|---|---|
| Context has at least 1,000 recorded turns | Rule-based concern | Recommend verified handoff/compaction review |
| CtxPack reports a fact conflict | Observed | High-priority decision conflict |
| At least five Claude worktrees exist | Observed | Request inventory review; never auto-delete |
| Quality report checked zero files | Observed | Mark inconclusive even if it says `passed: true` |
| Cathedral Keeper has high findings | Observed | Surface representative evidence |
| Eval scorecard missing | Observed | Production-readiness evidence is incomplete |
| Eval has no considered cases | Observed | Fail closed; skipped/empty suites cannot be green |

The numerical context thresholds are initial product defaults, not provider
limits. A later configuration contract should make them repository-specific.

## Safety boundaries

- No agent control, approval, pause, deletion, or worktree pruning.
- No remote bind without a future authenticated deployment design.
- No transcript, assistant-response, or tool-output capture.
- No tool inputs unless explicitly opted in.
- No “healthy” status from a missing, empty, all-skipped, or zero-file artifact.
- No orphan classification from directory presence alone; Git evidence is
  required before the product may call a worktree removable.

## Next increments

1. Correlate tasks, files, tool calls, parent agents, and subagents as a DAG.
2. Add exact token/context telemetry when the harness exposes it; visualize
   compaction start/end and validate handoff completeness.
3. Add changed-surface detectors for overlapping agents and merge risk.
4. Model security and production readiness from named QG/CK/eval policies.
5. Add loop/stall detection with replayable evidence and positive controls.
6. Add original theme packs over the stable snapshot contract.
7. Add Codex and other harness adapters that emit the same event schema.

Decision: the observability contract remains read-only until the evidence model
is trusted; intervention controls are a separate security-sensitive increment.

