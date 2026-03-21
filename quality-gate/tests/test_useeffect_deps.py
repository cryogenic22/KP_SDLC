"""S3 — Tests for useEffect dependency array enforcement.

Team Feedback: 47 useEffect hooks without dependency arrays found
but only in architecture narrative, not as per-file warnings.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qg.checks_nextjs import _check_useeffect_missing_deps


# ── Helpers ──────────────────────────────────────────────────────────


def _run_check(code: str) -> list[dict]:
    issues = []

    def add_issue(*, line, rule, severity, message, suggestion="", **kwargs):
        issues.append({"line": line, "rule": rule, "message": message})

    lines = code.splitlines()
    _check_useeffect_missing_deps(
        file_path=Path("Component.tsx"),
        lines=lines,
        add_issue=add_issue,
        severity="warning",
    )
    return issues


# ── Should Flag ──────────────────────────────────────────────────────


def test_flags_useeffect_no_deps():
    """useEffect with no dependency array should be flagged."""
    code = """
import { useEffect } from 'react';

function Component() {
  useEffect(() => {
    fetchData();
  })
  return <div />;
}
"""
    issues = _run_check(code)
    assert len(issues) >= 1
    assert any("useEffect" in i["message"] for i in issues)


def test_flags_useeffect_multiline_no_deps():
    """Multi-line useEffect with no deps should be flagged."""
    code = """
  useEffect(() => {
    const data = fetchData();
    setResult(data);
  })
"""
    issues = _run_check(code)
    assert len(issues) >= 1


# ── Should NOT Flag ──────────────────────────────────────────────────


def test_passes_useeffect_empty_deps():
    """useEffect with empty dependency array [] should NOT be flagged."""
    code = """
  useEffect(() => {
    fetchData();
  }, [])
"""
    issues = _run_check(code)
    assert len(issues) == 0


def test_passes_useeffect_with_deps():
    """useEffect with dependency array [id] should NOT be flagged."""
    code = """
  useEffect(() => {
    fetchData(id);
  }, [id])
"""
    issues = _run_check(code)
    assert len(issues) == 0


def test_passes_useeffect_deps_next_line():
    """Dependency array on the next line should NOT be flagged."""
    code = """
  useEffect(() => {
    fetchData();
  },
  [id, name])
"""
    issues = _run_check(code)
    assert len(issues) == 0


def test_passes_useeffect_inline():
    """Inline useEffect with deps should NOT be flagged."""
    code = """
  useEffect(() => { doThing() }, [])
"""
    issues = _run_check(code)
    assert len(issues) == 0


# ── Edge Cases ───────────────────────────────────────────────────────


def test_multiple_useeffects_mixed():
    """File with one good and one bad useEffect: flag only the bad one."""
    code = """
  useEffect(() => {
    fetchA();
  }, [])

  useEffect(() => {
    fetchB();
  })
"""
    issues = _run_check(code)
    assert len(issues) == 1


def test_no_useeffects():
    """File with no useEffect at all should produce no issues."""
    code = """
function Component() {
  const data = useMemo(() => calc(), []);
  return <div>{data}</div>;
}
"""
    issues = _run_check(code)
    assert len(issues) == 0


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
