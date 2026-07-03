# ADR 0001 — Repo structure and packaging

**Status:** Accepted · **Date:** 2026-07-03
**Relates to:** execution plan Loop 0 (E0.1, R0) · `docs/plans/sdlc-harness-execution-plan.md`

## Context

The repo is consumed two ways, and the structure must serve both:

1. **Direct-run (primary today):** adopters clone and run `python quality-gate/quality_gate.py --root .` — zero install, air-gap friendly, referenced by the Makefile, every CI template, and `cathedral-keeper.config.json` (`qg_path`). This portability is a product feature, not an accident.
2. **Installed (`pip install .`):** advertised via `[project.scripts]` (`qg`, `ck`) but broken twice over — the declared `build-backend` (`setuptools.backends._legacy:_Backend`) does not exist, and `packages.find` over `where = ["quality-gate", ...]` could never capture `quality_gate.py` as a top-level module, so the `qg` entry point was unresolvable even with a valid backend.

Additionally, the repo root had accumulated working notes, strategy docs, HTML deliverables, screenshots, and a stray `nul` artifact — noise that obscures the five component homes.

## Decision

**1. Component homes stay.** `quality-gate/`, `cathedral-keeper/`, `fix-engine/`, `reporting/`, `harness/` are the product's module identity (matching all docs and adoption material) and keep the direct-run story intact. We do **not** move to a `src/` layout now.

**2. Packaging is made honest with explicit mapping** (no `find`):

```toml
build-backend = "setuptools.build_meta"

[tool.setuptools]
py-modules = ["quality_gate"]
packages = ["qg", "cathedral_keeper", "cathedral_keeper.policies", "cathedral_keeper.integrations"]

[tool.setuptools.package-dir]
"" = "quality-gate"
cathedral_keeper = "cathedral-keeper/cathedral_keeper"
```

Distribution scope = the declared CLI entry points (`qg`, `ck`). `fix-engine/` and `reporting/` remain direct-run components; they join the distribution in phase 2 (below) when their root-level modules (`fix_engine.py`, `sarif_formatter.py`) move inside importable packages — two top-level `py-modules` from different directories cannot both resolve under one `package-dir` root, and inventing a second mapping hack is worse than sequencing the move.

**3. Docs tree.**
- `docs/decisions/` — the repo's own ADRs (committed; distinct from `harness/decisions/` which ships templates *to adopters*).
- `docs/deliverables/` — self-contained HTML pages (commit at the owner's discretion).
- `docs/plans/` — execution plans (commit at the owner's discretion).
- `docs/internal/` — working notes, superseded strategy docs, screenshots. **Gitignored:** internal content must never be published by accident; keeping it local-only is enforced structurally, not by vigilance.

**4. Phase 2 (deferred until PRs #1–#4 merge, to avoid conflicting with reviewed work):**
- Move CLI monolith code into the importable packages (`quality_gate.py` → `qg/`, `fix_engine.py` + `sarif_formatter.py` → `fe/`), leaving thin shims at the old paths so every direct-run reference keeps working.
- Add `fe` (and `reporting` if warranted) entry points to the distribution; rename the generic `reporting` package before it ever ships to site-packages (top-level name-collision risk).
- Wire a `pip install .` + `qg --help`/`ck --help` smoke test into self-CI (E0.2) so packaging cannot silently regress.
- New components from the expansion (`runtime-verify/`, `eval-engine/`, `sdlc-init/`) land as sibling component homes with their packages importable from day one — no retrofit.

## Alternatives considered

- **Full `src/` layout now** — cleanest for packaging, but breaks the direct-run paths referenced by the Makefile, all CI templates, CK's QG integration, and every adoption doc, for no user-visible gain today. Revisit at a 1.0 boundary.
- **`package-dir` hacks to force `fix_engine` in now** — rejected; sequencing the code move (phase 2) is honest, a mapping contortion is debt.
- **Empty scaffolds for the three planned components** — rejected as speculative structure (over-engineering); each lands when its loop starts.

## Consequences

- `pip install .` yields working `qg` and `ck` on a clean venv (verified 2026-07-03: RED `BackendUnavailable` → GREEN both `--help` + imports; 42/42 component test files pass; all direct-run paths unchanged).
- The repo root contains exactly: the five component homes, `docs/`, `Makefile`, `pyproject.toml`, `README.md` (+ per-branch floor files).
- Known gap carried forward: the Makefile's `test` target omits `fix-engine/tests` — fold into the self-CI work (E0.2) rather than patching piecemeal here.
