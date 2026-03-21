# Cathedral Keeper

Cathedral Keeper (CK) is a portable **architecture governance** module: policy-as-code + evidence-first findings.

It is designed to complement (not replace) `quality-gate/`:
- `quality-gate/`: fast deterministic merge gate (file-level PRS + rule checks + per-file patterns)
- **Cathedral Keeper**: cross-file architecture governance (import cycles, boundary enforcement, layer direction) + consolidated reporting

### Policies

| Policy ID | Category | What It Does |
|-----------|----------|-------------|
| CK-PY-CYCLES | Import graph | Detect import cycles via Tarjan's SCC algorithm |
| CK-PY-BOUNDARIES | Import graph | Enforce module boundary rules |
| CK-ARCH-LAYER-DIRECTION | Import graph | Enforce one-way dependency flow between architectural layers |
| CK-ARCH-DEAD-MODULES | Import graph | Find orphaned modules with zero incoming imports |
| CK-ARCH-DRIFT | Evolutionary | Track and score architectural change from a baseline snapshot |
| CK-ARCH-SERVICE-BOUNDARIES | Import graph | Enforce cross-service interface contracts |
| CK-ARCH-CONFIG-SPRAWL | Source scan | Detect scattered/inconsistent configuration access |
| CK-ARCH-TEST-ALIGNMENT | Structural | Verify test directory structure mirrors source structure |
| CK-ARCH-ENV-PARITY | Source scan | Detect environment-conditional code and undocumented env vars |
| CK-ARCH-DEPENDENCY-HEALTH | Dependency files | Flag overlapping, unused, and undeclared dependencies |

Three former CK policies (`CK-PY-ASYNC-BLOCKING`, `CK-PY-REQUESTS-TIMEOUT`, `CK-PY-SYSPATH`) have been migrated to quality-gate as per-file rules. CK focuses exclusively on cross-file architecture governance and project-level structural health.

## Integrations (optional, not dependencies)

CK can integrate with SDLC tools by contract, without depending on them:
- `quality_gate` integration (ingests PRS/issue JSON if `quality-gate/` exists)
- `external_findings_json` integration (run any command that outputs CK Findings JSON)

## Requirements

- Python 3.10+
- No network access required (stdlib only)

## Quick Start (this repo)

```bash
python medcontent-ai-platform/cathedral-keeper/ck.py analyze --root .
```

Outputs:
- Markdown report: `.quality-reports/cathedral-keeper/report.md`
- JSON report: `.quality-reports/cathedral-keeper/report.json`

## Modes

- Repo sweep (full): `ck.py analyze --root . --mode repo`
- PR/diff sweep (changed-files-only): `ck.py analyze --root . --mode diff`
- Disable quality-gate ingestion: `ck.py analyze --root . --no-qg`
- Create/update baseline: `ck.py baseline --root .`

## Notes

- Architecture/value analysis: `medcontent-ai-platform/cathedral-keeper/ANALYSIS.md`

## Portability

To reuse in another repo:
1. Copy `cathedral-keeper/` to your repo root.
2. Add a repo override config at `/.cathedral-keeper.json` (optional).
3. Run `python cathedral-keeper/ck.py analyze --root .`.

### Python Root Configuration

CK auto-discovers Python package roots by scanning the top two directory levels for `__init__.py`. For repositories with non-standard layouts, configure roots explicitly in `.cathedral-keeper.json`:

```json
{
  "python_roots": [
    { "prefix": "src", "path": "myproject/src" },
    { "prefix": "backend", "path": "myproject/backend" }
  ]
}
```

Each entry maps a module prefix to a directory path (relative to repo root). CK uses these to build its import graph and resolve internal imports.
