"""input_gate -- the G1 input-sufficiency gate (Tier C, Loop 3).

Zero runtime dependencies (stdlib + the in-repo ``sdlc_schemas``). Consumes the
E1.7 ``sdlc/def-of-ready@1`` contract as the single home of every readiness
requirement, iterates ``kinds[K].requires[]``, and runs one DETERMINISTIC
evaluator per closed ``check.type`` (section_present / field_present /
pattern_present) against the spec under test: a failing ``block`` requirement is
a named gap (hard block), a failing ``warn`` an advisory. The optional
sufficiency judge is wired through the ``resolve_rubric`` admissibility choke as
a LOUD named skip that can never gate green (no LLM adapter this increment).
Fails closed on every absence: no contract, an unknown kind, an invalid
contract, an unreadable spec, or a zero-evaluated run is a loud non-zero, never
a silent pass.
"""

from __future__ import annotations

from .cli import build_parser, cmd_preflight, main, preflight
from .contract import (
    ContractInvalid,
    KindNotFound,
    load_validated_dor,
    select_kind,
)
from .evaluators import (
    MalformedCheck,
    Spec,
    UnknownCheckType,
    evaluate_check,
    parse_spec,
)
from .judge import (
    SKIP_INADMISSIBLE,
    SKIP_NO_ADAPTER,
    load_judge_bundle,
    sufficiency_skip_reason,
)
from .model import Gap, PreflightResult, Severity

__all__ = [
    "ContractInvalid",
    "Gap",
    "KindNotFound",
    "MalformedCheck",
    "PreflightResult",
    "SKIP_INADMISSIBLE",
    "SKIP_NO_ADAPTER",
    "Severity",
    "Spec",
    "UnknownCheckType",
    "build_parser",
    "cmd_preflight",
    "evaluate_check",
    "load_judge_bundle",
    "load_validated_dor",
    "main",
    "parse_spec",
    "preflight",
    "select_kind",
    "sufficiency_skip_reason",
]

__version__ = "0.1.0"
