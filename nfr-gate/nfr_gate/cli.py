"""``g6`` command-line entry point.

``g6 nfr budget --core-dir DIR --observations OBS.json`` resolves and
E1.7-validates the nfr-budget contract under DIR, compares each budget's
supplied observation to the contract bound, and maps the outcome to an exit
code:

  - 0: every budget observed and within its bound.
  - 1: a budget breach OR an unmeasured budget (a declared budget with no
    supplied observation is a block, never a silent pass).
  - 2: config-unresolved -- a missing/invalid/unparseable nfr-budget contract,
    or an ``--observations`` file that was given but cannot be read/parsed.

Not passing ``--observations`` is NOT a config error: it means nothing was
measured, so every budget blocks as NFR-NO-OBSERVATION (exit 1). The
measurement adapters (pipeline metrics, app profiling) land in a later PR; the
observations file is the deterministic stub input this PR.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sdlc_schemas import miniyaml

from .budgets import ContractInvalid, load_validated_budgets
from .packs.nfr_budget import check_budgets

_DEFAULT_CORE = ".sdlc-core"
_EXIT_OK = 0
_EXIT_BLOCK = 1
_EXIT_CONFIG = 2

# Every absence in the contract load (missing file, an unreadable path -- a
# directory or permission-denied is an OSError -- unparseable YAML/JSON, or an
# unknown singleton tag) collapses to one loud exit 2; ContractInvalid is kept
# separate only so its E1.7 findings are echoed for accountability.
_CONTRACT_ABSENT = (OSError, ValueError, miniyaml.MiniYAMLError)


class _ConfigUnresolved(Exception):
    """A contract/observations absence that must fail closed to exit 2."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="g6", description="G6 NFR-budget gate")
    sub = parser.add_subparsers(dest="domain", required=True)
    nfr = sub.add_parser("nfr", help="non-functional-requirement checks")
    checks = nfr.add_subparsers(dest="check", required=True)
    budget = checks.add_parser("budget", help="check observed NFRs against their budgets")
    budget.add_argument("--core-dir", default=_DEFAULT_CORE,
                        help="overlay dir holding nfr-budget.yaml")
    budget.add_argument("--observations", default=None,
                        help="JSON file mapping budget_id -> observed value "
                             "(absent => nothing measured => every budget blocks)")
    budget.set_defaults(func=cmd_budget)
    return parser


def _load_contract(core_dir):
    """Resolve + E1.7-validate the nfr-budget contract, fail-closed on absence."""
    try:
        return load_validated_budgets(core_dir)
    except ContractInvalid as exc:
        for finding in exc.findings:
            print(f"[g6]   {finding['rule']}: {finding['message']}", file=sys.stderr)
        raise _ConfigUnresolved(str(exc)) from exc
    except _CONTRACT_ABSENT as exc:
        raise _ConfigUnresolved(f"no usable nfr-budget contract: {exc}") from exc


def _load_observations(path):
    """Load the JSON observations map. Absent path => {} (nothing measured, a
    fail-closed block, not a config error). A given-but-unreadable/malformed file
    IS a config error (exit 2): it is never silently treated as no measurements."""
    if not path:
        return {}
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise _ConfigUnresolved(f"unusable observations file {path!r}: {exc}") from exc
    if not isinstance(payload, dict):
        raise _ConfigUnresolved(
            f"observations file {path!r} must be a JSON object of "
            "budget_id -> value")
    return payload


def cmd_budget(args) -> int:
    try:
        contract, path = _load_contract(args.core_dir)
        observations = _load_observations(args.observations)
    except _ConfigUnresolved as exc:
        print(f"[g6] refusing to run: {exc}", file=sys.stderr)
        return _EXIT_CONFIG
    result = check_budgets(contract, observations, contract_path=str(path))
    _report(result)
    return _EXIT_OK if result.ok else _EXIT_BLOCK


def _report(result) -> None:
    for finding in result.findings():
        print(f"[g6] {finding['severity'].upper()} {finding['rule']}: "
              f"{finding['message']}", file=sys.stderr)
    verdict = "ok" if result.ok else "BLOCKED"
    print(f"[g6] nfr budget {verdict}: checked={result.checked} "
          f"skipped={result.skipped} issues={len(result.issues)}", file=sys.stderr)


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
