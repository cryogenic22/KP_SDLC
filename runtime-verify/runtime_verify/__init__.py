"""runtime_verify -- the G4 runtime-verify spine (Tier C, Loop 2).

Zero runtime dependencies. Consumes the E1.7 metric-library contract (via
``sdlc_schemas``) as the single home of every compare number: pack code carries
no numeric literal in comparison position (the Loop-2 grep-gate enforces this).
The spine ships one end-to-end data-pack check -- reconciliation -- plus a
deterministic in-repo ``StubAdapter`` so the architecture is proven without any
external data source. Fails closed on absence: no data, no adapter, or an
invalid contract is a loud error, never a silent pass.
"""

from __future__ import annotations

from .adapters import (
    AdapterError,
    AdapterProtocol,
    AdapterRegistry,
    AdapterUnresolved,
    StubAdapter,
)
from .model import Assertion, CheckResult, Issue, Severity
from .packs.data_reconcile import reconcile
from .thresholds import (
    ContractInvalid,
    Tolerance,
    load_validated_library,
    tolerance_of,
    within_tolerance,
)

__all__ = [
    "AdapterError",
    "AdapterProtocol",
    "AdapterRegistry",
    "AdapterUnresolved",
    "Assertion",
    "CheckResult",
    "ContractInvalid",
    "Issue",
    "Severity",
    "StubAdapter",
    "Tolerance",
    "load_validated_library",
    "reconcile",
    "tolerance_of",
    "within_tolerance",
]

__version__ = "0.1.0"
