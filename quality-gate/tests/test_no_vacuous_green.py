"""No vacuous green: a gate that checks nothing must not report a pass.

Two holes today (proven empirically):
  * `--root` on a non-git project hits the filesystem fallback, which walks
    config paths.include — shipped as [] — so it scans nothing.
  * run() returns passed=True with files_checked=0, so scanning zero files
    is reported as a clean pass.

TDD: written before the fix.
  - test_full_scan_nongit_walks_filesystem  -> RED (files_checked == 0)
  - test_full_scan_zero_files_fails_closed   -> RED (passed is True)
  - test_staged_noop_passes / explicit-paths -> conservation guards (stay green)
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _qg_nongit(tmp: str):
    """A QualityGate rooted at tmp, deterministically treated as non-git."""
    from quality_gate import QualityGate
    qg = QualityGate(root_dir=tmp, quiet=True)
    qg.git_root = None  # simulate a project that is not a git repo
    return qg


def test_full_scan_nongit_walks_filesystem():
    """A non-git full scan must actually walk the tree, not scan nothing."""
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "m.py"), "w", encoding="utf-8") as f:
            f.write("import requests\n\nx = requests.get('http://a')\n")
        qg = _qg_nongit(tmp)
        result = qg.run()  # full scan: no paths, not staged
        assert result.stats.get("files_checked", 0) >= 1, \
            f"non-git full scan scanned nothing: {result.stats}"


def test_full_scan_zero_files_fails_closed():
    """Scanning zero files (nothing to gate) must fail closed, not pass green."""
    with tempfile.TemporaryDirectory() as tmp:
        qg = _qg_nongit(tmp)  # empty dir -> zero code files
        result = qg.run()
        assert result.stats.get("files_checked", 0) == 0
        assert result.passed is False, "zero files scanned must not report passed=True"
        assert any(i.rule == "no_files_checked" for i in result.issues), \
            "fail-closed must surface a 'no_files_checked' finding"


def test_staged_noop_passes():
    """No staged files is a legitimate no-op (pre-commit) and must pass."""
    with tempfile.TemporaryDirectory() as tmp:
        qg = _qg_nongit(tmp)  # no git -> --staged finds nothing
        result = qg.run(staged_only=True)
        assert result.passed is True, "empty --staged run must remain a clean pass"


def test_explicit_clean_file_not_fail_closed():
    """A real scanned file with no violations must pass — fail-closed must not over-trigger."""
    with tempfile.TemporaryDirectory() as tmp:
        test_file = os.path.join(tmp, "clean.py")
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("x = 1\n")
        qg = _qg_nongit(tmp)
        result = qg.run(paths=[test_file])
        assert result.stats.get("files_checked", 0) == 1
        assert result.passed is True
        assert not any(i.rule == "no_files_checked" for i in result.issues)


def test_explicit_paths_all_noncode_passes():
    """Docs-only change: explicit/--paths-from paths with no code files is a no-op, not fail-closed.

    Mirrors the shipped CI workflow (`--paths-from <changed-files>`) on a
    docs-only PR — must not red-fail.
    """
    with tempfile.TemporaryDirectory() as tmp:
        doc = os.path.join(tmp, "README.md")
        with open(doc, "w", encoding="utf-8") as f:
            f.write("# docs only\n")
        qg = _qg_nongit(tmp)
        result = qg.run(paths=[doc])  # like a docs-only --paths-from run
        assert result.stats.get("files_checked", 0) == 0
        assert result.passed is True, "docs-only explicit paths must pass (no-op), not fail closed"
        assert not any(i.rule == "no_files_checked" for i in result.issues)


def test_run_does_not_accumulate_issues_across_reruns():
    """Re-running on the same instance must not accumulate synthetic findings."""
    with tempfile.TemporaryDirectory() as tmp:
        qg = _qg_nongit(tmp)  # empty dir -> fail closed each run
        qg.run()
        result2 = qg.run()
        assert len([i for i in result2.issues if i.rule == "no_files_checked"]) == 1, \
            "run() must reset accumulated issues; got duplicates on re-run"


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
