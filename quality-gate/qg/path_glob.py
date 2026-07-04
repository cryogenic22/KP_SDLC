from __future__ import annotations

import fnmatch


def normalize_rel_path(path: str) -> str:
    return str(path).replace("\\", "/").lstrip("./")


def _pattern_variants(pattern: str) -> list[str]:
    pat = str(pattern).replace("\\", "/").strip()
    if not pat:
        return []
    if pat.startswith("./"):
        pat = pat[2:]
    if pat.startswith("**/"):
        return [pat, pat[3:]]
    if "/" not in pat:
        # Bare basename patterns (e.g. "legacy.*") match at any depth —
        # compatible with configs written for basename-only matching.
        return [pat, "**/" + pat]
    return [pat]


def matches_any(rel_path: str, patterns: list[str]) -> bool:
    rel = normalize_rel_path(rel_path)
    for pattern in patterns:
        for variant in _pattern_variants(pattern):
            if not variant:
                continue
            if fnmatch.fnmatchcase(rel, variant):
                return True
    return False

