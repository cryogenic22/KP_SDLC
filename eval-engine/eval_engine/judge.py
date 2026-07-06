"""The judge-admissibility choke point.

Whether a ``judged`` case may gate is decided by exactly one thing:
``sdlc_schemas.resolve_rubric``. Admissibility is DERIVED from calibration
evidence (kappa >= KAPPA_FLOOR, content-hash intact, judge-model match, an
active anti-case probe), never self-reported -- so a deliberately weakened
(kappa < 0.80) rubric returns ``Inadmissible`` and the case becomes a LOUD,
named skip that cannot gate green. This increment ships no LLM adapter, so even
an ADMISSIBLE rubric skips loudly for want of a judge: a judged case NEVER
returns a pass here. The point of this PR is the choke, not the model call.
"""

from __future__ import annotations

from sdlc_schemas import Inadmissible, resolve_rubric

SKIP_INADMISSIBLE = "EE-JUDGE-INADMISSIBLE"
SKIP_NO_ADAPTER = "EE-JUDGE-NO-ADAPTER"


def judged_skip_reason(case: dict, bundle: dict, judge_model_id: str) -> str:
    """Return the loud, named skip reason for a judged case.

    A judged case can only skip this PR -- it never gates. An inadmissible
    rubric yields its machine-readable reason (so a below-floor rubric is
    provably unable to gate); an admissible rubric still skips, because no judge
    adapter exists yet (fail closed on a missing adapter, never a silent pass).
    """
    ref = case.get("judge", {}).get("rubric", "")
    verdict = resolve_rubric(ref, judge_model_id, bundle)
    if isinstance(verdict, Inadmissible):
        return f"{SKIP_INADMISSIBLE}: {verdict.reason}"
    return (f"{SKIP_NO_ADAPTER}: rubric {ref!r} is admissible but no judge "
            "adapter ships this increment")
