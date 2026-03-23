# KP_SDLC — Agentic AI Quality & Governance Platform

**Portable, zero-dependency quality enforcement, architecture governance, and auto-fix tooling for agentic AI projects.** 434 tests, 100+ detection rules, 28 auto-fixers, SARIF 2.1.0 output — all stdlib Python, no pip install required.

## The Problem

AI-assisted coding produces code that works in demos but fails in production — unvalidated LLM output, unbounded agent loops, silent data quality issues, prompts without version tracking, and technical debt from accepting AI-generated code without review.

**The goal:** make the right approach the easiest approach. Detect issues, generate fixes, and teach better patterns through corrections — not documentation.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         DETECT                                       │
│                                                                      │
│  ┌──────────────────────┐    ┌────────────────────────────────────┐ │
│  │  Quality Gate (QG)   │    │  Cathedral Keeper (CK)            │ │
│  │  100+ rules, PRS     │    │  16 policies, blast radius,       │ │
│  │  AI/LLM/Prompt/Data  │    │  schema drift, test recommender   │ │
│  └──────────────────────┘    └────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────────────┤
│                          FIX                                         │
│                                                                      │
│  ┌──────────────────────┐    ┌────────────────────────────────────┐ │
│  │  Fix Engine (FE)     │    │  LLM Fix Suggestions              │ │
│  │  28 auto-fixers      │    │  Gold-standard code via Claude/   │ │
│  │  SARIF 2.1.0 output  │    │  OpenAI (feature-toggled)         │ │
│  └──────────────────────┘    └────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────────────┤
│                        REPORT                                        │
│                                                                      │
│  ┌──────────────────────┐    ┌────────────────────────────────────┐ │
│  │  HTML Dashboard      │    │  SARIF → GitHub Code Scanning     │ │
│  │  Radar chart, AI     │    │  PR suggestion blocks             │ │
│  │  section, filters    │    │  GitHub Actions workflows         │ │
│  └──────────────────────┘    └────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

## Components

### Quality Gate (`quality-gate/`)

File-level code quality enforcement with a numeric **Production Readiness Score (PRS)**. 100+ rules across 15 check packs.

| Pack | Rules | Examples |
|------|-------|----------|
| **Foundation** | 15+ | File/function size, TODO/FIXME, debug statements, silent catches, hardcoded secrets |
| **Python** | 10+ | Mutable defaults, bare except, command injection, SQL injection |
| **FastAPI** | 5+ | Sync endpoints, missing response models, unvalidated params |
| **LangChain/LLM** | 8+ | Unbounded graph, missing callbacks, hardcoded models, prompt injection |
| **AI Code Detection** | 5 | Over-commenting, verbose no-op handlers, excessive docstrings, redundant type checks, generic names |
| **LLM Output Safety** | 4 | Unvalidated JSON, direct eval, silent fallbacks, unguarded dict access |
| **Agent Loop Safety** | 3 | while True + LLM, unbounded for-loops, LangGraph without recursion_limit |
| **Prompt Quality** | 4 | No version tracking, system/user concatenation, no structured output, injection vectors |
| **Data Contracts** | 3 | Unvalidated API data, raw dict access, pipeline tasks without retry |
| **Security** | 8+ | SQL interpolation, XSS, credential exposure, secret detection |
| **Databases** | 5+ | N+1 queries, missing timeouts, connection leaks |
| **React/Next.js** | 5+ | useEffect deps, server/client boundaries, unoptimized images |

```bash
python quality-gate/quality_gate.py --root /path/to/repo --json
python quality-gate/quality_gate.py --root . --staged          # pre-commit
python quality-gate/quality_gate.py --root . --sarif report.sarif  # SARIF output
python quality-gate/quality_gate.py --root . --json --autofix  # with fix diffs
```

### Cathedral Keeper (`cathedral-keeper/`)

Architecture governance via import graph analysis. 16 policies + blast radius + schema drift detection + test recommendation.

