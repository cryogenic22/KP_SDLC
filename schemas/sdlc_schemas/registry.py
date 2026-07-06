"""Tag -> shape dispatch, the admissibility floor, and resolve_rubric().

Dispatch is envelope-exclusive: an instance is validated against the shape
named by its own ``schema`` tag and no other, so a file claiming ``@2`` is
never checked against ``@1`` — an unknown major fails closed (E-SCHEMA-TAG).

The judge admissibility floor is the engine constant KAPPA_FLOOR (0.80), NOT
an overlay field: ``eval.judge_kappa_floor`` is a reserved key so no overlay
can silently lower it. resolve_rubric() is the single choke point both the
G1 sufficiency judge and ``ee run`` share — admissibility is DERIVED from
evidence (calibration present, kappa >= floor, content hash intact, model
match, an active anti-case probe), never self-reported.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

KAPPA_FLOOR = 0.80

KNOWN = {
    "sdlc/def-of-ready@1": "def-of-ready.schema.yaml",
    "sdlc/metric-library@1": "metric-library.schema.yaml",
    "sdlc/standards@1": "standards.schema.yaml",
    "sdlc/rubric@1": "rubric.schema.yaml",
    "sdlc/golden-case@1": "golden-case.schema.json",
    "sdlc/architecture-contract@1": "architecture-contract.schema.yaml",
}


class SchemaTagError(Exception):
    """An instance names a schema tag the engine cannot dispatch (fail-closed).
    Carries code E-SCHEMA-TAG for surfacing as a SchemaIssue."""

    code = "E-SCHEMA-TAG"


@dataclass(frozen=True)
class Inadmissible:
    """A rubric that cannot gate. ``reason`` is machine-readable so callers
    degrade to a LOUD named skip rather than a silent pass."""

    reason: str


def dispatch(tag: str) -> str:
    """Resolve an instance tag to its shipped shape filename, fail-closed."""
    if tag not in KNOWN:
        raise SchemaTagError(f"unknown schema tag: {tag!r}")
    return KNOWN[tag]


def parse_ref(ref: str):
    """Parse an ``id@version`` reference into (id, version:int) or None."""
    if "@" not in ref:
        return None
    name, _, major = ref.rpartition("@")
    if not major.isdigit():
        return None
    return name, int(major)


def content_hash(rubric: dict) -> str:
    """sha256 hex over the canonical compiled content (prompt+criteria+scale+
    threshold). Any semantic edit after calibration changes this hash, which
    is what derives inadmissibility — the drift binding is not honor-system."""
    canonical = json.dumps(
        {
            "prompt": rubric.get("prompt"),
            "criteria": rubric.get("criteria"),
            "scale": rubric.get("scale"),
            "threshold": rubric.get("threshold"),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def resolve_rubric(ref: str, judge_model_id: str, bundle: dict):
    """Return the rubric dict when admissible, else Inadmissible(reason)."""
    key = parse_ref(ref)
    rubric = bundle.get("rubrics", {}).get(key) if key else None
    if rubric is None:
        return Inadmissible(f"unresolved rubric {ref!r}")
    verdict = _admissibility(rubric, judge_model_id, bundle)
    return verdict if verdict is not None else rubric


def _admissibility(rubric: dict, judge_model_id: str, bundle: dict):
    cal = rubric.get("calibration")
    if not cal:
        return Inadmissible("uncalibrated: no calibration record")
    if cal.get("kappa", 0) < KAPPA_FLOOR:
        return Inadmissible(f"kappa {cal.get('kappa')} below floor {KAPPA_FLOOR}")
    binding = cal.get("binding", {})
    if content_hash(rubric) != binding.get("content_hash"):
        return Inadmissible("content drift: recomputed hash != binding")
    if judge_model_id != binding.get("model_id"):
        return Inadmissible("model mismatch vs calibration binding")
    probe = rubric.get("meta_eval", {}).get("probe_tag")
    if not probe or probe not in bundle.get("tags_anti", set()):
        return Inadmissible("no active anti-case resolves the probe tag")
    return None
