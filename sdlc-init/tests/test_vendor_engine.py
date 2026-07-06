"""A freshly init'd repo must actually RUN the engine gates from birth:
`sdlc init` vendors the QG+CK engines into tools/qa/ (byte-identical,
hashed into the manifest), ships root configs that wire them, activates
the engine-gates workflow, and proves the gate fires before declaring
success (clean scan green, planted fixture red, CK smoke ok).

Each guarantee has its anti-case: byte-copy vs substitution corruption,
'tools/qa/**' vs the '**/'-prefixed exclude that silently fails fnmatch,
and a proof phase that fails closed when the gate cannot run.
"""

from __future__ import annotations

import atexit
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# The vendored tree must stay byte-exact (manifest sha256 record): keep the
# subprocess runs here from littering it with __pycache__.
_NO_BYTECODE_ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sdlc_init import harness_map as hm
from sdlc_init import phases as ph
from sdlc_init.cli import main
from sdlc_init.executor import InitContext
from sdlc_init.manifest import InitManifest

ENGINE = Path(__file__).resolve().parents[2]  # KP_SDLC checkout


def _init(target: Path, *extra: str) -> int:
    return main(["init", "--name", "Demo", "--owner", "@tester",
                 "--target", str(target), "--engine-root", str(ENGINE),
                 "--as-of", "2026-01-01", *extra])


_shared: list[Path] = []  # one fully-init'd repo, shared by read-only tests


def _born_repo() -> Path:
    """Init once and reuse: every init runs the born-gated proof (two QG
    subprocess scans + a CK run), so re-provisioning per test would multiply
    the suite's subprocess cost without adding coverage."""
    if not _shared:
        tmp = Path(tempfile.mkdtemp(prefix="sdlc-vendor-"))
        atexit.register(shutil.rmtree, tmp, ignore_errors=True)
        rc = _init(tmp)
        assert rc == 0, f"sdlc init failed with rc={rc} — cannot provision the shared repo"
        _shared.append(tmp)
    return _shared[0]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_vendored_engine_installed():
    """Both engines land under tools/qa/ — code and config, but never
    caches, tests, or the stray Windows-reserved 'nul' file."""
    t = _born_repo()
    for rel in (
        "tools/qa/quality-gate/quality_gate.py",
        "tools/qa/quality-gate/qg/prs_engine.py",
        "tools/qa/quality-gate/quality-gate.config.json",
        "tools/qa/cathedral-keeper/ck.py",
        "tools/qa/cathedral-keeper/cathedral_keeper/runner.py",
        "tools/qa/cathedral-keeper/cathedral-keeper.config.json",
    ):
        assert (t / rel).is_file(), f"vendored file missing: {rel}"
    qa = t / "tools/qa"
    assert not list(qa.glob("**/__pycache__")), "__pycache__ was vendored"
    assert not [p for p in qa.glob("**/tests") if p.is_dir()], "a tests/ dir was vendored"
    assert not [p for p in qa.rglob("*") if p.name == "nul"], "stray 'nul' file vendored"


def test_vendored_files_byte_identical_and_hashed():
    """Byte-copy guarantee: no placeholder substitution or LF-forcing may
    touch vendored code (SHA integrity), and the manifest records the pin."""
    t = _born_repo()
    src_digest = _sha256(ENGINE / "quality-gate/quality_gate.py")
    assert _sha256(t / "tools/qa/quality-gate/quality_gate.py") == src_digest, (
        "vendored quality_gate.py is not byte-identical to the engine source — "
        "the copy path corrupted it (substitution/newline translation)")
    rec = _load_json(t / ".harness/manifest.json")["engine"]["vendored"]
    assert rec["path"] == "tools/qa"
    assert rec["sha256"], "manifest engine.vendored.sha256 missing"
    disk_count = sum(1 for p in (t / "tools/qa").rglob("*") if p.is_file())
    assert rec["file_count"] == len(rec["files"]) == disk_count, (
        f"vendored-file record ({rec['file_count']}) does not match disk ({disk_count})")
    assert rec["files"]["tools/qa/quality-gate/quality_gate.py"] == src_digest


