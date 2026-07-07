"""``g1`` command-line entry point plus the ``preflight`` orchestrator.

``g1 preflight <spec-file> --kind K [--core-dir .sdlc-core] [--judge-model ID]``
resolves and E1.7-validates the def-of-ready contract, selects the requested
kind (fail-closed on the unknown), runs each requirement's deterministic
evaluator against the parsed spec, and wires the sufficiency-judge choke as a
loud skip that can never gate. The exit code is 0 on a clean preflight, 1 when a
``block`` requirement gap remains, and 2 on any config-unresolved absence -- a
missing/invalid contract, an unknown kind, an unreadable spec, or a malformed
check. Every absence is a loud non-zero exit, never a vacuous pass.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sdlc_schemas import miniyaml

from .contract import ContractInvalid, KindNotFound, load_validated_dor, select_kind
from .evaluators import MalformedCheck, UnknownCheckType, evaluate_check, parse_spec
from .judge import load_judge_bundle, sufficiency_skip_reason
from .model import Gap, PreflightResult, Severity

_DEFAULT_CORE = ".sdlc-core"
_BLOCK = "block"
_BLOCK_RULE = "G1-BLOCK-GAP"
_WARN_RULE = "G1-WARN-ADVISORY"
_EXIT_OK = 0
_EXIT_BLOCK = 1
_EXIT_CONFIG = 2


def _make_gap(requirement: dict, detail: str, spec_file: str) -> Gap:
    """Build a Gap from a failing requirement; the id is quoted in the message
    so the block report names the gap, never an anonymous count."""
    rid = requirement.get("id", "")
    check_type = requirement.get("check", {}).get("type", "")
    message = f"{rid}: {requirement.get('description', '')} ({detail})"
    if requirement.get("severity") == _BLOCK:
        return Gap(rule=_BLOCK_RULE, requirement_id=rid, severity=Severity.ERROR,
                   message=message, check_type=check_type, file=spec_file)
    return Gap(rule=_WARN_RULE, requirement_id=rid, severity=Severity.WARNING,
               message=message, check_type=check_type, file=spec_file)


def preflight(kind: dict, kind_name: str, spec, *, bundle=None,
              judge_model_id: str = "") -> PreflightResult:
    """Run every requirement in a resolved kind against the spec.

    Returns a fail-closed ``PreflightResult``: a failing ``block`` requirement
    becomes a gap (exit 1), a failing ``warn`` an advisory (exit 0), and the
    sufficiency judge contributes only a loud, named SKIP that never touches
    ``ok``. Raises ``UnknownCheckType`` / ``MalformedCheck`` on a check that
    slipped past E1.7 -- the caller turns that into a config-unresolved exit."""
    requires = kind.get("requires", [])
    gaps = []
    advisories = []
    spec_file = spec.file
    for requirement in requires:
        passed, detail = evaluate_check(requirement["check"], spec)
        if passed:
            continue
        gap = _make_gap(requirement, detail, spec_file)
        (gaps if gap.severity is Severity.ERROR else advisories).append(gap)
    skip = sufficiency_skip_reason(kind, bundle or {}, judge_model_id)
    # every requirement above was evaluated (a malformed check raises out), so
    # the evaluated count is exactly the checklist length -- never a partial run.
    return PreflightResult(kind=kind_name, evaluated=len(requires),
                           gaps=tuple(gaps), advisories=tuple(advisories),
                           skips=(skip,) if skip else ())


def build_parser() -> argparse.ArgumentParser:
    """The ``g1`` argument parser: one ``preflight`` subcommand."""
    parser = argparse.ArgumentParser(prog="g1", description="G1 input-sufficiency gate")
    sub = parser.add_subparsers(dest="command", required=True)
    pre = sub.add_parser("preflight", help="check a spec against the def-of-ready")
    pre.add_argument("spec", help="path to the spec file being gated")
    pre.add_argument("--kind", required=True, help="def-of-ready kind to enforce")
    pre.add_argument("--core-dir", default=_DEFAULT_CORE,
                     help="overlay dir holding def-of-ready.yaml (+ rubrics/)")
    pre.add_argument("--judge-model", default="",
                     help="judge model id checked against a rubric's binding")
    pre.set_defaults(func=cmd_preflight)
    return parser


def _fail_config(message: str) -> int:
    """Emit a loud config-unresolved refusal and return the exit-2 code."""
    print(f"[g1] refusing to run: {message}", file=sys.stderr)
    return _EXIT_CONFIG


def _report(result: PreflightResult) -> None:
    """Render every gap, advisory and judge skip, then the verdict line."""
    for gap in result.gaps:
        print(f"[g1] BLOCK {gap.requirement_id}: {gap.message}", file=sys.stderr)
    for advisory in result.advisories:
        print(f"[g1] warn {advisory.requirement_id}: {advisory.message}", file=sys.stderr)
    for skip in result.skips:
        print(f"[g1] JUDGE SKIP (never gates): {skip}", file=sys.stderr)
    verdict = "ok" if result.ok else "BLOCKED"
    print(f"[g1] preflight {verdict}: kind={result.kind} evaluated={result.evaluated} "
          f"gaps={len(result.gaps)} advisories={len(result.advisories)} "
          f"skips={len(result.skips)}", file=sys.stderr)


def _run_preflight(kind: dict, args, spec_path: str) -> int:
    """Parse the spec, run the checks, and map the result to an exit code."""
    try:
        spec = parse_spec(spec_path)
    except OSError as exc:
        return _fail_config(f"unreadable spec file {spec_path!r}: {exc}")
    except miniyaml.MiniYAMLError as exc:
        return _fail_config(f"spec front-matter is not valid YAML: {exc.message}")
    bundle = load_judge_bundle(args.core_dir)
    try:
        result = preflight(kind, args.kind, spec, bundle=bundle,
                           judge_model_id=args.judge_model)
    except (UnknownCheckType, MalformedCheck) as exc:
        return _fail_config(f"malformed def-of-ready check: {exc}")
    _report(result)
    if result.ok:
        return _EXIT_OK
    if result.evaluated == 0 or not result.kind:
        return _fail_config("no requirement was evaluated (fail closed)")
    return _EXIT_BLOCK


def cmd_preflight(args) -> int:
    """Resolve the contract + kind, then delegate to ``_run_preflight``."""
    try:
        contract, _ = load_validated_dor(args.core_dir)
    except FileNotFoundError as exc:
        return _fail_config(f"no def-of-ready contract: {exc}")
    except ContractInvalid as exc:
        for finding in exc.findings:
            print(f"[g1]   {finding['rule']}: {finding['message']}", file=sys.stderr)
        return _fail_config(f"{exc}")
    try:
        kind = select_kind(contract, args.kind)
    except KindNotFound as exc:
        return _fail_config(f"{exc}")
    return _run_preflight(kind, args, args.spec)


def main(argv=None) -> int:
    """Parse args and dispatch the subcommand."""
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
