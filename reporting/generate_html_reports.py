#!/usr/bin/env python3
"""
Quality & Architecture HTML Report Generator
=============================================
Reads quality-gate and cathedral-keeper JSON reports for each discovered
repository and produces a single, well-designed HTML report per repo.

Usage:
    # Auto-discover repos under a workspace directory
    python generate_html_reports.py --root /path/to/workspace

    # Single repo that already has .quality-reports/
    python generate_html_reports.py --root /path/to/my-repo

    # Explicit repo list
    python generate_html_reports.py --repos /path/repo1 /path/repo2

    # Custom output directory and branding
    python generate_html_reports.py --root . --out ./reports --title "My Quality Report"
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from collections import Counter, defaultdict

# Allow running both as ``python reporting/generate_html_reports.py`` from the
# KP_SDLC root and as ``python generate_html_reports.py`` from inside reporting/.
_THIS_DIR = Path(__file__).resolve().parent
if _THIS_DIR not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from __init__ import (  # noqa: E402  (reporting package helpers)
    load_json, discover_repos, infer_friendly_name, infer_tech_stack,
    health_score, health_color, prs_grade, esc,
)


SEVERITY_ORDER = {"blocker": 0, "error": 1, "high": 2, "medium": 3, "warning": 4, "low": 5, "info": 6}
SEVERITY_COLORS = {
    "blocker": "#dc2626", "error": "#dc2626", "high": "#ea580c",
    "medium": "#d97706", "warning": "#d97706", "low": "#2563eb", "info": "#6b7280",
}
SEVERITY_BG = {
    "blocker": "#fef2f2", "error": "#fef2f2", "high": "#fff7ed",
    "medium": "#fffbeb", "warning": "#fffbeb", "low": "#eff6ff", "info": "#f9fafb",
}


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def strip_repo_prefix(filepath, repo_name):
    """Remove the repo folder prefix from file paths."""
    filepath = filepath.replace("\\", "/")
    prefix = repo_name + "/"
    if filepath.startswith(prefix):
        return filepath[len(prefix):]
    return filepath


def build_qg_file_issues(qg_data, repo_name):
    """Group QG issues by file."""
    files = defaultdict(list)
    for issue in qg_data.get("issues", []):
        f = strip_repo_prefix(issue.get("file", ""), repo_name)
        files[f].append(issue)
    return dict(files)


def build_qg_rule_counts(qg_data):
    """Count issues per rule."""
    counts = Counter()
    for issue in qg_data.get("issues", []):
        counts[issue.get("rule", "unknown")] += 1
    return counts


def build_prs_table(qg_data, repo_name):
    """Build sorted PRS data."""
    rows = []
    for filepath, data in qg_data.get("prs", {}).items():
        clean = strip_repo_prefix(filepath, repo_name)
        rows.append({
            "file": clean,
            "score": data.get("score", 0),
            "min_score": data.get("min_score", 85),
            "errors": data.get("errors", 0),
            "warnings": data.get("warnings", 0),
            "passed": data.get("score", 0) >= data.get("min_score", 85),
        })
    rows.sort(key=lambda r: r["score"])
    return rows


# ---------------------------------------------------------------------------
# Narrative generator
# ---------------------------------------------------------------------------

def generate_narrative(friendly_name, tech_stack, qg_data, ck_data, prs_rows, file_issues, qg_rule_counts, health):
    """Generate a lead reviewer narrative synthesizing all findings."""
    qg_stats = qg_data.get("stats", {}) if qg_data else {}
    ck_findings = ck_data.get("findings", []) if ck_data else []
    files_checked = qg_stats.get("files_checked", 0)
    lines_checked = qg_stats.get("lines_checked", 0)
    total_errors = qg_stats.get("error", 0)
    total_warnings = qg_stats.get("warning", 0)
    prs_failed = qg_stats.get("prs_files_failed", 0)
    prs_scored = qg_stats.get("prs_files_scored", 0)
    prs_pass_rate = round((prs_scored - prs_failed) / prs_scored * 100, 1) if prs_scored else 0

    all_scores = [r["score"] for r in prs_rows]
    avg_prs = round(sum(all_scores) / len(all_scores), 1) if all_scores else 0

    worst_files = prs_rows[:5] if len(prs_rows) >= 5 else prs_rows
    failing_files = [r for r in prs_rows if not r["passed"]]

    # ---- OVERALL FEEDBACK ----
    paras = []
    if health >= 80:
        verdict = "in reasonable shape, with some areas needing attention"
    elif health >= 60:
        verdict = "showing moderate quality concerns that should be addressed before the next milestone"
    elif health >= 40:
        verdict = "carrying significant technical debt that poses risk to maintainability and reliability"
    else:
        verdict = "in a state that requires urgent remediation before any new feature work continues"

    paras.append(
        f"This is a review of the <strong>{esc(friendly_name)}</strong> codebase ({esc(tech_stack)}), "
        f"covering {files_checked} files and {lines_checked:,} lines of code. "
        f"The repository scored <strong>{health}/100</strong> on overall health and is {verdict}."
    )

    if prs_scored:
        paras.append(
            f"Of the {prs_scored} files scored for production readiness, {prs_scored - prs_failed} passed "
            f"the minimum threshold of 85 ({prs_pass_rate}% pass rate). The average PRS across all files is "
            f"<strong>{avg_prs}</strong>. "
            + (f"The worst offenders -- files scoring below 50 -- need immediate attention as they represent "
               f"concentrated pockets of risk: "
               + ", ".join(f"<code>{esc(r['file'].split('/')[-1])}</code> ({r['score']})"
                           for r in worst_files if r['score'] < 50)
               + "."
               if any(r['score'] < 50 for r in worst_files) else
               "No files scored below 50, which is a positive signal, but the failing files still need work.")
        )

    # ---- KEY THEMES ----
    themes = []

    fn_size_errors = qg_stats.get("error_function_size", 0)
    file_size_errors = qg_stats.get("error_file_size", 0)
    if fn_size_errors > 0 or file_size_errors > 0:
        theme_text = "<strong>Monolithic Functions and Files.</strong> "
        parts = []
        if fn_size_errors:
            parts.append(f"{fn_size_errors} functions exceed the 50-line limit")
        if file_size_errors:
            parts.append(f"{file_size_errors} files exceed the 800-line limit")
        theme_text += " and ".join(parts) + ". "
        theme_text += (
            "Large functions are the single biggest contributor to low PRS scores in this repo. "
            "They tend to accumulate complexity, make testing difficult, and create merge conflicts. "
            "The pattern to follow: one function does one thing. Extract validation, transformation, "
            "and I/O into separate named helpers. This is not about arbitrary line counts -- it is "
            "about cognitive load and testability."
        )
        themes.append(theme_text)

    complexity_count = qg_stats.get("warning_max_complexity", 0)
    if complexity_count >= 10:
        themes.append(
            f"<strong>High Cyclomatic Complexity.</strong> "
            f"{complexity_count} functions exceed the complexity threshold (max: 10). "
            f"High complexity means more execution paths, which means more places for bugs to hide "
            f"and more test cases needed for coverage. The fix is straightforward: use early returns "
            f"to eliminate nesting, extract conditional branches into well-named predicate functions, "
            f"and prefer lookup tables/dicts over long if/elif chains."
        )

    recomp = qg_stats.get("warning_redundant_recomputation", 0)
    if recomp >= 20:
        themes.append(
            f"<strong>Redundant Recomputation.</strong> "
            f"{recomp} instances of repeated identical expressions were detected. "
            f"This pattern typically indicates copy-paste development or insufficient refactoring. "
            f"When you call the same function with the same arguments multiple times, store the result "
            f"in a variable. It improves readability, reduces bugs when logic changes, and in some "
            f"cases has meaningful performance implications (especially for DB or API calls)."
        )

    dead_vars = qg_stats.get("warning_dead_variable", 0)
    dead_params = qg_stats.get("warning_dead_parameters", 0)
    dead_modules = sum(1 for f in ck_findings if f.get("policy_id") == "CK-ARCH-DEAD-MODULES")
    if dead_vars + dead_params + dead_modules >= 10:
        themes.append(
            f"<strong>Dead Code Accumulation.</strong> "
            f"The analysis found {dead_vars} dead variables, {dead_params} unused parameters, "
            f"and {dead_modules} orphaned modules. Dead code is not harmless -- it misleads new "
            f"developers, inflates complexity metrics, and creates false dependencies in mental models. "
            f"Set up a regular hygiene pass: remove variables assigned but never read, prefix truly "
            f"unused parameters with underscore, and verify orphaned modules are genuinely needed "
            f"before deleting."
        )

    has_secrets = qg_stats.get("error_no_hardcoded_secrets", 0) > 0
    has_cors = qg_stats.get("error_missing_cors_config", 0) > 0
    has_injection = qg_stats.get("warning_prompt_injection_risk", 0) > 0
    if has_secrets or has_cors or has_injection:
        sec_parts = []
        if has_secrets:
            sec_parts.append("hardcoded credentials/secrets in source code")
        if has_cors:
            sec_parts.append("CORS configured with wildcard origins (allow_origins=['*'])")
        if has_injection:
            sec_parts.append("potential prompt injection vectors in LLM pipelines")
        themes.append(
            f"<strong>Security Concerns.</strong> "
            f"This codebase has: {'; '.join(sec_parts)}. "
            f"Hardcoded secrets are a critical finding -- they persist in git history even after removal "
            f"and can be harvested by anyone with repo access. Move all secrets to environment variables "
            f"or a vault service immediately. CORS wildcards bypass browser same-origin protections and "
            f"should be locked to specific trusted domains in production."
        )

    missing_await = qg_stats.get("error_missing_await", 0)
    blocking_async = qg_stats.get("error_blocking_in_async", 0)
    if missing_await or blocking_async:
        themes.append(
            f"<strong>Async Discipline.</strong> "
            + (f"{missing_await} missing 'await' calls were detected. " if missing_await else "")
            + (f"{blocking_async} blocking calls inside async functions were found. " if blocking_async else "")
            + "Missing awaits return coroutine objects instead of actual results, leading to silent "
            "data corruption or NoneType errors downstream. Blocking calls in async contexts defeat "
            "the purpose of the async runtime and can starve the event loop. Use 'await' consistently "
            "and move blocking I/O to thread executors."
        )

    llm_timeout = qg_stats.get("warning_llm_timeout", 0)
    llm_retry = qg_stats.get("warning_llm_retry", 0)
    llm_callbacks = qg_stats.get("warning_missing_callbacks", 0)
    unbounded_tokens = qg_stats.get("warning_unbounded_tokens", 0)
    token_tracking = qg_stats.get("info_missing_token_tracking", 0)
    if llm_timeout + llm_retry + llm_callbacks + unbounded_tokens + token_tracking >= 5:
        themes.append(
            f"<strong>LLM Integration Hygiene.</strong> "
            f"This service integrates with LLM providers but has gaps in production hardening: "
            + (f"{llm_timeout} LLM calls lack explicit timeouts, " if llm_timeout else "")
            + (f"{llm_retry} calls have no retry logic, " if llm_retry else "")
            + (f"{unbounded_tokens} calls set no max_tokens bound, " if unbounded_tokens else "")
            + (f"{token_tracking} modules do no token usage tracking, " if token_tracking else "")
            + (f"{llm_callbacks} calls are missing streaming callbacks. " if llm_callbacks else "")
            + "LLM APIs are inherently unreliable -- they timeout, rate-limit, and produce variable-cost "
            "responses. Every LLM call should have: (1) an explicit timeout, (2) retry with backoff, "
            "(3) a max_tokens cap to control cost, and (4) token usage logging for observability."
        )

    db_loop = qg_stats.get("error_db_call_in_loop", 0)
    n_plus_one = qg_stats.get("warning_n_plus_one_signal", 0)
    missing_pool = qg_stats.get("warning_missing_pool_config", 0)
    missing_retry_db = qg_stats.get("warning_missing_connection_retry", 0)
    if db_loop + n_plus_one + missing_pool + missing_retry_db >= 3:
        themes.append(
            f"<strong>Database Access Patterns.</strong> "
            + (f"{db_loop} database calls inside loops (N+1 pattern) were detected. " if db_loop else "")
            + (f"{missing_retry_db} connection initializations lack retry logic. " if missing_retry_db else "")
            + (f"{missing_pool} database connections have no pool configuration. " if missing_pool else "")
            + "N+1 queries are one of the most common performance killers in data-heavy applications. "
            "Each loop iteration fires a separate round-trip to the database. Batch your reads with "
            "$in / WHERE IN clauses, configure connection pooling (min/max pool size, idle timeout), "
            "and add retry-with-backoff on connection initialization to survive transient failures."
        )

    missing_timeout = qg_stats.get("warning_missing_requests_timeout", 0)
    rate_limit = qg_stats.get("warning_rate_limit_handling", 0)
    if missing_timeout >= 5 or rate_limit >= 5:
        themes.append(
            f"<strong>HTTP Client Discipline.</strong> "
            + (f"{missing_timeout} outbound HTTP calls lack explicit timeout parameters. " if missing_timeout else "")
            + (f"{rate_limit} external API calls have no rate-limit handling. " if rate_limit else "")
            + "An HTTP call without a timeout will block the worker indefinitely if the remote server "
            "hangs. This is a production outage waiting to happen. Set timeout=30 (or appropriate value) "
            "on every requests/httpx call, and implement 429 retry-after handling for rate-limited APIs."
        )

    useeffect = qg_stats.get("warning_useeffect_dependency_array", 0)
    debug_stmts = qg_stats.get("warning_no_debug_statements", 0)
    server_client = qg_stats.get("error_server_client_boundary", 0)
    todo_fixme = qg_stats.get("error_no_todo_fixme", 0)
    if useeffect >= 10:
        themes.append(
            f"<strong>React useEffect Discipline.</strong> "
            f"{useeffect} useEffect hooks were found without proper dependency arrays. "
            f"A useEffect without a dependency array runs on every render, which causes: unnecessary "
            f"API calls, infinite re-render loops, performance degradation, and stale closure bugs. "
            f"Always specify the dependency array. If the effect should run once on mount, use []. "
            f"If it depends on specific values, list them explicitly. This is not optional -- it is a "
            f"fundamental React pattern."
        )

    if debug_stmts >= 10:
        themes.append(
            f"<strong>Debug Statements Left in Code.</strong> "
            f"{debug_stmts} console.log/debug statements were found. "
            f"These leak implementation details to browser dev tools in production, add noise to logs, "
            f"and suggest the code was not properly cleaned up before commit. Set up a linting rule "
            f"(no-console) to block these at the CI gate level."
        )

    if server_client >= 5:
        themes.append(
            f"<strong>Server/Client Boundary Violations.</strong> "
            f"{server_client} Next.js server/client boundary violations were detected. "
            f"Mixing server-only imports (database, fs, env secrets) into client components exposes "
            f"internal logic to the browser bundle. Use 'use client' and 'use server' directives "
            f"intentionally, and keep data fetching on the server side."
        )

    if todo_fixme >= 10:
        themes.append(
            f"<strong>Unresolved TODOs and FIXMEs.</strong> "
            f"{todo_fixme} TODO/FIXME comments remain in the codebase. "
            f"These represent acknowledged but unaddressed technical debt. Each one is a decision "
            f"that was deferred. Track them as tickets instead -- a TODO in code is invisible to "
            f"project management and tends to stay forever."
        )

    dup_code = qg_stats.get("warning_no_duplicate_code", 0)
    if dup_code >= 5:
        themes.append(
            f"<strong>Code Duplication.</strong> "
            f"{dup_code} instances of duplicate or near-duplicate code were detected. "
            f"Duplicated logic means bugs need to be fixed in multiple places, and behavioral "
            f"drift between copies is inevitable. Extract shared logic into utility functions or "
            f"custom hooks (in React). If two components share 80% of their code, consider a "
            f"shared base component with composition."
        )

    # ---- MISTAKES TO AVOID ----
    mistakes = []

    if fn_size_errors:
        mistakes.append(
            "Do not keep adding logic to an existing function just because that is where the flow "
            "currently lives. When a function crosses 30-40 lines, pause and ask whether it is doing "
            "more than one thing."
        )
    if has_secrets:
        mistakes.append(
            "Never commit credentials, API keys, or database passwords into source code -- not even "
            "temporarily. Use .env files excluded from git, and validate they are loaded at startup."
        )
    if missing_await or blocking_async:
        mistakes.append(
            "Do not mix sync and async patterns carelessly. If a function is async, every I/O call "
            "inside it must also be async and properly awaited."
        )
    if recomp >= 20:
        mistakes.append(
            "Avoid copy-pasting code blocks and changing one or two parameters. If you find yourself "
            "doing this, extract a parameterized helper function instead."
        )
    if useeffect >= 10:
        mistakes.append(
            "Never write useEffect(() => { ... }) without a dependency array. This is the most common "
            "source of performance bugs in React applications."
        )
    if debug_stmts >= 10:
        mistakes.append(
            "Do not use console.log for debugging in committed code. Use a proper logger or debugging "
            "tool, and add a pre-commit hook to catch stray debug statements."
        )
    bare_exceptions = qg_stats.get("error_bare_exception_in_route", 0) + qg_stats.get("error_no_silent_catch", 0)
    if bare_exceptions:
        mistakes.append(
            "Avoid bare except clauses or generic try/except blocks that swallow all errors. "
            "Catch specific exceptions, log the traceback, and re-raise or return a meaningful error."
        )
    if llm_timeout >= 3:
        mistakes.append(
            "Do not call LLM APIs without timeout and max_tokens parameters. A single hung LLM call "
            "can block a worker thread and cascade into a service outage."
        )
    if missing_timeout >= 5:
        mistakes.append(
            "Never make an outbound HTTP request without a timeout. The default for most HTTP libraries "
            "is infinite, which means a misbehaving upstream service can permanently block your workers."
        )
    if db_loop:
        mistakes.append(
            "Do not query the database inside a for-loop. Collect the IDs or keys first, then execute "
            "a single batch query. This is the difference between 1 round-trip and N round-trips."
        )
    missing_response = qg_stats.get("warning_missing_response_model", 0)
    if missing_response >= 10:
        mistakes.append(
            "Do not leave FastAPI route handlers without a response_model. Without it, you lose "
            "automatic serialization, OpenAPI documentation, and response validation."
        )

    # ---- Build HTML ----
    html_parts = []
    html_parts.append('<div class="narrative-box">')
    html_parts.append('<div class="narrative-header">Lead Reviewer Assessment</div>')

    html_parts.append('<div class="narrative-section">')
    html_parts.append('<h3 class="narrative-subtitle">Overall Assessment</h3>')
    for p in paras:
        html_parts.append(f'<p class="narrative-para">{p}</p>')
    html_parts.append('</div>')

    if themes:
        html_parts.append('<div class="narrative-section">')
        html_parts.append(f'<h3 class="narrative-subtitle">Key Themes to Address ({len(themes)})</h3>')
        html_parts.append('<p class="narrative-intro">These are the recurring patterns that need systemic attention, not just point fixes:</p>')
        for i, theme in enumerate(themes, 1):
            html_parts.append(f'<div class="narrative-theme"><span class="theme-num">{i}</span><div>{theme}</div></div>')
        html_parts.append('</div>')

    if mistakes:
        html_parts.append('<div class="narrative-section">')
        html_parts.append('<h3 class="narrative-subtitle">Patterns to Break Going Forward</h3>')
        html_parts.append('<p class="narrative-intro">These are the habits to change in day-to-day development:</p>')
        html_parts.append('<ul class="narrative-mistakes">')
        for m in mistakes:
            html_parts.append(f'<li>{m}</li>')
        html_parts.append('</ul>')
        html_parts.append('</div>')

    html_parts.append('<div class="narrative-section">')
    html_parts.append('<h3 class="narrative-subtitle">Closing Remarks</h3>')
    if health >= 80:
        html_parts.append(
            f'<p class="narrative-para">This codebase is in a serviceable state. The issues identified are real but manageable. '
            f'Focus remediation on the {len(failing_files)} failing PRS files, address any security '
            f'findings immediately, and introduce the discipline patterns described above into your '
            f'code review process.</p>'
        )
    elif health >= 60:
        html_parts.append(
            f'<p class="narrative-para">This codebase needs focused improvement. With {total_errors} errors and {total_warnings} '
            f'warnings across {files_checked} files, the debt is accumulating faster than it is being '
            f'paid down. Dedicate time specifically to reducing the worst-scoring files (the bottom 20% '
            f'by PRS) and enforce the patterns above in all new code reviews. Do not add features on '
            f'top of broken foundations.</p>'
        )
    else:
        html_parts.append(
            f'<p class="narrative-para">This codebase is carrying dangerous levels of technical debt. {total_errors} errors and '
            f'{total_warnings} warnings across {files_checked} files is not sustainable. The recommendation '
            f'is to freeze feature development until the worst files are remediated, security issues '
            f'are resolved, and the team has adopted the patterns described above. Shipping new features '
            f'on this foundation will only compound the cost of eventual cleanup.</p>'
        )
    html_parts.append('</div>')

    html_parts.append('<div class="narrative-footer">This narrative was synthesized from deterministic quality-gate and cathedral-keeper analysis results.</div>')
    html_parts.append('</div>')

    return "\n".join(html_parts)


# ---------------------------------------------------------------------------
# Full HTML generation for one repo
# ---------------------------------------------------------------------------

def generate_html(repo_name, friendly_name, tech_stack, qg_data, ck_data, brand_title):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    health = health_score(qg_data, ck_data)
    hcolor = health_color(health)

    qg_stats = qg_data.get("stats", {}) if qg_data else {}
    files_checked = qg_stats.get("files_checked", 0)
    lines_checked = qg_stats.get("lines_checked", 0)
    total_errors = qg_stats.get("error", 0)
    total_warnings = qg_stats.get("warning", 0)
    total_info = qg_stats.get("info", 0)
    prs_failed = qg_stats.get("prs_files_failed", 0)
    prs_scored = qg_stats.get("prs_files_scored", 0)
    prs_pass_rate = round((prs_scored - prs_failed) / prs_scored * 100, 1) if prs_scored else 0

    ck_findings = ck_data.get("findings", []) if ck_data else []
    ck_sev = defaultdict(int)
    for f in ck_findings:
        ck_sev[f.get("severity", "info")] += 1
    ck_policies = Counter(f.get("policy_id", "?") for f in ck_findings)

    qg_rule_counts = build_qg_rule_counts(qg_data) if qg_data else Counter()
    prs_rows = build_prs_table(qg_data, repo_name) if qg_data else []
    file_issues = build_qg_file_issues(qg_data, repo_name) if qg_data else {}

    all_scores = [r["score"] for r in prs_rows]
    avg_prs = round(sum(all_scores) / len(all_scores), 1) if all_scores else 0
    avg_grade, avg_grade_color = prs_grade(avg_prs)
    top_rules = qg_rule_counts.most_common(15)

    # ---- HTML ----
    html = []
    html.append(f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(brand_title)} - {esc(friendly_name)}</title>
<style>
  :root {{
    --bg: #f8fafc; --card: #ffffff; --border: #e2e8f0;
    --text: #1e293b; --text2: #475569; --text3: #94a3b8;
    --accent: #3b82f6; --green: #16a34a; --red: #dc2626;
    --orange: #ea580c; --yellow: #d97706;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
    background: var(--bg); color: var(--text); line-height: 1.6; padding: 0;
  }}
  .header {{
    background: linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #334155 100%);
    color: white; padding: 40px 48px; position: relative; overflow: hidden;
  }}
  .header::after {{
    content: ''; position: absolute; top: 0; right: 0; bottom: 0; left: 0;
    background: repeating-linear-gradient(45deg, transparent, transparent 35px,
      rgba(255,255,255,0.015) 35px, rgba(255,255,255,0.015) 70px);
  }}
  .header-content {{ position: relative; z-index: 1; max-width: 1400px; margin: 0 auto; }}
  .header h1 {{ font-size: 28px; font-weight: 700; margin-bottom: 4px; letter-spacing: -0.5px; }}
  .header .subtitle {{ color: #94a3b8; font-size: 14px; }}
  .header .meta {{ display: flex; gap: 24px; margin-top: 16px; font-size: 13px; color: #cbd5e1; }}
  .health-badge {{
    display: inline-flex; align-items: center; gap: 8px;
    background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.2);
    border-radius: 8px; padding: 8px 16px; margin-top: 16px;
  }}
  .health-score {{ font-size: 32px; font-weight: 800; letter-spacing: -1px; }}
  .health-label {{ font-size: 12px; color: #94a3b8; text-transform: uppercase; letter-spacing: 1px; }}
  .container {{ max-width: 1400px; margin: 0 auto; padding: 32px 48px; }}
  .section {{ margin-bottom: 32px; }}
  .section-title {{
    font-size: 18px; font-weight: 700; color: var(--text);
    border-bottom: 2px solid var(--border); padding-bottom: 8px; margin-bottom: 16px;
    display: flex; align-items: center; gap: 8px;
  }}
  .section-title .icon {{ font-size: 20px; }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; }}
  .card {{
    background: var(--card); border: 1px solid var(--border);
    border-radius: 10px; padding: 20px; transition: box-shadow 0.2s;
  }}
  .card:hover {{ box-shadow: 0 4px 12px rgba(0,0,0,0.06); }}
  .card-value {{ font-size: 28px; font-weight: 800; letter-spacing: -1px; }}
  .card-label {{ font-size: 12px; color: var(--text3); text-transform: uppercase; letter-spacing: 0.5px; margin-top: 4px; }}
  .card-sub {{ font-size: 12px; color: var(--text2); margin-top: 8px; }}
  .grade-circle {{
    display: inline-flex; align-items: center; justify-content: center;
    width: 48px; height: 48px; border-radius: 50%;
    font-size: 24px; font-weight: 800; color: white;
  }}
  .two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }}
  @media (max-width: 900px) {{ .two-col {{ grid-template-columns: 1fr; }} }}
  table {{
    width: 100%; border-collapse: collapse; background: var(--card);
    border: 1px solid var(--border); border-radius: 10px; overflow: hidden; font-size: 13px;
  }}
  th {{
    background: #f1f5f9; padding: 10px 14px; text-align: left; font-weight: 600;
    font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px;
    color: var(--text2); border-bottom: 1px solid var(--border);
  }}
  td {{ padding: 9px 14px; border-bottom: 1px solid #f1f5f9; vertical-align: top; }}
  tr:last-child td {{ border-bottom: none; }}
  tr:hover td {{ background: #f8fafc; }}
  .sev-badge {{
    display: inline-block; padding: 2px 8px; border-radius: 4px;
    font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.3px;
  }}
  .prs-bar {{ width: 100%; height: 6px; border-radius: 3px; background: #e2e8f0; overflow: hidden; }}
  .prs-bar-fill {{ height: 100%; border-radius: 3px; transition: width 0.3s; }}
  .file-group {{ margin-bottom: 16px; }}
  .file-header {{
    font-weight: 600; font-size: 13px; padding: 10px 14px;
    background: #f1f5f9; border: 1px solid var(--border);
    border-radius: 8px 8px 0 0; cursor: pointer;
    display: flex; justify-content: space-between; align-items: center;
  }}
  .file-header:hover {{ background: #e2e8f0; }}
  .file-body {{
    border: 1px solid var(--border); border-top: none;
    border-radius: 0 0 8px 8px; overflow: hidden;
  }}
  .issue-row {{ padding: 10px 14px; border-bottom: 1px solid #f1f5f9; font-size: 13px; }}
  .issue-row:last-child {{ border-bottom: none; }}
  .issue-rule {{ font-weight: 600; color: var(--accent); font-size: 12px; }}
  .issue-msg {{ color: var(--text); margin: 4px 0; }}
  .issue-fix {{ color: var(--text2); font-size: 12px; font-style: italic; }}
  .issue-line {{ color: var(--text3); font-size: 11px; }}
  .tag {{
    display: inline-block; padding: 2px 6px; border-radius: 3px;
    font-size: 11px; font-weight: 500; background: #eff6ff; color: #2563eb; margin-right: 4px;
  }}
  .collapsible {{ display: none; }}
  .collapsible.open {{ display: block; }}
  .policy-group {{ margin-bottom: 16px; }}
  .policy-header {{
    font-weight: 600; font-size: 14px; padding: 12px 16px;
    background: #f1f5f9; border: 1px solid var(--border);
    border-radius: 8px; cursor: pointer;
    display: flex; justify-content: space-between; align-items: center;
    transition: background 0.15s;
  }}
  .policy-header:hover {{ background: #e2e8f0; }}
  .policy-header .arrow {{ transition: transform 0.2s; display: inline-block; }}
  .policy-header.open .arrow {{ transform: rotate(90deg); }}
  .policy-body {{ border: 1px solid var(--border); border-top: none; border-radius: 0 0 8px 8px; }}
  .radar-container {{ display: flex; justify-content: center; margin: 16px 0 24px; }}
  .nav-toc {{ position: sticky; top: 0; z-index: 100; }}
  .chart-bar {{ display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }}
  .chart-bar-label {{ width: 180px; font-size: 12px; text-align: right; color: var(--text2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .chart-bar-track {{ flex: 1; height: 20px; background: #f1f5f9; border-radius: 4px; overflow: hidden; }}
  .chart-bar-fill {{ height: 100%; border-radius: 4px; display: flex; align-items: center; padding-left: 6px; font-size: 11px; font-weight: 600; color: white; min-width: 24px; }}
  .chart-bar-count {{ font-size: 12px; font-weight: 600; color: var(--text); width: 36px; }}
  .nav-toc {{
    background: var(--card); border: 1px solid var(--border);
    border-radius: 10px; padding: 16px 20px; margin-bottom: 24px;
  }}
  .nav-toc a {{ color: var(--accent); text-decoration: none; font-size: 13px; display: inline-block; margin-right: 20px; margin-bottom: 4px; }}
  .nav-toc a:hover {{ text-decoration: underline; }}
  .narrative-box {{
    background: var(--card); border: 1px solid var(--border); border-radius: 12px;
    padding: 32px 36px; margin-bottom: 32px; border-left: 5px solid #6366f1;
  }}
  .narrative-header {{
    font-size: 22px; font-weight: 800; color: #312e81; margin-bottom: 20px;
    padding-bottom: 12px; border-bottom: 2px solid #e0e7ff; letter-spacing: -0.3px;
  }}
  .narrative-section {{ margin-bottom: 24px; }}
  .narrative-subtitle {{ font-size: 16px; font-weight: 700; color: #3730a3; margin-bottom: 10px; }}
  .narrative-para {{ font-size: 14px; line-height: 1.75; color: var(--text); margin-bottom: 10px; }}
  .narrative-intro {{ font-size: 13px; color: var(--text2); margin-bottom: 12px; font-style: italic; }}
  .narrative-theme {{
    display: flex; gap: 14px; margin-bottom: 16px; padding: 14px 18px;
    background: #fafafe; border: 1px solid #e8e8f4; border-radius: 8px;
    font-size: 13.5px; line-height: 1.7; color: var(--text);
  }}
  .theme-num {{
    flex-shrink: 0; width: 28px; height: 28px; background: #6366f1; color: white;
    border-radius: 50%; display: flex; align-items: center; justify-content: center;
    font-size: 13px; font-weight: 700; margin-top: 2px;
  }}
  .narrative-mistakes {{ list-style: none; padding: 0; }}
  .narrative-mistakes li {{
    position: relative; padding: 10px 16px 10px 32px; margin-bottom: 8px;
    background: #fef2f2; border: 1px solid #fecaca; border-radius: 6px;
    font-size: 13px; line-height: 1.65; color: var(--text);
  }}
  .narrative-mistakes li::before {{
    content: '\\2716'; position: absolute; left: 12px; top: 11px;
    color: #dc2626; font-size: 12px; font-weight: 700;
  }}
  .narrative-footer {{
    font-size: 11px; color: var(--text3); font-style: italic;
    margin-top: 16px; padding-top: 12px; border-top: 1px solid var(--border);
  }}
  .ck-finding {{
    background: var(--card); border: 1px solid var(--border);
    border-radius: 10px; padding: 16px 20px; margin-bottom: 12px;
  }}
  .ck-finding-title {{ font-weight: 700; font-size: 14px; margin-bottom: 6px; }}
  .ck-evidence {{ background: #f8fafc; padding: 8px 12px; border-radius: 6px; margin: 8px 0; font-size: 12px; font-family: 'Cascadia Code', 'Fira Code', monospace; }}
  .ck-fix {{ color: var(--text2); font-size: 13px; margin-top: 6px; }}
  .ck-why {{ color: var(--text2); font-size: 12px; margin-bottom: 8px; }}
  .footer {{
    text-align: center; padding: 24px; color: var(--text3); font-size: 12px;
    border-top: 1px solid var(--border); margin-top: 48px;
  }}
</style>
</head>
<body>
""")

    # ---- HEADER ----
    html.append(f"""
<div class="header">
  <div class="header-content">
    <h1>{esc(friendly_name)}</h1>
    <div class="subtitle">{esc(brand_title)}</div>
    <div class="meta">
      <span>Generated: {now}</span>
      <span>Repository: {esc(repo_name)}</span>
    </div>
    <div class="health-badge">
      <div>
        <div class="health-label">Overall Health</div>
        <div class="health-score" style="color:{hcolor}">{health}/100</div>
      </div>
    </div>
  </div>
</div>
""")

    # ---- NAV ----
    html.append("""
<div class="container">
  <div class="nav-toc">
    <strong>Navigate:</strong>
    <a href="#summary">Executive Summary</a>
    <a href="#narrative">Lead Reviewer Narrative</a>
    <a href="#prs">PRS Scores</a>
    <a href="#rules">Rule Breakdown</a>
    <a href="#arch">Architecture Findings</a>
    <a href="#files">File-Level Details</a>
    <a href="#actions">Recommended Actions</a>
  </div>
""")

    # ---- EXECUTIVE SUMMARY ----
    html.append(f"""
  <div class="section" id="summary">
    <div class="section-title"><span class="icon">&#x1F4CA;</span> Executive Summary</div>
    <div class="cards">
      <div class="card">
        <div class="card-value">{files_checked}</div>
        <div class="card-label">Files Analyzed</div>
        <div class="card-sub">{lines_checked:,} lines of code</div>
      </div>
      <div class="card">
        <div class="card-value" style="color:var(--red)">{total_errors}</div>
        <div class="card-label">Errors</div>
        <div class="card-sub">Hard blocks that need fixing</div>
      </div>
      <div class="card">
        <div class="card-value" style="color:var(--yellow)">{total_warnings}</div>
        <div class="card-label">Warnings</div>
        <div class="card-sub">Quality improvements needed</div>
      </div>
      <div class="card">
        <div class="card-value" style="color:var(--text3)">{total_info}</div>
        <div class="card-label">Info</div>
        <div class="card-sub">Suggestions &amp; observations</div>
      </div>
      <div class="card" style="text-align:center">
        <div class="grade-circle" style="background:{avg_grade_color}">{avg_grade}</div>
        <div class="card-label" style="margin-top:8px">Average PRS</div>
        <div class="card-sub">{avg_prs}/100 across {prs_scored} files</div>
      </div>
      <div class="card">
        <div class="card-value" style="color:{'var(--green)' if prs_pass_rate > 70 else 'var(--red)'}">{prs_pass_rate}%</div>
        <div class="card-label">PRS Pass Rate</div>
        <div class="card-sub">{prs_scored - prs_failed}/{prs_scored} files pass &ge; 85</div>
      </div>
      <div class="card">
        <div class="card-value">{len(ck_findings)}</div>
        <div class="card-label">Architecture Findings</div>
        <div class="card-sub">{ck_sev.get('high', 0) + ck_sev.get('blocker', 0)} high, {ck_sev.get('medium', 0)} medium, {ck_sev.get('low', 0)} low</div>
      </div>
    </div>
  </div>
""")

    # ---- RADAR CHART (SVG) ----
    # Compute dimension scores (0-100, higher = better)
    # Each formula uses a denominator and scale that produces a meaningful
    # gradient across real codebases, not a binary 0/100 spike.

    # Code Quality: avg PRS across all scored files (already 0-100)
    dim_code_quality = max(0, min(100, avg_prs)) if prs_scored else 50

    # Error-Free: % of files with zero errors (excludes prs_score enforcement)
    real_errors_by_file = Counter(i["file"] for i in qg_data.get("issues", []) if i.get("severity") == "error" and i.get("rule") != "prs_score") if qg_data else Counter()
    files_with_errors = len(real_errors_by_file)
    dim_error_free = max(0, min(100, round((1 - files_with_errors / max(files_checked, 1)) * 100)))

    # Architecture: native CK findings only (exclude QG integration), log scale
    # 0 findings = 100, findings/file ratio of 2+ = ~20
    ck_native = [f for f in ck_findings if "quality_gate" not in f.get("policy_id", "")]
    ck_file_count = len(set(f.get("evidence", [{}])[0].get("file", "") for f in ck_findings)) or files_checked
    ck_ratio = len(ck_native) / max(ck_file_count, 1)
    import math
    dim_arch_health = max(0, min(100, round(100 * math.exp(-0.5 * ck_ratio))))

    # Test Coverage: % of CK-analysed files that DON'T have a test-coverage finding
    test_cov_count = ck_policies.get("CK-ARCH-TEST-COVERAGE", 0)
    dim_test_coverage = max(0, min(100, round((1 - test_cov_count / max(ck_file_count, 1)) * 100)))

    # PRS Pass Rate: direct percentage
    dim_prs_pass = prs_pass_rate

    # Maintainability: % of files without complexity or size violations
    maint_issues = qg_rule_counts.get("max_complexity", 0) + qg_rule_counts.get("function_size", 0)
    maint_files = len(set(i["file"] for i in qg_data.get("issues", []) if i.get("rule") in ("max_complexity", "function_size"))) if qg_data else 0
    dim_maintainability = max(0, min(100, round((1 - maint_files / max(files_checked, 1)) * 100)))

    dimensions = [
        ("Code Quality", dim_code_quality),
        ("Error-Free", dim_error_free),
        ("Architecture", dim_arch_health),
        ("Test Coverage", dim_test_coverage),
        ("PRS Pass Rate", dim_prs_pass),
        ("Maintainability", dim_maintainability),
    ]

    # Generate SVG radar chart
    cx, cy, r = 160, 160, 120
    n = len(dimensions)
    angles = [math.pi / 2 + 2 * math.pi * i / n for i in range(n)]

    # Grid circles
    radar_svg = f'<svg width="320" height="340" viewBox="0 0 320 340" xmlns="http://www.w3.org/2000/svg">'
    for pct in [25, 50, 75, 100]:
        gr = r * pct / 100
        pts = " ".join(f"{cx + gr * math.cos(a):.1f},{cy - gr * math.sin(a):.1f}" for a in angles)
        radar_svg += f'<polygon points="{pts}" fill="none" stroke="#e2e8f0" stroke-width="1"/>'

    # Axis lines
    for a in angles:
        radar_svg += f'<line x1="{cx}" y1="{cy}" x2="{cx + r * math.cos(a):.1f}" y2="{cy - r * math.sin(a):.1f}" stroke="#e2e8f0" stroke-width="1"/>'

    # Data polygon
    data_pts = " ".join(f"{cx + r * (d[1]/100) * math.cos(angles[i]):.1f},{cy - r * (d[1]/100) * math.sin(angles[i]):.1f}" for i, d in enumerate(dimensions))
    radar_svg += f'<polygon points="{data_pts}" fill="rgba(99,102,241,0.2)" stroke="#6366f1" stroke-width="2"/>'

    # Data points + labels
    for i, (label, val) in enumerate(dimensions):
        px = cx + r * (val / 100) * math.cos(angles[i])
        py = cy - r * (val / 100) * math.sin(angles[i])
        radar_svg += f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4" fill="#6366f1"/>'
        # Labels
        lx = cx + (r + 20) * math.cos(angles[i])
        ly = cy - (r + 20) * math.sin(angles[i])
        anchor = "middle"
        if lx < cx - 10: anchor = "end"
        elif lx > cx + 10: anchor = "start"
        radar_svg += f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}" font-size="11" fill="#475569" font-family="Segoe UI, sans-serif">{label}</text>'
        radar_svg += f'<text x="{lx:.1f}" y="{ly + 13:.1f}" text-anchor="{anchor}" font-size="10" fill="#94a3b8" font-family="Segoe UI, sans-serif">{val:.0f}%</text>'

    radar_svg += '</svg>'

    html.append(f"""
  <div class="section">
    <div class="section-title"><span class="icon">&#x1F578;</span> Quality Dimensions</div>
    <div class="radar-container">{radar_svg}</div>
  </div>
""")

    # ---- NARRATIVE ----
    narrative_html = generate_narrative(friendly_name, tech_stack, qg_data, ck_data, prs_rows, file_issues, qg_rule_counts, health)
    html.append(f"""
  <div class="section" id="narrative">
    <div class="section-title"><span class="icon">&#x1F9D1;&#x200D;&#x1F4BB;</span> Lead Reviewer Narrative</div>
    {narrative_html}
  </div>
""")

    # ---- PRS SCORES ----
    html.append("""
  <div class="section" id="prs">
    <div class="section-title"><span class="icon">&#x1F3AF;</span> Production Readiness Scores (PRS)</div>
""")
    if prs_rows:
        html.append("""<table>
      <thead><tr><th>File</th><th>Score</th><th style="width:200px">Bar</th><th>Grade</th><th>Errors</th><th>Warnings</th><th>Status</th></tr></thead><tbody>""")
        for r in prs_rows:
            g, gcolor = prs_grade(r["score"])
            status = '<span style="color:#16a34a;font-weight:600">PASS</span>' if r["passed"] else '<span style="color:#dc2626;font-weight:600">FAIL</span>'
            pct = max(0, min(100, r["score"]))
            html.append(f"""<tr>
  <td style="font-family:monospace;font-size:12px">{esc(r['file'])}</td>
  <td style="font-weight:700">{r['score']}</td>
  <td><div class="prs-bar"><div class="prs-bar-fill" style="width:{pct}%;background:{gcolor}"></div></div></td>
  <td><span style="color:{gcolor};font-weight:800">{g}</span></td>
  <td style="color:var(--red)">{r['errors']}</td>
  <td style="color:var(--yellow)">{r['warnings']}</td>
  <td>{status}</td>
</tr>""")
        html.append("</tbody></table>")
    else:
        html.append("<p>No PRS data available.</p>")
    html.append("</div>")

    # ---- RULE BREAKDOWN ----
    html.append("""
  <div class="section" id="rules">
    <div class="section-title"><span class="icon">&#x1F4CB;</span> Rule Breakdown (Top Offenders)</div>
""")
    if top_rules:
        max_count = top_rules[0][1] if top_rules else 1
        for rule, count in top_rules:
            pct = count / max_count * 100
            color = "#dc2626" if "error" in rule or rule in ("function_size", "file_size", "no_silent_catch", "no_hardcoded_secrets", "missing_await", "prs_score", "db_call_in_loop") else "#3b82f6"
            html.append(f"""<div class="chart-bar">
  <div class="chart-bar-label">{esc(rule)}</div>
  <div class="chart-bar-track"><div class="chart-bar-fill" style="width:{pct}%;background:{color}">{count}</div></div>
  <div class="chart-bar-count">{count}</div>
</div>""")
    html.append("</div>")

    # ---- ARCHITECTURE FINDINGS ----
    html.append("""
  <div class="section" id="arch">
    <div class="section-title"><span class="icon">&#x1F3DB;</span> Architecture Findings (Cathedral Keeper)</div>
""")
    if ck_findings:
        # Policy tag navigation — clickable to jump to that policy group
        html.append('<div style="margin-bottom:16px">')
        for policy, count in ck_policies.most_common():
            pid_anchor = policy.replace("::", "-").replace(" ", "-").lower()
            sev_label = ""
            policy_findings = [f for f in ck_findings if f.get("policy_id") == policy]
            high_in_policy = sum(1 for f in policy_findings if f.get("severity") in ("high", "blocker"))
            if high_in_policy:
                sev_label = f' <span style="color:#dc2626;font-size:10px">({high_in_policy} high)</span>'
            html.append(f'<a href="#ck-{pid_anchor}" style="text-decoration:none"><span class="tag" style="cursor:pointer">{esc(policy)}: {count}{sev_label}</span></a>')
        html.append('</div>')

        # Group findings by policy — each group is collapsible
        from collections import OrderedDict
        grouped = OrderedDict()
        for policy, _ in ck_policies.most_common():
            grouped[policy] = sorted(
                [f for f in ck_findings if f.get("policy_id") == policy],
                key=lambda f: SEVERITY_ORDER.get(f.get("severity", "info"), 9)
            )

        for policy, policy_findings in grouped.items():
            pid_anchor = policy.replace("::", "-").replace(" ", "-").lower()
            high_count = sum(1 for f in policy_findings if f.get("severity") in ("high", "blocker"))
            med_count = sum(1 for f in policy_findings if f.get("severity") == "medium")
            badge_parts = []
            if high_count: badge_parts.append(f'<span style="color:#dc2626">{high_count} high</span>')
            if med_count: badge_parts.append(f'<span style="color:#d97706">{med_count} med</span>')
            badge_parts.append(f'{len(policy_findings)} total')
            badge_html = " &middot; ".join(badge_parts)

            html.append(f"""<div class="policy-group" id="ck-{pid_anchor}">
  <div class="policy-header" onclick="this.classList.toggle('open');this.nextElementSibling.classList.toggle('open')">
    <span>{esc(policy)} &mdash; {badge_html}</span>
    <span class="arrow">&#9654;</span>
  </div>
  <div class="policy-body collapsible">""")

            for finding in policy_findings:
                sev = finding.get("severity", "info")
                sev_color = SEVERITY_COLORS.get(sev, "#6b7280")
                sev_bg = SEVERITY_BG.get(sev, "#f9fafb")
                html.append(f"""<div class="ck-finding" style="border-left:4px solid {sev_color};border-radius:0;border:none;border-bottom:1px solid var(--border)">
  <div class="ck-finding-title">
    <span class="sev-badge" style="background:{sev_bg};color:{sev_color}">{esc(sev.upper())}</span>
    {esc(finding.get('title', ''))}
  </div>
  <div class="ck-why">{esc(finding.get('why_it_matters', ''))}</div>""")
                for ev in finding.get("evidence", []):
                    html.append(f"""<div class="ck-evidence">{esc(ev.get('file', ''))}:{ev.get('line', '?')} &mdash; {esc(ev.get('snippet', ''))} <em>({esc(ev.get('note', ''))})</em></div>""")
                fixes = finding.get("fix_options", [])
                if fixes:
                    html.append('<div class="ck-fix"><strong>Recommended fix:</strong><ul style="margin:4px 0 0 18px">')
                    for fix in fixes:
                        html.append(f"<li>{esc(fix)}</li>")
                    html.append("</ul></div>")
                verifs = finding.get("verification", [])
                if verifs:
                    html.append('<div class="ck-fix"><strong>Verify:</strong> <code>' + esc("; ".join(verifs)) + '</code></div>')
                html.append("</div>")

            html.append("</div></div>")
    else:
        html.append("<p>No architecture findings.</p>")
    html.append("</div>")

    # ---- FILE-LEVEL DETAILS ----
    html.append("""
  <div class="section" id="files">
    <div class="section-title"><span class="icon">&#x1F4C2;</span> File-Level Issue Details</div>
    <p style="color:var(--text2);font-size:13px;margin-bottom:12px">Click a file to expand its issues.</p>
""")
    sorted_files = sorted(file_issues.items(), key=lambda x: (-len([i for i in x[1] if i.get("severity") == "error"]), -len(x[1])))
    for filepath, issues in sorted_files:
        err_count = sum(1 for i in issues if i.get("severity") == "error")
        warn_count = sum(1 for i in issues if i.get("severity") == "warning")
        info_count = sum(1 for i in issues if i.get("severity") == "info")
        prs_info = ""
        for r in prs_rows:
            if r["file"] == filepath:
                prs_info = f' | PRS: {r["score"]}'
                break
        fid = filepath.replace("/", "-").replace("\\", "-").replace(".", "-")
        html.append(f"""<div class="file-group">
  <div class="file-header" onclick="document.getElementById('{fid}').classList.toggle('open')">
    <span style="font-family:monospace">{esc(filepath)}</span>
    <span>
      {'<span style="color:var(--red);font-weight:600">' + str(err_count) + 'E</span>' if err_count else ''}
      {'<span style="color:var(--yellow);font-weight:600;margin-left:6px">' + str(warn_count) + 'W</span>' if warn_count else ''}
      {'<span style="color:var(--text3);margin-left:6px">' + str(info_count) + 'I</span>' if info_count else ''}
      <span style="color:var(--text3);font-size:11px;margin-left:8px">{esc(prs_info)}</span>
    </span>
  </div>
  <div class="file-body collapsible" id="{fid}">""")
        issues_sorted = sorted(issues, key=lambda i: SEVERITY_ORDER.get(i.get("severity", "info"), 9))
        for issue in issues_sorted:
            sev = issue.get("severity", "info")
            sev_color = SEVERITY_COLORS.get(sev, "#6b7280")
            sev_bg = SEVERITY_BG.get(sev, "#f9fafb")
            line = issue.get("line", "?")
            rule = issue.get("rule", "")
            msg = issue.get("message", "")
            suggestion = issue.get("suggestion", "")
            snippet = issue.get("snippet", "")
            html.append(f"""<div class="issue-row">
  <span class="sev-badge" style="background:{sev_bg};color:{sev_color}">{esc(sev.upper())}</span>
  <span class="issue-rule">{esc(rule)}</span>
  <span class="issue-line">Line {line}</span>
  <div class="issue-msg">{esc(msg)}</div>
  {'<div style="font-family:monospace;font-size:11px;color:var(--text3);background:#f8fafc;padding:4px 8px;border-radius:4px;margin:4px 0">' + esc(snippet) + '</div>' if snippet else ''}
  {'<div class="issue-fix">&#x1F4A1; ' + esc(suggestion) + '</div>' if suggestion else ''}
</div>""")
        html.append("</div></div>")
    html.append("</div>")

    # ---- RECOMMENDED ACTIONS ----
    html.append("""
  <div class="section" id="actions">
    <div class="section-title"><span class="icon">&#x2705;</span> Recommended Actions</div>
""")
    actions = []
    if any(i.get("rule") == "no_hardcoded_secrets" for issues in file_issues.values() for i in issues):
        actions.append(("CRITICAL", "#dc2626", "Remove hardcoded secrets and use environment variables for all credentials, passwords, and API keys."))
    if any(i.get("rule") == "no_silent_catch" for issues in file_issues.values() for i in issues):
        actions.append(("CRITICAL", "#dc2626", "Eliminate silent exception catches (except: pass). Log or handle every error appropriately."))
    if any(i.get("rule") == "missing_await" for issues in file_issues.values() for i in issues):
        actions.append(("HIGH", "#ea580c", "Add missing 'await' keywords on async calls. Current code returns coroutine objects instead of results."))
    if qg_stats.get("error_function_size", 0) > 0:
        c = qg_stats["error_function_size"]
        actions.append(("HIGH", "#ea580c", f"Refactor {c} oversized functions (>50 lines). Extract helper functions for readability and testability."))
    if qg_stats.get("error_file_size", 0) > 0:
        c = qg_stats["error_file_size"]
        actions.append(("HIGH", "#ea580c", f"Split {c} oversized files (>800 lines) into focused, single-responsibility modules."))
    if qg_stats.get("error_db_call_in_loop", 0) > 0:
        actions.append(("HIGH", "#ea580c", "Eliminate N+1 database query patterns. Use batch queries ($in, WHERE IN) instead of per-item lookups."))
    if any(i.get("rule") in ("missing_requests_timeout", "llm_timeout") for issues in file_issues.values() for i in issues):
        actions.append(("MEDIUM", "#d97706", "Add explicit timeout parameters to all HTTP/API calls to prevent worker hangs."))
    if any(i.get("rule") == "missing_connection_retry" for issues in file_issues.values() for i in issues):
        actions.append(("MEDIUM", "#d97706", "Add retry logic with exponential backoff for database connection initialization."))
    dup_count = qg_stats.get("warning_no_duplicate_code", 0) + sum(1 for f in ck_findings if "duplicate" in f.get("title", "").lower())
    if dup_count:
        actions.append(("MEDIUM", "#d97706", f"Consolidate {dup_count} instances of duplicate function definitions into shared utility modules."))
    dead_mods = sum(1 for f in ck_findings if f.get("policy_id") == "CK-ARCH-DEAD-MODULES")
    if dead_mods:
        actions.append(("LOW", "#2563eb", f"Review {dead_mods} dead/orphaned modules. Delete if unused or register as entry points in config."))
    complex_count = qg_stats.get("warning_max_complexity", 0)
    if complex_count:
        actions.append(("LOW", "#2563eb", f"Reduce cyclomatic complexity in {complex_count} functions. Use early returns, guard clauses, and extracted helpers."))
    if prs_failed:
        worst = prs_rows[:3] if len(prs_rows) >= 3 else prs_rows
        worst_files_str = ", ".join(r["file"].split("/")[-1] for r in worst)
        actions.append(("LOW", "#2563eb", f"Focus PRS remediation on worst files: {worst_files_str}. Each error costs 10 PRS points."))

    if actions:
        html.append('<table><thead><tr><th style="width:80px">Priority</th><th>Action</th></tr></thead><tbody>')
        for priority, color, action in actions:
            html.append(f'<tr><td><span class="sev-badge" style="background:{SEVERITY_BG.get(priority.lower(), "#f9fafb")};color:{color}">{priority}</span></td><td>{esc(action)}</td></tr>')
        html.append("</tbody></table>")
    else:
        html.append("<p>No critical actions needed. Repository is in good shape.</p>")
    html.append("</div>")

    # ---- FOOTER ----
    html.append(f"""
  <div class="footer">
    {esc(brand_title)} &middot; Generated {now} &middot;
    Powered by Quality Gate + Cathedral Keeper
  </div>
</div>
</body>
</html>""")

    return "\n".join(html)


