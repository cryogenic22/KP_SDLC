# Adaptive reflection and maturity contract

Observatory reflects the repository's actual harness and engineering approach;
it does not require every project to look like KP_SDLC or every harness to look
like Claude Code.

## Stable core, evolving edges

Harness-specific adapters may change whenever a harness adds telemetry. They
publish canonical capabilities such as session lifecycle, tool lifecycle,
permissions, subagents, compaction, cost, or context utilization. Unknown event
types remain visible to the adapter so new harness behaviour can be added
without changing the snapshot or dashboard contract.

Repository adapters follow the same approach for quality, architecture, evals,
memory, Git/worktrees, security, CI, deployment, and production operations.
The core records three states distinctly:

- capability observed and evidence available;
- capability supported but no current evidence available;
- capability unavailable from the installed harness/tooling.

## Maturity is improvement, not busyness

The initial maturity model tracks five independent dimensions from level 0
(`unobserved`) through level 5 (`improving`):

- observability;
- memory discipline;
- quality governance;
- behavioural evaluation;
- parallel coordination.

Levels are earned by capabilities and non-vacuous evidence. Event volume, code
volume, agent count, and token spend do not increase maturity.

`record-maturity` writes an explicit checkpoint only when its evidence
fingerprint changes:

```bash
python -m observatory record-maturity
```

The dashboard can then show improved and regressed dimensions relative to the
last checkpoint. This provides a feedback loop: detect a gap, improve the
harness/repository, record the new evidence, and demonstrate the maturity gain.

Run the adaptive experiment with:

```bash
python -m observatory install-hooks
python -m observatory serve
```

