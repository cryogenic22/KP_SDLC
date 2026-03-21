from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from cathedral_keeper.models import Finding, confidence_rank, normalize_path, severity_rank


@dataclass(frozen=True, slots=True)
class Report:
    root: str
    created_at: str
    findings: List[Finding]
    stats: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "root": self.root,
            "created_at": self.created_at,
            "stats": dict(self.stats),
            "findings": [f.to_dict() for f in self.findings],
        }


def build_report(*, root: Path, findings: List[Finding]) -> Report:
    created_at = datetime.now().isoformat()
    stats = _summarize(findings)
    return Report(root=normalize_path(str(root)), created_at=created_at, findings=findings, stats=stats)


def write_json(report: Report, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")


def write_markdown(report: Report, path: Path, *, top_findings: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(report, top_findings=top_findings), encoding="utf-8")


def render_markdown(report: Report, *, top_findings: int) -> str:
    f_sorted = sorted(
        report.findings,
        key=lambda f: (severity_rank(f.severity), confidence_rank(f.confidence)),
        reverse=True,
    )
    lines: List[str] = []
    lines.extend(_md_header(report))
    lines.extend(_md_summary(report))
    lines.extend(_md_top_findings(f_sorted, top_findings=top_findings))
    lines.extend(_md_hotspots(report))
    lines.extend(_md_policy_breakdown(report))
    return "\n".join(lines)


def _md_header(report: Report) -> List[str]:
    return [
        "# Cathedral Keeper Report",
        "",
        f"- Root: `{report.root}`",
        f"- Created: `{report.created_at}`",
        f"- Findings: `{len(report.findings)}`",
        "",
    ]


def _md_summary(report: Report) -> List[str]:
    sev = report.stats.get("severity_counts", {})
    return [
        "## Summary",
        "",
        f"- Blockers: `{sev.get('blocker', 0)}`",
        f"- High: `{sev.get('high', 0)}`",
        f"- Medium: `{sev.get('medium', 0)}`",
        f"- Low: `{sev.get('low', 0)}`",
        "",
    ]


def _md_top_findings(findings: List[Finding], *, top_findings: int) -> List[str]:
    lines: List[str] = ["## Top Findings", ""]
    for idx, f in enumerate(findings[: max(0, int(top_findings))], start=1):
        lines.append(f"### {idx}. {f.severity.upper()} ({f.confidence}) - {f.title}")
        lines.append(f"- Policy: `{f.policy_id}`")
        lines.append(f"- Why: {f.why_it_matters}")
        if f.evidence:
            ev = f.evidence[0]
            lines.append(f"- Evidence: `{ev.file}:{ev.line}` - {ev.snippet}")
        if f.fix_options:
            lines.append(f"- Fix: {f.fix_options[0]}")
        if f.verification:
            lines.append(f"- Verify: `{f.verification[0]}`")
        lines.append("")
    return lines


def _md_hotspots(report: Report) -> List[str]:
    lines: List[str] = ["## Hotspots (Files)", ""]
    by_file = defaultdict(int)
    for f in report.findings:
        for e in f.evidence:
            by_file[e.file] += 1
    for file, count in sorted(by_file.items(), key=lambda kv: kv[1], reverse=True)[:30]:
        lines.append(f"- `{file}` - `{count}` findings")
    lines.append("")
    return lines


def _md_policy_breakdown(report: Report) -> List[str]:
    lines: List[str] = ["## Policy Breakdown", ""]
    by_policy = Counter([f.policy_id for f in report.findings])
    for pid, count in by_policy.most_common():
        lines.append(f"- `{pid}` - `{count}`")
    lines.append("")
    return lines


def _summarize(findings: List[Finding]) -> Dict[str, Any]:
    sev = Counter([str(f.severity or "").lower() for f in findings])
    return {"severity_counts": dict(sev)}
