"""E0.4 — QG baseline & ratchet (Clean-as-You-Code brownfield unlock).

TDD: written before qg/baseline.py exists (RED first).

Guarantees under test:
  * --mode baseline writes a provenance-stamped, forward-slash-keyed,
    per-file baseline (version/generated_at/commit/generated_by).
  * check --baseline tolerates baselined (known) debt but blocks any
    per-file regression (errors/warnings/PRS ratchet).
  * New files absent from the baseline must meet the existing floor.
  * Comparison is per-file and order-independent (dict-key lookup).
  * A security veto is never baselined away.
  * ANTI-CASE: --mode baseline refuses to write under CI env
    (CI/GITHUB_ACTIONS) without --allow-ci-baseline; check/audit modes
    never write (byte-identical).
  * Corrupt baseline fails closed as 'baseline_unreadable', distinct
    from 'baseline_missing'.
  * Windows backslash relpath keys match forward-slash baseline keys.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

QG_DIR = Path(__file__).resolve().parents[1]
QG_SCRIPT = QG_DIR / "quality_gate.py"

# ── Fixture sources (assembled so THIS file does not trip the rules) ──

# 8 warnings -> PRS 84.0 (below the 85 floor, no errors): the "known debt" file.
DEBT_8W = "".join(f"w{i} = {i}  # type: " + f"ignore\n" for i in range(8))
# 10 warnings -> PRS 80.0: the same file after a warning regression.
DEBT_10W = "".join(f"w{i} = {i}  # type: " + f"ignore\n" for i in range(10))

_MARK = "TO" + "DO"  # avoids a literal marker in this test's own source
ERR_1E = f"# {_MARK} first\nx = 1\n"                     # 1 error  -> PRS 90.0
ERR_2E = f"# {_MARK} first\n# {_MARK} second\nx = 1\n"   # 2 errors -> PRS 80.0

# Triggers LLM-PY-DIRECT-EVAL (a DEFAULT_VETO_RULES member) in the fixture
# file only — the call/sink strings are split so THIS file is not flagged.
_EVAL = "ev" + "al"
VETO_SRC = (
    "result = l" + "lm.invoke(prompt)\n"
    "computed = " + _EVAL + "(result.content)\n"
)

CLEAN = "x = 1\n"


# ── Helpers ───────────────────────────────────────────────────────────

def _write(root: str, rel: str, content: str) -> str:
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return str(path)


def _gate(tmp: str, baseline: str | None = None):
    """A QualityGate rooted at tmp, deterministically treated as non-git."""
    from quality_gate import QualityGate
    qg = QualityGate(root_dir=tmp, quiet=True, baseline=baseline)
    qg.git_root = None
    return qg


def _no_ci_env() -> dict:
    env = dict(os.environ)
    env.pop("CI", None)
    env.pop("GITHUB_ACTIONS", None)
    return env


def _write_baseline_from_scan(tmp: str, bpath: str) -> dict:
    """Full scan of tmp, then build+write a baseline via the module API."""
    from qg.baseline import build_baseline, write_baseline
    gate = _gate(tmp)
    gate.run()
    data = build_baseline(gate.file_prs, root=tmp, min_score=85, git_root=None)
    ok, msg = write_baseline(bpath, data, env={})  # env={} -> never CI-refused
    assert ok, f"baseline write failed: {msg}"
    return data


def _manual_baseline(bpath: str, files: dict) -> None:
    data = {
        "version": 1,
        "generated_by": "quality-gate baseline",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "commit": "unknown",
        "min_score": 85,
        "files": files,
    }
    Path(bpath).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _cli(args: list[str], cwd: str, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(QG_SCRIPT), *args],
        cwd=cwd, env=env, capture_output=True, text=True, timeout=180,
    )


# ── Baseline write: provenance + normalized keys ─────────────────────

def test_baseline_mode_writes_provenance_stamped_file():
    """build+write produces version/provenance and forward-slash file keys."""
    with tempfile.TemporaryDirectory() as tmp:
        _write(tmp, "pkg/debt.py", DEBT_8W)
        _write(tmp, "clean.py", CLEAN)
        bpath = os.path.join(tmp, ".quality-gate.baseline.json")
        _write_baseline_from_scan(tmp, bpath)

        loaded = json.loads(Path(bpath).read_text(encoding="utf-8"))
        assert loaded["version"] == 1
        assert loaded["generated_by"] == "quality-gate baseline"
        assert "T" in loaded["generated_at"], "generated_at must be ISO8601"
        assert loaded["commit"] == "unknown", "non-git project stamps 'unknown'"
        assert loaded["min_score"] == 85

        files = loaded["files"]
        assert "pkg/debt.py" in files, f"expected forward-slash key, got {list(files)}"
        assert not any("\\" in k for k in files), "keys must never contain backslashes"
        entry = files["pkg/debt.py"]
        assert set(entry) == {"prs", "errors", "warnings", "vetoed"}
        assert entry["errors"] == 0 and entry["warnings"] == 8
        assert entry["prs"] == 84.0 and entry["vetoed"] is False


# ── Ratchet semantics ─────────────────────────────────────────────────

def test_check_with_baseline_tolerates_known_debt():
    """A below-floor file with a matching baseline entry passes (the unlock)."""
    with tempfile.TemporaryDirectory() as tmp:
        _write(tmp, "pkg/debt.py", DEBT_8W)
        _write(tmp, "clean.py", CLEAN)
        # Sanity: without a baseline the debt file fails the floor.
        r0 = _gate(tmp).run()
        assert r0.passed is False and any(i.rule == "prs_score" for i in r0.issues)

        bpath = os.path.join(tmp, "bl.json")
        _write_baseline_from_scan(tmp, bpath)

        gate = _gate(tmp, baseline=bpath)
        result = gate.run()
        assert result.passed is True, \
            f"baselined debt must be tolerated; issues={[ (i.file, i.rule) for i in result.issues ]}"
        assert not any(i.rule == "prs_score" for i in result.issues)
        assert not any(i.rule == "baseline_ratchet" for i in result.issues)
        assert result.stats.get("baseline_files_matched") == 2
        assert result.stats.get("baseline_ratchet_failed") == 0
        assert result.stats.get("baseline_new_files") == 0

        report = json.loads(gate.generate_json_report(result))
        assert report["baseline"]["status"] == "ok"
        assert report["baseline"]["matched"] == 2
        assert report["baseline"]["regressed"] == 0


def test_check_with_baseline_blocks_regression():
    """errors grew 1 -> 2 vs baseline: ERROR rule 'baseline_ratchet' naming the metric."""
    with tempfile.TemporaryDirectory() as tmp:
        _write(tmp, "bad.py", ERR_2E)  # current: 2 errors
        bpath = os.path.join(tmp, "bl.json")
        _manual_baseline(bpath, {
            "bad.py": {"prs": 90.0, "errors": 1, "warnings": 0, "vetoed": False},
        })
        result = _gate(tmp, baseline=bpath).run()
        assert result.passed is False
        ratchet = [i for i in result.issues if i.rule == "baseline_ratchet"]
        assert ratchet, "a regressed file must raise a 'baseline_ratchet' ERROR"
        assert any("errors 2 > baselined 1" in i.message for i in ratchet), \
            f"message must name the regressed metric; got {[i.message for i in ratchet]}"
        assert result.stats.get("baseline_ratchet_failed") == 1


def test_new_file_absent_from_baseline_must_meet_floor():
    """A new below-floor file fails via prs_score even when a baseline is loaded."""
    with tempfile.TemporaryDirectory() as tmp:
        _write(tmp, "debt.py", DEBT_8W)
        bpath = os.path.join(tmp, "bl.json")
        _write_baseline_from_scan(tmp, bpath)

        _write(tmp, "newbad.py", DEBT_10W)  # below floor, absent from baseline
        result = _gate(tmp, baseline=bpath).run()
        assert result.passed is False
        floor = [i for i in result.issues if i.rule == "prs_score"]
        assert floor and all(i.file.endswith("newbad.py") for i in floor), \
            f"only the new file fails the floor; got {[(i.file, i.rule) for i in result.issues]}"
        assert not any(i.rule == "baseline_ratchet" for i in result.issues)
        assert result.stats.get("baseline_new_files") == 1
        assert result.stats.get("baseline_files_matched") == 1


def test_comparison_is_per_file_and_order_independent():
    """Scanning [a,b] vs [b,a] yields identical verdicts (per-file dict lookup)."""
    with tempfile.TemporaryDirectory() as tmp:
        a = _write(tmp, "a.py", DEBT_8W)
        b = _write(tmp, "b.py", DEBT_8W)
        bpath = os.path.join(tmp, "bl.json")
        _write_baseline_from_scan(tmp, bpath)

        _write(tmp, "b.py", DEBT_10W)  # regress b only

        def run_with(paths):
            gate = _gate(tmp, baseline=bpath)
            return gate, gate.run(paths=paths)

        gate_ab, r_ab = run_with([a, b])
        gate_ba, r_ba = run_with([b, a])

        assert r_ab.passed == r_ba.passed is False
        key = lambda r: sorted((Path(i.file).name, i.rule) for i in r.issues)
        k_ab, k_ba = key(r_ab), key(r_ba)
        assert k_ab == k_ba, \
            f"file order changed the verdicts: {k_ab} vs {k_ba}"
        for r in (r_ab, r_ba):
            ratchet = [i for i in r.issues if i.rule == "baseline_ratchet"]
            assert len(ratchet) == 1 and ratchet[0].file.endswith("b.py")
            assert not any(i.rule == "prs_score" for i in r.issues)
        assert gate_ab.file_prs == gate_ba.file_prs


DUP_FN = (
    "def compute_total(items):\n"
    "    total = 0\n"
    "    for item in items:\n"
    "        total += item\n"
    "    return total\n"
)
WARN_LINE = "wx = 0  # type: " + "ignore\n"  # exactly one real warning


def test_cross_file_duplicate_warnings_do_not_flap_with_scan_order():
    """Cross-file duplicate attribution is load-bearing for the ratchet:
    the same file SET must give the same verdict in any scan order — no
    fabricated regression, and no real regression masked by the duplicate
    warning migrating onto another file's vacated headroom."""
    with tempfile.TemporaryDirectory() as tmp:
        x = _write(tmp, "x.py", DUP_FN)              # duplicate carrier
        y = _write(tmp, "y.py", DUP_FN + WARN_LINE)  # duplicate + 1 real warning
        bpath = os.path.join(tmp, "bl.json")
        _write_baseline_from_scan(tmp, bpath)

        def verdict(paths):
            result = _gate(tmp, baseline=bpath).run(paths=paths)
            ratchet = sorted(Path(i.file).name for i in result.issues
                             if i.rule == "baseline_ratchet")
            return result.passed, ratchet

        # (a) Unchanged files: every order passes (no fabricated regression).
        for paths in ([x, y], [y, x]):
            passed, ratchet = verdict(paths)
            assert passed is True and ratchet == [], \
                f"scan order fabricated a regression: {ratchet}"

        # (b) Fix y's real warning, add a real one to x: the duplicate
        # warning must not migrate onto y's vacated headroom and mask it.
        _write(tmp, "y.py", DUP_FN)
        _write(tmp, "x.py", DUP_FN + WARN_LINE)
        assert _gate(tmp, baseline=bpath).run().passed is False, \
            "authoritative full scan must see the regression (anti-vacuous)"
        for paths in ([x, y], [y, x]):
            passed, ratchet = verdict(paths)
            assert passed is False and ratchet == ["x.py"], \
                f"scan order masked a real regression: passed={passed} ratchet={ratchet}"


