"""The init manifest — inputs to a run and the record it leaves behind.

`InitManifest` is the resolved intent (one manifest → one executor → any
surface). `write_repo_manifest` emits `.harness/manifest.json` into the target:
the durable record of which engine SHA gated the repo at birth, what was
installed, and each phase outcome — the read surface for a future
`sdlc status` / drift check (E0.14).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .harness_map import ENGINE_VENDOR_DEST

SCHEMA = "sdlc-init/manifest@1"
SDLC_INIT_VERSION = "0.1.0"


@dataclass
class InitManifest:
    project_name: str
    owner: str
    target: Path
    engine_root: Path
    profile: str = "explore"
    onboard_ctxpack: bool = False

    def validate(self) -> None:
        if not self.project_name.strip():
            raise ValueError("project_name is required")
        if not self.owner.strip():
            raise ValueError("owner is required (e.g. @user or @org/team)")
        # Vendoring the QG+CK engines is a core phase, so a usable engine
        # root must carry all three components — not just harness/.
        for component in ("harness", "quality-gate", "cathedral-keeper"):
            if not (self.engine_root / component).is_dir():
                raise ValueError(
                    f"engine_root has no {component}/ dir: {self.engine_root}")


def engine_sha(engine_root: Path) -> str:
    """Current engine commit, or 'unknown' if engine_root is not a git repo."""
    try:
        out = subprocess.run(
            ["git", "-C", str(engine_root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        return out.stdout.strip() if out.returncode == 0 else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def engine_version(engine_root: Path) -> str:
    """Best-effort engine version from pyproject.toml (no toml dep needed)."""
    pyproject = engine_root / "pyproject.toml"
    if not pyproject.exists():
        return "unknown"
    for line in pyproject.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("version"):
            return stripped.split("=", 1)[1].strip().strip('"').strip("'")
    return "unknown"


def vendored_record(hashes: dict[str, str]) -> dict:
    """The engine.vendored manifest block: the read surface for `sdlc status`
    / `sdlc update` drift detection. The aggregate sha256 digests the sorted
    per-file digests, so any single-file tamper changes it."""
    ordered = sorted(hashes.items())
    aggregate = hashlib.sha256(
        "".join(f"{rel}:{digest}\n" for rel, digest in ordered).encode("utf-8")
    ).hexdigest()
    return {
        "path": ENGINE_VENDOR_DEST,
        "file_count": len(hashes),
        "sha256": aggregate,
        "files": dict(ordered),
    }


def build_repo_manifest(m: InitManifest, as_of: str, phase_results: list[dict],
                        vendor_hashes: dict[str, str] | None = None) -> dict:
    engine: dict = {
        "source": m.engine_root.as_posix(),  # portable in a committed file
        "sha": engine_sha(m.engine_root),
        "version": engine_version(m.engine_root),
    }
    if vendor_hashes:
        engine["vendored"] = vendored_record(vendor_hashes)
    return {
        "schema": SCHEMA,
        "sdlc_init_version": SDLC_INIT_VERSION,
        # Self-describing: manifest presence alone must not read as success.
        "status": "ok" if all(p.get("status") != "fail" for p in phase_results) else "failed",
        "project_name": m.project_name,
        "owner": m.owner,
        "profile": m.profile,
        "created": as_of,
        "engine": engine,
        "phases": phase_results,
    }


def write_repo_manifest(target: Path, manifest: dict) -> Path:
    dest = target / ".harness" / "manifest.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return dest
