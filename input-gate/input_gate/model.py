"""The G1 data model: Gap -> PreflightResult.

``Gap.to_finding()`` renders a failing requirement in the quality-gate finding
shape ({rule, severity, file, line, message}) so Loop 5 reporting folds a G1
input gap in exactly like ``sdlc_schemas.issues_to_findings`` folds a schema
issue and ``runtime_verify.Issue.to_finding`` folds a data breach -- one
reporting contract, never a divergent one.

``PreflightResult.ok`` fails CLOSED on a vacuous run: it is True only when the
kind actually resolved AND at least one requirement was evaluated AND no
``block`` requirement gap remains. A judge SKIP never contributes to ``ok`` --
an unknown-kind or zero-evaluated run is never a silent pass, mirroring E1.7's
E-NO-FILES, G4's ``CheckResult.ok`` and G5's ``Scorecard.ok`` doctrine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Severity(str, Enum):
    """Finding severity, string-valued so it serializes exactly as the
    quality-gate reports (and ``sdlc_schemas``) already expect: a ``block``
    requirement gaps at ``error``, a ``warn`` requirement at ``warning``."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class Gap:
    """One failing requirement.

    ``requirement_id`` is the stable checklist gap name; it is also embedded in
    ``message`` so the id is literally quoted in every rendered finding (a block
    report must name the gap, never an anonymous count).
    """

    rule: str
    requirement_id: str
    severity: Severity
    message: str
    check_type: str = ""
    file: str = ""
    line: int = 0

    def to_finding(self) -> dict:
        """Render as a quality-gate finding: {rule, severity, file, line, message}."""
        return {
            "rule": self.rule,
            "severity": self.severity.value,
            "file": self.file,
            "line": self.line,
            "message": self.message,
        }


@dataclass(frozen=True)
class PreflightResult:
    """The verdict of one ``g1 preflight`` run.

    ``gaps`` are failing ``block`` requirements (hard block, exit 1);
    ``advisories`` are failing ``warn`` requirements (advisory, exit 0);
    ``skips`` are the loud, named judge skips that can NEVER gate green.
    """

    kind: str
    evaluated: int
    gaps: tuple = ()
    advisories: tuple = ()
    skips: tuple = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        """Green ONLY when the kind resolved, a real requirement was evaluated,
        and no block gap remains. A judge skip is deliberately absent from this
        expression: the sufficiency judge cannot turn a run green."""
        return bool(self.kind) and self.evaluated > 0 and not self.gaps

    def findings(self) -> list:
        """Every gap and advisory in the shared quality-gate finding shape."""
        return [item.to_finding() for item in (*self.gaps, *self.advisories)]
