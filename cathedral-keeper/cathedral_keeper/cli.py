from __future__ import annotations

import argparse
from pathlib import Path

from cathedral_keeper.runner import run, run_baseline


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ck", description="Cathedral Keeper (architecture governance).")
    sub = p.add_subparsers(dest="cmd", required=True)

    analyze = sub.add_parser("analyze", help="Analyze repo or diffs and emit an evidence-first report.")
    analyze.add_argument("--root", type=Path, default=None, help="Repo root (default: git root or CWD).")
    analyze.add_argument(
        "--mode",
        choices=["repo", "diff"],
        default="repo",
        help="repo=analyze all included files, diff=analyze changed files only.",
    )
    analyze.add_argument("--config", type=Path, default=None, help="Optional config path (JSON).")
    analyze.add_argument("--paths-from", type=Path, default=None, help="Optional newline-delimited paths to analyze.")
    analyze.add_argument("--base", type=str, default="HEAD~1", help="Diff base ref for --mode diff (default: HEAD~1).")
    analyze.add_argument("--out-md", type=Path, default=None, help="Markdown output path.")
    analyze.add_argument("--out-json", type=Path, default=None, help="JSON output path.")
    analyze.add_argument("--no-qg", action="store_true", help="Disable quality-gate ingestion policy.")
    analyze.add_argument("--blast-radius", action="store_true", help="Run blast-radius analysis on changed/analyzed files.")
    analyze.add_argument("--top", type=int, default=None, help="Override top findings count in markdown output.")
    analyze.add_argument("--verbose", action="store_true", help="Verbose console output.")

    baseline = sub.add_parser("baseline", help="Create or update the architectural baseline snapshot.")
    baseline.add_argument("--root", type=Path, default=None, help="Repo root (default: git root or CWD).")
    baseline.add_argument("--config", type=Path, default=None, help="Optional config path (JSON).")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "analyze":
        return run(args)
    if args.cmd == "baseline":
        return run_baseline(args)
    raise SystemExit(f"Unknown command: {args.cmd}")

