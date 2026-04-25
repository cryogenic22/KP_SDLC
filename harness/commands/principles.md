---
description: Print Tier 0 + Tier 1 design-philosophy reminder. Use when context is high or before non-trivial design choices.
---

Re-ground in the design philosophy. Read the full skill at `.claude/skills/design-philosophy/SKILL.md`. The condensed reminder:

## Tier 0 — Entropy

> Every change either fights entropy or feeds it. Default is feeding. Choose.

## Tier 1 — Always-on (22)

**Design (Ousterhout):** deep modules · information hiding (no leakage) · pull complexity downward · define errors out of existence · different layer different abstraction.

**Process (Pragmatic):** don't live with broken windows · tracer bullets · reversibility · crash early · DRY · good enough software.

**Discipline (Karpathy):** think before coding · simplicity first · surgical changes · goal-driven execution.

**Cross-cutting:** design twice · refactor mercilessly · design by contract · test ruthlessly · code is read 10× more than written.

State which 3-5 of these are most relevant to what you're about to do, and why. If none feel relevant, the change is probably trivial — proceed without ceremony.
