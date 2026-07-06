"""eval_engine -- the G5 eval-engine scaffold (Tier C, Loop 4).

Zero runtime dependencies. Loads an E1.7-validated golden-case corpus (via
``sdlc_schemas``), runs the DETERMINISTIC case kinds (assertion / golden /
property / anti_case), wires the judge-admissibility choke (``resolve_rubric``:
an inadmissible rubric is a LOUD named skip that cannot gate green -- no LLM
call this increment), and emits a strict SUPERSET of the shipped eval
``latest.json`` contract. Fails closed on every absence: no corpus, zero active
cases, an invalid instance, an inadmissible rubric, or a missing judge adapter
is a loud non-green, never a silent pass.
"""

from __future__ import annotations

from .corpus import CorpusInvalid, LoadedCorpus, load_corpus
from .judge import judged_skip_reason
from .result import CaseResult, Outcome, Scorecard, evaluate_corpus
from .taxonomy import CASE_KINDS, CaseKind, UnknownKind, require_kind

__all__ = [
    "CASE_KINDS",
    "CaseKind",
    "CaseResult",
    "CorpusInvalid",
    "LoadedCorpus",
    "Outcome",
    "Scorecard",
    "UnknownKind",
    "evaluate_corpus",
    "judged_skip_reason",
    "load_corpus",
    "require_kind",
]

__version__ = "0.1.0"
