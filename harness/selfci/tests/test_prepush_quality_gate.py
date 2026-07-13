"""Contract for the pre-push QG gate hook (harness/hooks/prepush_quality_gate.py).

The hook mirrors CI's `make check` before a model-driven `git push`, so a QG
baseline-ratchet regression is caught locally instead of on a red CI run. These
tests pin the three load-bearing properties:
  * it fires on `git push` and ONLY on `git push` (no false blocks);
  * it BLOCKS on a real ratchet violation (QG exit 1) and FAILS OPEN on any
    infrastructure problem (QG/baseline absent, odd exit code);
  * on the real (clean) repo it does not block.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve()
_ROOT = _HERE.parents[3]
sys.path.insert(0, str(_ROOT / "harness" / "hooks"))

import prepush_quality_gate as gate


def test_is_git_push_fires_only_on_real_pushes():
    """Detection must catch pushes (incl. global flags, chained commands) and
    reject look-alikes — a false positive would gate unrelated Bash calls."""
    for yes in (
        "git push",
        "git push origin main",
        "git push -u origin feat/x",
        "git -C /repo push",
        "  git   push --force-with-lease ",
        "cd repo && git push",
        "git commit -m x && git push origin main",
    ):
        assert gate.is_git_push(yes), f"should detect push: {yes!r}"
    for no in (
        "git status",
        "git log --grep=push",
        "git commit -m 'push later'",
        "echo git push",           # git not at a command boundary
        "gitpush",
        "python push_tool.py",
    ):
        assert not gate.is_git_push(no), f"should NOT detect push: {no!r}"


def test_verdict_mapping_blocks_only_on_exit_1():
    """Exit 0 -> pass; exit 1 -> block (with a finding summary); anything else ->
    skip (fail open). This is the anti-vacuity core: the block path must fire on
    a real QG failure, and infra errors must not."""
    assert gate.verdict_for(0, "")[0] == "pass"
    ratchet = json.dumps({"issues": [
        {"severity": "error", "file": "a.py", "line": 3,
         "rule": "baseline_ratchet", "message": "warnings 4 > baselined 3"},
        {"severity": "warning", "file": "b.py", "line": 9, "rule": "x", "message": "y"},
    ]})
    verdict, detail = gate.verdict_for(1, ratchet)
    assert verdict == "block"
    assert "baseline_ratchet" in detail and "1 blocking QG finding" in detail
    assert gate.verdict_for(2, "")[0] == "skip"      # argparse/config error
    assert gate.verdict_for(139, "")[0] == "skip"    # crash


def test_run_gate_fails_open_when_qg_absent():
    """No QG / baseline in the tree -> 'skip' (never block on missing tooling)."""
    with tempfile.TemporaryDirectory() as d:
        verdict, _ = gate.run_gate(Path(d))
        assert verdict == "skip"


def test_decide_allows_non_push_and_non_bash():
    """decide() returns None (allow) for non-Bash tools and non-push Bash."""
    assert gate.decide({"tool_name": "Write", "tool_input": {"file_path": "x"}}) is None
    assert gate.decide({"tool_name": "Bash", "tool_input": {"command": "ls -la"}}) is None


def test_decide_emits_deny_on_block():
    """When the gate verdict is 'block', decide() must emit a well-formed deny
    decision. Swap run_gate to force the block branch deterministically."""
    original = gate.run_gate
    gate.run_gate = lambda root: ("block", "1 blocking QG finding(s):\n  a.py:3 [baseline_ratchet]")
    try:
        decision = gate.decide({"tool_name": "Bash",
                                "tool_input": {"command": "git push origin main"},
                                "cwd": str(_ROOT)})
    finally:
        gate.run_gate = original
    assert decision is not None, "block verdict must produce a deny decision"
    out = decision["hookSpecificOutput"]
    assert out["hookEventName"] == "PreToolUse"
    assert out["permissionDecision"] == "deny"
    assert "baseline_ratchet" in out["permissionDecisionReason"]


def test_clean_repo_does_not_block():
    """Integration: the real (green) repo must not be blocked by its own gate —
    run_gate returns pass (or skip if QG cannot run here), never block."""
    verdict, detail = gate.run_gate(_ROOT)
    assert verdict in ("pass", "skip"), f"gate would block a clean tree: {detail}"


# ── Runner ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    passed = failed = 0
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
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  ERROR {name}: {e}")

    print(f"\n{passed} passed, {failed} failed out of {len(tests)} tests")
    raise SystemExit(1 if failed else 0)
