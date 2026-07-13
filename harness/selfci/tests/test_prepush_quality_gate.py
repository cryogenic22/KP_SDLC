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
    """Detection must catch pushes across the spellings a model actually emits —
    metachar-terminated, env/path/sudo-prefixed, chained — while rejecting
    look-alikes. A false NEGATIVE silently un-gates a real push (the worse
    direction); a false positive merely runs QG on a non-push."""
    for yes in (
        "git push",
        "git push origin main",
        "git push -u origin feat/x",
        "git -C /repo push",
        "git -c user.name=x push",              # value-taking global option
        "  git   push --force-with-lease ",
        "cd repo && git push",
        "git commit -m x && git push origin main",
        "git push; echo done",                  # metachar-terminated (was missed)
        "git push;",
        "git push|cat",
        "(git push)",
        "HUSKY=0 git push",                     # env-prefixed (was missed)
        "FOO=bar BAZ=1 git push",
        "sudo git push",                        # wrapper (was missed)
        "/usr/bin/git push",                    # path-prefixed (was missed)
        "git status && git push",
    ):
        assert gate.is_git_push(yes), f"should detect push: {yes!r}"
    for no in (
        "git status",
        "git log --grep=push",
        "git commit -m 'push later'",
        "echo git push",           # git not in command position
        "gitpush",
        "git pushup",              # not the push subcommand
        "python push_tool.py",
    ):
        assert not gate.is_git_push(no), f"should NOT detect push: {no!r}"


def test_verdict_mapping_fails_open_except_on_real_violation():
    """block ONLY when QG completed a real scan and reported failure (exit 1,
    parseable JSON, files_checked>0, passed=false). A QG crash also exits 1, so
    exit 1 without a parseable verdict (or a zero-file scan) must SKIP (fail
    open) — otherwise a broken QG wedges every push (the reviewer's MAJOR).
    Note: check-mode `issues` also lists baselined debt, so the verdict keys off
    `passed`, not error-counting."""
    assert gate.verdict_for(0, "")[0] == "pass"
    failed = json.dumps({
        "passed": False,
        "stats": {"files_checked": 42},
        "prs": 92.0,
        "issues": [
            {"severity": "error", "rule": "baseline_ratchet",
             "message": "warnings 4 > baselined 3"},
            {"severity": "error", "rule": "function_size",   # baselined debt, ignored
             "message": "too long"},
        ],
    })
    verdict, detail = gate.verdict_for(1, failed)
    assert verdict == "block"
    assert "baseline_ratchet" in detail        # ratchet signal surfaced...
    assert "function_size" not in detail        # ...but baselined debt is not
    # exit 1 but a QG CRASH (non-JSON stdout) -> skip, NOT block
    assert gate.verdict_for(1, "Traceback (most recent call last):\nRuntimeError")[0] == "skip"
    # exit 1 valid JSON but no `passed` verdict -> skip (incomplete run)
    assert gate.verdict_for(1, json.dumps({"stats": {"files_checked": 5}}))[0] == "skip"
    # exit 1 with zero files scanned -> skip (infra, not a real violation)
    assert gate.verdict_for(1, json.dumps({"passed": False, "stats": {"files_checked": 0}}))[0] == "skip"
    assert gate.verdict_for(2, "")[0] == "skip"      # argparse/config error
    assert gate.verdict_for(139, "")[0] == "skip"    # crash signal


def test_run_gate_fails_open_when_qg_absent():
    """No QG / baseline in the tree -> 'skip' (never block on missing tooling)."""
    with tempfile.TemporaryDirectory() as d:
        verdict, _ = gate.run_gate(Path(d))
        assert verdict == "skip"


def test_run_gate_resolves_repo_root_from_subdir():
    """A push whose cwd is a repo SUBDIR is still gated: the upward walk finds
    the real root, and the live repo does not block."""
    assert gate._resolve_root(_HERE.parent) == _ROOT
    verdict, detail = gate.run_gate(_HERE.parent)  # harness/selfci/tests
    assert verdict in ("pass", "skip"), f"subdir push mis-verdict: {detail}"


def _make_stub_repo(root: Path, qg_body: str) -> None:
    """A throwaway repo whose quality_gate.py is `qg_body` (ignores argv)."""
    (root / "quality-gate").mkdir(parents=True, exist_ok=True)
    (root / "quality-gate" / "quality_gate.py").write_text(qg_body, encoding="utf-8")
    (root / ".quality-gate.baseline.json").write_text("{}", encoding="utf-8")


def test_run_gate_blocks_on_real_qg_exit_1():
    """End-to-end teeth (not a stubbed verdict): a real QG subprocess that exits
    1 with an error finding drives run_gate to 'block'."""
    body = (
        "import json, sys\n"
        "print(json.dumps({'passed': False, 'stats': {'files_checked': 3}, 'issues': ["
        "{'severity': 'error', 'file': 'x.py', 'line': 1, "
        "'rule': 'baseline_ratchet', 'message': 'warnings 4 > baselined 3'}]}))\n"
        "sys.exit(1)\n"
    )
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _make_stub_repo(root, body)
        verdict, detail = gate.run_gate(root)
        assert verdict == "block", f"real QG exit-1 with errors must block: {detail}"
        assert "baseline_ratchet" in detail


def test_run_gate_fails_open_on_real_qg_crash():
    """End-to-end teeth for the MAJOR fix: a QG that crashes also exits 1, but
    run_gate must SKIP (fail open), not block — a broken QG can't wedge pushes."""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _make_stub_repo(root, "raise RuntimeError('QG import blew up')\n")
        verdict, _ = gate.run_gate(root)
        assert verdict == "skip", "a QG crash (exit 1, no JSON) must fail OPEN, not block"


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
