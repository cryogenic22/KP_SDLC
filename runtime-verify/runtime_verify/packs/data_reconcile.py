"""The reconciliation data pack (G4, Loop 2).

For each metric in a validated metric-library, fetch the authoritative value
via the adapter bound to ``source.system`` at ``source.ref`` and compare it to
the reported value within the contract's tolerance. Every absence fails closed:
an unresolved adapter, a missing authoritative value, or a missing reported
value raises an error-severity Issue (never a silent skip), and a zero-metric
run yields E-NO-DATA -- so the pack can never pass vacuously.
"""

from __future__ import annotations

from ..adapters import AdapterError
from ..model import CheckResult, Issue, Severity
from ..thresholds import tolerance_of, within_tolerance

RULE_NO_DATA = "RV-NO-DATA"
RULE_ADAPTER_UNRESOLVED = "RV-ADAPTER-UNRESOLVED"
RULE_RECONCILE_BREACH = "RV-RECONCILE-BREACH"


def reconcile(library, registry, reported, *, contract_path=""):
    """Reconcile every metric's reported value against its authoritative one.

    ``library`` is a validated metric-library instance, ``registry`` maps
    source.system -> adapter, and ``reported`` maps metric_id -> the reported
    value (a stub input this PR; a derived source lands later).
    """
    metrics = library.get("metrics") or {}
    if not metrics:
        return _no_data_result(library, contract_path)
    outcomes = [
        _reconcile_one(metric_id, metric, registry, reported, contract_path)
        for metric_id, metric in metrics.items()
    ]
    checked = sum(counted for counted, _ in outcomes)
    issues = tuple(issue for _, issue in outcomes if issue is not None)
    return CheckResult(checked=checked, skipped=0, issues=issues)


def _reconcile_one(metric_id, metric, registry, reported, contract_path):
    """Reconcile one metric. Returns (counted, issue): ``counted`` is True only
    when the metric was actually compared; ``issue`` is a fail-closed error or a
    breach (a breach is both counted and an error)."""
    source = metric["source"]
    adapter = registry.get(source["system"])
    if adapter is None:
        detail = f"no adapter registered for system {source['system']!r}"
        return False, _fail(RULE_ADAPTER_UNRESOLVED, metric_id, metric, contract_path, detail)
    try:
        authoritative = adapter.fetch(source["ref"])
    except AdapterError as exc:
        return False, _fail(RULE_NO_DATA, metric_id, metric, contract_path, f"{exc}")
    if metric_id not in reported:
        detail = f"no reported value supplied for metric {metric_id!r}"
        return False, _fail(RULE_NO_DATA, metric_id, metric, contract_path, detail)
    observed = reported[metric_id]
    if _non_numeric(authoritative) or _non_numeric(observed):
        detail = (f"non-numeric value (authoritative={authoritative!r}, "
                  f"reported={observed!r}); a NULL is absent data, not a match")
        return False, _fail(RULE_NO_DATA, metric_id, metric, contract_path, detail)
    return _compare(metric_id, metric, authoritative, observed, contract_path)


def _non_numeric(value) -> bool:
    """A value must be a real number to reconcile. None (SQL NULL), a bool, or a
    non-numeric type is absent/invalid data -- fail closed as RV-NO-DATA rather
    than crash on ``abs(x - None)``."""
    return not isinstance(value, (int, float)) or isinstance(value, bool)


def _compare(metric_id, metric, authoritative, observed, contract_path):
    tolerance = tolerance_of(metric)
    if within_tolerance(observed, authoritative, tolerance):
        return True, None
    bound = tolerance.describe()
    message = (
        f"metric {metric_id!r} breach: reported {observed} vs authoritative "
        f"{authoritative} exceeds tolerance {bound}"
    )
    issue = Issue(
        rule=RULE_RECONCILE_BREACH,
        severity=Severity.ERROR,
        message=message,
        metric_id=metric_id,
        owner=metric.get("owner", ""),
        observed=observed,
        expected=authoritative,
        tolerance=bound,
        file=contract_path,
    )
    return True, issue


def _fail(rule, metric_id, metric, contract_path, detail):
    return Issue(
        rule=rule,
        severity=Severity.ERROR,
        message=f"{metric_id}: {detail}",
        metric_id=metric_id,
        owner=metric.get("owner", ""),
        file=contract_path,
    )


def _no_data_result(library, contract_path):
    issue = Issue(
        rule=RULE_NO_DATA,
        severity=Severity.ERROR,
        message=(
            "metric-library resolved zero metrics; nothing to reconcile "
            "(fail closed, never a vacuous pass)"
        ),
        owner=library.get("owner", ""),
        file=contract_path,
    )
    return CheckResult(checked=0, skipped=0, issues=(issue,))
