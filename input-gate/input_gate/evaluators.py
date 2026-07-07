"""The CLOSED deterministic evaluator set, plus the spec front-matter parser.

``check.type`` is a closed 3-value enum in ``sdlc/def-of-ready@1``
(``section_present | field_present | pattern_present``); this module is the
single in-engine home of one evaluator per value. E1.7's E-ENUM already gates an
unknown type upstream, but ``evaluate_check`` fails closed AGAIN here
(``UnknownCheckType``) so a check that reached the runner outside the closed set
is a hard error, never a silently skipped -- and thus vacuously passing --
requirement. Widening the set is an ADR plus a schema bump, never a code edit.

The spec is parsed ONCE: a leading ``---`` front-matter fence (if any) is split
off and its inner block fed to ``sdlc_schemas.miniyaml`` (no PyYAML runtime
dep); everything after the closing fence is the markdown body. field_present
reads the front-matter; section_present and pattern_present read the body.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from sdlc_schemas import miniyaml

_FENCE = "---"
_ATX_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_MISSING = object()


class UnknownCheckType(Exception):
    """A check names a type outside the closed evaluator set (fail closed)."""


class MalformedCheck(Exception):
    """A check is missing its required argument, or carries an invalid regex.
    E1.7's allOf already binds each type to its argument; this is the
    defence-in-depth choke so a check that bypassed validation cannot pass by
    evaluating nothing."""


@dataclass(frozen=True)
class Spec:
    """A parsed spec file: the front-matter map, the markdown body, and the
    source path used to locate a gap in the finding shape."""

    front_matter: dict
    body: str
    file: str = ""


def _split_front_matter(text: str):
    """Split a leading ``---`` fenced front-matter block from the body.

    Returns ``(front_text, body_text)``. Only a document whose very first line
    is exactly ``---`` and that has a matching closing ``---`` carries
    front-matter; anything else is all body (a bare ``---`` horizontal rule in
    prose is never mistaken for a fence)."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != _FENCE:
        return "", text
    for idx in range(1, len(lines)):
        if lines[idx].strip() == _FENCE:
            return "\n".join(lines[1:idx]), "\n".join(lines[idx + 1:])
    return "", text


def parse_spec(path) -> Spec:
    """Read and parse a spec file into a ``Spec``.

    Raises ``OSError`` when the file is absent (fail closed -- a spec that is not
    there cannot be preflighted) and ``miniyaml.MiniYAMLError`` when the
    front-matter leaves the supported YAML subset."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    front, body = _split_front_matter(text)
    front_matter: dict = {}
    if front.strip():
        data, _ = miniyaml.load(front)
        if isinstance(data, dict):
            front_matter = data
    return Spec(front_matter=front_matter, body=body, file=str(path))


def _headings(body: str) -> frozenset:
    """The set of ATX (``#``-prefixed) heading texts in a markdown body."""
    found = set()
    for line in body.split("\n"):
        match = _ATX_HEADING.match(line)
        if match:
            found.add(match.group(2).strip())
    return frozenset(found)


def _is_present(value) -> bool:
    """True when a front-matter value is present AND non-empty. ``0`` / ``False``
    are real values; ``None`` and an empty string/collection are not."""
    if value is None:
        return False
    if isinstance(value, (str, list, dict, tuple, set)):
        return len(value) > 0
    return True


def _resolve_path(front_matter: dict, dotted: str):
    """Resolve a dotted front-matter path (``owner.team``) to its value, or
    ``_MISSING`` when any segment is absent."""
    node = front_matter
    for key in dotted.split("."):
        if not isinstance(node, dict) or key not in node:
            return _MISSING
        node = node[key]
    return node


def _eval_section(check: dict, spec: Spec):
    """section_present: the body carries an ATX heading matching ``heading``."""
    heading = check.get("heading")
    if not heading:
        raise MalformedCheck("section_present requires a 'heading'")
    if heading in _headings(spec.body):
        return True, ""
    return False, f"section heading {heading!r} is absent from the spec body"


def _eval_field(check: dict, spec: Spec):
    """field_present: a dotted front-matter path resolves to a non-empty value."""
    path = check.get("path")
    if not path:
        raise MalformedCheck("field_present requires a 'path'")
    value = _resolve_path(spec.front_matter, path)
    if value is _MISSING or not _is_present(value):
        return False, f"front-matter field {path!r} is absent or empty"
    return True, ""


def _eval_pattern(check: dict, spec: Spec):
    """pattern_present: ``re.search(pattern, body)`` matches."""
    pattern = check.get("pattern")
    if not pattern:
        raise MalformedCheck("pattern_present requires a 'pattern'")
    try:
        matched = re.search(pattern, spec.body) is not None
    except re.error as exc:
        raise MalformedCheck(f"invalid regex {pattern!r}: {exc}") from exc
    if matched:
        return True, ""
    return False, f"pattern {pattern!r} did not match the spec body"


_EVALUATORS = {
    "section_present": _eval_section,
    "field_present": _eval_field,
    "pattern_present": _eval_pattern,
}


def evaluate_check(check: dict, spec: Spec):
    """Dispatch a single check to its evaluator, fail-closed on the unknown.

    Returns ``(passed, detail)`` where ``detail`` explains a miss. An unknown
    ``check.type`` raises ``UnknownCheckType`` (never a silent skip) -- the
    belt-and-suspenders behind E1.7's E-ENUM."""
    check_type = check.get("type")
    evaluator = _EVALUATORS.get(check_type)
    if evaluator is None:
        raise UnknownCheckType(
            f"unknown check type {check_type!r}; the evaluator set is closed "
            "(widening needs an ADR + a def-of-ready schema bump)"
        )
    return evaluator(check, spec)
