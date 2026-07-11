"""The one finding shape every Observatory projection emits.

The shape is a superset of the Quality Gate finding contract
(``{rule, severity, file, line, message}``) so the reporting layer can fold
Observatory findings in alongside gate findings, extended with the evidence,
classification, confidence, and recommended action the dashboard renders.

``classification`` names *how much we know*, and the dashboard must keep the
distinction visible:

- ``observed``          — a direct fact from an event or artifact;
- ``rule-based concern``— a deterministic rule over observed facts;
- ``heuristic``         — a probabilistic reading (carry ``confidence``);
- ``evaluation``        — a verdict from an explicit eval contract.
"""

from __future__ import annotations

from typing import Any


def finding(identifier: str, title: str, severity: str, message: str,
            evidence: list[dict[str, Any]], action: str, *,
            classification: str = "observed", confidence: str = "high",
            source: str = "observatory") -> dict[str, Any]:
    """Build a finding record. Keyword-only metadata keeps call sites readable."""
    return {
        "id": identifier,
        "title": title,
        "severity": severity,
        "classification": classification,
        "confidence": confidence,
        "message": message,
        "evidence": evidence,
        "recommended_action": action,
        "source": source,
    }
