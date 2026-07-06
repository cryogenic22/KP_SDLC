# Quality Gate

**Portable Code Quality Enforcement System**

Drop this into any codebase for instant, enforceable quality standards equivalent to senior Google engineers.

---

## Quick Start

```bash
# 1. Copy quality-gate/ folder to your project root
cp -r quality-gate/ /path/to/your/project/

# 2. Install git hooks (recommended: pre-commit)
cd /path/to/your/project
cp quality-gate/.pre-commit-config.yaml .pre-commit-config.yaml
pre-commit install

# 3. Done! Quality checks now run automatically on every commit.
```

If you don't use `pre-commit`, you can use the bundled installers (`quality-gate/install.sh` or `quality-gate/install.ps1`).

---

## What Gets Enforced

### Rule Packs (Extensible)

This folder includes optional modular rule packs under `quality-gate/qg/` (security/test heuristics).
They are disabled by default and can be enabled via `/.quality-gate.json` per repo/team.

### Production Readiness Score (PRS) - Hard Merge Gate

Every checked file receives a numeric score and must meet the minimum:

#### PRS Formula

```
PRS = 100 - (errors * error_weight) - (warnings * warning_weight)

Default weights:
  - error_weight = 10
  - warning_weight = 2
  - min_score = 85
```

#### Score Interpretation

| Score | Status | Guidance |
|-------|--------|----------|
| 95-100 | Excellent | Ship confidently |
| 85-94 | Good | Minor improvements suggested |
| 70-84 | Needs Work | Address issues before merge |
| <70 | Poor | Requires significant refactoring |

#### Example Calculations

```
File with 1 error, 2 warnings:
PRS = 100 - (1 * 10) - (2 * 2) = 100 - 10 - 4 = 86 (PASS)

File with 2 errors, 3 warnings:
PRS = 100 - (2 * 10) - (3 * 2) = 100 - 20 - 6 = 74 (FAIL)
```

If a file falls below the minimum, a blocking issue is emitted:

```
[E] Line 1: [prs_score] PRS 74.0/100 below minimum 85.
```

#### PRS Configuration

```json
{
  "prs": {
    "enabled": true,
    "min_score": 85,
    "error_weight": 10,
    "warning_weight": 2
  }
}
```

#### Disabling PRS

```bash
# CLI flag
python quality-gate/quality_gate.py --no-prs

# Or in config
{ "prs": { "enabled": false } }
```

**See Also:** [Quality Gate Adoption Guide](../docs/quality-gate-adoption-guide.md) for team integration.

---

### Hard Blocks (Errors - Cannot Commit)

| Rule | What It Catches | Why It Matters |
|------|-----------------|----------------|
| `file_size` | Files > 500 lines | Mega-files are unmaintainable |
| `function_size` | Functions > 50 lines | Long functions hide bugs |
| `no_todo_fixme` | TODO/FIXME without issue link | Orphaned todos never get done |
| `no_debug_statements` | console.log, print(), debugger | Debug code in production |
| `no_type_escape` | `any`, `@ts-ignore`, `# type: ignore` | Type system bypasses |
| `no_silent_catch` | `except: pass`, `catch(e) {}` | Swallowed errors |
| `no_hardcoded_secrets` | Passwords, API keys, tokens | Security vulnerabilities |
| `prs_score` | PRS < minimum score | Quantitative quality bar (>= 85) |

### Soft Warnings (Won't Block, But Tracked)

| Rule | What It Catches |
|------|-----------------|
| `max_complexity` | Cyclomatic complexity > 10 |
| `no_duplicate_code` | Same function in multiple files |
| `naming_conventions` | Inconsistent naming patterns |
| `max_parameters` | Functions with > 5 parameters |
| `max_nesting` | Code nested > 4 levels deep |

---

## Team Protocol

### For Developers

**Before Every Commit:**

1. Quality gate runs automatically (blocks if issues found)
2. Fix any errors shown
3. Warnings are allowed but tracked

**When You See an Error:**

```
[E] Line 42: [file_size] File has 523 lines (max: 500). Split into smaller modules.
```

**How to Fix:**
1. Extract logical sections into separate files
2. Move utility functions to shared modules
3. Split components into smaller pieces

**Exceptions:**
- If a file legitimately needs to be large, add it to `exceptions` in config
- Requires team lead approval

### For Code Reviewers

**Checklist Before Approving:**

- [ ] Quality gate passes (green check in CI)
- [ ] No new warnings introduced
- [ ] File sizes remain reasonable
- [ ] No obvious duplication
- [ ] Types are properly used (no `any`)

### For Tech Leads

**Weekly Review:**

