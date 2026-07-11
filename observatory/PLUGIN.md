# Pluggable KP_SDLC component boundary

Use the single entry point for this repository:

```bash
python -m observatory install-hooks
python -m observatory serve
```

`ObservatoryPlugin` composes the stable base snapshot with zero or more memory
adapters. `CtxPackMemoryAdapter` is the reference implementation. An adopting
repository may supply another adapter implementing:

```python
class MemoryAdapter(Protocol):
    provider_id: str
    def assess(self) -> dict: ...
```

The CtxPack adapter assesses all mechanisms required for repository memory:

- checkpoint ledger presence and per-session archives/gists;
- pre-compaction capture;
- session-start gist injection;
- stop and session-end finalization;
- MCP structured-recall availability;
- conflicts, lint state, and exact-literal fidelity;
- structured ledger reads versus raw-transcript fallbacks;
- context activity pressure and checkpoint history.

CtxPack remains the system of record. Observatory does not copy its ledger,
perform recall, compact transcripts, or rewrite gists; it reports whether those
mechanisms are configured, healthy, and actually used.

Distribution into another repository has two supported shapes:

1. Install `kp-sdlc` and run the packaged `kp-observatory` console script.
2. Vendor the stdlib-only `observatory/` directory through `sdlc init`.

Observatory now ships from the single root `kp-sdlc` distribution — it is listed
in the root `pyproject.toml` alongside every other component (there is no
separate `observatory/pyproject.toml`), and its `static/index.html` travels as
package data so the packaged `kp-observatory serve` works from an installed
wheel. Vendoring still preserves KP_SDLC's zero-dependency adoption story
because the package is stdlib-only.

**Build note.** The wheel builds cleanly through the PEP 517
`setuptools.build_meta` backend (verified: `python -m build --wheel`). A direct,
non-isolated `setup.py`/`egg_info` build can fail with
`ModuleNotFoundError: No module named 'pkg_resources'` — that is an *environment*
fault, not a packaging one: a globally-installed PBR registers an
`egg_info.writers` entry point that imports `pkg_resources`, which setuptools
≥81 removed. Build in isolation (as `python -m build` does) or in an environment
without a stray PBR; do not work around it by mutating global packages.

