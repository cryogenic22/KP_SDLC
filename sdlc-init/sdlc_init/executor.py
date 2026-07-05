"""The one executor. Every surface (CLI, a future UI, a CI re-run) resolves an
`InitManifest` and hands it here; nothing else provisions. Phases are ordered,
idempotent (safe to re-run — files that exist are skipped), and journaled to
`.harness/init-journal.jsonl` so a run can be inspected or resumed.
"""

from __future__ import annotations

import json
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .manifest import InitManifest

_PLACEHOLDER = re.compile(r"\{\{[A-Z0-9_]+\}\}")


@dataclass
class PhaseResult:
    name: str
    status: str  # "ok" | "skip" | "dry" | "fail"
    detail: str = ""
    changes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"name": self.name, "status": self.status, "detail": self.detail,
                "changes": self.changes}


@dataclass
class InitContext:
    manifest: InitManifest
    harness_dir: Path
    as_of: str
    subs: dict[str, str]
    dry_run: bool
    log: Callable[[str], None]
    results: list[PhaseResult] = field(default_factory=list)

    @property
    def target(self) -> Path:
        return self.manifest.target

    def rel(self, path: Path) -> str:
        return path.relative_to(self.target).as_posix()


def _apply_subs(text: str, subs: dict[str, str]) -> str:
    for key, value in subs.items():
        text = text.replace(key, value)
    return text


def install_file(ctx: InitContext, src: Path, dest_rel: str) -> str | None:
    """Copy one harness file to dest_rel under the target, substituting
    placeholders in text. Idempotent: returns None if the destination already
    exists (never silently overwrites). Returns dest_rel if it was created (or
    would be, under dry-run)."""
    dest = ctx.target / dest_rel
    if dest.exists():
        return None
    if ctx.dry_run:
        return dest_rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    text = _apply_subs(src.read_text(encoding="utf-8"), ctx.subs)
    # Force LF: on Windows, text-mode writes translate \n→\r\n, which puts CRLF
    # into shipped .sh/.yml files and breaks POSIX CI ("bad interpreter: ^M").
    dest.write_text(text, encoding="utf-8", newline="\n")
    if src.suffix == ".sh":
        dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return dest_rel


def assert_no_residual_placeholders(ctx: InitContext, dest_rel: str) -> None:
    """A file shipped to an active location must not carry an unfilled
    {{PLACEHOLDER}} — that would be invalid/aspirational output. This is the
    copy phase's anti-case (no vacuous green)."""
    dest = ctx.target / dest_rel
    if ctx.dry_run or not dest.exists():
        return
    found = _PLACEHOLDER.findall(dest.read_text(encoding="utf-8"))
    if found:
        raise RuntimeError(
            f"{dest_rel} still contains unfilled placeholders {sorted(set(found))} "
            f"after substitution — it must be parked or given a value, not shipped."
        )


def run(ctx: InitContext, phases: list[Callable[[InitContext], PhaseResult]]) -> list[PhaseResult]:
    """Run phases in order, accumulating results on ctx (so a later phase — e.g.
    write_manifest — can read earlier outcomes). Journals unless dry-run."""
    for phase in phases:
        try:
            result = phase(ctx)
        except Exception as exc:  # a phase must never crash the run — record + journal
            result = PhaseResult(getattr(phase, "__name__", "phase"), "fail",
                                 detail=str(exc)[:200])
        ctx.results.append(result)
        n = len(result.changes)
        ctx.log(f"  [{result.status:4}] {result.name}"
                + (f" ({n} file{'s' if n != 1 else ''})" if n else "")
                + (f" — {result.detail}" if result.detail else ""))
    if not ctx.dry_run:
        _write_journal(ctx, ctx.results)
    return ctx.results


def _write_journal(ctx: InitContext, results: list[PhaseResult]) -> None:
    journal = ctx.target / ".harness" / "init-journal.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    with journal.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps({"as_of": ctx.as_of,
                             "phases": [r.as_dict() for r in results]}) + "\n")