# ── Process layer: config overrides sit on the protected surface ─────

def test_engine_discovered_config_overrides_are_protected_surface():
    """Anti-regeneration layer (c) must not be bypassable by an UNPROTECTED
    config override redirecting baseline.path to a fabricated baseline:
    every config file the engine auto-discovers at the scan root must
    itself sit on the protected surface (CODEOWNERS)."""
    surface = QG_DIR.parent / "protected-surface.txt"
    assert surface.exists(), "engine repo must ship protected-surface.txt"
    entries = [
        ln.strip().split()[0]
        for ln in surface.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]

    def protected(rel: str) -> bool:
        for pat in entries:
            if rel == pat or (pat.endswith("/") and rel.startswith(pat)):
                return True
            if "/" not in pat and rel.rsplit("/", 1)[-1] == pat:
                return True  # bare filename: any depth (CODEOWNERS semantics)
        return False

    # Derive the auto-discovered override filenames from the engine source,
    # so adding a new unprotected discovery path fails this test too.
    src = QG_SCRIPT.read_text(encoding="utf-8")
    discovered = set(re.findall(r'self\.root_dir\s*/\s*"([^"]+\.json)"', src))
    assert discovered >= {".quality-gate.json", "quality-gate.config.json"}, \
        f"discovery-set extraction broke; got {discovered}"

    for name in sorted(discovered):
        assert protected(name), (
            f"engine auto-discovers '{name}' at the scan root but it is NOT "
            "on the protected surface — an unreviewed override there can "
            "redirect baseline.path to a fabricated baseline or gut the "
            "thresholds. Add it to protected-surface.txt and regenerate "
            "CODEOWNERS."
        )

    from qg.baseline import DEFAULT_BASELINE_FILENAME
    assert protected(DEFAULT_BASELINE_FILENAME), \
        "the baseline itself must stay on the protected surface"
    assert not protected("definitely-not-a-config.json"), \
        "protected() matcher is vacuous — it matches anything"


