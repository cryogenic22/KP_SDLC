"""The report artifact: parse it, then extract the metric ids it references.

The report artifact is a YAML or JSON sidecar the reporting pipeline (Loop 5)
emits, listing every metric the report presents. Two shapes are accepted and
normalised to one set of referenced ids:

  {"metrics": [{"id": "revenue_total", "value": 1234}, ...]}   (objects), or
  {"metrics": ["revenue_total", ...]}                          (bare ids).

The extractor is the vacuous-green risk of this gate: a parse bug that silently
extracts ZERO ids from a non-empty artifact would let a dangling reference sail
through. So it fails CLOSED, never silently drops. A metrics entry with no
``id`` field, a non-string / empty id, a ``metrics`` value that is not a list,
or a document that is not a mapping with a ``metrics`` key is a MALFORMED
artifact (``MalformedArtifact``) -- the caller maps that to a loud exit 2, never
a pass. Parsing itself reuses ``sdlc_schemas.load_document`` (miniyaml for YAML,
stdlib json for JSON) so the gate keeps zero runtime dependencies.
"""

from __future__ import annotations

from sdlc_schemas import load_document


class MalformedArtifact(Exception):
    """The report artifact is structurally unusable; G2 refuses to run (a report
    that cannot be read is not 'zero dangling references')."""


def parse_artifact(path):
    """Load a report artifact -> its raw decoded document.

    Raises ``OSError`` if the file is unreadable and the loader's parse error
    (``miniyaml.MiniYAMLError`` for YAML, ``json.JSONDecodeError``/``ValueError``
    for JSON) if it is unparseable -- every absence is loud, never a silent
    empty document.
    """
    data, _ = load_document(path)
    return data


def extract_metric_ids(data) -> list:
    """Return the ordered, de-duplicated set of metric ids the artifact references.

    Fails closed (``MalformedArtifact``) on any shape the report contract does
    not permit, so a parse bug can never masquerade as an empty reference set. A
    genuinely empty ``metrics`` list yields ``[]`` -- a report may reference no
    metric, and that is a clean (nothing-to-dangle) pass at the check layer.
    """
    if not isinstance(data, dict) or "metrics" not in data:
        raise MalformedArtifact(
            "report artifact must be a mapping with a 'metrics' key "
            f"(got {type(data).__name__}); a report that cannot be read is "
            "not 'zero dangling references'"
        )
    entries = data["metrics"]
    if not isinstance(entries, list):
        raise MalformedArtifact(
            f"report artifact 'metrics' must be a list, got {type(entries).__name__}"
        )
    ids: list = []
    seen: set = set()
    for index, entry in enumerate(entries):
        metric_id = _entry_id(entry, index)
        if metric_id not in seen:
            seen.add(metric_id)
            ids.append(metric_id)
    return ids


def _entry_id(entry, index: int) -> str:
    """Extract one referenced id from a bare-string or object entry, fail-closed."""
    if isinstance(entry, str):
        raw = entry
    elif isinstance(entry, dict):
        if "id" not in entry:
            raise MalformedArtifact(
                f"metrics[{index}] object has no 'id' field: {entry!r}"
            )
        raw = entry["id"]
    else:
        raise MalformedArtifact(
            f"metrics[{index}] is neither a bare id nor an object: {entry!r}"
        )
    return _clean_id(raw, index)


def _clean_id(raw, index: int) -> str:
    """Validate a referenced id is a non-empty string (bool is not a string)."""
    if not isinstance(raw, str) or isinstance(raw, bool):
        raise MalformedArtifact(
            f"metrics[{index}] id is not a string: {raw!r}"
        )
    stripped = raw.strip()
    if not stripped:
        raise MalformedArtifact(f"metrics[{index}] id is empty")
    return stripped
