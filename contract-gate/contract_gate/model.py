"""The G2 model: Gap -> ContractCheckResult.

``Gap.to_finding()`` renders a metric-contract gap in the quality-gate finding
shape ({rule, severity, file, line, message}) so Loop 5 reporting folds a G2 gap
in exactly like ``sdlc_schemas.issues_to_findings`` folds a schema issue and
``runtime_verify.Issue.to_finding`` folds a data breach -- one reporting
contract, never a divergent one.

``ContractCheckResult.ok`` fails CLOSED: it is True only when no ``block``
(unresolved) reference remains. The other two ``ok`` preconditions the spec
names -- the library resolved and the artifact parsed -- are enforced UPSTREAM
by the CLI, which fail-closes to exit 2 before this result is ever constructed
(a result object is only built once both are in hand). Unlike G4's
``CheckResult``, a zero-reference run is a legitimate clean pass: a report that
cites no metric has nothing to dangle. The extractor's real-ness (that the ids
which ARE present are all checked) is pinned by the test suite, not by a
``checked > 0`` guard here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Severity(str, Enum):
    """Finding severity, string-valued so it serializes exactly as the
    quality-gate reports (and ``sdlc_schemas``) already expect: an unresolved
    reference gaps at ``error``, an unreported-metric advisory at ``warning``."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class Gap:
    """One metric-contract gap.

    ``metric_id`` is the referenced (or unreferenced) metric id; it is also
    embedded in ``message`` so the id is literally quoted in every rendered
    finding (a block report must name the metric, never an anonymous count).
    ``owner`` is the accountability contact rendered on the finding.
    """

    rule: str
    metric_id: str
    severity: Severity
    message: str
    owner: str = ""
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
class ContractCheckResult:
    """The verdict of one ``g2 contract`` run.

    ``checked`` is the number of distinct metric ids the artifact referenced and
    the check resolved (every reference is a membership query, so ``checked``
    equals the referenced-id count). ``gaps`` are unresolved (dangling)
    references -- hard blocks, exit 1. ``advisories`` are library metrics the
    artifact never referenced -- warn coverage hints, exit 0.
    """

    checked: int
    gaps: tuple = ()
    advisories: tuple = ()

    @property
    def ok(self) -> bool:
        """Green ONLY when no ``block`` (unresolved) reference remains. Advisories
        are ``warning`` and never touch ``ok``; a dangling reference always does."""
        return not any(gap.severity is Severity.ERROR for gap in self.gaps)

    def findings(self) -> list:
        """Every gap and advisory in the shared quality-gate finding shape."""
        return [item.to_finding() for item in (*self.gaps, *self.advisories)]
