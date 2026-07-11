"""The single command-line entry point for the Agent Observatory.

    python -m observatory install-hooks    # merge capture hooks (idempotent)
    python -m observatory snapshot          # print the current adaptive snapshot
    python -m observatory record-maturity   # append a maturity checkpoint if evidence changed
    python -m observatory serve             # run the localhost dashboard

Every command is backed by :class:`AdaptiveObservatory`, so ``snapshot`` and the
served dashboard expose the full contract — base health, memory assessment,
telemetry capabilities, and maturity — from one place. The Claude hook adapter
lives in ``claude_hook.py`` and is invoked directly by the installed hook.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .adaptive import AdaptiveObservatory
from .install_hooks import install
from .server import serve


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="observatory",
        description="Adaptive, evidence-first observability for coding-agent harnesses")
    parser.add_argument("--root", default=".", help="repository root (default: current directory)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("install-hooks", help="merge Observatory hooks into .claude/settings.json")
    commands.add_parser("snapshot", help="print the current normalized snapshot")
    commands.add_parser("record-maturity", help="append a maturity checkpoint when evidence changes")
    dashboard = commands.add_parser("serve", help="run the localhost dashboard")
    dashboard.add_argument("--host", default="127.0.0.1")
    dashboard.add_argument("--port", type=int, default=8765)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()
    observatory = AdaptiveObservatory(root)
    if args.command == "install-hooks":
        path, added = install(root)
        print(f"[observatory] {path}: added {len(added)} hook events")
        return 0
    if args.command == "snapshot":
        print(json.dumps(observatory.snapshot(), indent=2))
        return 0
    if args.command == "record-maturity":
        path, recorded = observatory.record_maturity()
        print(f"[observatory] {'recorded new checkpoint' if recorded else 'unchanged'}: {path}")
        return 0
    if args.command == "serve":
        serve(observatory.snapshot, root=root, host=args.host, port=args.port)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
