"""Contract-sourced budgets for the G6 NFR gate.

Every compare number G6 uses -- each NFR ceiling/floor -- is read here from the
E1.7 nfr-budget contract via ``sdlc_schemas``. This module and the packs carry
NO numeric literal in comparison position; the bound lives only in the contract
(the grep-gate test enforces this, exactly as Loop 2 does for G4's tolerance).
``load_validated_budgets`` dogfoods the E1.7 validator: G6 refuses to run on a
contract E1.7 would reject, so a malformed contract fails closed upstream.

This composes E1.7's public primitives (resolve_instance + load_schema +
validate) the same way ``runtime_verify.thresholds`` does for the
metric-library -- it is USING the validator, not forking it. If a third
contract-loading consumer appears, the resolve+validate+filter glue is the
natural thing to hoist into ``sdlc_schemas`` (rule of three).
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

_NFR_BUDGET_TAG = "sdlc/nfr-budget@1"
_MAX = "max"
_MIN = "min"
_ERROR = "error"


class ContractInvalid(Exception):
    """The nfr-budget contract is structurally invalid; G6 refuses to run."""

    def __init__(self, path, findings) -> None:
        self.path = path
        self.findings = list(findings)
        super().__init__(
            f"nfr-budget contract at {path} is invalid ({len(self.findings)} "
            "issue(s)); G6 refuses to run on an unvalidated contract"
        )


@dataclass(frozen=True)
class Budget:
    """A one-sided compare bound sourced from the contract; ``limit`` never
    appears as a literal in pack code. ``direction`` selects the comparator:
    ``max`` is a ceiling, ``min`` is a floor."""

    limit: float
    unit: str
    direction: str

    def describe(self) -> str:
        relation = "must be <=" if self.direction == _MAX else "must be >="
        return f"{relation} {self.limit} {self.unit}".rstrip()


def load_validated_budgets(core_dir):
    """Resolve and E1.7-validate the nfr-budget contract under an overlay dir.

    Fails closed: a missing instance raises via ``resolve_instance`` and a
    structurally invalid one raises ``ContractInvalid`` -- G6 never runs on a
    contract E1.7 would reject.
    """
    data, path = resolve_instance(_NFR_BUDGET_TAG, [Path(core_dir)])
    schema = load_schema(_NFR_BUDGET_TAG)
    issues = validate(data, schema, file=str(path))
    errors = [issue for issue in issues if issue.severity == _ERROR]
    if errors:
        raise ContractInvalid(path, issues_to_findings(errors))
    return data, path


def budget_of(entry) -> Budget:
    """Read the compare bound for one NFR from its contract entry."""
    return Budget(
        limit=float(entry["limit"]),
        unit=str(entry["unit"]),
        direction=str(entry["direction"]),
    )


def within_budget(observed, budget) -> bool:
    """True when ``observed`` satisfies the budget in its declared direction.

    ``max`` (ceiling): observed <= limit passes. ``min`` (floor): observed >=
    limit passes. The bound is always ``budget.limit`` (contract-sourced); no
    numeric literal appears in the comparison.
    """
    if budget.direction == _MAX:
        return observed <= budget.limit
    return observed >= budget.limit
