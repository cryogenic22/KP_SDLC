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

| Subdir | Purpose | Status |
|---|---|---|
| `skills/` | `.claude/skills/*` for design-philosophy + coding-discipline | ✅ |
| `templates/` | `CLAUDE.md` + `AGENTS.md` + `PULL_REQUEST_TEMPLATE.md` | ✅ |
| `commands/` | Slash commands (`/principles`, `/review`, `/entropy-check`, `/before-i-commit`) | ✅ |
| `decisions/` | ADR templates including the design-philosophy ADR | ✅ |
| `hooks/` | Pre-commit base config + `red-flag-attestation.sh` + `second_pass_reviewer.py` | ✅ |
| `ci/` | GitHub Actions workflow templates: `quality.yml`, `web.yml`, `eval.yml`, `second-pass-reviewer.yml` | ✅ |
| `scripts/` | `setup.sh` and `check.sh` one-command entry points | ✅ |
| `bootstrap.sh` | Idempotent installer | ✅ |

The harness is consumable from any project today.

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

### What gets installed (20 files at first bootstrap)

```
target-project/
├── CLAUDE.md                                       Tier 0 + Tier 1 condensed
├── AGENTS.md                                       same content for AGENTS.md convention
├── .claude/
│   ├── skills/
│   │   ├── design-philosophy/SKILL.md              Tier 0/1/2 — 4 sources
│   │   └── coding-discipline/SKILL.md              Karpathy guidelines (MIT)
│   └── commands/
│       ├── principles.md                           /principles
│       ├── review.md                               /review (22-flag walk)
│       ├── entropy-check.md                        /entropy-check
│       └── before-i-commit.md                      /before-i-commit
├── .github/
│   ├── PULL_REQUEST_TEMPLATE.md                    Spec/Summary/Verification/Self-review
│   └── workflows/
│       ├── quality.yml                             ruff/mypy/pytest/QG/CK + PR template lint + diff size
│       ├── web.yml                                 pnpm typecheck/lint/test/build/size
│       ├── eval.yml                                golden suite (skip-without-key)
│       └── second-pass-reviewer.yml                fresh-context Claude review on PR open
├── .harness/
│   └── hooks/
│       ├── red-flag-attestation.sh                 prepare-commit-msg: appends Self-review skeleton
│       └── second_pass_reviewer.py                 stdlib-only Claude API client (used by CI)
├── .pre-commit-config.yaml                         universal hygiene + QG + CK + red-flag-attestation
├── docs/decisions/
│   ├── _template.md                                ADR template
│   └── 0001-design-philosophy.md                   adoption ADR (cites all 4 sources)
└── scripts/
    ├── setup.sh                                    one-command install (auto-detects uv/pnpm/pre-commit/alembic)
    └── check.sh                                    one-command smoke (lint+typecheck+test+build+QG+CK)
```

### Substitute placeholders after bootstrap

The bootstrap fills `{{BOOTSTRAP_DATE}}` automatically. Other placeholders are left for you to substitute (one-shot sed):

```bash
PROJECT_NAME="myproject"
PYTHON_PACKAGE="myproject"           # often same as PROJECT_NAME
FRONTEND_WORKSPACE="myproject_web"   # for monorepos with a frontend
POSTGRES_USER="myproject"
POSTGRES_PASSWORD="myproject"        # CI-only — production envs use repo secrets
POSTGRES_DB="myproject"
EVAL_MODULE="tests.eval.runner"      # if you adopt the golden eval pattern

find . -type f \( -name "*.md" -o -name "*.sh" -o -name "*.yml" \) \
  -not -path "./.git/*" -not -path "./node_modules/*" \
  -exec sed -i \
    -e "s/{{PROJECT_NAME}}/$PROJECT_NAME/g" \
    -e "s/{{PYTHON_PACKAGE}}/$PYTHON_PACKAGE/g" \
    -e "s/{{FRONTEND_WORKSPACE}}/$FRONTEND_WORKSPACE/g" \
    -e "s/{{POSTGRES_USER}}/$POSTGRES_USER/g" \
    -e "s/{{POSTGRES_PASSWORD}}/$POSTGRES_PASSWORD/g" \
    -e "s/{{POSTGRES_DB}}/$POSTGRES_DB/g" \
    -e "s/{{EVAL_MODULE}}/$EVAL_MODULE/g" \
    {} \;
```

If your project has no Postgres / no frontend / no eval suite, delete the corresponding workflow file or block.

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
