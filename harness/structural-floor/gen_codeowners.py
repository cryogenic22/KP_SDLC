#!/usr/bin/env python3
"""Generate (and verify) .github/CODEOWNERS from protected-surface.txt.

`protected-surface.txt` is the single source of truth for what defines
"success" — the gates, thresholds, configs, and eval gold sets that must
not be quietly changed. Every protected path must require the owner's
review; this script renders the CODEOWNERS that enforces that, and its
``--check`` mode fails when the two drift, so the success-definition
surface cannot be relocated without the owner noticing.

The coupling protected-surface.txt -> CODEOWNERS -> branch protection,
guarded by a sync test, is what stops a builder from moving its own
Goodhart point.

Usage:
  python gen_codeowners.py                 # write .github/CODEOWNERS from protected-surface.txt
  python gen_codeowners.py --check         # exit 1 if CODEOWNERS is stale (for CI / pre-commit)
  python gen_codeowners.py --root path/to/repo
  python gen_codeowners.py --surface S --out O

Zero dependencies — Python stdlib only.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

Entry = Tuple[str, List[str]]

_DEFAULT_OWNER_RE = re.compile(r"^#\s*default-owner:\s*(\S+)", re.IGNORECASE)

_HEADER = (
    "# DO NOT EDIT — generated from protected-surface.txt by gen_codeowners.py.\n"
    "# Regenerate after editing protected-surface.txt, then commit both files.\n"
    "# A sync test (test_protected_surface_sync) and CI gate fail the build if\n"
    "# this file and protected-surface.txt ever drift apart.\n"
)

# A CODEOWNERS owner is a @user, a @org/team, or an email. GitHub silently
# ignores anything else, so an invalid owner is an unenforceable (vacuous)
# protection — we reject it rather than emit a green-but-meaningless line.
_OWNER_HANDLE_RE = re.compile(r"^@[A-Za-z0-9][A-Za-z0-9-]*(?:/[A-Za-z0-9._-]+)?$")
_OWNER_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate_owner(owner: str, path: str) -> None:
    if "{{" in owner or "}}" in owner:
        raise ValueError(
            f"protected path '{path}' has an unsubstituted placeholder owner '{owner}'. "
            f"Replace it (e.g. '# default-owner: @your-org/leads') before generating — "
            f"GitHub ignores a malformed owner, which would leave the path unprotected."
        )
    if not (_OWNER_HANDLE_RE.match(owner) or _OWNER_EMAIL_RE.match(owner)):
        raise ValueError(
            f"protected path '{path}' has an invalid CODEOWNERS owner '{owner}'. "
            f"Owners must be @user, @org/team, or an email — GitHub ignores anything else."
        )


def parse_protected_surface(text: str) -> Tuple[Optional[str], List[Entry]]:
    """Parse protected-surface.txt.

    Returns ``(default_owner, entries)`` where ``entries`` is a list of
    ``(path, explicit_owners)``. Explicit owners are kept separate from the
    default so the default can be resolved (and validated) at render time.
    Blank lines and ``#`` comments are ignored, except the
    ``# default-owner: @x`` directive.
    """
    default_owner: Optional[str] = None
    entries: List[Entry] = []

    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            m = _DEFAULT_OWNER_RE.match(line)
            if m:
                default_owner = m.group(1)
            continue
        parts = line.split()
        path = parts[0]
        owners = parts[1:]
        entries.append((path, owners))

    return default_owner, entries


def render_codeowners(default_owner: Optional[str], entries: List[Entry]) -> str:
    """Render CODEOWNERS content from a parsed protected surface.

    Each entry becomes ``<path> <owner...>``. An entry with no explicit
    owner uses ``default_owner``; if neither exists the protection would be
    unenforceable, so this raises ``ValueError`` rather than emit a vacuous
    ownerless line (no vacuous green).
    """
    if not entries:
        raise ValueError(
            "protected surface is empty — it protects nothing. Add at least one "
            "path, otherwise this gate is a vacuous green."
        )
    lines: List[str] = [_HEADER]
    for path, owners in entries:
        resolved = owners or ([default_owner] if default_owner else [])
        if not resolved:
            raise ValueError(
                f"protected path '{path}' has no owner and no default-owner is set; "
                f"add an owner on the line or a '# default-owner: @owner' directive"
            )
        for owner in resolved:
            _validate_owner(owner, path)
        lines.append(f"{path} {' '.join(resolved)}")
    return "\n".join(lines) + "\n"


def _normalize(text: str) -> str:
    """Strip trailing whitespace per line and trailing blank lines for robust compare."""
    out = [ln.rstrip() for ln in text.replace("\r\n", "\n").split("\n")]
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out)


def check_sync(surface_text: str, codeowners_text: str) -> Tuple[bool, str]:
    """Return (in_sync, message): does CODEOWNERS match what the surface renders?"""
    expected = render_codeowners(*parse_protected_surface(surface_text))
    if _normalize(expected) == _normalize(codeowners_text):
        return True, "CODEOWNERS is in sync with protected-surface.txt."
    return (
        False,
        "CODEOWNERS is OUT OF SYNC with protected-surface.txt. "
        "Run `python scripts/gen_codeowners.py` and commit the result.",
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Generate/verify CODEOWNERS from protected-surface.txt")
    parser.add_argument("--root", default=".", help="Repo root (default: cwd)")
    parser.add_argument("--surface", default=None, help="Path to protected-surface.txt")
    parser.add_argument("--out", default=None, help="Path to write CODEOWNERS")
    parser.add_argument("--check", action="store_true", help="Verify sync; exit 1 if stale (no write)")
    args = parser.parse_args(argv)

    root = Path(args.root)
    surface = Path(args.surface) if args.surface else root / "protected-surface.txt"
    out = Path(args.out) if args.out else root / ".github" / "CODEOWNERS"

    if not surface.exists():
        print(f"[structural-floor] protected-surface.txt not found at {surface}", file=sys.stderr)
        return 2

    surface_text = surface.read_text(encoding="utf-8")
    try:
        rendered = render_codeowners(*parse_protected_surface(surface_text))
    except ValueError as exc:
        print(f"[structural-floor] {exc}", file=sys.stderr)
        return 2

    if args.check:
        existing = out.read_text(encoding="utf-8") if out.exists() else ""
        in_sync, msg = check_sync(surface_text, existing)
        print(f"[structural-floor] {msg}")
        return 0 if in_sync else 1

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(rendered, encoding="utf-8")
    _, entries = parse_protected_surface(surface_text)
    print(f"[structural-floor] wrote {out} ({len(entries)} protected paths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
