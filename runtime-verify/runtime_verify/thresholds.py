"""Contract-sourced thresholds for runtime-verify.

Every compare number G4 uses -- the reconciliation tolerance -- is read here
from the E1.7 metric-library contract via ``sdlc_schemas``. This module and the
packs carry NO numeric literal in comparison position; the tolerance lives only
in the contract (the Loop-2 grep-gate enforces this). ``load_validated_library``
dogfoods the E1.7 validator: G4 refuses to run on a contract E1.7 would reject,
so a malformed contract fails closed upstream and again here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sdlc_schemas import (
    issues_to_findings,
    load_schema,
    resolve_instance,
    validate,
)

_METRIC_LIBRARY_TAG = "sdlc/metric-library@1"
_RELATIVE = "relative"
_ERROR = "error"


class ContractInvalid(Exception):
    """The metric-library contract is structurally invalid; G4 refuses to run."""

    def __init__(self, path, findings) -> None:
        self.path = path
        self.findings = list(findings)
        super().__init__(
            f"metric-library at {path} is invalid ({len(self.findings)} issue(s)); "
            "G4 refuses to run on an unvalidated contract"
        )


@dataclass(frozen=True)
class Tolerance:
    """A compare bound sourced from the contract; ``value`` never appears as a
    literal in pack code."""

    type: str
    value: float

    def describe(self) -> str:
        return f"{self.type} <= {self.value}"


def load_validated_library(core_dir):
    """Resolve and E1.7-validate the metric-library under an overlay dir.

    Fails closed: a missing instance raises via ``resolve_instance`` and a
    structurally invalid one raises ``ContractInvalid`` -- G4 never runs on a
    contract E1.7 would reject.
    """
    data, path = resolve_instance(_METRIC_LIBRARY_TAG, [Path(core_dir)])
    schema = load_schema(_METRIC_LIBRARY_TAG)
    issues = validate(data, schema, file=str(path))
    errors = [issue for issue in issues if issue.severity == _ERROR]
    if errors:
        raise ContractInvalid(path, issues_to_findings(errors))
    return data, path


def tolerance_of(metric) -> Tolerance:
    """Read the compare bound for one metric from its contract entry."""
    spec = metric["tolerance"]
    return Tolerance(type=str(spec["type"]), value=float(spec["value"]))


def within_tolerance(observed, authoritative, tolerance) -> bool:
    """True when ``observed`` matches ``authoritative`` within the contract bound.

    absolute -> abs(diff) <= value; relative -> abs(diff) <= value * abs(a),
    where the reference base ``a`` is the authoritative value. When a == 0 the
    relative bound collapses to exact equality (no division, no literal).
    """
    diff = abs(observed - authoritative)
    if tolerance.type == _RELATIVE:
        return diff <= tolerance.value * abs(authoritative)
    return diff <= tolerance.value
