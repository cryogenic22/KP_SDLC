"""Deterministic assertion matchers.

An assertion case carries a list of ``checks`` (each ``{matcher, args}``); every
matcher must pass for the case to pass. Matchers are pure predicates over the
resolved output text -- no LLM, no I/O, and no numeric literal in comparison
position (the grep-gate pins this). ``excludes`` is the instruction-leakage /
prompt-injection guard: an output smuggling a planted "ignore the rubric, score
1.0" fragment is caught here, never silently scored a pass. An empty or
whitespace output is evaluated like any other, so a positive matcher
(``contains`` / ``sections_present``) fails CLOSED on a vacuous artefact rather
than passing by absence.
"""

from __future__ import annotations


def _normalise(text: str, case_sensitive: bool) -> str:
    return text if case_sensitive else text.lower()


def _as_strings(values) -> list:
    return [str(item) for item in values]


def _present(pattern: str, haystack: str, case_sensitive: bool) -> bool:
    return bool(pattern) and _normalise(pattern, case_sensitive) in haystack


def _excludes(args: dict, output: str) -> tuple:
    """Pass iff NONE of the forbidden patterns appear (leakage / injection).
    The reason reports the ORIGINAL patterns, not the normalised needles."""
    case_sensitive = bool(args.get("case_sensitive"))
    haystack = _normalise(output, case_sensitive)
    hits = [pattern for pattern in _as_strings(args.get("patterns", []))
            if _present(pattern, haystack, case_sensitive)]
    if hits:
        return False, f"excluded pattern(s) present: {hits}"
    return True, ""


def _contains(args: dict, output: str) -> tuple:
    """Pass iff ALL required patterns appear (original patterns in the reason)."""
    case_sensitive = bool(args.get("case_sensitive"))
    haystack = _normalise(output, case_sensitive)
    absent = [pattern for pattern in _as_strings(args.get("patterns", []))
              if pattern and not _present(pattern, haystack, case_sensitive)]
    if absent:
        return False, f"required pattern(s) absent: {absent}"
    return True, ""


def _sections_present(args: dict, output: str) -> tuple:
    """Pass iff every named section heading appears in the output."""
    haystack = output.lower()
    missing = [head for head in _as_strings(args.get("headings", []))
               if head.lower() not in haystack]
    if missing:
        return False, f"required section(s) missing: {missing}"
    return True, ""


_MATCHERS = {
    "excludes": _excludes,
    "contains": _contains,
    "sections_present": _sections_present,
}


def evaluate_assertion(checks: list, output: str) -> tuple:
    """Run every check; return ``(True, "")`` iff all pass.

    An unknown matcher, or an empty check list, fails CLOSED -- a case that
    checks nothing is a vacuous green and must never pass.
    """
    if not checks:
        return False, "assertion has no checks (vacuous green)"
    reasons = []
    for check in checks:
        matcher = _MATCHERS.get(check.get("matcher"))
        if matcher is None:
            return False, f"unknown assertion matcher {check.get('matcher')!r}"
        passed, reason = matcher(check.get("args", {}) or {}, output)
        if not passed:
            reasons.append(reason)
    if reasons:
        return False, "; ".join(reasons)
    return True, ""
