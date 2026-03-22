"""TDD spec for Commit-Aware Blast Radius (pre-commit).

Shows which downstream files are affected by staged changes.
"This change to models.py affects 14 files including 3 API endpoints."
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cathedral_keeper.blast_precommit import compute_commit_blast_radius, format_blast_summary


# ── Blast Radius Computation ─────────────────────────────────────────


def test_finds_direct_dependents():
    """Changed file's direct importers should be in blast radius."""
    import_graph = {
        "src/models.py": [],
        "src/auth.py": ["src/models.py"],
        "src/api.py": ["src/models.py"],
    }
    changed = ["src/models.py"]
    result = compute_commit_blast_radius(changed_files=changed, import_graph=import_graph)
    assert "src/auth.py" in result["affected_files"]
    assert "src/api.py" in result["affected_files"]


def test_finds_transitive_dependents():
    """Transitive importers should also be included."""
    import_graph = {
        "src/db.py": [],
        "src/models.py": ["src/db.py"],
        "src/api.py": ["src/models.py"],
        "src/admin.py": ["src/api.py"],
    }
    changed = ["src/db.py"]
    result = compute_commit_blast_radius(changed_files=changed, import_graph=import_graph)
    assert "src/models.py" in result["affected_files"]
    assert "src/api.py" in result["affected_files"]
    assert "src/admin.py" in result["affected_files"]


def test_no_affected_files():
    """Leaf file with no dependents → empty blast radius."""
    import_graph = {
        "src/utils.py": [],
        "src/models.py": [],
    }
    changed = ["src/utils.py"]
    result = compute_commit_blast_radius(changed_files=changed, import_graph=import_graph)
    assert len(result["affected_files"]) == 0


def test_excludes_changed_files_from_affected():
    """Changed files themselves should NOT appear in affected list."""
    import_graph = {
        "src/models.py": [],
        "src/api.py": ["src/models.py"],
    }
    changed = ["src/models.py"]
    result = compute_commit_blast_radius(changed_files=changed, import_graph=import_graph)
    assert "src/models.py" not in result["affected_files"]


def test_result_has_counts():
    """Result should include total affected count and test count."""
    import_graph = {
        "src/models.py": [],
        "src/auth.py": ["src/models.py"],
        "tests/test_auth.py": ["src/auth.py"],
    }
    changed = ["src/models.py"]
    result = compute_commit_blast_radius(changed_files=changed, import_graph=import_graph)
    assert "total_affected" in result
    assert "test_files_affected" in result
    assert "source_files_affected" in result
    assert result["total_affected"] >= 1


def test_multiple_changed_files():
    """Multiple changed files should union their blast radii."""
    import_graph = {
        "src/a.py": [],
        "src/b.py": [],
        "src/c.py": ["src/a.py"],
        "src/d.py": ["src/b.py"],
    }
    changed = ["src/a.py", "src/b.py"]
    result = compute_commit_blast_radius(changed_files=changed, import_graph=import_graph)
    assert "src/c.py" in result["affected_files"]
    assert "src/d.py" in result["affected_files"]


# ── Summary Formatting ───────────────────────────────────────────────


def test_format_summary_readable():
    """Summary should be human-readable for pre-commit output."""
    result = {
        "changed_files": ["src/models.py"],
        "affected_files": ["src/auth.py", "src/api.py", "tests/test_auth.py"],
        "total_affected": 3,
        "source_files_affected": 2,
        "test_files_affected": 1,
    }
    summary = format_blast_summary(result)
    assert "models.py" in summary
    assert "3" in summary or "three" in summary.lower()


def test_format_summary_empty():
    """No affected files → clean message."""
    result = {
        "changed_files": ["src/utils.py"],
        "affected_files": [],
        "total_affected": 0,
        "source_files_affected": 0,
        "test_files_affected": 0,
    }
    summary = format_blast_summary(result)
    assert isinstance(summary, str)
    assert len(summary) > 0


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
