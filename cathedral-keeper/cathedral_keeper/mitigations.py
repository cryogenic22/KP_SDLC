"""S6 — Mitigation Detection.

Team Feedback #7: Before generating findings narrative, check whether
the repo already has quality gates, ratchet systems, or CI pipelines.
A repo with existing controls should get "incremental improvement" tone,
not "urgent remediation."
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict


@dataclass(frozen=True, slots=True)
class Mitigations:
    """Inventory of existing quality infrastructure in a repo."""

    has_ci: bool               # .github/workflows/ or .gitlab-ci.yml
    has_quality_gate: bool     # quality-gate/ directory
    has_ck_config: bool        # .cathedral-keeper.json
    has_coverage_threshold: bool  # cov-fail-under in pyproject.toml
    has_pre_commit: bool       # .pre-commit-config.yaml

    @property
    def count(self) -> int:
        """Total number of mitigations detected."""
        return sum([
            self.has_ci,
            self.has_quality_gate,
            self.has_ck_config,
            self.has_coverage_threshold,
            self.has_pre_commit,
        ])

    @property
    def narrative_tone(self) -> str:
        """Suggested narrative tone based on mitigation level.

        'incremental' = repo has controls, suggest improvements within existing framework.
        'urgent' = repo has no controls, findings are more critical.
        """
        return "incremental" if self.count >= 2 else "urgent"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "has_ci": self.has_ci,
            "has_quality_gate": self.has_quality_gate,
            "has_ck_config": self.has_ck_config,
            "has_coverage_threshold": self.has_coverage_threshold,
            "has_pre_commit": self.has_pre_commit,
            "count": self.count,
            "narrative_tone": self.narrative_tone,
        }


def detect_mitigations(root: Path) -> Mitigations:
    """Detect existing quality infrastructure in a repository.

    Checks for CI pipelines, quality gates, coverage thresholds,
    pre-commit hooks, and CK configuration.
    """
    return Mitigations(
        has_ci=_has_ci(root),
        has_quality_gate=_has_quality_gate(root),
        has_ck_config=_has_ck_config(root),
        has_coverage_threshold=_has_coverage_threshold(root),
        has_pre_commit=_has_pre_commit(root),
    )


def _has_ci(root: Path) -> bool:
    """Check for CI pipeline configuration."""
    checks = [
        root / ".github" / "workflows",
        root / ".gitlab-ci.yml",
        root / ".circleci",
        root / "Jenkinsfile",
        root / ".azure-pipelines.yml",
    ]
    return any(p.exists() for p in checks)


def _has_quality_gate(root: Path) -> bool:
    """Check for quality-gate tooling."""
    checks = [
        root / "quality-gate",
        root / ".quality-gate.json",
        root / "quality-gate.config.json",
    ]
    return any(p.exists() for p in checks)


def _has_ck_config(root: Path) -> bool:
    """Check for Cathedral Keeper configuration."""
    return (root / ".cathedral-keeper.json").exists()


def _has_coverage_threshold(root: Path) -> bool:
    """Check for coverage threshold in pyproject.toml or setup.cfg."""
    for config_file in ["pyproject.toml", "setup.cfg", ".coveragerc"]:
        path = root / config_file
        if path.exists():
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
                if "cov-fail-under" in content or "fail_under" in content:
                    return True
            except OSError:
                pass
    return False


def _has_pre_commit(root: Path) -> bool:
    """Check for pre-commit hooks."""
    checks = [
        root / ".pre-commit-config.yaml",
        root / ".pre-commit-config.yml",
        root / ".husky",
    ]
    return any(p.exists() for p in checks)
