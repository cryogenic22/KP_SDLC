"""sdlc_schemas — the E1.7 core/overlay schema component.

Zero runtime dependencies. Ships six SHAPE documents (engine layer,
brand-neutral) plus a stdlib validator: instances live in the private overlay
(.sdlc-core/, and architecture.yaml at the adopter repo root) and are the only
place VALUES live. The split is structural in both directions — shape docs
carry ``$id`` and no ``schema:`` tag; instances carry ``schema: sdlc/<name>@1``
and never carry shape keywords.
"""

from __future__ import annotations

from .api import (
    Report,
    Schema,
    check_overlay,
    issues_to_findings,
    iter_anti_cases,
    iter_valid_cases,
    load_document,
    load_schema,
    resolve_instance,
    validate,
)
from .errors import CODES, SchemaDefinitionError, SchemaIssue
from .registry import KAPPA_FLOOR, Inadmissible, resolve_rubric

__all__ = [
    "CODES",
    "KAPPA_FLOOR",
    "Inadmissible",
    "Report",
    "Schema",
    "SchemaDefinitionError",
    "SchemaIssue",
    "check_overlay",
    "issues_to_findings",
    "iter_anti_cases",
    "iter_valid_cases",
    "load_document",
    "load_schema",
    "resolve_instance",
    "resolve_rubric",
    "validate",
]

__version__ = "0.1.0"
