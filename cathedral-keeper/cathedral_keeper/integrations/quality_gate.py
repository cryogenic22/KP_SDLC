from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from cathedral_keeper.integrations.types import IntegrationContext
from cathedral_keeper.models import Evidence, Finding, clamp_snippet
from cathedral_keeper.retry import RetryFailure, retry_call


# Sentinel distinguishing "QG returned no issues" from "QG failed to run"
_QG_FAILED = object()


def run_quality_gate(ctx: IntegrationContext, cfg: Dict[str, Any]) -> List[Finding]:
    """
    Optional integration that ingests quality-gate results without making CK depend on it.

    Phase 1 fix: If quality-gate crashes or fails, emits a WARNING finding
    instead of silently returning []. This prevents "QG crashed" from being
    indistinguishable from "no quality issues found."
    """
    qg_path = str((cfg.get("qg_path") or "quality-gate/quality_gate.py")).strip()
    qg = (ctx.root / qg_path).resolve()
    if not qg.exists():
        return [
            Finding(
                policy_id="CK-INTEGRATION::quality_gate",
                title="Quality Gate script not found",
                severity="info",
                confidence="high",
                why_it_matters=(
                    "CK is configured to integrate with Quality Gate but the script "
                    f"was not found at '{qg_path}'. QG checks will be skipped."
                ),
                evidence=[Evidence(file=qg_path, line=0, snippet="(file not found)", note="Expected QG script path")],
                fix_options=[f"Verify qg_path in config points to the correct location (currently: {qg_path})."],
                verification=[f"test -f {qg_path}"],
                metadata={"qg_path": qg_path, "status": "not_found"},
            )
        ]

    payload, error_info = _run_quality_gate_json(root=ctx.root, qg=qg, paths_file=ctx.target_paths_file)

    if error_info is not None:
        # QG failed to execute — emit a finding instead of silently returning []
        return [
            Finding(
                policy_id="CK-INTEGRATION::quality_gate",
                title="Quality Gate failed to execute",
                severity="medium",
                confidence="high",
                why_it_matters=(
                    "Quality Gate subprocess crashed or returned invalid output. "
                    "This means 'no QG findings' is actually 'QG did not run' — "
                    "a silent failure that masks real quality issues."
                ),
                evidence=[Evidence(file=qg_path, line=0, snippet=clamp_snippet(error_info), note="QG execution error")],
                fix_options=[
                    "Check that quality_gate.py runs correctly standalone.",
                    f"Run: python {qg_path} --root {ctx.root} --json",
                ],
                verification=[f"python {qg_path} --root . --json"],
                metadata={"qg_path": qg_path, "error": error_info, "status": "execution_failed"},
            )
        ]

    if not payload:
        return []

    prs = dict(payload.get("prs", {}) or {})
    stats = _collect_issue_stats(list(payload.get("issues", []) or []))
    return _findings_from_prs(prs=prs, qg_path=qg_path, stats=stats)


def _run_quality_gate_json(
    *, root: Path, qg: Path, paths_file: Path
) -> Tuple[Dict[str, Any], Optional[str]]:
    """Run QG subprocess and return (payload, error_info).

    Returns:
        (payload_dict, None) on success.
        ({}, error_string) on failure — caller MUST check error_info.
    """
    args = [sys.executable, str(qg), "--root", str(root), "--mode", "audit", "--json", "--paths-from", str(paths_file)]

    def _call() -> subprocess.CompletedProcess:
        return subprocess.run(args, capture_output=True, timeout=120)

    result = retry_call(_call, max_retries=1, base_delay=1.0, transient_exceptions=(OSError, TimeoutError))

    if isinstance(result, RetryFailure):
        return {}, f"Retry exhausted after {result.attempts} attempts: {result.last_error}"

    proc = result
    stderr_text = proc.stderr.decode("utf-8", errors="ignore").strip() if proc.stderr else ""

    if proc.returncode not in (0, 1):
        # returncode 0=pass, 1=errors found (both valid). Anything else is a crash.
        return {}, f"QG exited with code {proc.returncode}. stderr: {stderr_text[:500]}"

    raw = proc.stdout.decode("utf-8", errors="ignore") if proc.stdout else ""
    if not raw.strip():
        # QG ran but produced no output — could be a crash or genuinely empty
        if proc.returncode != 0:
            return {}, f"QG exited with code {proc.returncode} but produced no stdout. stderr: {stderr_text[:500]}"
        return {}, None  # genuinely empty (no files to check)

    try:
        return dict(json.loads(raw)), None
    except (json.JSONDecodeError, ValueError) as e:
        return {}, f"QG stdout was not valid JSON: {e}. First 200 chars: {raw[:200]}"


