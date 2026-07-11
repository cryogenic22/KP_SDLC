"""Readiness-gate projections: quality, architecture, and behavioural evaluation.

Each projection reads one KP_SDLC artifact and returns
``(gate_summary, findings)``. Every gate fails closed: a missing, empty,
zero-file, or all-skipped artifact is never rendered as healthy or ``pass``,
even when the artifact itself says ``passed`` or ``ok``, and a present-but-not-
passing result surfaces a finding in the attention queue (not only in the gate
panel). Nested artifact fields are read through tolerant coercers so a
half-written report degrades a single gate instead of raising through the
snapshot.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .findings import finding
from .sources import as_dict, as_int, read_json


def quality_gate(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Latest root Quality Gate report; a zero-file pass is inconclusive, never green."""
    reports = sorted((root / ".quality-reports").glob("report_*.json"))
    report_path = reports[-1] if reports else None
    report = read_json(report_path) if report_path else None
    if report is None:
        gate = {"id": "quality", "name": "Quality Gate", "status": "missing", "source": None}
        return gate, [finding(
            "quality-missing", "No current quality report", "medium",
            "The observatory could not find a root quality report.", [],
            "Run Quality Gate and refresh the dashboard.", source="quality-gate")]
    checked = as_int(as_dict(report.get("stats")).get("files_checked"))
    if report.get("passed") is True and checked > 0:
        status = "pass"
    elif checked == 0:
        status = "inconclusive"
    else:
        status = "fail"
    gate = {"id": "quality", "name": "Quality Gate", "status": status,
            "files_checked": checked, "source": str(report_path)}
    findings = []
    if checked == 0:
        findings.append(finding(
            "quality-vacuous", "Quality report checked zero files", "high",
            "A report marked passed without checking files is not usable release evidence.",
            [{"path": str(report_path), "passed": report.get("passed"), "files_checked": checked}],
            "Run the gate against the repository and require a non-zero file count.",
            source="quality-gate"))
    return gate, findings


def architecture_gate(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Cathedral Keeper report; an empty/structureless report is inconclusive, not pass."""
    report_path = root / ".quality-reports" / "cathedral-keeper" / "report.json"
    report = read_json(report_path)
    if report is None:
        return {"id": "architecture", "name": "Architecture", "status": "missing", "source": None}, []
    counts = as_dict(as_dict(report.get("stats")).get("severity_counts"))
    raw_findings = report.get("findings")
    findings_list = raw_findings if isinstance(raw_findings, list) else []
    # A present report is only trustworthy if it carries evidence of an actual
    # scan: recognizable severity counts, or a findings array. A bare `{}` must
    # not be credited as a clean run.
    if not counts and not isinstance(raw_findings, list):
        gate = {"id": "architecture", "name": "Architecture", "status": "inconclusive",
                "severity_counts": {}, "source": str(report_path)}
        return gate, [finding(
            "architecture-vacuous", "Architecture report has no scan evidence", "high",
            "A present but empty or structureless Cathedral Keeper report is not proof of a "
            "clean run.",
            [{"path": str(report_path)}],
            "Run Cathedral Keeper against the repository and require real scan output.",
            source="cathedral-keeper")]
    high = as_int(counts.get("high"))
    gate = {"id": "architecture", "name": "Architecture", "status": "fail" if high else "pass",
            "severity_counts": counts, "source": str(report_path)}
    representative = [item for item in findings_list
                      if isinstance(item, dict) and item.get("severity") == "high"
                      and item.get("policy_id") != "CK-INTEGRATION::quality_gate"]
    if not representative:
        return gate, []
    item = representative[0]
    return gate, [finding(
        "architecture-high", "High-severity architecture findings exist", "high",
        f"Cathedral Keeper reports {high} high-severity findings. "
        f"Representative: {item.get('title', 'finding')}.",
        [ev for ev in (item.get("evidence") or [])[:3] if isinstance(ev, dict)],
        "Open the Cathedral Keeper report and address or explicitly baseline "
        "changed-surface findings.",
        source="cathedral-keeper")]


def eval_gate(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Eval Engine scorecard; a missing, failing, or all-skipped suite is not evidence."""
    candidates = [root / ".sdlc-core" / "evals" / "latest.json",
                  root / ".quality-reports" / "eval" / "latest.json"]
    scorecard_path = next((path for path in candidates if path.exists()), None)
    scorecard = read_json(scorecard_path) if scorecard_path else None
    if scorecard is None:
        gate = {"id": "eval", "name": "Evaluations", "status": "missing", "source": None}
        return gate, [finding(
            "eval-missing", "No current evaluation scorecard", "high",
            "Tests and static analysis do not prove that the requested behaviour "
            "meets its acceptance criteria.",
            [{"searched": [str(path) for path in candidates]}],
            "Run the relevant eval corpus and publish latest.json before calling "
            "the change production-ready.",
            source="eval-engine")]
    considered = as_int(scorecard.get("total")) - as_int(scorecard.get("skipped"))
    ok = scorecard.get("ok") is True and considered > 0
    gate = {"id": "eval", "name": "Evaluations", "status": "pass" if ok else "fail",
            "total": scorecard.get("total", 0), "skipped": scorecard.get("skipped", 0),
            "source": str(scorecard_path)}
    if ok:
        return gate, []
    return gate, [finding(
        "eval-failing", "Evaluation scorecard is not passing", "high",
        "A published eval scorecard ran but did not pass — it has failing cases, or every "
        "case was skipped, so no acceptance behaviour is actually proven.",
        [{"path": str(scorecard_path), "ok": scorecard.get("ok"),
          "total": scorecard.get("total"), "skipped": scorecard.get("skipped")}],
        "Make the acceptance evaluations pass, or investigate why every case skipped, "
        "before calling the change production-ready.",
        source="eval-engine")]
