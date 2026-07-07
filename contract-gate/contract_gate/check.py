"""The G2 completeness check: every referenced metric id must be a library key.

The metric-library ``metrics`` map (E12.1) is the membership set. For each id a
report artifact references:

  - unresolved (dangling) -> a ``block`` Gap (``G2-METRIC-UNRESOLVED``), exit 1;
    the finding names the id AND the library-level ``owner`` (the accountability
    fallback: a dangling id has no library entry, so no per-metric owner exists).
  - resolved -> counted, nothing emitted.

Reverse coverage is a single non-blocking advisory: a library metric the report
never referenced -> a ``warn`` Gap (``G2-METRIC-UNREPORTED``), exit 0, carrying
that metric's own ``owner``. It is a coverage hint, never a gate.
"""

from __future__ import annotations

from .model import ContractCheckResult, Gap, Severity

RULE_UNRESOLVED = "G2-METRIC-UNRESOLVED"
RULE_UNREPORTED = "G2-METRIC-UNREPORTED"


def check_contract(library, referenced_ids, *, contract_path: str = "") -> ContractCheckResult:
    """Resolve every referenced id against the library membership set.

    ``library`` is an E1.7-validated metric-library instance and
    ``referenced_ids`` the ids the artifact extractor returned. Returns a
    fail-closed ``ContractCheckResult``: a dangling reference is a block gap
    (exit 1), an unreferenced library metric a warn advisory (exit 0).
    """
    metrics = library.get("metrics") or {}
    library_owner = library.get("owner", "")
    gaps = tuple(
        _unresolved_gap(metric_id, library_owner, contract_path)
        for metric_id in referenced_ids
        if metric_id not in metrics
    )
    referenced = set(referenced_ids)
    advisories = tuple(
        _unreported_gap(metric_id, entry, library_owner, contract_path)
        for metric_id, entry in metrics.items()
        if metric_id not in referenced
    )
    return ContractCheckResult(checked=len(referenced), gaps=gaps, advisories=advisories)


def _unresolved_gap(metric_id: str, library_owner: str, contract_path: str) -> Gap:
    """A dangling reference: named id + library owner, block severity (exit 1)."""
    message = (
        f"metric {metric_id!r} is referenced by the report but has no entry in "
        f"the metric-library (owner {library_owner or '(none)'}); a number tying "
        "to no library entry blocks"
    )
    return Gap(rule=RULE_UNRESOLVED, metric_id=metric_id, severity=Severity.ERROR,
               message=message, owner=library_owner, file=contract_path)


def _unreported_gap(metric_id: str, entry, library_owner: str, contract_path: str) -> Gap:
    """An unreferenced library metric: warn advisory (coverage hint, exit 0)."""
    owner = entry.get("owner", "") or library_owner
    message = (
        f"metric {metric_id!r} is defined in the metric-library (owner "
        f"{owner or '(none)'}) but no report artifact references it (coverage hint)"
    )
    return Gap(rule=RULE_UNREPORTED, metric_id=metric_id, severity=Severity.WARNING,
               message=message, owner=owner, file=contract_path)
