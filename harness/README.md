# KP_SDLC harness layer

The 5th component of KP_SDLC: the **agent-facing harness**. Sits alongside `quality-gate/`, `cathedral-keeper/`, `fix-engine/`, and `reporting/`.

## What it is

Where the other four components are mechanical (DETECT / FIX / REPORT), the harness layer is where **judgment** lives — the philosophy, conventions, and Claude/Cursor/Codex orchestration that an agentic codebase needs but no linter can enforce.

```
KP_SDLC
├── quality-gate/        DETECT — file-level rules, PRS scoring        ┐
├── cathedral-keeper/    DETECT — architecture governance              │  mechanical
├── fix-engine/          FIX    — auto-fix diffs + LLM suggestions     │  (no agent
├── reporting/           REPORT — HTML + SARIF                         ┘   memory needed)
└── harness/             JUDGE  — skills + templates + commands + CI   ─  agent-facing
```

## What it ships

| Subdir | Purpose | T1 | T2 | T3 |
|---|---|---|---|---|
| `skills/` | `.claude/skills/*` for design-philosophy + coding-discipline | ✅ | | |
| `templates/` | `CLAUDE.md` + `AGENTS.md` templates with placeholders | ✅ | | |
| `bootstrap.sh` | Idempotent installer; copies harness into target project | ✅ | | |
| `commands/` | Slash commands (`/principles`, `/review`, `/entropy-check`, `/before-i-commit`) | | ✅ | |
| `decisions/` | ADR templates incl. design-philosophy ADR | | ✅ | |
| `hooks/` | Pre-commit hook config + red-flag-attestation script | | ✅ | |
| `ci/` | GitHub Actions workflow templates (quality, web, eval, second-pass-reviewer) | | | ✅ |
| `scripts/` | `setup.sh` and `check.sh` one-command entry points | | | ✅ |

T1 lands enough to consume from any project (skills + Claude/Agents docs + bootstrap). T2 + T3 add the runtime hooks and CI templates progressively.

## Sources of philosophy

The `design-philosophy` skill synthesises four sources, all credited:

1. **Karpathy** — coding heuristics on simplicity, surgical changes, goal-driven loops (via `forrestchang/andrej-karpathy-skills`, MIT)
2. **Ousterhout — *A Philosophy of Software Design*** — deep modules, information hiding, define errors out, 13 design red flags
3. **Hunt & Thomas — *The Pragmatic Programmer*** — broken windows, tracer bullets, DRY, reversibility, good-enough software
4. **Software entropy / broken-window theory** — applied to software per Hunt & Thomas; framed here as the meta-principle that gives the others their *why*

The skill is structured in tiers:

- **Tier 0** — entropy meta-principle (one paragraph, top of `CLAUDE.md`)
- **Tier 1** — 22 always-on principles (read every session)
- **Tier 2** — 22-item red-flag checklist (run every commit)

Mechanical detection of a *small subset* of Tier 2 lives in `quality-gate/` (size, vague names, secrets, debug, silent-catch) and `cathedral-keeper/` (architecture). The harness layer is **only** the judgment part — by design.

## Use

### Bootstrap into a new or existing project

```bash
# From the target project root:
bash /path/to/KP_SDLC/harness/bootstrap.sh

# Or with explicit target:
bash /path/to/KP_SDLC/harness/bootstrap.sh /path/to/some-project
```

The script is idempotent. Re-run after any harness update — existing files are skipped, new ones added. To force overwrite an individual file: delete it first, then re-run.

### What gets installed

```
target-project/
├── CLAUDE.md                              ← from templates/CLAUDE.md.tmpl
├── AGENTS.md                              ← from templates/AGENTS.md.tmpl
├── .claude/
│   ├── skills/
│   │   ├── design-philosophy/SKILL.md     ← Tier 1 + Tier 2 (Karpathy + Ousterhout + Pragmatic + entropy)
│   │   └── coding-discipline/SKILL.md     ← Karpathy guidelines (MIT, attributed)
│   └── commands/                          ← T2: slash commands
├── .github/workflows/                     ← T3: CI templates
├── docs/decisions/                        ← T2: ADR-0001 design philosophy
└── scripts/                               ← T3: setup.sh, check.sh
```

### Then

1. Replace `{{PROJECT_NAME}}` in `CLAUDE.md` and `AGENTS.md` (single sed or manual).
2. Read `.claude/skills/design-philosophy/SKILL.md` once.
3. Add project-specific addenda under `<!-- project-specific -->` (e.g. `Cited<T>` envelope, brand-agnostic naming).
4. Run `quality-gate/` and `cathedral-keeper/` against the project as you normally would.

## Update flow

When this harness layer ships new principles, slash commands, or workflows:

```bash
cd /path/to/some-project
bash /path/to/KP_SDLC/harness/bootstrap.sh
# Only new files are copied. Existing project content is preserved.
```

The audit log under `harness/decisions/` captures retired rules and the reasoning, so projects can inspect what changed and why.

## Design rules for the harness itself

The harness layer is governed by the same philosophy it ships:

- **Simplicity first.** Bash + plain markdown only. No build step. No package install. Drop into any environment.
- **Surgical changes.** Bootstrap only adds; never overwrites without explicit user action.
- **Good enough software.** Don't overload `bootstrap.sh` with options nobody uses.
- **Test it on at least one real project before committing harness changes.** Atlas is the dogfooder; project #2 will be the second.
