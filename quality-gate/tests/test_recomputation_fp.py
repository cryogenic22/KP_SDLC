"""S5 — Tests for smarter redundant recomputation false positive reduction.

Team Feedback: 480 "redundant recomputation" findings is extremely high
and likely includes many false positives from DB calls, property access,
string formatting, etc.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qg.checks_ai_smells import _call_sig


# ── Should Return None (excluded from recomputation check) ───────────


def test_db_get_excluded():
    """db.get(id) should be excluded — results may differ between calls."""
    code = "db.get(user_id)"
    tree = ast.parse(code, mode="eval")
    sig = _call_sig(tree.body)
    assert sig is None, f"db.get should be excluded but got sig={sig}"


def test_db_execute_excluded():
    """db.execute() should be excluded."""
    code = "db.execute(query)"
    tree = ast.parse(code, mode="eval")
    sig = _call_sig(tree.body)
    assert sig is None


def test_session_get_excluded():
    """session.get() should be excluded."""
    code = "session.get(Model, pk)"
    tree = ast.parse(code, mode="eval")
    sig = _call_sig(tree.body)
    assert sig is None


def test_fetch_excluded():
    """fetch() calls should be excluded."""
    code = "fetch(url)"
    tree = ast.parse(code, mode="eval")
    sig = _call_sig(tree.body)
    assert sig is None


def test_requests_get_excluded():
    """requests.get() should be excluded."""
    code = "requests.get(url)"
    tree = ast.parse(code, mode="eval")
    sig = _call_sig(tree.body)
    assert sig is None


def test_query_excluded():
    """db.query() should be excluded."""
    code = "db.query(Model)"
    tree = ast.parse(code, mode="eval")
    sig = _call_sig(tree.body)
    assert sig is None


def test_commit_excluded():
    """db.commit() should be excluded."""
    code = "db.commit()"
    tree = ast.parse(code, mode="eval")
    sig = _call_sig(tree.body)
    assert sig is None


def test_refresh_excluded():
    """db.refresh() should be excluded."""
    code = "db.refresh(obj)"
    tree = ast.parse(code, mode="eval")
    sig = _call_sig(tree.body)
    assert sig is None


# ── Should Return Signature (real recomputation) ─────────────────────


def test_pure_calc_included():
    """Pure computation like calc(x) should still be flagged."""
    code = "calculate_total(items)"
    tree = ast.parse(code, mode="eval")
    sig = _call_sig(tree.body)
    assert sig is not None


def test_len_included():
    """len(items) should still be flagged."""
    code = "len(items)"
    tree = ast.parse(code, mode="eval")
    sig = _call_sig(tree.body)
    assert sig is not None


def test_sorted_included():
    """sorted(data) should still be flagged."""
    code = "sorted(data)"
    tree = ast.parse(code, mode="eval")
    sig = _call_sig(tree.body)
    assert sig is not None


# ── Runner ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    passed = 0
    failed = 0
    tests = [
        (name, obj)
        for name, obj in sorted(globals().items())
        if name.startswith("test_") and callable(obj)
    ]
    for name, fn in tests:
        try:
            fn()
            passed += 1
            print(f"  PASS  {name}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {name}: {e}")
        except Exception as e:
            failed += 1
            print(f"  ERROR {name}: {e}")

    print(f"\n{passed} passed, {failed} failed out of {len(tests)} tests")
    raise SystemExit(1 if failed else 0)
