"""The NFR budget pack (G6, Loop 5).

For each budget in a validated nfr-budget contract, compare the supplied
observed measurement to the contract bound in its declared direction. Every
absence fails closed: an unmeasured budget (no observation supplied) or a
non-numeric observation raises an error-severity Issue (never a silent skip),
and a zero-budget run yields NFR-NO-BUDGETS -- so the pack can never pass
vacuously. An unmeasured NFR is the classic fail-open ("we didn't measure
latency, so the gate is green"); here it BLOCKS.
"""

from __future__ import annotations

import math

from ..budgets import budget_of, within_budget
from ..model import CheckResult, Issue, Severity

RULE_NO_BUDGETS = "NFR-NO-BUDGETS"
RULE_NO_OBSERVATION = "NFR-NO-OBSERVATION"
RULE_BUDGET_BREACH = "NFR-BUDGET-BREACH"


def check_budgets(contract, observations, *, contract_path=""):
    """Check every budget's observed measurement against its contract bound.

    ``contract`` is a validated nfr-budget instance and ``observations`` maps
    budget_id -> the observed value (a stub input this PR; a measurement adapter
    lands later).
    """
    budgets = contract.get("budgets") or {}
    if not budgets:
        return _no_budgets_result(contract, contract_path)
    outcomes = [
        _check_one(budget_id, entry, observations, contract_path)
        for budget_id, entry in budgets.items()
    ]
    checked = sum(counted for counted, _ in outcomes)
    issues = tuple(issue for _, issue in outcomes if issue is not None)
    return CheckResult(checked=checked, skipped=0, issues=issues)


def _check_one(budget_id, entry, observations, contract_path):
    """Check one budget. Returns (counted, issue): ``counted`` is True only when
    the budget was actually compared; ``issue`` is a fail-closed error or a
    breach (a breach is both counted and an error)."""
    if budget_id not in observations:
        detail = (f"no observation supplied for budget {budget_id!r}; an "
                  "unmeasured NFR fails closed, never a silent pass")
        return False, _fail(RULE_NO_OBSERVATION, budget_id, entry, contract_path, detail)
    observed = observations[budget_id]
    if _unusable_observation(observed):
        detail = (f"unusable observation ({observed!r}); a missing/NULL, "
                  "non-finite (nan/inf), or negative value is absent/invalid "
                  "data, not a satisfied budget")
        return False, _fail(RULE_NO_OBSERVATION, budget_id, entry, contract_path, detail)
    return _compare(budget_id, entry, observed, contract_path)


def _unusable_observation(value) -> bool:
    """A usable observation is a FINITE, NON-NEGATIVE real number. Anything else
    is absent/invalid data -- fail closed as NFR-NO-OBSERVATION rather than count
    it toward a green gate (and never crash on ``x <= None``):

      - None (a missing measurement) or a non-number -> unusable;
      - a bool (``True == 1`` smuggling) -> unusable;
      - a non-finite float (nan / +-inf: a timeout or overflow is not a
        measurement) -> unusable, so ``-inf`` cannot silently pass a ceiling nor
        ``+inf`` a floor (the one-sided comparator, unlike G4's difference,
        gives no fail-closed posture on non-real inputs on its own);
      - a negative value -> unusable: the nfr-budget domain is non-negative (the
        schema pins ``limit >= 0`` and every shipped unit -- ms, count, mb, usd,
        percent -- is non-negative), so a negative reading is out of domain and,
        in practice, the canonical ``-1`` "measurement failed" sentinel.

    A signed-domain NFR would be a deliberate schema extension, not a silent
    hole today.
    """
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return True
    return not math.isfinite(value) or value < 0


def _compare(budget_id, entry, observed, contract_path):
    budget = budget_of(entry)
    if within_budget(observed, budget):
        return True, None
    bound = budget.describe()
    message = (
        f"budget {budget_id!r} breach: observed {observed} {budget.unit} "
        f"({bound})".rstrip()
    )
    issue = Issue(
        rule=RULE_BUDGET_BREACH,
        severity=Severity.ERROR,
        message=message,
        budget_id=budget_id,
        owner=entry.get("owner", ""),
        observed=observed,
        limit=budget.limit,
        unit=budget.unit,
        direction=budget.direction,
        file=contract_path,
    )
    return True, issue


def _fail(rule, budget_id, entry, contract_path, detail):
    return Issue(
        rule=rule,
        severity=Severity.ERROR,
        message=f"{budget_id}: {detail}",
        budget_id=budget_id,
        owner=entry.get("owner", ""),
        file=contract_path,
    )


def _no_budgets_result(contract, contract_path):
    issue = Issue(
        rule=RULE_NO_BUDGETS,
        severity=Severity.ERROR,
        message=(
            "nfr-budget contract resolved zero budgets; nothing to check "
            "(fail closed, never a vacuous pass)"
        ),
        owner=contract.get("owner", ""),
        file=contract_path,
    )
    return CheckResult(checked=0, skipped=0, issues=(issue,))
