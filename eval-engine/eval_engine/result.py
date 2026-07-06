"""Case outcomes, the run engine, and the latest.json-superset scorecard.

``Scorecard.to_dict`` emits a strict SUPERSET of the shipped eval
``latest.json`` contract (``scope``, ``total``, ``passed``, ``skipped``,
``failures[]``, ``pass_rate``, ``iaa_kappa``, ``regression_baseline``) so the
PR-delta comment reads it unchanged; engine detail rides along as ADDITIONAL
keys. ``ok`` fails CLOSED: a run is green only when at least one active case
actually PASSED and nothing failed -- an all-skipped or zero-active corpus is
never a vacuous pass (mirrors G4's ``CheckResult.ok`` and E1.7's E-NO-FILES).
Every kind that cannot run -- a judged case with no adapter, a not-yet-shipped
scenario/trace, an unresolvable input -- becomes a LOUD named skip, never a
silent green, and an anti-case whose guard stops firing FAILS the run.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .judge import judged_skip_reason
from .kinds import evaluate_assertion, evaluate_golden, evaluate_property
from .taxonomy import CaseKind, require_kind

_NO_ACTIVE = "EE-NO-ACTIVE-CASES"
_NO_OUTPUT = "EE-NO-OUTPUT"
_GOLDEN_NO_REF = "EE-GOLDEN-NO-REFERENCE"
_ANTI_SOFT = "EE-ANTI-CASE-SOFT"
_ANTI_INCONCLUSIVE = "EE-ANTI-CASE-INCONCLUSIVE"
_KIND_UNIMPLEMENTED = "EE-KIND-NOT-IMPLEMENTED"
_TARGET_FIELDS = ("checks", "expected", "property", "steps", "trace", "judge")


class Outcome(str, Enum):
    """A case verdict. Deterministic kinds yield PASS/FAIL; a case that cannot
    run (choke skip, unimplemented kind) yields SKIP -- never a silent PASS."""

    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"


@dataclass(frozen=True)
class CaseResult:
    """One case's verdict. ``reason`` is empty on a pass and machine-readable
    (rule-prefixed) on a fail/skip so it renders straight into the scorecard."""

    id: str
    kind: str
    outcome: Outcome
    reason: str = ""


@dataclass(frozen=True)
class Scorecard:
    """The run scorecard. ``to_dict`` is the latest.json superset emitter."""

    scope: str
    results: tuple
    run_failures: tuple = ()
    iaa_kappa: float | None = None
    regression_baseline: str | None = None

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(result.outcome is Outcome.PASS for result in self.results)

    @property
    def skipped(self) -> int:
        return sum(result.outcome is Outcome.SKIP for result in self.results)

    @property
    def case_failures(self) -> list:
        return [r for r in self.results if r.outcome is Outcome.FAIL]

    @property
    def failures(self) -> list:
        """Run-level failures (e.g. zero active cases) plus every failed case,
        each ``{id, reason}`` -- the shape the PR-delta comment reads."""
        runs = [dict(failure) for failure in self.run_failures]
        cases = [{"id": r.id, "reason": r.reason} for r in self.case_failures]
        return runs + cases

    @property
    def pass_rate(self) -> float:
        """Passed over the non-skipped considered cases; skips never inflate it.
        Zero considered cases collapses to ``0.0`` (fail-closed, not a divide)."""
        denominator = max(1, self.total - self.skipped)
        return self.passed / denominator

    @property
    def ok(self) -> bool:
        """Green ONLY when a real case passed and nothing failed. An all-skipped
        or zero-active run is never a vacuous pass."""
        return self.passed > 0 and not self.failures

    def to_dict(self) -> dict:
        """Emit the strict superset of the latest.json contract keys."""
        return {
            "scope": self.scope,
            "total": self.total,
            "passed": self.passed,
            "skipped": self.skipped,
            "failures": self.failures,
            "pass_rate": self.pass_rate,
            "iaa_kappa": self.iaa_kappa,
            "regression_baseline": self.regression_baseline,
            "ok": self.ok,
            "skips": [{"id": r.id, "reason": r.reason}
                      for r in self.results if r.outcome is Outcome.SKIP],
        }


def evaluate_corpus(loaded, *, scope: str, judge_model_id: str = "",
                    regression_baseline: str | None = None) -> Scorecard:
    """Run every active case and assemble the fail-closed scorecard.

    Zero active cases is not a vacuous pass: it yields a run-level
    EE-NO-ACTIVE-CASES failure (scope still reflected), so ``ok`` is False and
    ``ee run`` exits non-zero -- mirroring E1.7 E-NO-FILES and G4 RV-NO-DATA.
    """
    active = tuple(loaded.active_cases)
    if not active:
        failure = ({"id": _NO_ACTIVE,
                    "reason": "corpus resolved zero active cases (fail closed)"},)
        return Scorecard(scope=scope, results=(), run_failures=failure,
                         regression_baseline=regression_baseline)
    results = tuple(_evaluate_case(case, loaded, judge_model_id)
                    for case in active)
    # iaa_kappa: no rubric admissibly gates this increment (every judged case
    # skips for lack of an adapter), so there is no gating kappa to attribute.
    return Scorecard(scope=scope, results=results, iaa_kappa=None,
                     regression_baseline=regression_baseline)


def _result_from(case, kind, passed, reason) -> CaseResult:
    """Map a matcher's ``(passed, reason)`` to a CaseResult: ``None`` -> SKIP,
    truthy -> PASS (reason dropped), falsy -> FAIL (reason kept)."""
    if passed is None:
        outcome = Outcome.SKIP
    elif passed:
        outcome = Outcome.PASS
    else:
        outcome = Outcome.FAIL
    return CaseResult(id=case.get("id", ""), kind=kind.value, outcome=outcome,
                      reason="" if outcome is Outcome.PASS else reason)


def _resolve_text(case, corpus_root):
    """Resolve a case's output text: an inline ``input.text`` (deterministic,
    the scaffold default) or a corpus-relative ``input.fixture`` file. Absence
    returns ``None`` so the caller fails closed rather than evaluating nothing."""
    envelope = case.get("input", {}) or {}
    if "text" in envelope:
        return str(envelope["text"])
    fixture = envelope.get("fixture")
    if fixture:
        path = Path(corpus_root) / fixture
        if path.exists():
            return path.read_text(encoding="utf-8")
    return None


def _resolve_reference(case, corpus_root):
    """Read the golden reference number from ``expected.ref`` (a corpus-relative
    file holding a single value). Missing / unparseable -> None (fail closed)."""
    ref = case.get("expected", {}).get("ref")
    if not ref:
        return None
    path = Path(corpus_root) / ref
    if not path.exists():
        return None
    try:
        return float(path.read_text(encoding="utf-8").strip())
    except ValueError:
        return None


def _resolve_tolerance(case, metrics):
    """Resolve the golden tolerance from the metric-library contract via
    ``expected.tolerance_metric`` -- the one bound shared with G4."""
    metric_id = case.get("expected", {}).get("tolerance_metric")
    if not metric_id:
        return None
    return (metrics.get(metric_id, {}) or {}).get("tolerance")


def _run_assertion(case, loaded, _judge_model_id) -> CaseResult:
    output = _resolve_text(case, loaded.corpus_root)
    if output is None:
        return _result_from(case, CaseKind.ASSERTION, False,
                            f"{_NO_OUTPUT}: no resolvable output for assertion")
    passed, reason = evaluate_assertion(case.get("checks", []), output)
    return _result_from(case, CaseKind.ASSERTION, passed, reason)


def _run_property(case, loaded, _judge_model_id) -> CaseResult:
    output = _resolve_text(case, loaded.corpus_root)
    if output is None:
        return _result_from(case, CaseKind.PROPERTY, False,
                            f"{_NO_OUTPUT}: no resolvable output for property")
    passed, reason = evaluate_property(case.get("property", {}), output)
    return _result_from(case, CaseKind.PROPERTY, passed, reason)


def _run_golden(case, loaded, _judge_model_id) -> CaseResult:
    actual = (case.get("input", {}) or {}).get("value")
    reference = _resolve_reference(case, loaded.corpus_root)
    tolerance = _resolve_tolerance(case, loaded.metrics)
    if reference is None:
        return _result_from(case, CaseKind.GOLDEN, False,
                            f"{_GOLDEN_NO_REF}: no resolvable golden reference")
    passed, reason = evaluate_golden(actual, reference, tolerance)
    return _result_from(case, CaseKind.GOLDEN, passed, reason)


def _run_judged(case, loaded, judge_model_id) -> CaseResult:
    reason = judged_skip_reason(case, loaded.bundle, judge_model_id)
    return _result_from(case, CaseKind.JUDGED, None, reason)


def _synthesize_anti_target(case) -> dict:
    """Build the case the anti-case's guard must FAIL. The engine passes the
    anti-case iff evaluating this synthesized target FAILS (release-gate
    inversion, per the golden-case shape)."""
    payload = case.get("payload", {}) or {}
    synthesized = {
        "schema": case.get("schema"),
        "id": case.get("id", "") + ".payload",
        "kind": case.get("target_kind"),
        "determinism": case.get("determinism"),
        "status": case.get("status"),
        "lineage": case.get("lineage"),
        "input": payload.get("input", case.get("input", {})),
    }
    for field_name in _TARGET_FIELDS:
        if field_name in payload:
            synthesized[field_name] = payload[field_name]
    return synthesized


def _run_anti_case(case, loaded, judge_model_id) -> CaseResult:
    inner = _evaluate_case(_synthesize_anti_target(case), loaded, judge_model_id)
    if inner.outcome is Outcome.FAIL:
        return _result_from(case, CaseKind.ANTI_CASE, True, "")
    if inner.outcome is Outcome.PASS:
        return _result_from(case, CaseKind.ANTI_CASE, False,
                            f"{_ANTI_SOFT}: guard no longer fires "
                            f"(target {case.get('target_kind')!r} passed)")
    return _result_from(case, CaseKind.ANTI_CASE, False,
                        f"{_ANTI_INCONCLUSIVE}: target skipped ({inner.reason})")


_DISPATCH = {
    CaseKind.ASSERTION: _run_assertion,
    CaseKind.GOLDEN: _run_golden,
    CaseKind.PROPERTY: _run_property,
    CaseKind.JUDGED: _run_judged,
    CaseKind.ANTI_CASE: _run_anti_case,
}


def _evaluate_case(case, loaded, judge_model_id) -> CaseResult:
    kind = require_kind(case.get("kind", ""))
    handler = _DISPATCH.get(kind)
    if handler is None:
        return _result_from(case, kind, None,
                            f"{_KIND_UNIMPLEMENTED}: kind {kind.value!r} has no "
                            "runner this increment")
    return handler(case, loaded, judge_model_id)