def test_vetoed_file_cannot_be_baselined_away():
    """A veto-rule finding still fails even with a matching baseline entry."""
    with tempfile.TemporaryDirectory() as tmp:
        _write(tmp, "veto.py", VETO_SRC)
        bpath = os.path.join(tmp, "bl.json")
        _manual_baseline(bpath, {
            "veto.py": {"prs": 0.0, "errors": 1, "warnings": 0, "vetoed": True},
        })
        gate = _gate(tmp, baseline=bpath)
        result = gate.run()
        assert gate.file_prs["veto.py"]["vetoed"] is True, \
            "fixture must actually trigger the veto (anti-vacuous)"
        assert result.passed is False, "a baseline must never mask a security veto"
        assert any(i.rule == "prs_score" and "VETOED" in i.message
                   for i in result.issues)


# ── ANTI-CASES: regeneration and write refusal ────────────────────────

def test_ci_env_refuses_baseline_write():
    """--mode baseline under CI env exits nonzero and writes nothing."""
    with tempfile.TemporaryDirectory() as tmp:
        _write(tmp, "clean.py", CLEAN)
        bpath = os.path.join(tmp, "bl.json")
        bfile = Path(bpath)
        base_env = _no_ci_env()

        for var in ("CI", "GITHUB_ACTIONS"):
            env = {**base_env, var: "true"}
            proc = _cli(["--root", tmp, "--mode", "baseline", "--baseline", bpath],
                        cwd=tmp, env=env)
            assert proc.returncode != 0, \
                f"{var}=true must refuse --mode baseline; stdout={proc.stdout!r}"
            assert not os.path.exists(bpath), \
                f"{var}=true must leave no baseline file behind"

        # An existing baseline must not be overwritten under CI either.
        bfile.write_bytes(b"SENTINEL")
        ci_env = {**base_env, "CI": "true"}
        proc = _cli(["--root", tmp, "--mode", "baseline", "--baseline", bpath],
                    cwd=tmp, env=ci_env)
        assert proc.returncode != 0
        assert bfile.read_bytes() == b"SENTINEL", \
            "CI refusal must leave the existing baseline byte-identical"

        # Explicit escape hatch: visible in any workflow diff (review-gated).
        proc = _cli(["--root", tmp, "--mode", "baseline", "--baseline", bpath,
                     "--allow-ci-baseline"], cwd=tmp, env=ci_env)
        assert proc.returncode == 0, \
            f"--allow-ci-baseline must permit the write; stderr={proc.stderr!r}"
        written = json.loads(bfile.read_text(encoding="utf-8"))
        assert written["version"] == 1 and "clean.py" in written["files"]


