#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class FileMetrics:
    file: str
    language: str
    is_test: bool
    lines: int
    prs_score: float
    prs_errors: int
    prs_warnings: int
    issues_error: int
    issues_warning: int
    issues_info: int
    distinct_rules: int
    top_rules: str
    faang_score_est: float
    faang_band: str
    faang_notes: str


def _repo_root() -> Path:
    try:
        out = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True)
        p = Path(out.strip())
        if p.exists():
            return p
    except Exception:
        pass
    fallback = Path(__file__).resolve().parents[2]
    return fallback if fallback.exists() else Path.cwd()


def _get_language(path: str) -> str:
    ext = Path(path).suffix.lower()
    return {
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "javascript",
        ".jsx": "javascript",
    }.get(ext, "unknown")


def _is_test_path(path: str) -> bool:
    rel = path.replace("\\", "/").lower()
    name = Path(path).name.lower()
    return (
        "/tests/" in rel
        or "/test/" in rel
        or rel.startswith("tests/")
        or rel.startswith("test/")
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name.endswith(".spec.ts")
        or name.endswith(".spec.tsx")
        or name.endswith(".test.ts")
        or name.endswith(".test.tsx")
        or name.endswith(".spec.js")
        or name.endswith(".test.js")
    )


def _run_gate_json(root: Path, *, paths: list[str] | None) -> dict[str, Any]:
    args = [
        sys.executable,
        str(root / "quality-gate" / "quality_gate.py"),
        "--root",
        str(root),
        "--mode",
        "audit",
        "--json",
    ]
    if paths:
        args.extend(paths)
    out = subprocess.check_output(args)
    return json.loads(out.decode("utf-8"))


def _read_lines(root: Path, rel_path: str) -> int:
    try:
        return len((root / rel_path).read_text(encoding="utf-8", errors="ignore").splitlines())
    except Exception:
        return 0


def _faang_score(
    prs_score: float,
    *,
    per_rule: Counter[str],
) -> tuple[float, str]:
    deductions: list[str] = []
    score = float(prs_score)

    def deduct(rule: str, points: float, label: str) -> None:
        nonlocal score
        count = per_rule.get(rule, 0)
        if count <= 0:
            return
        score -= points
        deductions.append(f"{label}={count}")

    # These are heuristic "review smell" penalties; keep small so PRS stays primary.
    deduct("no_type_escape", 3.0, "type_escapes")
    deduct("function_size", 3.0, "long_functions")
    deduct("file_size", 2.0, "large_file")
    deduct("max_complexity", 2.0, "high_complexity")
    deduct("no_duplicate_code", 1.0, "dup_helpers")
    deduct("duplicate_class_defs", 1.0, "dup_classes")
    deduct("classvar_in_tests", 1.0, "classvar_in_tests")
    deduct("missing_test_assertion", 1.0, "no_assertions")
    deduct("test_isolation", 1.0, "test_global_state")

    score = max(0.0, min(100.0, score))
    return round(score, 1), ";".join(deductions)


def _faang_band(score: float) -> str:
    if score >= 90:
        return "strong"
    if score >= 80:
        return "good"
    if score >= 70:
        return "ok"
    return "needs_work"


def build_metrics(report: dict[str, Any], *, root: Path) -> list[FileMetrics]:
    prs = dict(report.get("prs", {}) or {})
    per_file_rules, per_file_sev = _collect_issue_stats(list(report.get("issues", []) or []))

    out: list[FileMetrics] = []
    for file, prs_entry in prs.items():
        out.append(
            _metric_for_file(
                file=file,
                prs_entry=dict(prs_entry or {}),
                root=root,
                per_file_rules=per_file_rules,
                per_file_sev=per_file_sev,
            )
        )

    out.sort(key=lambda m: (m.faang_score_est, m.prs_score, m.lines), reverse=False)
    return out


def _collect_issue_stats(
    issues: list[dict[str, Any]],
) -> tuple[dict[str, Counter[str]], dict[str, Counter[str]]]:
    per_file_rules: dict[str, Counter[str]] = defaultdict(Counter)
    per_file_sev: dict[str, Counter[str]] = defaultdict(Counter)
    for issue in issues:
        file = str(issue.get("file") or "")
        rule = str(issue.get("rule") or "")
        sev = str(issue.get("severity") or "")
        if not file or not rule or rule == "prs_score":
            continue
        per_file_rules[file][rule] += 1
        if sev:
            per_file_sev[file][sev] += 1
    return per_file_rules, per_file_sev


def _metric_for_file(
    *,
    file: str,
    prs_entry: dict[str, Any],
    root: Path,
    per_file_rules: dict[str, Counter[str]],
    per_file_sev: dict[str, Counter[str]],
) -> FileMetrics:
    language = _get_language(file)
    is_test = _is_test_path(file)
    lines = _read_lines(root, file)

    score = float(prs_entry.get("score", 100.0))
    prs_errors = int(prs_entry.get("errors", 0))
    prs_warnings = int(prs_entry.get("warnings", 0))

    sev_counts = per_file_sev.get(file, Counter())
    issue_error = int(sev_counts.get("error", 0))
    issue_warning = int(sev_counts.get("warning", 0))
    issue_info = int(sev_counts.get("info", 0))

    rules = per_file_rules.get(file, Counter())
    top_rules = ",".join([r for r, _ in rules.most_common(5)])
    faang_score, notes = _faang_score(score, per_rule=rules)

    return FileMetrics(
        file=file,
        language=language,
        is_test=is_test,
        lines=lines,
        prs_score=score,
        prs_errors=prs_errors,
        prs_warnings=prs_warnings,
        issues_error=issue_error,
        issues_warning=issue_warning,
        issues_info=issue_info,
        distinct_rules=len(rules),
        top_rules=top_rules,
        faang_score_est=faang_score,
        faang_band=_faang_band(faang_score),
        faang_notes=notes,
    )


def write_csv(metrics: list[FileMetrics], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "file",
                "language",
                "is_test",
                "lines",
                "prs_score",
                "prs_errors",
                "prs_warnings",
                "issues_error",
                "issues_warning",
                "issues_info",
                "distinct_rules",
                "top_rules",
                "faang_score_est",
                "faang_band",
                "faang_notes",
            ],
        )
        writer.writeheader()
        for m in metrics:
            writer.writerow(
                {
                    "file": m.file,
                    "language": m.language,
                    "is_test": str(bool(m.is_test)).lower(),
                    "lines": m.lines,
                    "prs_score": f"{m.prs_score:.1f}",
                    "prs_errors": m.prs_errors,
                    "prs_warnings": m.prs_warnings,
                    "issues_error": m.issues_error,
                    "issues_warning": m.issues_warning,
                    "issues_info": m.issues_info,
                    "distinct_rules": m.distinct_rules,
                    "top_rules": m.top_rules,
                    "faang_score_est": f"{m.faang_score_est:.1f}",
                    "faang_band": m.faang_band,
                    "faang_notes": m.faang_notes,
                }
            )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export per-file quality metrics (PRS + issues) and a heuristic FAANG review score to CSV."
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(".quality-reports/quality_assessment.csv"),
        help="Output CSV path (relative to repo root by default).",
    )
    parser.add_argument(
        "--paths",
        nargs="*",
        default=None,
        help="Optional paths to include (default: all files under repo root).",
    )
    args = parser.parse_args()

    root = _repo_root()
    report = _run_gate_json(root, paths=list(args.paths) if args.paths else None)
    metrics = build_metrics(report, root=root)
    out_path = (root / args.out).resolve() if not args.out.is_absolute() else args.out
    write_csv(metrics, out_path)
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