1. Check `.quality-reports/` for trends
2. Review warning counts - are they increasing?
3. Identify candidates for refactoring
4. Update config if rules need tuning

---

## Configuration

Defaults live in `quality-gate/quality-gate.config.json`. To override per-repo without forking the folder, add a repo-root file:

- `.quality-gate.json` (recommended)

Example override:

```json
{
  "rules": {
    "file_size": {
      "enabled": true,
      "max_lines": 500,
      "exceptions": ["generated/*.ts", "schemas.py"]
    },
    "no_debug_statements": {
      "enabled": true,
      "exceptions": ["console.error"]
    }
  },
  "prs": { "min_score": 85 },
  "thresholds": {
    "error_count": 0,
    "warning_count": 10
  }
}
```

### Path Configuration

```json
{
  "paths": {
    "include": ["apps/", "packages/", "src/"],
    "exclude": ["node_modules/", "dist/", "*.min.js"]
  }
}
```

### Team-Specific Overrides

```json
{
  "team_overrides": {
    "ui_team": {
      "paths": ["apps/web/"],
      "rules": {
        "max_complexity": { "cyclomatic_max": 15 }
      }
    }
  }
}
```

---

## CLI Usage

```bash
# Check all files
python quality-gate/quality_gate.py

# Check staged files only (used by pre-commit)
python quality-gate/quality_gate.py --staged

# Check specific files
python quality-gate/quality_gate.py apps/web/components/Button.tsx

# Verbose output with suggestions
python quality-gate/quality_gate.py --verbose

# Generate JSON report (for CI)
python quality-gate/quality_gate.py --json > report.json

# PowerShell note: `>` writes UTF-16 by default. Prefer:
# python quality-gate/quality_gate.py --json | Out-File -Encoding utf8 report.json

# Strict mode (fail on warnings too)
python quality-gate/quality_gate.py --strict

# Override PRS minimum score
python quality-gate/quality_gate.py --staged --min-score 90

# Save detailed report
python quality-gate/quality_gate.py --report

# Audit mode helpers
python quality-gate/quality_gate.py --mode audit --top 20   # Lowest PRS (highest slop)
```

### Summarize JSON Reports (Optional)

```bash
# Summarize a `--json` report (handles UTF-16/UTF-8 output)
python quality-gate/tools/summarize_audit.py .quality-gate.report.json --top 15
```

---

## Baseline & Ratchet (Clean-as-You-Code)

Adopting the gate on an existing (brownfield) codebase usually fails on
day one: dozens of legacy files sit below the PRS floor, and the team
either lowers the bar or turns the gate off. The baseline unlocks
adoption without either: **legacy debt is tolerated, new debt is
blocked, and every file may only get better.**

```bash
# 1. Snapshot the current per-file state (run locally, NOT in CI)
python quality-gate/quality_gate.py --mode baseline

# 2. Commit the generated .quality-gate.baseline.json (it is a reviewable diff)

# 3. Enforce the ratchet in check mode
python quality-gate/quality_gate.py --mode check --baseline .quality-gate.baseline.json
```

Ratchet semantics, per scanned file:

| Situation | Outcome |
|-----------|---------|
| In baseline, not regressed | Passes — even below the PRS floor (known debt is tolerated) |
| In baseline, regressed (more errors, more warnings, or lower PRS) | Blocked with ERROR rule `baseline_ratchet` naming the metric (e.g. `errors 2 > baselined 1`) |
| Not in baseline (new file) | Must meet the normal PRS floor (`prs_score`) |
| Vetoed (critical/security finding) | Always blocked — a baseline never masks a security veto |
| In baseline but not scanned | Ignored (safe for diff-scoped CI runs) |

Guarantees:

- **The baseline is never auto-tightened or auto-written.** It changes
  only via an explicit `--mode baseline` re-run, so every loosening or
  tightening is a reviewable git diff. `check`/`audit` never write it.
- **CI cannot regenerate it.** `--mode baseline` refuses to write when a
  CI environment is detected (`CI`/`GITHUB_ACTIONS`) unless
  `--allow-ci-baseline` is passed explicitly — and that flag would be
  visible in any workflow diff, which is owner-review-gated.
- **Every write is provenance-stamped** (`generated_at`, `commit`,
  `generated_by`), so any regeneration is attributable.
- **Config redirects are review-gated too.** The runtime config overrides
  the engine auto-discovers at the scan root (`.quality-gate.json`,
  `quality-gate.config.json`) belong on the protected surface (CODEOWNERS)
  alongside the baseline itself — otherwise an unreviewed override could
  redirect `baseline.path` to a fabricated baseline. This repo protects
  both; keep that pairing when adopting the gate elsewhere.