def test_shipped_configs_wire_the_vendored_engine():
    """Deep-merge REPLACES lists, so the shipped overrides must restate the
    portable default excludes; and the self-exclude must be the literally
    anchored 'tools/qa/**' (the '**/'-prefixed variant silently fails fnmatch)."""
    t = _born_repo()
    qg_cfg = _load_json(t / ".quality-gate.json")
    excl = qg_cfg["paths"]["exclude"]
    assert "tools/qa/**" in excl, "QG override lacks the tools/qa/** self-exclude"
    assert "**/tools/qa/**" not in excl, "'**/tools/qa/**' silently fails fnmatch"
    for default in ("**/node_modules/**", "**/__pycache__/**", "**/.venv/**"):
        assert default in excl, f"{default} lost — lists replace, defaults must be restated"

    ck_cfg = _load_json(t / ".cathedral-keeper.json")
    qg_path = ck_cfg["integrations"]["quality_gate"]["qg_path"]
    assert qg_path == "tools/qa/quality-gate/quality_gate.py", (
        f"CK integration points at {qg_path!r}, not the vendored QG")
    ck_excl = ck_cfg["paths"]["exclude"]
    assert "tools/qa/**" in ck_excl and "**/tools/qa/**" not in ck_excl
    for default in ("**/node_modules/**", "**/__pycache__/**", "**/.venv/**"):
        assert default in ck_excl, f"{default} lost — lists replace, defaults must be restated"


def test_target_scan_green_and_engine_excluded():
    """Anti-vacuous + anti-self-flag: the born repo scans green, files WERE
    checked, and the vendored engine never flags itself."""
    t = _born_repo()
    root = str(t)
    proc = subprocess.run(
        [sys.executable, str(t / "tools/qa/quality-gate/quality_gate.py"),
         "--root", root, "--config", str(t / ".quality-gate.json"), "--json"],
        capture_output=True, text=True, cwd=root, env=_NO_BYTECODE_ENV)
    assert proc.returncode == 0, (
        f"born repo is not green: QG exit {proc.returncode}\n{proc.stdout[-2000:]}")
    data = json.loads(proc.stdout)
    assert data["stats"]["files_checked"] > 0, "QG checked nothing — vacuous green"
    flagged = [i.get("file", "") for i in data.get("issues", [])] + list(data.get("prs", {}))
    self_flagged = sorted({f for f in flagged
                           if f.replace("\\", "/").startswith("tools/qa/")})
    assert not self_flagged, f"vendored engine scanned itself: {self_flagged[:5]}"


def test_shipped_config_excludes_root_level_artifact_dirs():
    """The fnmatch anchor gotcha applies to artifact/env dirs too: a
    '**/node_modules/**' pattern never matches a ROOT-level node_modules/x.py
    (fnmatch needs a literal '/' before 'node_modules'), so a JS/TS target that
    runs `npm ci` in CI would have its whole root node_modules scanned by the
    always-on engine gate — day-1 red CI, defeating green-from-birth. The
    shipped config must carry the root-anchored twins (node_modules/**, dist/**,
    ...) beside the '**/'-prefixed forms, exactly as tools/qa/** is anchored."""
    t = _born_repo()
    qg = t / "tools/qa/quality-gate/quality_gate.py"
    artifact_dirs = ["node_modules", "dist", "build", ".next", "coverage", ".venv", "venv"]
    with tempfile.TemporaryDirectory() as tmp:
        scan = Path(tmp)
        shutil.copy(t / ".quality-gate.json", scan / ".quality-gate.json")
        (scan / "app.py").write_text("x = 1\n", encoding="utf-8")  # clean root file
        for d in artifact_dirs:
            pkg = scan / d / "pkg"
            pkg.mkdir(parents=True)
            # Known-bad content: if the dir is scanned it trips >=2 errors (exit 1).
            (pkg / "bad.py").write_text(ph.bad_fixture_source(), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(qg), "--root", str(scan),
             "--config", str(scan / ".quality-gate.json"), "--json"],
            capture_output=True, text=True, cwd=str(scan), env=_NO_BYTECODE_ENV)
        data = json.loads(proc.stdout)
        flagged = [i.get("file", "") for i in data.get("issues", [])] + list(data.get("prs", {}))
        leaked = sorted({f.replace("\\", "/") for f in flagged
                         if any(f"{d}/" in f.replace("\\", "/") for d in artifact_dirs)})
        assert not leaked, (
            "root-level artifact dirs were scanned — the '**/'-prefixed excludes "
            f"miss root-level paths, needs the anchored twins: {leaked}")
        assert proc.returncode == 0, (
            f"born repo not green with root-level artifact dirs present: QG exit "
            f"{proc.returncode}\n{proc.stdout[-1500:]}")


