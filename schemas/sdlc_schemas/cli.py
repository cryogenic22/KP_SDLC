"""CLI: ``sdlc schemas check`` and ``sdlc schemas init``.

``check`` validates an overlay and its bundle links, exiting 0 (clean),
1 (errors), or 2 (no instance files — fail-closed, distinct from clean).
``init`` copies the engine-shipped starters into the overlay; each starter is
deliberately red (E-PLACEHOLDER) until an org edits it, so scaffolding can
never go vacuously green.
"""

from __future__ import annotations

import argparse
import importlib.resources as resources
from pathlib import Path

from .api import check_overlay, issues_to_findings

_STARTERS = (
    "def-of-ready.yaml",
    "metric-library.yaml",
    "nfr-budget.yaml",
    "standards.yaml",
    "rubrics/example-rubric.yaml",
)


def cmd_check(args) -> int:
    report = check_overlay([args.core_dir])
    if report.files_checked == 0:
        print(f"[sdlc schemas] no instance files under {args.core_dir} "
              "(fail-closed: E-NO-FILES)")
        return 2
    for finding in issues_to_findings(report.issues):
        print(f"  {finding['rule']}  {finding['file']}:{finding['line']}  "
              f"{finding['message']}")
    if report.ok:
        print(f"[sdlc schemas] OK — {report.files_checked} instance(s) clean")
        return 0
    print(f"[sdlc schemas] FAILED — {len(report.issues)} issue(s) across "
          f"{report.files_checked} instance(s)")
    return 1


def cmd_init(args) -> int:
    dest = Path(args.into)
    written = _copy_starters(dest)
    print(f"[sdlc schemas] wrote {len(written)} starter(s) into {dest}")
    print("[sdlc schemas] each starter FAILS validation until you replace "
          "every REPLACE-ME (born-red scaffolding).")
    return 0


def _copy_starters(dest: Path) -> list:
    base = resources.files("sdlc_schemas").joinpath("starters")
    written: list = []
    for rel in _STARTERS:
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(base.joinpath(rel).read_text(encoding="utf-8"),
                          encoding="utf-8")
        written.append(str(target))
    return written


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sdlc schemas",
        description="Validate and scaffold the .sdlc-core overlay (E1.7).")
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="Validate the overlay + bundle links")
    check.add_argument("--core-dir", default=".sdlc-core",
                       help="Overlay root to validate (default: .sdlc-core)")
    check.set_defaults(func=cmd_check)

    init = sub.add_parser("init", help="Copy the failing starter instances")
    init.add_argument("--into", default=".sdlc-core",
                      help="Destination overlay directory (default: .sdlc-core)")
    init.set_defaults(func=cmd_init)
    return parser


def main(argv: list | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