# ---------------------------------------------------------------------------
# CLI + main
# ---------------------------------------------------------------------------

def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Generate HTML quality reports from quality-gate and cathedral-keeper JSON output."
    )
    p.add_argument("--root", type=str, default=".",
                   help="Workspace directory to scan for repos (default: cwd)")
    p.add_argument("--repos", nargs="+", type=str, default=None,
                   help="Explicit repo directories (skips auto-discovery)")
    p.add_argument("--out", type=str, default=None,
                   help="Output directory (default: <root>/.quality-reports)")
    p.add_argument("--title", type=str, default="Quality & Architecture Report",
                   help="Report branding title")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    root = Path(args.root).resolve()

    # Discover repos
    if args.repos:
        repos = []
        for r in args.repos:
            rp = Path(r).resolve()
            qg = rp / ".quality-reports" / "quality-gate-report.json"
            ck = rp / ".quality-reports" / "cathedral-keeper" / "report.json"
            if qg.is_file() or ck.is_file():
                repos.append((rp, qg if qg.is_file() else None, ck if ck.is_file() else None))
            else:
                print(f"  SKIP  {rp.name} (no .quality-reports/ found)")
    else:
        repos = discover_repos(root)

    if not repos:
        print("No repositories with quality reports found.")
        return 1

    # Output directory
    if args.out:
        output_dir = Path(args.out).resolve()
    elif len(repos) == 1:
        output_dir = repos[0][0] / ".quality-reports"
    else:
        output_dir = root / ".quality-reports"
    output_dir.mkdir(parents=True, exist_ok=True)

    generated = []
    for repo_dir, qg_path, ck_path in repos:
        repo_name = repo_dir.name
        friendly = infer_friendly_name(repo_name)
        qg_data = load_json(qg_path) if qg_path else None
        ck_data = load_json(ck_path) if ck_path else None

        if not qg_data and not ck_data:
            print(f"  SKIP  {repo_name} (no report data found)")
            continue

        tech = infer_tech_stack(qg_data)
        html = generate_html(repo_name, friendly, tech, qg_data, ck_data, args.title)

        slug = friendly.lower().replace(" ", "_")
        out_path = output_dir / f"quality_report_{slug}.html"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)

        # Also save inside the repo's own .quality-reports
        repo_out = repo_dir / ".quality-reports" / "quality_report.html"
        repo_out.parent.mkdir(parents=True, exist_ok=True)
        with open(repo_out, "w", encoding="utf-8") as f:
            f.write(html)

        print(f"  OK    {friendly}")
        print(f"        -> {out_path}")
        print(f"        -> {repo_out}")
        generated.append(out_path)

    print(f"\nDone. {len(generated)} report(s) generated in {output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
