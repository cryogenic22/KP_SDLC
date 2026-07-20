# CTX dogfood baseline — sanitized results

Immutable, **sanitized** freezes of Git + ledger + CTX-runtime state across the
dogfood repos, emitted by `python -m eval_engine.ctx_baseline` and validated
against `schemas/eval/ctx-dogfood-baseline.schema.json`.

## What is (and is not) in these files

Stored: hashes, counts, opaque repo labels, commit shas, MCP server names, and
`ctxpack session stats` aggregates (the last-checkpoint-per-session surface).

**Never** stored — enforced by the generator's `scan_forbidden` (it refuses to
emit on a match) and by `eval-engine/tests/test_ctx_baseline.py`: raw transcript
content, absolute paths, session UUIDs, usernames, env values, or raw commands.

The **label → repo mapping is intentionally NOT committed.** It lives only in the
uncommitted `--repos-config` file. Without it, `repo-a … repo-d` are opaque.

## `manifest-v1-2026-07-15.json`

Initial reference capture (4 repos). It is a snapshot of a specific moment, not a
clean-tree canonical baseline — all four repos show `code_worktree_dirty: true`
(the split-dirty fields make that honest; a single `dirty` flag would have hidden
it). Regenerate on clean trees for a canonical run.

### Runtime-provenance comparison (the step-3 finding)

All four repos resolved the **same** ctxpack runtime (`version 0.5.0`,
`impl_commit fe2685e…`) and captured cleanly (`torn: false`, one attempt each).
The only material configuration divergence is MCP topology:

| label | MCP servers | sets PYTHONPATH |
|-------|-------------|-----------------|
| repo-a, repo-b, repo-d | `ctxpack` | none |
| **repo-c** | `ctxpack`, **`ctxpack-code`** | `ctxpack-code` → **true** |

This pins the Market-Zero-vs-Transmax difference structurally: one repo exposes an
extra `PYTHONPATH`-backed `ctxpack-code` MCP server. It does **not** establish that
this server handled that repo's recorded reads — determining which server served
the reads is open work before treating any repo's config as the one to emulate.
