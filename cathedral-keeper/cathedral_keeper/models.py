from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass(frozen=True, slots=True)
class Evidence:
    file: str
    line: int
    snippet: str
    note: str = ""


@dataclass(frozen=True, slots=True)
class Finding:
    policy_id: str
    title: str
    severity: str
    confidence: str
    why_it_matters: str
    evidence: List[Evidence]
    fix_options: List[str]
    verification: List[str]
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "title": self.title,
            "severity": self.severity,
            "confidence": self.confidence,
            "why_it_matters": self.why_it_matters,
            "evidence": [
                {"file": e.file, "line": e.line, "snippet": e.snippet, "note": e.note} for e in self.evidence
            ],
            "fix_options": list(self.fix_options),
            "verification": list(self.verification),
            "metadata": dict(self.metadata),
        }


def severity_rank(sev: str) -> int:
    s = str(sev or "").strip().lower()
    return {"blocker": 4, "high": 3, "medium": 2, "low": 1}.get(s, 0)


def confidence_rank(conf: str) -> int:
    c = str(conf or "").strip().lower()
    return {"high": 3, "medium": 2, "low": 1}.get(c, 0)


def normalize_path(p: str) -> str:
    return str(p or "").replace("\\", "/")


def clamp_snippet(s: str, limit: int = 240) -> str:
    text = " ".join(str(s or "").strip().split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."