def test_ck_runs_with_shipped_config():
    """CK config-discovery smoke (friction-log row 4): CK runs green with the
    shipped .cathedral-keeper.json, finds the vendored QG, and never flags
    vendored engine code."""
    t = _born_repo()
    root = str(t)
    proc = subprocess.run(
        [sys.executable, str(t / "tools/qa/cathedral-keeper/ck.py"),
         "analyze", "--root", root],
        capture_output=True, text=True, cwd=root, env=_NO_BYTECODE_ENV)
    assert proc.returncode == 0, (
        f"CK smoke failed: exit {proc.returncode}\n{proc.stderr[-1000:]}")
    report_path = t / ".quality-reports/cathedral-keeper/report.json"
    assert report_path.exists(), "CK wrote no report.json"
    findings = _load_json(report_path).get("findings", [])
    assert not [f for f in findings if "Quality Gate script not found" in f.get("title", "")], (
        "CK could not find the vendored QG — qg_path is miswired")
    evidence_paths: list[str] = []
    for f in findings:
        evidence_paths.extend(str(ev.get("file", "")).replace("\\", "/")
                              for ev in f.get("evidence", []) or [])
    self_flagged = [p for p in evidence_paths if p.startswith("tools/qa/")]
    assert not self_flagged, f"CK flagged vendored engine code: {self_flagged[:5]}"


def test_born_gated_proof_recorded():
    """The proof phase must journal its discrimination pair (clean scan green,
    planted fixture caught with exit 1) and leave no fixture residue."""
    t = _born_repo()
    m = _load_json(t / ".harness/manifest.json")
    proof = next((p for p in m["phases"] if p["name"] == "born_gated_proof"), None)
    assert proof is not None, "born_gated_proof phase not recorded in the manifest"
    assert proof["status"] == "ok", f"proof did not pass: {proof}"
    assert "clean scan green" in proof["detail"], f"no green-side evidence: {proof['detail']!r}"
    assert "exit 1" in proof["detail"], f"no red-side evidence: {proof['detail']!r}"
    assert not (t / ".harness/proof/born_gated_fixture.py").exists(), (
        "planted fixture left behind in the target tree")


def test_born_gated_proof_fails_closed_when_gate_missing():
    """THE anti-case: a proof that cannot run must not pass — and a repo that
    is not green at birth must fail init entirely (exit 1), not report ok."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        # (a) direct phase call on a target with no vendored gate → 'fail'
        no_gate = base / "no-gate"
        no_gate.mkdir()
        ctx = InitContext(
            manifest=InitManifest("Demo", "@tester", no_gate, ENGINE),
            harness_dir=ENGINE / "harness", as_of="2026-01-01",
            subs={}, dry_run=False, log=lambda _m: None)
        result = ph.born_gated_proof(ctx)
        assert result.status == "fail", (
            f"proof passed without a runnable gate: {result.status} — vacuous green")
        # (b) end-to-end: pre-existing failing code makes the clean scan red,
        # so cmd_init must exit 1 (a gate that fires at birth is not green-born).
        red_at_birth = base / "red-at-birth"
        red_at_birth.mkdir()
        (red_at_birth / "app.py").write_text(ph.bad_fixture_source(), encoding="utf-8")
        assert _init(red_at_birth) == 1, "cmd_init must exit 1 when born_gated_proof fails"


if __name__ == "__main__":
    passed = failed = 0
    tests = [(n, o) for n, o in sorted(globals().items())
             if n.startswith("test_") and callable(o)]
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
