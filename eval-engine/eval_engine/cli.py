"""``ee`` command-line entry point.

``ee run --core-dir DIR [--corpus DIR] [--judge-model ID] [--scope SCOPE]
[--baseline-ref REF] [--report PATH]`` loads and E1.7-validates the corpus,
runs the deterministic case kinds plus the judge-admissibility choke, and emits
the ``latest.json``-superset scorecard (to ``--report`` or stdout). The exit
code is 0 only on a fail-closed-green run (>=1 active case PASSED and nothing
failed); every absence -- no corpus, zero active cases, an invalid instance, an
inadmissible gating rubric -- yields a loud non-zero exit.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .corpus import CorpusInvalid, load_corpus
from .result import evaluate_corpus

_DEFAULT_CORE = ".sdlc-core"
_DEFAULT_SCOPE = "harness-only"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ee", description="eval-engine")
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run", help="run the golden-case corpus")
    run_parser.add_argument("--core-dir", default=_DEFAULT_CORE,
                            help="overlay dir holding rubrics + metric-library")
    run_parser.add_argument("--corpus", default=None,
                            help="corpus dir (default: <core-dir>/corpus)")
    run_parser.add_argument("--judge-model", default="",
                            help="judge model id checked against a rubric's binding")
    run_parser.add_argument("--scope", default=_DEFAULT_SCOPE,
                            help="scope label recorded in the scorecard")
    run_parser.add_argument("--baseline-ref", default=None,
                            help="regression baseline ref recorded in the scorecard")
    run_parser.add_argument("--report", default=None,
                            help="write the scorecard JSON here (default: stdout)")
    run_parser.set_defaults(func=cmd_run)
    return parser


def cmd_run(args) -> int:
    try:
        loaded = load_corpus(args.core_dir, args.corpus)
    except CorpusInvalid as exc:
        _report_refusal(exc.findings)
        return 1
    except (ValueError, OSError) as exc:
        print(f"[ee] refusing to run: unreadable corpus: {exc}", file=sys.stderr)
        return 1
    scorecard = evaluate_corpus(
        loaded, scope=args.scope, judge_model_id=args.judge_model,
        regression_baseline=args.baseline_ref)
    _emit(scorecard, args.report)
    _report_console(scorecard)
    return 0 if scorecard.ok else 1


def _emit(scorecard, report_path) -> None:
    payload = json.dumps(scorecard.to_dict(), indent=2, sort_keys=True)
    if report_path:
        Path(report_path).write_text(payload + "\n", encoding="utf-8")
        return
    print(payload)


def _report_console(scorecard) -> None:
    for failure in scorecard.failures:
        print(f"[ee] FAIL {failure['id']}: {failure['reason']}", file=sys.stderr)
    verdict = "ok" if scorecard.ok else "FAILED"
    print(f"[ee] run {verdict}: total={scorecard.total} passed={scorecard.passed} "
          f"skipped={scorecard.skipped} failures={len(scorecard.failures)}",
          file=sys.stderr)


def _report_refusal(findings) -> None:
    print("[ee] refusing to run: corpus failed E1.7 validation", file=sys.stderr)
    for finding in findings:
        print(f"[ee]   {finding['rule']}: {finding['message']}", file=sys.stderr)


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
