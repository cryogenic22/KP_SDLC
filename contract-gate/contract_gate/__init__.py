"""contract_gate -- the G2 metric-contract completeness gate (Tier C, Loop 3).

Zero runtime dependencies (stdlib + the in-repo ``sdlc_schemas`` and
``runtime_verify``). Consumes the E1.7 ``sdlc/metric-library@1`` contract as the
single home of every metric id (the membership set), reusing G4's
``load_validated_library`` rather than forking contract loading. It extracts the
metric ids a report artifact references and BLOCKS (exit 1) any that resolve to
no library entry -- the finding naming the id and the library owner (E12.1: a
number tying to no library entry blocks). An unreferenced library metric is a
single warn advisory (exit 0). Fails closed on every absence: a missing/invalid/
unparseable library or a missing/unreadable/malformed report artifact is a loud
exit 2, never a silent pass.
"""

from __future__ import annotations

from .artifact import MalformedArtifact, extract_metric_ids, parse_artifact
from .check import RULE_UNREPORTED, RULE_UNRESOLVED, check_contract
from .cli import build_parser, cmd_contract, main
from .model import ContractCheckResult, Gap, Severity

# Re-exported from runtime_verify so consumers see G2's contract-loading surface
# in one place, without a second implementation (G2 depends on G4's loader).
from runtime_verify.thresholds import ContractInvalid, load_validated_library

__all__ = [
    "ContractCheckResult",
    "ContractInvalid",
    "Gap",
    "MalformedArtifact",
    "RULE_UNREPORTED",
    "RULE_UNRESOLVED",
    "Severity",
    "build_parser",
    "check_contract",
    "cmd_contract",
    "extract_metric_ids",
    "load_validated_library",
    "main",
    "parse_artifact",
]

__version__ = "0.1.0"
