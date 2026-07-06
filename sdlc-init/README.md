# sdlc-init

The born-gated front door (Track A / Epic 11). One command turns an empty
directory into a repo that is gated from birth.

```bash
sdlc init --name "My Project" --owner "@me/team" --target ./my-project
```

This installs the harness, fills placeholders, vendors the Quality Gate +
Cathedral Keeper engines into `tools/qa/` (with an ACTIVE `engine-gates.yml`
workflow that runs them from birth), parks config-carrying workflows until
their stack exists, generates the structural floor and proves it in sync,
proves the gate actually fires (clean scan green, planted fixture caught),
and records an engine-pin manifest — all idempotently and journaled.

## The invariant

**One manifest → one executor → any surface.** The CLI is the first surface; a
future UI or CI re-run resolves the same `InitManifest` and calls the same
executor. Nothing else provisions. The harness file-map lives in exactly one
place (`harness_map.py`), consumed by both `sdlc init` and the thin
`bootstrap.sh` shim — no dispersion.

## Phases (ordered, idempotent, journaled)

| Phase | What |
|---|---|
| `copy_harness` | skills, files, dir fan-outs; parks config workflows; asserts no active workflow ships an unfilled placeholder (anti-case) |
| `park_readme` | explains why parked workflows are parked |
| `vendor_engine` | byte-copies the pinned QG+CK engines into `tools/qa/` (never substituted or newline-translated; `*.py`/`*.json` only, caches and tests pruned); fails closed if the engine checkout lacks a component; per-file sha256 recorded |
| `setup_floor` | fills the owner, generates `CODEOWNERS`, proves surface↔CODEOWNERS in sync |
| `born_gated_proof` | proves the gate fires: vendored QG clean scan exits 0, a planted known-bad fixture makes it exit 1, CK runs green with the shipped config (and finds the vendored QG); the fixture is removed; any deviation fails init |
| `write_manifest` | emits `.harness/manifest.json` — engine SHA + version + `engine.vendored` (per-file sha256 pin) + provenance + phase outcomes |

Re-running is safe: existing files are skipped (a locally modified vendored
file is never repaired by re-init — surfacing that drift against the
manifest's sha256 record is `sdlc status`'s job); only the append-only
`.harness/init-journal.jsonl` grows.

## The gates a born repo runs

`engine-gates.yml` is active from birth (it needs only Python): the vendored
QG in check mode (`--root .` is load-bearing — the vendored default root is
`tools/qa/`) plus CK with blast-radius. Its command lines are single-sourced
from `harness_map.py` (`QG_GATE_CMD`/`CK_GATE_CMD`) and are the same argv the
proof phase runs, so the local proof and the CI gate cannot drift. The shipped
`.quality-gate.json` / `.cathedral-keeper.json` restate the default excludes
(deep-merge replaces lists) and add `tools/qa/**` so the engine never scans
itself; `.cathedral-keeper.json` points CK's QG integration at the vendored
path. `quality.yml` (uv/ruff/mypy/pytest/Postgres) stays parked until that
stack exists.

## Surfaces

- `sdlc init …` — the full born-gated setup (installed entry point).
- `sdlc bootstrap --target DIR` — copy-only path the `bootstrap.sh` shim calls
  (placeholders left for manual fill; backward compatibility). It never
  vendors `tools/qa/`, so it parks `engine-gates.yml` alongside the config
  workflows — an active workflow invoking engines that were never installed
  would be red CI from the first push. Only `sdlc init` activates it.
- `bash harness/bootstrap.sh [DIR]` — thin shim over `sdlc bootstrap`.

## Not yet (deferred, tracked in the execution plan)

Manifest signing (E11.1), profile-driven workflow activation (E11.4),
resume-from-failure (vs the current resume-by-idempotent-rerun), the UI
(E11.10+), and `sdlc status`/`sdlc update` reading the `engine.vendored`
sha256 record for drift/tamper detection. The born-gated proof runs locally
during init; the branch+PR+CI-catches-it variant needs push credentials init
does not have and stays a documented manual step. Branch protection must be
enabled on the remote for CODEOWNERS to be enforced — init prints this as the
next step; automating it is future work.