def _collect_issue_stats(issues: List[Dict[str, Any]]) -> Dict[str, Any]:
    per_file_msgs: dict[str, list[str]] = defaultdict(list)
    per_file_rules: dict[str, Counter[str]] = defaultdict(Counter)
    per_file_first_line: dict[str, int] = {}
    for issue in issues[:5000]:
        file = str(issue.get("file") or "")
        if not file:
            continue
        per_file_first_line.setdefault(file, int(issue.get("line") or 1))
        rule = str(issue.get("rule") or "quality_gate")
        if rule:
            per_file_rules[file][rule] += 1
        msg = str(issue.get("message") or "").strip()
        if msg:
            per_file_msgs[file].append(msg)
    return {"msgs": per_file_msgs, "rules": per_file_rules, "first_line": per_file_first_line}


def _findings_from_prs(*, prs: Dict[str, Any], qg_path: str, stats: Dict[str, Any]) -> List[Finding]:
    per_file_msgs = stats.get("msgs") or {}
    per_file_rules = stats.get("rules") or {}
    per_file_first_line = stats.get("first_line") or {}
    findings: List[Finding] = []
    for file, prs_entry in prs.items():
        entry = dict(prs_entry or {})
        score = float(entry.get("score", 100.0))
        errors = int(entry.get("errors", 0))
        warnings = int(entry.get("warnings", 0))
        if errors <= 0 and score >= 85:
            continue
        top_rules = _top_rules(per_file_rules.get(file))
        fix_msgs = [clamp_snippet(m) for m in (per_file_msgs.get(file) or [])[:5] if m]
        line = int(per_file_first_line.get(file, 1))
        findings.append(
            _prs_finding(
                file=file,
                line=line,
                qg_path=qg_path,
                score=score,
                errors=errors,
                warnings=warnings,
                top_rules=top_rules,
                fix_msgs=fix_msgs,
            )
        )
    return sorted(findings, key=lambda f: float(f.metadata.get("prs", 100.0)))


def _prs_finding(
    *, file: str, line: int, qg_path: str, score: float, errors: int, warnings: int, top_rules: str, fix_msgs: List[str]
) -> Finding:
    why = f"PRS={score:.1f} (errors={errors}, warnings={warnings}). Deterministic gate issues block safe change velocity."
    return Finding(
        policy_id="CK-INTEGRATION::quality_gate",
        title=f"Quality Gate PRS below threshold ({score:.1f})",
        severity="high" if errors > 0 or score < 85 else "medium",
        confidence="high",
        why_it_matters=why,
        evidence=[Evidence(file=file, line=line, snippet=clamp_snippet(top_rules or "quality-gate issues"), note="quality-gate summary")],
        fix_options=fix_msgs or (["Run quality gate on the file and fix blocking rules."] if errors else []),
        verification=[f"python {qg_path} --root . {file}"],
        metadata={
            "source": "quality-gate",
            "prs": score,
            "errors": errors,
            "warnings": warnings,
            "top_rules": top_rules,
        },
    )


def _top_rules(counter: Counter[str] | None) -> str:
    if not counter:
        return ""
    return ", ".join([r for r, _ in counter.most_common(3)])

