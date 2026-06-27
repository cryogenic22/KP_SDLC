"""KP_SDLC dogfood: its own .github/CODEOWNERS must match protected-surface.txt.

If this fails, the success-definition surface and its enforcement have
drifted: run `python harness/structural-floor/gen_codeowners.py` and commit
the regenerated .github/CODEOWNERS.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[1]))  # harness/structural-floor (gen_codeowners.py)
_ROOT = _HERE.parents[3]                    # repo root

from gen_codeowners import check_sync


def test_kp_sdlc_codeowners_in_sync_with_protected_surface():
    surface = _ROOT / "protected-surface.txt"
    codeowners = _ROOT / ".github" / "CODEOWNERS"
    assert surface.exists(), f"missing {surface}"
    surface_text = surface.read_text(encoding="utf-8")
    existing = codeowners.read_text(encoding="utf-8") if codeowners.exists() else ""
    in_sync, msg = check_sync(surface_text, existing)
    assert in_sync, msg


if __name__ == "__main__":
    try:
        test_kp_sdlc_codeowners_in_sync_with_protected_surface()
        print("  PASS  test_kp_sdlc_codeowners_in_sync_with_protected_surface")
        print("\n1 passed, 0 failed out of 1 tests")
    except AssertionError as e:
        print(f"  FAIL  test_kp_sdlc_codeowners_in_sync_with_protected_surface: {e}")
        print("\n0 passed, 1 failed out of 1 tests")
        raise SystemExit(1)
