"""The closed case-kind taxonomy.

The seven kinds mirror ``sdlc/golden-case@1``'s ``kind`` enum exactly; this
module is the single in-engine home of that closed set. The golden-case shape's
enum is the contract, so widening the taxonomy needs an ADR plus a schema bump,
never a corpus edit: ``require_kind`` fails closed (UnknownKind) on anything
outside the set, and a test pins ``CASE_KINDS`` against the shipped shape so the
two can never silently drift apart.
"""

from __future__ import annotations

from enum import Enum


class UnknownKind(Exception):
    """A case names a kind outside the closed taxonomy (fail closed)."""


class CaseKind(str, Enum):
    """The closed set of eval case kinds. String-valued so a kind serialises
    into the scorecard exactly as the corpus declares it."""

    ASSERTION = "assertion"
    GOLDEN = "golden"
    PROPERTY = "property"
    SCENARIO = "scenario"
    TRACE = "trace"
    JUDGED = "judged"
    ANTI_CASE = "anti_case"


CASE_KINDS = frozenset(kind.value for kind in CaseKind)


def require_kind(value: str) -> CaseKind:
    """Resolve a kind string to a ``CaseKind``; fail closed on the unknown.

    The corpus is already E1.7-validated against the same enum at load, so this
    is a defence-in-depth choke: a kind that reached the runner outside the
    closed set is a hard error, never a silently skipped case.
    """
    try:
        return CaseKind(value)
    except ValueError as exc:
        raise UnknownKind(
            f"unknown case kind {value!r}; the taxonomy is closed "
            "(widening needs an ADR + a golden-case schema bump)"
        ) from exc