def test_check_mode_never_writes_baseline():
    """check/audit with --baseline leave the baseline file byte-identical."""
    with tempfile.TemporaryDirectory() as tmp:
        _write(tmp, "debt.py", DEBT_8W)
        bpath = os.path.join(tmp, "bl.json")
        _write_baseline_from_scan(tmp, bpath)
        bfile = Path(bpath)
        before = bfile.read_bytes()
        env = _no_ci_env()

        proc = _cli(["--root", tmp, "--mode", "check", "--baseline", bpath],
                    cwd=tmp, env=env)
        assert proc.returncode == 0, \
            f"tolerated debt must pass at the CLI; stdout={proc.stdout!r}"
        assert bfile.read_bytes() == before, "check mode must never write"

        proc = _cli(["--root", tmp, "--mode", "audit", "--json",
                     "--baseline", bpath], cwd=tmp, env=env)
        assert proc.returncode == 0, "audit mode keeps exit 0 (report-only)"
        report = json.loads(proc.stdout)
        assert report["baseline"]["status"] == "ok", \
            "JSON report must carry the additive 'baseline' block"
        assert bfile.read_bytes() == before, "audit mode must never write"


# ── Fail-closed loading ───────────────────────────────────────────────

def _assert_fails_closed(tmp: str, bfile: str, expected_rule: str, other_rule: str):
    result = _gate(tmp, baseline=bfile).run()
    assert result.passed is False, \
        f"{expected_rule}: unusable baseline must fail closed"
    assert any(i.rule == expected_rule for i in result.issues), \
        f"expected {expected_rule}; got {[i.rule for i in result.issues]}"
    assert not any(i.rule == other_rule for i in result.issues), \
        "corrupt and missing must stay distinct rules"