- **Fail-closed loading.** A corrupt baseline raises `baseline_unreadable`
  and an explicitly requested missing one raises `baseline_missing` —
  the gate never silently runs ratchet-free.
- **Cross-platform keys.** File keys are forward-slash-normalized on both
  write and compare, so a baseline written on Windows matches in POSIX CI.
- The current (review-gated) config always supplies the PRS floor; the
  `min_score` stored in the baseline is informational only.

Write baselines from **full scans** (the default for `--mode baseline`):
cross-file checks can under-count on partial scans, so the authoritative
ratchet run is the full one. Note that the ratchet governs the per-file
PRS floor; the global `thresholds.error_count` still applies to
error-severity findings, so brownfield repos typically pair the baseline
with a per-repo `thresholds` override while errors are burned down.

Config (dormant until the baseline file exists; the `--baseline` flag
overrides it):

```json
{
  "baseline": {
    "path": ".quality-gate.baseline.json"
  }
}
```

The JSON report (`--json`) gains an additive `baseline` block:
`{path, status, commit, matched, regressed}`.

---

## CI/CD Integration

### GitHub Actions

Copy `quality-gate/workflows/quality-gate.yml` to `.github/workflows/`:

```bash
mkdir -p .github/workflows
cp quality-gate/workflows/quality-gate.yml .github/workflows/
```

The workflow will:
- Run quality gate on every PR
- Block merge if errors found
- Comment on PR with issues
- Upload quality report as artifact

## Adoption Guide

- `docs/quality-gate-adoption-guide.md` (this repo)

## Example Configs

- `quality-gate/examples/` (copy into `/.quality-gate.json` in your repo)

### GitLab CI

Add to `.gitlab-ci.yml`:

```yaml
quality-gate:
  stage: test
  script:
    - python quality-gate/quality_gate.py --strict
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
```

### Azure DevOps

Add to `azure-pipelines.yml`:

```yaml
- task: PythonScript@0
  inputs:
    scriptSource: 'filePath'
    scriptPath: 'quality-gate/quality_gate.py'
    arguments: '--strict'
  displayName: 'Quality Gate'
```

---

## Fixing Common Issues

### File Too Large

**Error:** `File has 823 lines (max: 500)`

**Fixes:**
1. **Extract Components:** Move UI components to separate files
2. **Extract Hooks:** Move React hooks to `hooks/` folder
3. **Extract Utils:** Move helper functions to `utils/` or `lib/`
4. **Extract Types:** Move TypeScript types to `types.ts`
5. **Split by Feature:** Break into feature-specific modules

### Function Too Long

**Error:** `Function 'handleSubmit' is 78 lines (max: 50)`

**Fixes:**
1. **Extract Steps:** Break into step functions (validateInput, processData, etc.)
2. **Use Early Returns:** Reduce nesting with guard clauses
3. **Extract Conditions:** Move complex conditions to named functions

### Type Escape Found

**Error:** `Type escape found: 'as any'`

**Fixes:**
1. **Define Proper Type:** Create interface/type for the data
2. **Use Type Guard:** Create type checking function
3. **Use Unknown:** Replace `any` with `unknown` and narrow

### Silent Catch

**Error:** `Silent exception catch (except: pass)`

**Fixes:**
```python
# Bad
try:
    risky_operation()
except:
    pass

# Good
try:
    risky_operation()
except SpecificError as e:
    logger.warning(f"Operation failed: {e}")
    # Handle gracefully or re-raise
```

---

## Architecture

```
quality-gate/
├── quality_gate.py          # Main quality checker (portable Python)
├── quality-gate.config.json # Default config (portable)
├── check_commit_msg.py      # Commit message format checker
├── .pre-commit-config.yaml  # Pre-commit hooks configuration
├── install.sh               # One-command installer
├── workflows/
│   └── quality-gate.yml     # GitHub Actions workflow
└── README.md                # This file
```

### Design Principles

1. **Zero Dependencies:** Pure Python, no pip install needed
2. **Portable:** Copy folder to any project, run installer
3. **Configurable:** JSON config for team customization
4. **Enforceable:** Blocks commits/merges on failures
5. **Fast:** Checks staged files only for pre-commit

---

## Roadmap

- [ ] Auto-fix capability for simple issues
- [ ] VS Code extension for real-time feedback
- [ ] Trend dashboards (quality over time)
- [ ] Custom rule definitions
- [ ] AI-powered suggestions

---

## License

MIT - Use freely in any project.

---

## Credits

Designed for teams that want Google-level code quality without Google-level overhead.
