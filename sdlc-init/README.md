# sdlc-init

The born-gated front door (Track A / Epic 11). One command turns an empty
directory into a repo that is gated from birth.

```bash
sdlc init --name "My Project" --owner "@me/team" --target ./my-project
```

This installs the harness, fills placeholders, parks config-carrying workflows
until their stack exists, generates the structural floor and proves it in sync,
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
| `setup_floor` | fills the owner, generates `CODEOWNERS`, proves surface↔CODEOWNERS in sync |
| `write_manifest` | emits `.harness/manifest.json` — engine SHA + version + provenance + phase outcomes |

Re-running is safe: existing files are skipped; only the append-only
`.harness/init-journal.jsonl` grows.

## Surfaces

- `sdlc init …` — the full born-gated setup (installed entry point).
- `sdlc bootstrap --target DIR` — copy-only path the `bootstrap.sh` shim calls
  (placeholders left for manual fill; backward compatibility).
- `bash harness/bootstrap.sh [DIR]` — thin shim over `sdlc bootstrap`.

## Not yet (deferred, tracked in the execution plan)

Manifest signing (E11.1), profile-driven workflow activation and the
failing-fixture proof phase (extension-layer, E11.4/E11.5), resume-from-failure
(vs the current resume-by-idempotent-rerun), and the UI (E11.10+). Branch
protection must be enabled on the remote for CODEOWNERS to be enforced — init
prints this as the next step; automating it is future work.
