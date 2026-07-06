"""Deterministic case-kind matchers for the eval engine.

Each kind exposes a pure ``evaluate_*`` predicate over already-resolved inputs
(text or numbers); the run engine (``eval_engine.result``) resolves a case's
input envelope and dispatches here. Keeping the matchers free of I/O and of any
numeric literal in comparison position (the grep-gate) is what lets the golden
tolerance live only in the metric contract and the whole layer stay trivially
testable and fail-closed.
"""

from __future__ import annotations

from .assertion import evaluate_assertion
from .golden import evaluate_golden
from .property import evaluate_property

__all__ = ["evaluate_assertion", "evaluate_golden", "evaluate_property"]
