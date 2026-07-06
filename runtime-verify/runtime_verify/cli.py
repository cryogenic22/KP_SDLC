"""``rv`` command-line entry point.

``rv data reconcile --core-dir DIR --adapter NAME`` resolves and E1.7-validates
the metric-library under DIR, builds the adapter registry, runs reconciliation,
and exits non-zero on any error-severity finding (fail closed). The only
built-in adapter is the deterministic ``stub`` (values supplied via
``--fixtures``); the SQL-warehouse adapter lands in a later PR, so an
unregistered system fails closed with RV-ADAPTER-UNRESOLVED rather than
silently passing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .adapters import AdapterRegistry, StubAdapter
from .packs.data_reconcile import reconcile
from .thresholds import ContractInvalid, load_validated_library

_STUB = "stub"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rv", description="runtime-verify")
    sub = parser.add_subparsers(dest="domain", required=True)
    data = sub.add_parser("data", help="data-pack checks")
    checks = data.add_subparsers(dest="check", required=True)
    rec = checks.add_parser("reconcile", help="reconcile reported vs authoritative values")
    rec.add_argument("--core-dir", default=".sdlc-core",
                     help="overlay dir holding metric-library.yaml")
    rec.add_argument("--adapter", default=_STUB,
                     help="adapter name bound to every source.system")
    rec.add_argument("--fixtures", default=None,
                     help="JSON fixtures for the stub adapter "
                          "({authoritative:{ref:value}, reported:{metric_id:value}})")
    rec.set_defaults(func=cmd_reconcile)
    return parser


def _load_fixtures(path):
    if not path:
        return {}, {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload.get("authoritative") or {}, payload.get("reported") or {}


def _build_registry(adapter_name, systems, authoritative):
    registry = AdapterRegistry()
    if adapter_name == _STUB:
        adapter = StubAdapter(authoritative)
        for system in systems:
            registry.register(system, adapter)
    return registry


def _systems_in(library):
    return sorted({metric["source"]["system"] for metric in library["metrics"].values()})


def cmd_reconcile(args) -> int:
    try:
        library, path = load_validated_library(args.core_dir)
    except (FileNotFoundError, ValueError) as exc:
        print(f"[rv] no usable metric-library: {exc}", file=sys.stderr)
        return 1
    except ContractInvalid as exc:
        print(f"[rv] refusing to run: {exc}", file=sys.stderr)
        return 1
    authoritative, reported = _load_fixtures(args.fixtures)
    registry = _build_registry(args.adapter, _systems_in(library), authoritative)
    result = reconcile(library, registry, reported, contract_path=str(path))
    _report(result)
    return 0 if result.ok else 1


def _report(result) -> None:
    for finding in result.findings():
        print(f"[rv] {finding['severity'].upper()} {finding['rule']}: {finding['message']}")
    verdict = "ok" if result.ok else "FAILED"
    print(f"[rv] reconcile {verdict}: checked={result.checked} "
          f"skipped={result.skipped} issues={len(result.issues)}")


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
