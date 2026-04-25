# ADR-0001: Adopt the KP_SDLC harness layer for design philosophy

**Date:** {{BOOTSTRAP_DATE}}
**Status:** accepted

## Context

The codebase is built primarily by autonomous agents (Claude Code, Cursor, Codex) supervised by a small team. Three problems compound when agents write the bulk of the code:

1. **Attention drift.** As context grows, instructions buried far back in the prompt fall out of effective attention. Rules in `CLAUDE.md` that the agent agreed to in turn 3 are no longer load-bearing by turn 80.
2. **Subjectivity collapse.** Without explicit principles, code-quality decisions become ad-hoc. The same agent makes opposite choices across files based on local context.
3. **Software entropy.** Without an active force fighting it, every codebase drifts toward incoherence — broken windows accumulate, abstractions calcify, the gap between intended and actual architecture widens.

We need a system that is:
- **Explicit** about which principles bind, with sources cited.
- **Layered** so the most important rules are mechanical (no agent memory needed), the rest are re-injected at moments-of-need.
- **Auditable** so we can retire rules that don't earn their keep and add ones we keep manually catching.
- **Reusable** across projects without rebuilding it each time.

## Decision

Adopt the KP_SDLC `harness/` layer. It synthesises four sources into one tiered system, drops into any project via `bootstrap.sh`, and integrates with the existing KP_SDLC mechanical platform (`quality-gate`, `cathedral-keeper`, `fix-engine`, `reporting`).

### The four sources

| Source | What it contributes |
|---|---|
| Andrej Karpathy — coding heuristics | Discipline for LLM-driven coding: think before coding, surgical changes, goal-driven execution, simplicity first |
| John Ousterhout — *A Philosophy of Software Design* | Design judgment: deep modules, information hiding, define errors out, 13 design red flags |
| Andrew Hunt & David Thomas — *The Pragmatic Programmer* | Process discipline: broken windows, tracer bullets, DRY, reversibility, good-enough software |
| Software-entropy / broken-window theory | Meta-principle: codebases drift toward incoherence unless an active force pushes the other way |

### The three tiers

- **Tier 0** — entropy meta-principle (one paragraph, top of `CLAUDE.md` and `AGENTS.md`).
- **Tier 1** — 22 always-on principles, read every session, drive judgment during planning and writing.
- **Tier 2** — 22-item red-flag checklist, walked before every commit; partly mechanical (via QG / CK), partly self-attested.

### The pipeline integration

| When | Mechanism | Survives high context? |
|---|---|---|
| `PreToolUse` (Edit/Write) | JIT inject relevant principle subset | ✅ Re-injects at moment of writing |
| Pre-commit | ruff/mypy/QG/CK + `red-flag-attestation` (appends Self-review skeleton) | ✅ Mechanical; attestation invites attention |
| CI on PR | All gates + `second-pass-reviewer` (independent Claude session, fresh context, only diff + principles) | ✅ No shared context to drift from |

## Consequences

### Better

- Every coding agent sees the same principles, in the same place, with the same sources cited.
- Re-injection at moments-of-need fights attention drift mechanically.
- The fresh-context second-pass reviewer catches what first-pass drift missed.
- Bootstrapping a new project is one command (`bash <KP_SDLC>/harness/bootstrap.sh`).
- Updates to the harness propagate via re-running bootstrap (skips existing files; only adds new).

### Worse / harder

- Adds a small but real maintenance surface: the harness itself is now a thing to keep working across projects.
- Rules can become entropy if applied dogmatically. Mitigation: Pragmatic's "good enough software" is encoded as Tier 1 principle #11; the rule-audit log under `harness/decisions/` is the explicit retirement mechanism.
- Agents may rubber-stamp the Self-review attestation. Mitigation: the second-pass reviewer audits attestations against the diff. If divergence is high, the attestation step gets retired or made stricter.

### Possible

- Project-specific addenda layer ON TOP of the harness via the `<!-- project-specific -->` block in `CLAUDE.md` and a project-named skill (e.g. `{{PROJECT_NAME}}-coding-discipline`).
- The harness can be extracted further into a versioned package once it's been used on 2-3 projects and the API is felt out.

## Alternatives considered

- **Per-project hand-written principles.** Rejected: fragments knowledge, reinvents the wheel, and means improvements don't propagate.
- **Strict CLAUDE.md without skills/templates/hooks.** Rejected: doesn't survive high context — that's the whole problem.
- **Mechanical-only enforcement (lint everything).** Rejected: most of these principles are judgment calls. Mechanical rules for subjective principles produce false positives and cargo-culting.
- **Single-source philosophy (Ousterhout-only or Pragmatic-only).** Rejected: each source covers a different layer. Karpathy speaks to LLM-specific failure modes neither book addresses; entropy is the meta-frame neither book makes explicit; Ousterhout and Pragmatic complement each other on design vs process.
- **Use someone else's harness.** Reviewed: no published harness covered all four sources + Claude Code skill conventions + idempotent bootstrap. Building this once and reusing across projects is cheaper than adapting an external harness per project.

## Affected teams / surfaces

- All current and future projects under this org.
- Existing project-specific coding-discipline addenda (if any) layer ON TOP of the harness; they are not replaced. Migration is additive.
- The KP_SDLC mechanical platform (`quality-gate`, `cathedral-keeper`) is consumed by the harness's pre-commit and CI templates — same tools, same rules, just orchestrated.