| Policy | What It Detects |
|--------|----------------|
| `CK-PY-CYCLES` | Import cycles (Tarjan's SCC) |
| `CK-ARCH-DEAD-MODULES` | Files never imported, with unit metadata |
| `CK-ARCH-LAYER-DIRECTION` | Imports violating layer hierarchy |
| `CK-ARCH-DRIFT` | Architectural degradation over time |
| `CK-BLAST-RADIUS` | High fan-in files (changes affect many dependents) |
| `CK-ARCH-TEST-COVERAGE` | Source files with no test imports |
| `CK-ARCH-TEST-ALIGNMENT` | Test files that don't match source structure |
| `CK-DATA-SCHEMA-DRIFT` | Pydantic model breaking changes (removed fields, type changes) |
| `CK-COHERENCE` | QG/CK metric divergence (bidirectional) |
| `CK-RED-TEAM` | Adversarial checks: count drops, suspicious scores, god modules |

**New capabilities:**
- **Test Recommender**: "You changed models.py → run test_auth.py, test_api.py" (BFS reverse import graph)
- **Commit-Aware Blast Radius**: Pre-commit hook showing downstream impact
- **Schema Drift**: Extracts Pydantic models via AST, compares against baseline
- **Severity Gradient**: Context-aware severity based on fan-in, PRS, and test coverage

```bash
python cathedral-keeper/ck.py analyze --root /path/to/repo --blast-radius --verbose
python cathedral-keeper/ck.py analyze --root . --mode diff --base origin/main
python cathedral-keeper/ck.py baseline --root .
```

### Fix Engine (`fix-engine/`)

Auto-fix diff engine with 28 deterministic fixers + optional LLM-generated suggestions for complex findings. Three output modes: `--fix` (apply), `--sarif` (CI), `--suggest` (PR comments).

| Category | Count | Examples |
|----------|-------|----------|
| **Safe** (auto-apply) | 14 | bare_except, mutable_default, no_debug, unused_import, equality_none, missing_encoding, missing_timeout |
| **Review** (suggest) | 14 | regex_hoist, string_concat, command_injection, assert_in_prod, hardcoded_model, missing_response_model |

**LLM Fix Suggestions** (feature-toggled):
- Configure via `.env` file: `ANTHROPIC_API_KEY`, `LLM_MODEL`, `LLM_MAX_FIXES_PER_RUN`
- Gold-standard prompt emphasizing SWE best practices
- Deterministic fixes always tried first (free, fast, reliable)
- LLM only for complex rules: `function_size`, `max_complexity`, `dead_variable`

```bash
python fix-engine/fix_engine.py --qg-report qg.json --fix --safe-only    # apply safe fixes
python fix-engine/fix_engine.py --qg-report qg.json --dry-run            # preview changes
python fix-engine/fix_engine.py --qg-report qg.json --suggest            # PR suggestions
python fix-engine/fix_engine.py --qg-report qg.json --sarif -o report.sarif  # SARIF
```

### HTML Reporting (`reporting/`)

Interactive HTML dashboards combining QG, CK, and Fix Engine results.

- **Radar/spider chart** — 6-dimension quality visualization (accurate formulas)
- **AI-Generated Code Analysis section** — detection + "How to Generate Better AI Code" guidance
- **Fix suggestions inline** — Auto-Fix (green) and AI Suggestion (purple) badges per finding
- **Filter buttons** — All Issues, Errors Only, Has Auto-Fix, Has AI Suggestion, No Fix Available
- **Collapsible architecture findings** — grouped by policy
- **Lead Reviewer Narrative** — auto-generated analysis summary
- **Health score** (0-100) with letter grades

```bash
python reporting/generate_html_reports.py --root /path/to/repo
python reporting/generate_html_reports.py --root /path/to/repo --llm-fixes  # with LLM suggestions
```

## Quick Start

```bash
# Clone
git clone https://github.com/cryogenic22/KP_SDLC.git
cd KP_SDLC

# Install (optional — also works without installing)
pip install .

# Run full analysis
python quality-gate/quality_gate.py --root /path/to/repo --json --report
python cathedral-keeper/ck.py analyze --root /path/to/repo --blast-radius --no-qg --verbose
python reporting/generate_html_reports.py --root /path/to/repo --title "Quality Report"

# Or use the Makefile
make test          # run all 434 tests
make report        # full QG+CK+HTML report
make sarif         # SARIF output for GitHub Code Scanning
```

## Configuration

### `.env` file (LLM settings)

```bash
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
LLM_MODEL=claude-3-haiku-20240307
LLM_MAX_FIXES_PER_RUN=20
LLM_MAX_TOKENS=1024
```

### `.quality-gate.json` (rule overrides)

```json
{
  "rules": {
    "function_size": { "severity": "warning", "max_lines": 80 },
    "db_call_in_loop": { "enabled": false }
  }
}
```

## Key Design Principles

1. **Zero external dependencies** — stdlib only. Drop into any project without pip install.
2. **Detection + Fix + Teach** — don't just flag issues, generate fixes and explain why.
3. **Evidence-first findings** — every violation backed by file, line, snippet, and fix suggestion.
4. **Measurement integrity** — golden-input tests, silent-failure detection, cross-metric coherence, red-team adversarial validation.
5. **Feature-toggled LLM** — deterministic fixes are always free. LLM is opt-in via `.env`.

## Test Suite

434 tests across 4 components, all passing:

| Component | Suites | Tests |
|-----------|--------|-------|
| Quality Gate | 18 | 181 |
| Cathedral Keeper | 14 | 142 |
| Fix Engine | 6 | 89 |
| Reporting | 1 | 22 |
| **Total** | **39** | **434** |

```bash
# Run all tests
make test

# Or individually
cd quality-gate && python -m pytest tests/
cd cathedral-keeper && for f in tests/test_*.py; do python "$f"; done
cd fix-engine && python -m pytest tests/
cd reporting && python tests/test_reporting.py
```

## GitHub Actions

Two workflow templates in `fix-engine/workflows/`:

- **`sarif-upload.yml`** — Runs QG+CK on PR, uploads SARIF to GitHub Code Scanning (findings appear as inline PR annotations)
- **`auto-fix.yml`** — Triggered by `autofix` label on PR, applies safe fixes and pushes a commit

## License

Internal tooling — SynaptyX / Scriptiva.
