# KP_SDLC — Developer Quality Tooling Ecosystem

**Portable, zero-dependency quality enforcement tools designed to be embedded in any Python/TypeScript codebase.** These tools run locally, in CI, or as Claude Code hooks — providing continuous quality feedback from the moment code is written to when it ships.

## The Problem

Development by junior engineers and AI-assisted coding produces code that works in demos but fails in production — inconsistent patterns, silent data quality issues, architectural drift, and technical debt from accepting code without understanding it.

**The goal:** make the right approach the easiest approach, so guardrails feel like productivity tools rather than bureaucracy.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    WHILE CODE IS WRITTEN                         │
│                                                                  │
│  ┌──────────────────────┐    ┌───────────────────────────────┐  │
│  │  Quality Gate (QG)   │    │  Claude Code Hooks            │  │
│  │  100+ rules, PRS     │    │  Real-time enforcement        │  │
│  └──────────────────────┘    └───────────────────────────────┘  │
├─────────────────────────────────────────────────────────────────┤
│                    AFTER CODE IS WRITTEN                         │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────┐ │
│  │ Cathedral    │  │ Blast-Radius │  │  HTML Reporting       │ │
│  │ Keeper (CK)  │  │ Analysis     │  │  Dashboard            │ │
│  └──────────────┘  └──────────────┘  └───────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

## Components

### Quality Gate (`quality-gate/`)

File-level code quality enforcement with a numeric **Production Readiness Score (PRS)**. Zero external dependencies — stdlib only.

**What it checks (100+ rules across 10+ technology packs):**

| Pack | Examples |
|------|----------|
| **Foundation** | File/function size, TODO/FIXME, debug statements, silent catches, hardcoded secrets |
| **Python** | Mutable defaults, bare except, command injection, SQL injection |
| **FastAPI** | Sync endpoints with I/O, missing response models, unvalidated params |
| **LangChain/LLM** | Unbounded graph execution, missing callbacks, hardcoded model names, prompt injection |
| **AI Code Smells** | Dead variables, nested enumeration, redundant recomputation, dead parameters |
| **Databases** | N+1 queries, missing timeouts, connection leaks |
| **Security** | SQL string interpolation, XSS vectors, credential exposure |
| **React/Next.js** | useEffect missing deps, server/client boundary violations, unoptimized images |

**PRS Formula:** `100 - (errors × 10) - (warnings × 2)`, minimum 85 to pass.

```bash
# Run on a repo
python quality-gate/quality_gate.py --root /path/to/repo --json

# Run on staged files (pre-commit)
python quality-gate/quality_gate.py --root . --staged
```

### Cathedral Keeper (`cathedral-keeper/`)

Architecture governance via import graph analysis. Detects cycles, dead modules, boundary violations, architectural drift, and now includes blast-radius analysis and test coverage detection.

**Policies:**

