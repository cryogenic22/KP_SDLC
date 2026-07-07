"""The sufficiency-judge admissibility choke.

Whether a kind's optional ``sufficiency_judge`` may run is decided by exactly
one thing: ``sdlc_schemas.resolve_rubric``. Admissibility is DERIVED from
calibration evidence (kappa >= KAPPA_FLOOR, content-hash intact, judge-model
match, an active anti-case probe), never self-reported -- so an uncalibrated or
below-floor rubric returns ``Inadmissible`` and the judge is a LOUD, named skip
that CANNOT gate green. This increment ships no LLM adapter, so even an
ADMISSIBLE rubric skips loudly for want of a judge: the judge never returns a
pass here, and ``PreflightResult.ok`` never reads it. The point of this PR is
the choke and the deterministic checks, not the model call.
"""

from __future__ import annotations

from pathlib import Path

from sdlc_schemas import Inadmissible, load_document, resolve_rubric
from sdlc_schemas.linkcheck import build_bundle

_RUBRIC_GLOB = "*.yaml"
SKIP_INADMISSIBLE = "G1-JUDGE-INADMISSIBLE"
SKIP_NO_ADAPTER = "G1-JUDGE-NO-ADAPTER"


def load_judge_bundle(core_dir) -> dict:
    """Assemble the symbol bundle ``resolve_rubric`` consumes from the overlay's
    ``rubrics/`` dir (mirroring the eval-engine corpus). An absent dir yields an
    empty bundle, so a referenced rubric resolves to ``Inadmissible`` (a loud
    skip) rather than silently gating."""
    base = Path(core_dir) / "rubrics"
    instances = []
    if base.exists():
        for path in sorted(base.glob(_RUBRIC_GLOB)):
            data, _ = load_document(path)
            if isinstance(data, dict):
                instances.append((data.get("schema"), data))
    return build_bundle(instances)


def sufficiency_skip_reason(kind: dict, bundle: dict, judge_model_id: str):
    """Return the loud, named skip reason for a kind's sufficiency judge, or
    ``None`` when the kind configures no judge.

    A configured judge can only SKIP this PR -- it never gates. An inadmissible
    rubric yields its machine-readable reason (so a below-floor / uncalibrated
    rubric is provably unable to gate); an admissible rubric still skips, because
    no judge adapter exists yet (fail closed on a missing adapter, never a silent
    pass)."""
    judge = kind.get("sufficiency_judge") or {}
    ref = judge.get("rubric")
    if not ref:
        return None
    verdict = resolve_rubric(ref, judge_model_id, bundle)
    if isinstance(verdict, Inadmissible):
        return f"{SKIP_INADMISSIBLE}: {verdict.reason}"
    return (f"{SKIP_NO_ADAPTER}: rubric {ref!r} is admissible but no judge "
            "adapter ships this increment")
