"""``g2`` command-line entry point.

``g2 contract <report-artifact> --core-dir .sdlc-core`` resolves and
E1.7-validates the metric-library (via G4's ``load_validated_library`` -- G2
does NOT fork contract loading), extracts the metric ids the report artifact
references, and blocks any that resolve to no library entry. The exit code is 0
on a clean run, 1 when a dangling (unresolved) reference remains, and 2 on any
config-unresolved absence -- a missing/invalid/unparseable metric-library, or a
missing/unreadable/malformed report artifact. Every absence is a loud non-zero
exit, never a vacuous pass.
"""

from __future__ import annotations

import argparse
import sys

from runtime_verify.thresholds import ContractInvalid, load_validated_library
from sdlc_schemas import miniyaml

from .artifact import MalformedArtifact, extract_metric_ids, parse_artifact
from .check import check_contract
from .model import ContractCheckResult

_DEFAULT_CORE = ".sdlc-core"
_EXIT_OK = 0
_EXIT_BLOCK = 1
_EXIT_CONFIG = 2


def build_parser() -> argparse.ArgumentParser:
    """The ``g2`` argument parser: one ``contract`` subcommand."""
    parser = argparse.ArgumentParser(prog="g2", description="G2 metric-contract gate")
    sub = parser.add_subparsers(dest="command", required=True)
    con = sub.add_parser("contract", help="check a report artifact against the metric-library")
    con.add_argument("artifact", help="path to the report artifact (YAML or JSON)")
    con.add_argument("--core-dir", default=_DEFAULT_CORE,
                     help="overlay dir holding metric-library.yaml")
    con.set_defaults(func=cmd_contract)
    return parser


def _fail_config(message: str) -> int:
    """Emit a loud config-unresolved refusal and return the exit-2 code."""
    print(f"[g2] refusing to run: {message}", file=sys.stderr)
    return _EXIT_CONFIG


def _report(result: ContractCheckResult) -> None:
    """Render every block gap, advisory, and the verdict line to stderr."""
    for gap in result.gaps:
        print(f"[g2] BLOCK {gap.metric_id} (owner {gap.owner or '(none)'}): "
              f"{gap.message}", file=sys.stderr)
    for advisory in result.advisories:
        print(f"[g2] warn {advisory.metric_id}: {advisory.message}", file=sys.stderr)
    verdict = "ok" if result.ok else "BLOCKED"
    print(f"[g2] contract {verdict}: checked={result.checked} "
          f"gaps={len(result.gaps)} advisories={len(result.advisories)}",
          file=sys.stderr)


# Every absence in the library load (missing file, an unreadable path -- a
# directory or permission-denied is an OSError -- unparseable YAML/JSON, or an
# unknown singleton tag) collapses to one loud exit 2; ContractInvalid is kept
# separate only so its E1.7 findings are echoed for accountability.
_LIBRARY_ABSENT = (OSError, ValueError, miniyaml.MiniYAMLError)
# Every absence in the artifact read (unreadable, unparseable YAML, malformed
# shape, or bad JSON -- json.JSONDecodeError is a ValueError) is one loud exit 2.
_ARTIFACT_ABSENT = (OSError, MalformedArtifact, miniyaml.MiniYAMLError, ValueError)


class _ConfigUnresolved(Exception):
    """A library/artifact absence that must fail closed to exit 2 (never a pass)."""


def _load_library(core_dir):
    """Resolve + E1.7-validate the metric-library, fail-closed on every absence.

    Reuses G4's ``load_validated_library`` (no forked contract loading). Any
    absence -- missing/unparseable/unknown-tag -- raises ``_ConfigUnresolved``;
    an E1.7-invalid contract echoes its findings first, so the refusal is loud.
    """
    try:
        return load_validated_library(core_dir)
    except ContractInvalid as exc:
        for finding in exc.findings:
            print(f"[g2]   {finding['rule']}: {finding['message']}", file=sys.stderr)
        raise _ConfigUnresolved(str(exc)) from exc
    except _LIBRARY_ABSENT as exc:
        raise _ConfigUnresolved(f"no usable metric-library: {exc}") from exc


def _extract_ids(artifact_path):
    """Parse the report artifact and extract its referenced ids, fail-closed.

    A report that cannot be read (unreadable / unparseable / malformed) raises
    ``_ConfigUnresolved`` -- it is never treated as 'zero dangling references'.
    """
    try:
        return extract_metric_ids(parse_artifact(artifact_path))
    except _ARTIFACT_ABSENT as exc:
        raise _ConfigUnresolved(f"unusable report artifact {artifact_path!r}: {exc}") from exc


def cmd_contract(args) -> int:
    """Load the library + artifact (fail-closed), run the check, map to exit code."""
    try:
        library, path = _load_library(args.core_dir)
        referenced_ids = _extract_ids(args.artifact)
    except _ConfigUnresolved as exc:
        return _fail_config(str(exc))
    result = check_contract(library, referenced_ids, contract_path=str(path))
    _report(result)
    return _EXIT_OK if result.ok else _EXIT_BLOCK


def main(argv=None) -> int:
    """Parse args and dispatch the subcommand."""
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
