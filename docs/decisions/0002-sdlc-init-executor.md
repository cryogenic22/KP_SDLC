# ADR 0002 — sdlc-init: one manifest, one executor

**Status:** Accepted · **Date:** 2026-07-05
**Relates to:** execution plan Track A (Epic 11), E1.10, E0.14 · derived from the
manual-init friction log (`docs/internal/e11-friction-log-vogue-init.md`)

## Context

Setting up a new gated repo (the `vogue` pilot) by hand surfaced nine friction
points (see the friction log). The two structural ones: the harness file-map
lived only inside `bootstrap.sh` (bash), so any second surface — a Python
executor, a UI — would have to duplicate it (the exact dispersion the harness
exists to prevent); and `bootstrap.sh` copied CI templates with raw
`{{PLACEHOLDER}}` values straight into `.github/workflows/`, shipping invalid
YAML that fails on every push (a gate that can't run, reported as present).

The execution plan's non-negotiable for this layer: **one manifest → one
executor → any surface**; the UI (later) composes manifests and reads journals,
it never provisions.

## Decision

**1. A new `sdlc-init/` component owns init, with the file-map as declarative
data.** `harness_map.py` is the single source of what a born-gated repo
receives and where. Both `sdlc init` and `bootstrap.sh` consume it;
`bootstrap.sh` is reduced to a thin shim over `sdlc bootstrap` (bash no longer
carries a copy of the map).

**2. The executor is ordered, idempotent, and journaled.** Phases
(`copy_harness → park_readme → setup_floor → write_manifest`) skip work already
done (resume-by-rerun) and append outcomes to `.harness/init-journal.jsonl`.
Resume-from-failure (skipping completed phases mid-run) is deferred; idempotency
makes a full re-run safe in the meantime.

**3. Config-carrying workflows are parked, not shipped active.** `quality.yml`,
`eval.yml`, `web.yml` carry placeholders no generic init can fill; they go to
`.github/workflows-parked/`. The `copy_harness` phase asserts no *active*
workflow retains an unfilled `{{PLACEHOLDER}}` — the born-gated analogue of
no-vacuous-green (a parked gate is honest; a broken active gate is not).

**4. The repo is pinned at birth.** `write_manifest` records the engine SHA,
version, owner, profile, and every phase outcome in `.harness/manifest.json` —
the read surface for a future `sdlc status` / drift check (E0.14).

**5. Reuse over reimplementation.** `setup_floor` shells the shipped
`gen_codeowners.py --check` rather than reimplementing CODEOWNERS generation or
the sync proof.

## Alternatives considered

- **Keep the map in bash, reimplement in Python** — rejected: two sources of
  the same mapping is the dispersion the coherence work (Epic 13) exists to kill.
- **Reimplement the copy in Python and delete bootstrap.sh** — rejected: breaks
  `bash bootstrap.sh` for anyone scripting against it; the shim preserves the
  interface at near-zero cost.
- **Full Epic 11 now (signing, tiers, provisioning service, UI)** — rejected as
  speculative; this is the golden-path MVP that retires the friction log, and
  each deferred piece lands when a pilot needs it (demand-gating).

## Consequences

- `sdlc init` produces a born-gated repo verified end-to-end: 28 files, floor
  sync test green on the generated repo, QG scan clean from inside it, engine
  pinned in the manifest (dogfooded 2026-07-05). 14 component tests; `make test`
  runs them via a new `test-init` target.
- `bootstrap.sh` now requires Python (the engine already does); it detects a
  working interpreter and skips the Windows Store `python3` alias stub.
- Retires friction-log items 1, 2, 3, 5, 6 (partial), 7, 8 (partial). Remaining:
  CK-config smoke (#4), branch-protection automation, the failing-fixture proof
  phase, and manifest signing — all tracked in the plan.
- `pyproject.toml` gains the `sdlc` entry point and the `sdlc_init` package
  mapping; `pip install .` yields working `sdlc`/`qg`/`ck` (verified on a clean
  venv).
