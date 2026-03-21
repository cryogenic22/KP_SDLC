from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List, Optional


def find_git_root(start: Path) -> Optional[Path]:
    p = start.resolve()
    for parent in [p, *p.parents]:
        if (parent / ".git").exists():
            return parent
    return None


def git_changed_files(*, root: Path, base: str) -> List[str]:
    out = _git_cmd(root, ["diff", "--name-only", "--diff-filter=ACMR", base, "HEAD"])
    if out.returncode != 0:
        return []
    lines = [line.strip() for line in (out.stdout or "").splitlines()]
    return [line for line in lines if line]


def _git_cmd(root: Path, args: List[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-c", f"safe.directory={root}", "-C", str(root), *args],
        capture_output=True,
        text=True,
    )