| Policy | What It Detects |
|--------|----------------|
| `CK-PY-CYCLES` | Import cycles (Tarjan's SCC algorithm) |
| `CK-ARCH-DEAD-MODULES` | Files never imported, not matching entry-point patterns |
| `CK-ARCH-LAYER-DIRECTION` | Imports violating layer hierarchy (e.g., data layer importing UI) |
| `CK-ARCH-DRIFT` | Architectural degradation over time (baseline comparison) |
| `CK-BLAST-RADIUS` | High fan-in files — changes affect many dependents |
| `CK-ARCH-TEST-COVERAGE` | Source files with zero TESTED_BY edges (no test imports them) |
| `CK-COHERENCE` | QG/CK metric divergence (catches measurement system failures) |
| `CK-RED-TEAM` | Adversarial checks: finding count drops, suspiciously clean results, god modules |

```bash
# Full analysis with blast-radius
python cathedral-keeper/ck.py analyze --root /path/to/repo --blast-radius --verbose

# Diff mode (PR review)
python cathedral-keeper/ck.py analyze --root . --mode diff --base origin/main

# Create baseline for drift tracking
python cathedral-keeper/ck.py baseline --root .
```

### HTML Reporting (`reporting/`)

Generates interactive HTML dashboards combining QG and CK results. Features:

- **Radar/spider chart** — 6-dimension quality visualization
- **Collapsible architecture findings** — grouped by policy, click to expand
- **Clickable navigation** — jump to any policy or section
- **Overall health score** (0-100) with letter grades
- **PRS table** with pass/fail bars per file
- **Recommended actions** prioritized by severity

```bash
# Generate report
python reporting/generate_html_reports.py --root /path/to/repo --title "My Report"
```

## Key Design Principles

1. **Zero external dependencies** — stdlib only. Drop into any project without installing packages.
2. **Configuration-driven** — all thresholds, rules, and policies configurable via JSON.
3. **Evidence-first findings** — every violation backed by file, line, snippet, and fix suggestion.
4. **Measurement integrity** — golden-input tests for the PRS formula itself, silent-failure detection, cross-metric coherence checks, and red-team adversarial validation.
5. **Portable** — copy `quality-gate/` or `cathedral-keeper/` into any repo and run immediately.

## Measurement Integrity (Lessons from CtxPack)

These tools include safeguards against their own measurement system failing:

- **PRS formula has golden-input tests** — if the formula changes, 16 tests break immediately
- **Silent failure detection** — if QG crashes, CK emits a WARNING finding instead of silently returning "no issues"
- **Cross-metric coherence** — flags when QG says "great code" but CK says "terrible architecture"
- **Red team checks** — RT1: finding count drops, RT2: suspiciously high PRS, RT3: zero findings on large codebase, RT4: god module detection
- **RetryFailure sentinel** — external calls never return `{}` on failure (which looks like "no issues")

## Quick Start

```bash
# Clone
git clone https://github.com/cryogenic22/KP_SDLC.git
cd KP_SDLC

# Run QG on any repo
python quality-gate/quality_gate.py --root /path/to/your/repo --json --report

# Run CK on any repo
python cathedral-keeper/ck.py analyze --root /path/to/your/repo --blast-radius --verbose

# Generate HTML dashboard
python reporting/generate_html_reports.py --root /path/to/your/repo --title "Quality Report"
```

## Embedding in Your Project

Copy the tool directories into your repo:

```bash
cp -r quality-gate/ /your/repo/quality-gate/
cp -r cathedral-keeper/ /your/repo/cathedral-keeper/

# Add to pre-commit
echo 'python quality-gate/quality_gate.py --root . --staged' >> .git/hooks/pre-commit

# Add to CI
# In .github/workflows/quality.yml:
#   - run: python quality-gate/quality_gate.py --root . --json --report --strict
#   - run: python cathedral-keeper/ck.py analyze --root . --blast-radius
```

## Test Suite

All modules are TDD-built with comprehensive test coverage:

```bash
# QG tests
cd quality-gate
python tests/test_metric_sanity.py        # 16 tests — PRS formula golden inputs
python tests/test_duplicate_exemptions.py  # 8 tests  — cross-stack exemption
python tests/test_contextual_size.py       # 19 tests — language-specific limits
python tests/test_useeffect_deps.py        # 8 tests  — useEffect enforcement
python tests/test_recomputation_fp.py      # 11 tests — false positive reduction

# CK tests
cd cathedral-keeper
python tests/test_phase1_retry.py          # 12 tests — retry wrapper
python tests/test_phase1_qg_integration.py # 8 tests  — silent failure detection
python tests/test_coherence.py             # 9 tests  — cross-metric coherence
python tests/test_blast_radius.py          # 15 tests — BFS blast-radius
python tests/test_cache.py                 # 11 tests — SQLite graph cache
python tests/test_test_coverage.py         # 9 tests  — TESTED_BY edges
python tests/test_red_team.py              # 11 tests — adversarial checks
python tests/test_heat_map.py              # 11 tests — risk-adjusted scoring
python tests/test_mitigations.py           # 9 tests  — mitigation detection
python tests/test_trend_scoring.py         # 9 tests  — ratchet-aware trends
```

**Total: 166 tests, all passing.**

## Documentation

| Document | Description |
|----------|-------------|
| `cathedral-keeper/SDLC_Vision.md` | Full SDLC tooling strategy — 8 components across 3 development phases |
| `cathedral-keeper/README.md` | CK-specific documentation |
| `quality-gate/README.md` | QG-specific documentation |
| `CTX_SDLC_Integration_Brief.md` | Integration brief from CtxPack harness engineering research |
| `eval_runner.md` | SynProbe evaluation tool design spec |
| `QG_ext_rules.md` | Extended QG rule definitions for all technology packs |

## License

Internal tooling — SynaptyX / Scriptiva.
