"""Phase 3 — Tests for SQLite graph cache.

TDD: Defines the contract for incremental graph caching.
Technique from code-review-graph: SHA-256 file hashing to detect
changes, only re-parse modified files.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cathedral_keeper.python_graph import ImportEdge


# ── Import module under test ─────────────────────────────────────────

from cathedral_keeper.cache import GraphCache


# ── Helpers ──────────────────────────────────────────────────────────


def _temp_db() -> str:
    """Create a temp file path for test DB."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return path


def _cleanup(path: str):
    """Remove temp DB file."""
    try:
        os.unlink(path)
    except OSError:
        pass


# ── Creation Tests ───────────────────────────────────────────────────


def test_cache_creates_db_file():
    """GraphCache should create the SQLite DB file on init."""
    path = _temp_db()
    _cleanup(path)  # remove so we can test creation
    assert not os.path.exists(path)

    cache = GraphCache(db_path=path)
    assert os.path.exists(path)
    cache.close()
    _cleanup(path)


def test_cache_creates_parent_dirs():
    """GraphCache should create parent directories if needed."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "subdir", "nested", "graph.db")
        cache = GraphCache(db_path=db_path)
        assert os.path.exists(db_path)
        cache.close()


# ── Staleness Detection Tests ────────────────────────────────────────


def test_cache_all_files_stale_on_empty_db():
    """On empty cache, all files should be stale."""
    path = _temp_db()
    cache = GraphCache(db_path=path)

    stale = cache.get_stale_files({"a.py": "hash_a", "b.py": "hash_b"})
    assert set(stale) == {"a.py", "b.py"}

    cache.close()
    _cleanup(path)


def test_cache_detects_changed_files():
    """Files with different hashes should be detected as stale."""
    path = _temp_db()
    cache = GraphCache(db_path=path)

    # Store initial state
    cache.update("a.py", "hash_v1", [])
    cache.update("b.py", "hash_v1", [])

    # a.py changed, b.py didn't
    stale = cache.get_stale_files({"a.py": "hash_v2", "b.py": "hash_v1"})
    assert stale == ["a.py"]

    cache.close()
    _cleanup(path)


def test_cache_returns_empty_for_unchanged():
    """If all file hashes match cache, nothing is stale."""
    path = _temp_db()
    cache = GraphCache(db_path=path)

    cache.update("a.py", "hash_a", [])
    cache.update("b.py", "hash_b", [])

    stale = cache.get_stale_files({"a.py": "hash_a", "b.py": "hash_b"})
    assert stale == []

    cache.close()
    _cleanup(path)


def test_cache_new_files_are_stale():
    """Files not in cache at all should be stale."""
    path = _temp_db()
    cache = GraphCache(db_path=path)

    cache.update("a.py", "hash_a", [])

    stale = cache.get_stale_files({"a.py": "hash_a", "new.py": "hash_new"})
    assert stale == ["new.py"]

    cache.close()
    _cleanup(path)


# ── Edge Storage Tests ───────────────────────────────────────────────


def test_cache_stores_and_retrieves_edges():
    """Cached edges should be retrievable."""
    path = _temp_db()
    cache = GraphCache(db_path=path)

    edges = [
        ImportEdge(src_file="a.py", dst_file="b.py", module="b", line=1),
        ImportEdge(src_file="a.py", dst_file="c.py", module="c", line=5),
    ]
    cache.update("a.py", "hash_a", edges)

    retrieved = cache.get_cached_edges()
    assert len(retrieved) == 2
    assert any(e.dst_file == "b.py" for e in retrieved)
    assert any(e.dst_file == "c.py" for e in retrieved)

    cache.close()
    _cleanup(path)


def test_cache_update_replaces_edges_for_file():
    """Updating a file should replace its edges, not append."""
    path = _temp_db()
    cache = GraphCache(db_path=path)

    # Initial edges
    cache.update("a.py", "hash_v1", [
        ImportEdge(src_file="a.py", dst_file="b.py", module="b", line=1),
    ])
    assert len(cache.get_cached_edges()) == 1

    # Updated edges (b.py removed, c.py added)
    cache.update("a.py", "hash_v2", [
        ImportEdge(src_file="a.py", dst_file="c.py", module="c", line=1),
    ])
    edges = cache.get_cached_edges()
    assert len(edges) == 1
    assert edges[0].dst_file == "c.py"

    cache.close()
    _cleanup(path)


def test_cache_preserves_edges_from_other_files():
    """Updating file A should not affect file B's edges."""
    path = _temp_db()
    cache = GraphCache(db_path=path)

    cache.update("a.py", "hash_a", [
        ImportEdge(src_file="a.py", dst_file="x.py", module="x", line=1),
    ])
    cache.update("b.py", "hash_b", [
        ImportEdge(src_file="b.py", dst_file="y.py", module="y", line=1),
    ])

    # Update a.py only
    cache.update("a.py", "hash_a2", [
        ImportEdge(src_file="a.py", dst_file="z.py", module="z", line=1),
    ])

    edges = cache.get_cached_edges()
    assert len(edges) == 2
    assert any(e.src_file == "a.py" and e.dst_file == "z.py" for e in edges)
    assert any(e.src_file == "b.py" and e.dst_file == "y.py" for e in edges)

    cache.close()
    _cleanup(path)


# ── Persistence Tests ────────────────────────────────────────────────


def test_cache_survives_between_runs():
    """Data should persist when cache is closed and reopened."""
    path = _temp_db()

    # First run: store data
    cache1 = GraphCache(db_path=path)
    cache1.update("a.py", "hash_a", [
        ImportEdge(src_file="a.py", dst_file="b.py", module="b", line=1),
    ])
    cache1.close()

    # Second run: data should be there
    cache2 = GraphCache(db_path=path)
    stale = cache2.get_stale_files({"a.py": "hash_a"})
    assert stale == []

    edges = cache2.get_cached_edges()
    assert len(edges) == 1

    cache2.close()
    _cleanup(path)


# ── Clear Tests ──────────────────────────────────────────────────────


def test_cache_clear_removes_all_data():
    """clear() should remove all cached data."""
    path = _temp_db()
    cache = GraphCache(db_path=path)

    cache.update("a.py", "hash_a", [
        ImportEdge(src_file="a.py", dst_file="b.py", module="b", line=1),
    ])

    cache.clear()

    assert cache.get_stale_files({"a.py": "hash_a"}) == ["a.py"]
    assert cache.get_cached_edges() == []

    cache.close()
    _cleanup(path)


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
