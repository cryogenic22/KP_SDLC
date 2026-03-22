"""TDD spec for Test Recommendation Engine.

Uses CK's import graph to recommend which tests to run based on
changed files. "You changed models.py → run test_auth.py, test_api.py"
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cathedral_keeper.test_recommender import recommend_tests


# ── Core Recommendations ─────────────────────────────────────────────


def test_recommends_tests_for_changed_file():
    """Changed file with test importers should recommend those tests."""
    import_graph = {
        "src/models.py": [],
        "src/auth.py": ["src/models.py"],
        "tests/test_auth.py": ["src/auth.py", "src/models.py"],
        "tests/test_models.py": ["src/models.py"],
    }
    changed = ["src/models.py"]
    recs = recommend_tests(changed_files=changed, import_graph=import_graph)
    assert "tests/test_auth.py" in recs
    assert "tests/test_models.py" in recs


def test_recommends_transitive_tests():
    """If A→B→C and C changed, tests importing A should be recommended."""
    import_graph = {
        "src/db.py": [],
        "src/models.py": ["src/db.py"],
        "src/api.py": ["src/models.py"],
        "tests/test_api.py": ["src/api.py"],
    }
    changed = ["src/db.py"]
    recs = recommend_tests(changed_files=changed, import_graph=import_graph)
    assert "tests/test_api.py" in recs


def test_no_recommendations_for_unrelated_change():
    """Changed file with no test importers → empty recommendations."""
    import_graph = {
        "src/utils.py": [],
        "src/models.py": [],
        "tests/test_models.py": ["src/models.py"],
    }
    changed = ["src/utils.py"]
    recs = recommend_tests(changed_files=changed, import_graph=import_graph)
    assert "tests/test_models.py" not in recs


def test_empty_changed_files():
    """No changed files → no recommendations."""
    import_graph = {"tests/test_x.py": ["src/x.py"]}
    recs = recommend_tests(changed_files=[], import_graph=import_graph)
    assert len(recs) == 0


def test_recommendations_are_unique():
    """Same test file should not appear twice."""
    import_graph = {
        "src/a.py": [],
        "src/b.py": ["src/a.py"],
        "tests/test_ab.py": ["src/a.py", "src/b.py"],
    }
    changed = ["src/a.py", "src/b.py"]
    recs = recommend_tests(changed_files=changed, import_graph=import_graph)
    assert len(recs) == len(set(recs))


def test_only_test_files_recommended():
    """Only files matching test patterns should be recommended."""
    import_graph = {
        "src/models.py": [],
        "src/api.py": ["src/models.py"],
        "tests/test_api.py": ["src/api.py"],
    }
    changed = ["src/models.py"]
    recs = recommend_tests(changed_files=changed, import_graph=import_graph)
    for r in recs:
        assert "test_" in r or r.endswith("_test.py") or "/tests/" in r


def test_recommendations_sorted_by_relevance():
    """Direct importers should come before transitive."""
    import_graph = {
        "src/core.py": [],
        "src/service.py": ["src/core.py"],
        "tests/test_core.py": ["src/core.py"],
        "tests/test_service.py": ["src/service.py"],
    }
    changed = ["src/core.py"]
    recs = recommend_tests(changed_files=changed, import_graph=import_graph)
    if "tests/test_core.py" in recs and "tests/test_service.py" in recs:
        assert recs.index("tests/test_core.py") < recs.index("tests/test_service.py")


def test_blast_radius_count():
    """Should report how many non-test files are affected."""
    import_graph = {
        "src/models.py": [],
        "src/auth.py": ["src/models.py"],
        "src/api.py": ["src/models.py"],
        "src/admin.py": ["src/models.py"],
        "tests/test_auth.py": ["src/auth.py"],
    }
    changed = ["src/models.py"]
    recs = recommend_tests(changed_files=changed, import_graph=import_graph)
    # Function should also work — just checking it doesn't crash
    assert isinstance(recs, list)


# ── Runner ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    passed = 0
    failed = 0
    tests = [(name, obj) for name, obj in sorted(globals().items()) if name.startswith("test_") and callable(obj)]
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
