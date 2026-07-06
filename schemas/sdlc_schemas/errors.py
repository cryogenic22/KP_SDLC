"""The error model: a frozen SchemaIssue and the CLOSED 23-code enum.

The code tuple is closed on purpose — every anti-case pins its
``must_fail_with`` against it, so widening the taxonomy is a deliberate,
reviewed act (an ADR + a code added here), never an accident. Constructing
a SchemaIssue with a code outside the enum raises, which keeps typos from
silently minting new codes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

CODES = (
    "E-SYNTAX",
    "E-SCHEMA-TAG",
    "E-REQUIRED",
    "E-TYPE",
    "E-UNKNOWN-FIELD",
    "E-ENUM",
    "E-CONST",
    "E-PATTERN",
    "E-RANGE",
    "E-MIN-ITEMS",
    "E-MAX-ITEMS",
    "E-MIN-PROPS",
    "E-MIN-LENGTH",
    "E-UNIQUE",
    "E-UNIQUE-FIELD",
    "E-FORBIDDEN",
    "E-PLACEHOLDER",
    "E-NO-FILES",
    "E-RESERVED",
    "E-LINK-UNRESOLVED",
    "E-LINK-DUPLICATE",
    "E-LINK-KIND",
    "E-LINK-CYCLE",
)

_CODESET = frozenset(CODES)


class SchemaDefinitionError(Exception):
    """A shape document is itself ill-formed (unknown keyword, a property
    without an x-consumer, too few pinned cases). Raised by load_schema at
    load time — distinct from a runtime SchemaIssue on a bad *instance*."""


@dataclass(frozen=True)
class SchemaIssue:
    """One validation finding. ``path`` is JSON-pointer-ish
    ('kinds/application/requires/0/check/type'); ``line`` comes from the
    miniyaml node map (0 for JSON instances / best-effort)."""

    code: str
    path: str
    message: str
    file: str = ""
    line: int = 0
    hint: str = ""
    severity: str = field(default="error")

    def __post_init__(self) -> None:
        if self.code not in _CODESET:
            raise ValueError(f"unknown schema issue code: {self.code!r}")
