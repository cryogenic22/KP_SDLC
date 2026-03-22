"""TDD spec for pyproject.toml and packaging.

The project should be installable via pip install and expose
CLI entry points for qg and ck commands.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Test pyproject.toml at repo root
REPO_ROOT = Path(__file__).resolve().parents[2]


def test_pyproject_exists():
    """pyproject.toml should exist at repo root."""
    assert (REPO_ROOT / "pyproject.toml").exists()


def test_pyproject_has_project_section():
    """pyproject.toml should have [project] section with name and version."""
    content = (REPO_ROOT / "pyproject.toml").read_text()
    assert "[project]" in content
    assert "name" in content
    assert "version" in content


def test_pyproject_has_scripts():
    """pyproject.toml should define CLI entry points."""
    content = (REPO_ROOT / "pyproject.toml").read_text()
    assert "[project.scripts]" in content
    assert "qg" in content
    assert "ck" in content


def test_pyproject_has_description():
    """pyproject.toml should have a description."""
    content = (REPO_ROOT / "pyproject.toml").read_text()
    assert "description" in content


def test_pyproject_zero_dependencies():
    """pyproject.toml should declare zero runtime dependencies."""
    content = (REPO_ROOT / "pyproject.toml").read_text()
    # Should have dependencies = [] (empty list)
    assert "dependencies = []" in content or "dependencies = [\n]" in content


def test_makefile_exists():
    """Makefile should exist at repo root."""
    assert (REPO_ROOT / "Makefile").exists()


def test_makefile_has_key_targets():
    """Makefile should have test, report, and lint targets."""
    content = (REPO_ROOT / "Makefile").read_text()
    assert "test:" in content
    assert "report:" in content


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
