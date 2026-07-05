#!/usr/bin/env python3
"""Fix Engine CLI — auto-fix findings from Quality Gate / Cathedral Keeper.

Usage examples
--------------
  python fix_engine.py --qg-report qg.json --dry-run
  python fix_engine.py --qg-report qg.json --fix --safe-only
  python fix_engine.py --qg-report qg.json --suggest --format github
  python fix_engine.py --qg-report qg.json --sarif --output out.sarif
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from fe.types import FixPatch, FixResult, SuggestionBlock
from fe.registry import get_fix, get_fix_meta, list_fixable_rules
from fe.applier import apply_patches, apply_fix_result, generate_diff
from sarif_formatter import generate_sarif


# ---------------------------------------------------------------------------
# Report loading
# ---------------------------------------------------------------------------

def _load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _qg_report_for_sarif(qg_data: Any) -> Dict[str, Any]:
    """Adapt a loaded QG report to the shape ``generate_sarif`` expects.

    Quality Gate natively emits ``{"issues": [...]}`` whose entries carry
    a ``rule`` key; fix-engine also accepts bare lists or
    ``{"findings": [...]}`` shapes keyed by ``rule_id``/``id``. Normalise
    to the ``issues`` shape so the SARIF run is never silently empty.
    """
    if isinstance(qg_data, dict) and "issues" in qg_data:
        return qg_data

    raw = qg_data if isinstance(qg_data, list) else qg_data.get("findings", [])
    issues: List[Dict[str, Any]] = []
    for finding in raw:
        issue = dict(finding)
        if "rule" not in issue:
            issue["rule"] = issue.get("rule_id", issue.get("id", "unknown"))
        issues.append(issue)
    return {"issues": issues}


# ---------------------------------------------------------------------------
# Patch generation from findings
# ---------------------------------------------------------------------------

def _build_patches(
    findings: List[Dict[str, Any]],
    root: Path,
    safe_only: bool,
    confidence_threshold: float,
) -> List[FixPatch]:
    """Turn raw QG/CK findings into FixPatch objects via the registry."""
    patches: List[FixPatch] = []
    for finding in findings:
        rule_id = finding.get("rule_id", finding.get("id", ""))
        fix_fn = get_fix(rule_id)
        if fix_fn is None:
            continue

        meta = get_fix_meta(rule_id) or {}
        category = meta.get("category", "manual")
        conf = meta.get("confidence", 0.0)

        if safe_only and category != "safe":
            continue
        if conf < confidence_threshold:
            continue

        patch = fix_fn(finding, root)
        if patch is not None:
            patches.append(patch)
    return patches


# ---------------------------------------------------------------------------
# Suggestion block generation
# ---------------------------------------------------------------------------

def _patches_to_suggestions(patches: List[FixPatch]) -> List[SuggestionBlock]:
    return [
        SuggestionBlock(
            rule_id=p.rule_id,
            file_path=p.file_path,
            line=p.line,
            original=p.original,
            replacement=p.replacement,
            explanation=p.explanation,
            confidence=p.confidence,
            category=p.category,
        )
        for p in patches
    ]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fix-engine",
        description="Auto-fix findings from Quality Gate and Cathedral Keeper.",
    )
    parser.add_argument("--root", default=".", help="Project root directory (default: .)")
    parser.add_argument("--qg-report", required=True, help="Path to QG JSON report")
    parser.add_argument("--ck-report", default=None, help="Path to CK JSON report (optional)")
    parser.add_argument("--fix", action="store_true", help="Apply fixes to files")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without modifying files")
    parser.add_argument("--suggest", action="store_true", help="Generate PR suggestion blocks")
    parser.add_argument(
        "--sarif",
        action="store_true",
        help=(
            "Output SARIF 2.1.0 (takes precedence over --suggest; combined "
            "with --fix/--dry-run, fixes are processed first and embedded "
            "as SARIF fixes[])"
        ),
    )
    parser.add_argument("--safe-only", action="store_true", help="Only apply safe-category fixes")
    parser.add_argument("--confidence", type=float, default=0.95, help="Minimum confidence threshold (default: 0.95)")
    parser.add_argument("--format", choices=["github", "gitlab"], default="github", help="Suggestion format (default: github)")
    parser.add_argument("--output", default=None, help="Output file path (default: stdout)")
    parser.add_argument("--config", default=None, help="Path to config JSON")
    parser.add_argument("--staged", action="store_true", help="Only fix staged files")
    parser.add_argument("--no-backup", action="store_true", help="Skip creating .bak backup files")
    return parser


def _render_output(
    args: argparse.Namespace,
    qg_data: Any,
    ck_report_dict: Dict[str, Any] | None,
    result: FixResult,
    patches: List[FixPatch],
) -> str:
    """Render the CLI output for the selected mode.

    --sarif takes precedence over --suggest; combined with --fix/--dry-run
    the applied patches are embedded as SARIF fixes[].
    """
    # ---- Mode: SARIF ----
    if args.sarif:
        sarif = generate_sarif(
            qg_report=_qg_report_for_sarif(qg_data),
            ck_report=ck_report_dict,
            patches=result.applied if (args.fix or args.dry_run) else patches,
        )
        return json.dumps(sarif, indent=2)

    # ---- Mode: suggest ----
    if args.suggest and not (args.fix or args.dry_run):
        suggestions = _patches_to_suggestions(patches)
        fmt_fn = (
            SuggestionBlock.to_github_markdown
            if args.format == "github"
            else SuggestionBlock.to_gitlab_markdown
        )
        return "\n---\n".join(fmt_fn(s) for s in suggestions)

    # ---- Default (and fix/dry-run): summary JSON ----
    return json.dumps(result.summary(), indent=2)


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()

    # Load findings (copy the QG list so CK findings never leak back into
    # qg_data, which --sarif re-uses for the Quality Gate run).
    qg_data = _load_json(args.qg_report)
    findings: List[Dict[str, Any]] = list(qg_data) if isinstance(qg_data, list) else list(qg_data.get("findings", []))

    ck_report_dict: Dict[str, Any] | None = None
    if args.ck_report:
        ck_data = _load_json(args.ck_report)
        ck_report_dict = ck_data if isinstance(ck_data, dict) else {"findings": ck_data}
        findings.extend(ck_report_dict.get("findings", []))

    # Load optional config overrides
    if args.config:
        _load_json(args.config)  # reserved for future use

    # Build patches
    patches = _build_patches(
        findings,
        root,
        safe_only=args.safe_only,
        confidence_threshold=args.confidence,
    )

    result = FixResult(patches=patches)

    # ---- Apply fixes when requested (combines with --sarif) ----
    if args.fix or args.dry_run:
        result = apply_fix_result(
            result,
            dry_run=args.dry_run,
            backup=not args.no_backup,
        )

    output = _render_output(args, qg_data, ck_report_dict, result, patches)

    # Write output
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output + "\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
