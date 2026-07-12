"""nfr_gate -- the G6 NFR-budget gate spine (Tier C, Loop 5).

Zero runtime dependencies. Consumes the E1.7 nfr-budget contract (via
``sdlc_schemas``) as the single home of every compare number: pack code carries
no numeric literal in comparison position (the grep-gate test enforces this,
exactly as Loop 2 does for G4). The spine ships one end-to-end check -- budget
-- taking observed measurements from a deterministic in-repo stub (a JSON
observations map) so the architecture is proven without any external profiler.
Fails closed on absence: no budgets, an unmeasured budget, or an invalid
contract is a loud error, never a silent pass.
"""

from __future__ import annotations

from .budgets import (
    Budget,
    ContractInvalid,
    budget_of,
    load_validated_budgets,
    within_budget,
)
from .model import CheckResult, Issue, Severity
from .packs.nfr_budget import check_budgets

__all__ = [
    "Budget",
    "CheckResult",
    "ContractInvalid",
    "Issue",
    "Severity",
    "budget_of",
    "check_budgets",
    "load_validated_budgets",
    "within_budget",
]

__version__ = "0.1.0"
