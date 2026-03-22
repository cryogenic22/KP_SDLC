"""Core data types for the Fix Engine.

These types are the contract between the registry, applier, CLI,
and all fix functions. Every fix function returns a FixPatch.
The applier consumes FixPatches and produces a FixResult.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass(frozen=True, slots=True)
class FixPatch:
    """A single code fix — the atomic unit of the fix engine."""

    rule_id: str                # QG rule that triggered this fix
    file_path: str              # Relative path to the file
    line: int                   # 1-based line number of the original code
    original: str               # The line(s) to replace
    replacement: str            # The fixed line(s)
    explanation: str            # Why this fix was applied (for teaching)
    confidence: float           # 0.0-1.0, only auto-apply if >= threshold
    category: str               # "safe" | "review" | "manual"
    diff: str = ""              # Unified diff representation


@dataclass
class FixResult:
    """Result of a fix engine run."""

    patches: List[FixPatch] = field(default_factory=list)
    applied: List[FixPatch] = field(default_factory=list)
    skipped: List[Dict[str, Any]] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)

    def summary(self) -> Dict[str, Any]:
        by_rule: Dict[str, int] = {}
        for p in self.patches:
            by_rule[p.rule_id] = by_rule.get(p.rule_id, 0) + 1
        return {
            "total_patches": len(self.patches),
            "applied": len(self.applied),
            "skipped": len(self.skipped),
            "by_rule": by_rule,
            "by_category": {
                "safe": sum(1 for p in self.patches if p.category == "safe"),
                "review": sum(1 for p in self.patches if p.category == "review"),
                "manual": sum(1 for p in self.patches if p.category == "manual"),
            },
        }


@dataclass(frozen=True, slots=True)
class SuggestionBlock:
    """A GitHub/GitLab PR suggestion comment."""

    rule_id: str
    file_path: str
    line: int
    original: str
    replacement: str
    explanation: str
    confidence: float
    category: str

    def to_github_markdown(self) -> str:
        """Generate GitHub suggestion block."""
        lines = [
            f"### Fix: `{self.rule_id}` in `{self.file_path}:{self.line}`\n",
            f"**Why:** {self.explanation}\n",
            "```suggestion",
            self.replacement.rstrip("\n"),
            "```\n",
            f"*Confidence: {self.confidence} | Category: {self.category}*",
        ]
        return "\n".join(lines)

    def to_gitlab_markdown(self) -> str:
        """Generate GitLab suggestion block."""
        # GitLab uses same suggestion syntax
        return self.to_github_markdown()