def test_corrupt_baseline_fails_closed_and_distinct_from_missing():
    """Malformed JSON -> 'baseline_unreadable'; explicit missing path -> 'baseline_missing'."""
    with tempfile.TemporaryDirectory() as tmp:
        _write(tmp, "clean.py", CLEAN)

        corrupt = os.path.join(tmp, "bl.json")
        Path(corrupt).write_text("{ this is not json", encoding="utf-8")
        absent = os.path.join(tmp, "absent.json")

        _assert_fails_closed(tmp, corrupt, "baseline_unreadable", "baseline_missing")
        _assert_fails_closed(tmp, absent, "baseline_missing", "baseline_unreadable")

        from qg.baseline import load_baseline
        assert load_baseline(absent) == (None, "missing")
        data, status = load_baseline(corrupt)
        assert data is None and status == "unreadable"


# ── Cross-platform key normalization (runs on POSIX CI too) ──────────

def test_backslash_paths_match_forward_slash_baseline_keys():
    """Windows backslash relpath keys must match '/' baseline keys (unit-level)."""
    from qg.baseline import compare_to_baseline
    file_prs = {
        "a\\b.py": {"score": 84.0, "display_score": "84.0", "min_score": 85,
                    "errors": 0, "warnings": 8, "vetoed": False},
    }
    baseline = {
        "version": 1,
        "files": {"a/b.py": {"prs": 84.0, "errors": 0, "warnings": 8, "vetoed": False}},
    }
    verdicts = compare_to_baseline(file_prs, baseline, 85)
    v = verdicts.get("a/b.py")
    assert v is not None, f"backslash key failed to normalize: {verdicts}"
    assert v["in_baseline"] is True, "'a\\\\b.py' must match baseline key 'a/b.py'"
    assert v["failed"] is False, "matching non-regressed entry must be tolerated"


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
