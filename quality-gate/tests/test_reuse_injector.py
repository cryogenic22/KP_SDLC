"""E0.9 — PreToolUse reuse injector: behaviour, parity, and fail-open anti-cases.

The injector (harness/hooks/reuse_injector.py) is a self-contained stdlib-only
hook: on Write/Edit of production Python it injects deterministic reuse hints
(exact body-hash clones + same-name symbols) as additionalContext. It must
NEVER block a tool call — every code path exits 0 (exit 2 is the PreToolUse
block signal and is forbidden), and emitted JSON never carries a 'deny'.

Parity (load-bearing): the hook's signature computation must produce the SAME
body-hash values as quality-gate/qg/checks_duplicates.py — same min_lines=4,
same skip-names, same tests-excluded semantics. Hook and gate disagreeing on
what counts as a clone is the dispersion disease this component exists to
fight, so that contract is pinned here by importing both sides.

TDD: written before the injector exists — every test is RED first.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
INJECTOR = REPO / "harness" / "hooks" / "reuse_injector.py"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # quality-gate/


def _load_injector():
    spec = importlib.util.spec_from_file_location("reuse_injector", INJECTOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# A public 5-line function body (>= min_lines=4) shared by fixtures.
CLONE_BODY = (
    "    total = 0\n"
    "    for item in items:\n"
    "        total += item * scale\n"
    "    return total\n"
)

NOVEL_CONTENT = (
    "def unrelated(records):\n"
    "    seen = set()\n"
    "    for rec in records:\n"
    "        seen.add(rec.strip().lower())\n"
    "    return sorted(seen)\n"
)


def _fixture(tmp: Path) -> None:
    """Minimal production repo: src/existing.py defines public foo() (5 lines)."""
    (tmp / "src").mkdir(parents=True, exist_ok=True)
    (tmp / "src" / "existing.py").write_text(
        "def foo(items, scale):\n" + CLONE_BODY, encoding="utf-8")


def _payload(tool_name: str = "Write", file_path: str = "new_mod.py",
             content: str = "", cwd: str = "") -> dict:
    tool_input: dict = {"file_path": file_path}
    if tool_name == "Edit":
        tool_input["new_string"] = content
    else:
        tool_input["content"] = content
    return {"hook_event_name": "PreToolUse", "tool_name": tool_name,
            "tool_input": tool_input, "cwd": cwd}


def _run_hook(stdin_text: str, cwd: Path) -> tuple[int, bytes, bytes]:
    proc = subprocess.run([sys.executable, "-P", str(INJECTOR)],
                          input=stdin_text.encode("utf-8"),
                          capture_output=True, cwd=str(cwd), timeout=120)
    return proc.returncode, proc.stdout, proc.stderr


# ── Injection behaviour ───────────────────────────────────────────────


def test_hook_injects_on_renamed_clone_write():
    """A Write whose content clones an existing body (renamed) must inject
    exit 0 + hookSpecificOutput JSON naming the existing symbol at path:line."""
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        _fixture(t)
        clone = "def compute_sum(items, scale):\n" + CLONE_BODY
        payload = json.dumps(_payload(content=clone, cwd=str(t)))
        rc, out, _err = _run_hook(payload, t)
        assert rc == 0, f"hook must exit 0, got {rc}"
        assert out, "expected an injection on an exact renamed clone, got silence"
        data = json.loads(out.decode("utf-8"))
        hso = data["hookSpecificOutput"]
        assert hso["hookEventName"] == "PreToolUse"
        assert hso["permissionDecision"] == "allow"
        ctx = hso["additionalContext"]
        assert "foo" in ctx, f"existing symbol name missing from context: {ctx!r}"
        assert "existing.py:1" in ctx, f"path:line missing from context: {ctx!r}"


def test_hook_injects_same_name_symbol_tier2():
    """TIER-2: a new definition reusing an existing public NAME (different
    body) must surface 'same-name symbol exists at path:line'."""
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        _fixture(t)
        same_name = (
            "def foo(payload):\n"
            "    parts = payload.split(',')\n"
            "    cleaned = [p.strip() for p in parts]\n"
            "    joined = '|'.join(cleaned)\n"
            "    return joined\n"
        )
        rc, out, _err = _run_hook(json.dumps(_payload(content=same_name, cwd=str(t))), t)
        assert rc == 0
        assert out, "expected a tier-2 same-name injection, got silence"
        ctx = json.loads(out.decode("utf-8"))["hookSpecificOutput"]["additionalContext"]
        assert "same-name" in ctx and "foo" in ctx and "existing.py:1" in ctx, ctx


def test_hook_silent_when_novel_code():
    """Genuinely new code must produce NO injection (anti-noise: a hook that
    always fires trains agents to ignore it)."""
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        _fixture(t)
        rc, out, _err = _run_hook(json.dumps(_payload(content=NOVEL_CONTENT, cwd=str(t))), t)
        assert rc == 0
        assert out == b"", f"novel code must stay silent, got: {out!r}"


def test_hook_silent_on_non_code_and_non_write_edit():
    """Read tool, non-Python targets, test files, and unknown tools must all
    be silent no-ops (defense in depth against the 'Write|Edit' matcher)."""
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        _fixture(t)
        cwd = str(t)
        clone = "def compute_sum(items, scale):\n" + CLONE_BODY
        cases = [
            _payload(tool_name="Read", file_path="src/existing.py", cwd=cwd),
            _payload(file_path="notes.md", content=clone, cwd=cwd),
            _payload(file_path="tests/test_x.py", content=clone, cwd=cwd),
            _payload(file_path="test_x.py", content=clone, cwd=cwd),
            _payload(tool_name="NotebookEdit", file_path="nb.py", content=clone, cwd=cwd),
        ]
        for payload in cases:
            rc, out, _err = _run_hook(json.dumps(payload), t)
            assert rc == 0, f"{payload['tool_name']}/{payload['tool_input']['file_path']}: rc={rc}"
            assert out == b"", (f"{payload['tool_name']}/"
                                f"{payload['tool_input']['file_path']} must be silent: {out!r}")


# ── ANTI-CASE: absolute fail-open ─────────────────────────────────────


def test_hook_fails_open_on_garbage():
    """Doctrine anti-case: garbage in any position must exit 0 (NEVER 2 — that
    would deny every Write in the session) with empty stdout, and no emitted
    byte may carry a 'deny' decision."""
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        _fixture(t)
        cwd = str(t)
        # (d) pre-corrupted cache file must be ignored, not fatal.
        cache = t / ".harness" / "cache" / "reuse-index.json"
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text("{this is NOT json][", encoding="utf-8")
        cases = {
            "non-json stdin": "this is not json {{{",
            "missing tool_input": json.dumps({"tool_name": "Write", "cwd": cwd}),
            "invalid python content": json.dumps(
                _payload(content="def broken(:\n    pass\n", cwd=cwd)),
            "corrupted cache": json.dumps(_payload(content=NOVEL_CONTENT, cwd=cwd)),
        }
        for label, stdin_text in cases.items():
            rc, out, _err = _run_hook(stdin_text, t)
            assert rc != 2, f"{label}: exit 2 blocks the tool call — forbidden (rc={rc})"
            assert rc == 0, f"{label}: fail-open means exit 0, got {rc}"
            assert out == b"", f"{label}: garbage must be silent, got {out!r}"
            assert b"deny" not in out, f"{label}: emitted a deny decision"
        # Corrupt cache + a REAL clone: still exit 0, still never 'deny'.
        rc, out, _err = _run_hook(
            json.dumps(_payload(content="def compute_sum(items, scale):\n" + CLONE_BODY,
                                cwd=cwd)), t)
        assert rc == 0 and b"deny" not in out


# ── Determinism + caps ────────────────────────────────────────────────


def test_hook_deterministic():
    """Identical fixture + payload → byte-identical stdout across runs (the
    second run exercises the mtime/size cache round-trip)."""
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        _fixture(t)
        payload = json.dumps(_payload(
            content="def compute_sum(items, scale):\n" + CLONE_BODY, cwd=str(t)))
        rc1, out1, _ = _run_hook(payload, t)
        assert rc1 == 0 and out1, "first run must inject"
        assert (t / ".harness" / "cache" / "reuse-index.json").exists(), \
            "cache file not persisted at .harness/cache/reuse-index.json"
        rc2, out2, _ = _run_hook(payload, t)
        assert rc2 == 0
        assert out1 == out2, "warm-cache run diverged from cold run (non-deterministic)"


def test_hook_caps_suggestions_and_context_size():
    """Many matches must be capped: at most 5 suggestion lines, context under
    ~1200 chars, stable (path,line) order."""
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        for i in range(7):
            (t / f"mod{i}.py").write_text(
                f"def helper{i}(items, scale):\n" + CLONE_BODY, encoding="utf-8")
        payload = json.dumps(_payload(
            content="def compute_sum(items, scale):\n" + CLONE_BODY, cwd=str(t)))
        rc, out, _err = _run_hook(payload, t)
        assert rc == 0 and out
        ctx = json.loads(out.decode("utf-8"))["hookSpecificOutput"]["additionalContext"]
        suggestions = [ln for ln in ctx.splitlines() if ln.startswith("- ")]
        count, size = len(suggestions), len(ctx)
        assert 1 <= count <= 5, f"cap of 5 violated: {count}"
        assert size <= 1200, f"context budget (~1200 chars) violated: {size}"
        assert suggestions == sorted(suggestions), \
            "suggestions not in stable (path,line) sorted order"


# ── CLI fallback (vendor-neutral contract) ────────────────────────────


def test_cli_fallback_matches_hook():
    """`python reuse_injector.py --scan <path>` must report the same
    path:line matches the hook would inject for the same content."""
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        _fixture(t)
        cwd = str(t)
        clone = "def compute_sum(items, scale):\n" + CLONE_BODY
        rc, out, _err = _run_hook(json.dumps(_payload(content=clone, cwd=cwd)), t)
        assert rc == 0 and out
        ctx = json.loads(out.decode("utf-8"))["hookSpecificOutput"]["additionalContext"]
        hook_lines = [ln[2:] for ln in ctx.splitlines() if ln.startswith("- ")]

        (t / "new_mod.py").write_text(clone, encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, "-P", str(INJECTOR), "--scan", "new_mod.py"],
            capture_output=True, cwd=cwd, timeout=120)
        assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
        cli_lines = [ln for ln in proc.stdout.decode("utf-8").splitlines() if ln.strip()]
        assert cli_lines == hook_lines, (
            f"CLI and hook disagree:\n  cli={cli_lines}\n  hook={hook_lines}")


# ── Behavioural parity with the QG duplicate gate (MANDATORY) ─────────


def test_signature_parity_with_quality_gate_duplicates():
    """On shared sources the injector must compute the SAME body-hash values
    as qg/checks_duplicates.py — same min_lines=4, same skip-names. This is
    the one contract that must never drift."""
    from collections import defaultdict

    from qg import checks_duplicates as qd
    inj = _load_injector()

    variant_body = CLONE_BODY.replace("items", "x_items")
    sources = {
        "public 5-liner": "def alpha(x, y):\n" + variant_body,
        "renamed clone": "def beta(x, y):\n" + variant_body,
        "skip-name upgrade": "def upgrade(a, b):\n" + CLONE_BODY,
        "skip-name values": "def values(a, b):\n" + CLONE_BODY,
        "dunder init": "def __init__(a, b):\n" + CLONE_BODY,
        "private": "def _hidden(a, b):\n" + CLONE_BODY,
        "too short (3 lines)": "def tiny(a):\n    b = a + 1\n    return b\n",
        "async public": "async def gamma(items, scale):\n" + CLONE_BODY,
    }
    for label, src in sources.items():
        gate_out: dict = defaultdict(list)
        qd._collect_function_sigs(
            file_path=Path("m.py"), content=src, lines=src.splitlines(),
            language="python", func_signatures=gate_out, min_lines=4)
        gate_sigs = set(gate_out.keys())
        inj_sigs = {sig for sig, _name, _line in inj.collect_signatures(src)}
        assert inj_sigs == gate_sigs, (
            f"{label}: injector sigs {inj_sigs} != gate sigs {gate_sigs}")

    # The renamed clone must hash IDENTICALLY on both sides (the whole point).
    a = inj.collect_signatures(sources["public 5-liner"])
    b = inj.collect_signatures(sources["renamed clone"])
    assert a and b and a[0][0] == b[0][0], "renamed clone did not hash-match"


def test_is_test_semantics_parity():
    """Tests-excluded semantics must match QualityGate._is_test_path for
    Python paths (a hook that suggests reuse of test helpers is noise)."""
    from quality_gate import QualityGate
    inj = _load_injector()
    samples = [
        "tests/test_x.py", "src/tests/helper.py", "test/mod.py", "src/app.py",
        "test_runner.py", "runner_test.py", "src/latest/mod.py",
        "attest/mod.py", "src/protest/x.py", "pkg/test/deep/mod.py",
    ]
    for s in samples:
        assert inj.is_test_path(s) == QualityGate._is_test_path(Path(s)), \
            f"is_test mismatch on {s!r}"


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
