"""End-to-end tests for `sdlc init` — a fresh directory must become a
born-gated repo. Each test runs the real CLI against a temp target and
inspects the result; nothing is mocked (the point is that init actually
provisions).
"""

from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

# An unfilled harness placeholder — NOT GitHub Actions' own ${{ ... }} syntax.
_PLACEHOLDER = re.compile(r"\{\{[A-Z_]+\}\}")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sdlc_init.cli import main
from sdlc_init import engine_assets as ea
from sdlc_init import harness_map as hm

ENGINE = Path(__file__).resolve().parents[2]  # KP_SDLC checkout


def _combined(capsys) -> str:
    captured = capsys.readouterr()
    return captured.out + captured.err


def _init(target: Path, *extra: str) -> int:
    return main(["init", "--name", "Demo", "--owner", "@tester",
                 "--target", str(target), "--engine-root", str(ENGINE),
                 "--as-of", "2026-01-01", *extra])


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _workflows(t: Path) -> tuple[list[Path], list[Path]]:
    """(active, parked) workflow files under .github/ — one tree walk."""
    wfs = sorted((t / ".github").rglob("*.yml"))
    return ([p for p in wfs if p.parent == t / hm.WORKFLOWS_DEST],
            [p for p in wfs if p.parent == t / hm.WORKFLOWS_PARKED])


def test_init_produces_born_gated_repo():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        assert _init(t) == 0

        # Harness judgment layer, structural floor, and engine-pin manifest.
        for rel in (".claude/skills/design-philosophy/SKILL.md",
                    ".claude/commands/review.md",
                    "CLAUDE.md",
                    ".github/CODEOWNERS",
                    ".harness/manifest.json",
                    ".harness/init-journal.jsonl"):
            assert (t / rel).exists(), f"missing {rel}"

        # Placeholders filled — no {{...}} left in the operating contract.
        claude = _read(t / "CLAUDE.md")
        assert "Demo" in claude and "{{" not in claude

        # Structural floor owner-filled and protecting the gate config.
        surface = _read(t / "protected-surface.txt")
        assert "@tester" in surface and ".quality-gate.json" in surface


def test_config_workflows_parked_active_ones_live():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        _init(t)
        active_wfs, parked_wfs = _workflows(t)
        active = {p.name for p in active_wfs}
        parked = {p.name for p in parked_wfs}
        assert "structural-floor.yml" in active
        assert "second-pass-reviewer.yml" in active
        assert hm.CONFIG_WORKFLOWS <= parked, f"expected {hm.CONFIG_WORKFLOWS} parked, got {parked}"
        assert not (hm.CONFIG_WORKFLOWS & active), "a config workflow shipped active"


def test_no_active_workflow_carries_placeholder():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        _init(t)
        for wf in (t / hm.WORKFLOWS_DEST).glob("*.yml"):
            residual = _PLACEHOLDER.findall(wf.read_text(encoding="utf-8"))
            assert not residual, f"{wf.name} shipped with placeholders {residual}"


def test_manifest_records_engine_pin_and_phases():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        _init(t)
        m = json.loads((t / ".harness/manifest.json").read_text(encoding="utf-8"))
        assert m["project_name"] == "Demo"
        assert m["owner"] == "@tester"
        assert m["created"] == "2026-01-01"
        assert "sha" in m["engine"] and m["engine"]["sha"]  # a SHA or 'unknown'
        names = {p["name"] for p in m["phases"]}
        assert {"copy_harness", "setup_floor"} <= names
        assert all(p["status"] != "fail" for p in m["phases"])


def test_idempotent_rerun_adds_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        assert _init(t) == 0
        before = {p for p in t.rglob("*") if p.is_file()}
        assert _init(t) == 0  # second run must not crash or overwrite
        after = {p for p in t.rglob("*") if p.is_file()}
        # Only the append-only journal may grow.
        new = {p.relative_to(t).as_posix() for p in (after - before)}
        assert new <= {".harness/init-journal.jsonl"}, f"rerun created {new}"


def test_dry_run_writes_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        assert _init(t, "--dry-run") == 0
        written = [p for p in t.rglob("*") if p.is_file()]
        assert not written, f"dry-run wrote {written}"


def test_gitignore_shipped():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        _init(t)
        gi = (t / ".gitignore")
        assert gi.exists() and "__pycache__" in gi.read_text(encoding="utf-8")


def test_missing_name_noninteractive_errors():
    with tempfile.TemporaryDirectory() as tmp:
        try:
            main(["init", "--owner", "@tester", "--target", tmp,
                  "--engine-root", str(ENGINE)])
        except SystemExit as exc:
            assert exc.code != 0
            return
        raise AssertionError("missing --name should error in non-interactive mode")


def test_bootstrap_parks_but_leaves_name_placeholder():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        rc = main(["bootstrap", "--target", str(t), "--engine-root", str(ENGINE),
                   "--as-of", "2026-01-01"])
        assert rc == 0
        # Copy-only: name/owner remain for manual fill...
        assert "{{PROJECT_NAME}}" in (t / "CLAUDE.md").read_text(encoding="utf-8")
        # ...but the strict improvements still apply.
        assert (t / ".gitignore").exists()
        assert hm.CONFIG_WORKFLOWS <= {p.name for p in (t / hm.WORKFLOWS_PARKED).glob("*.yml")}


# ── Regressions from the adversarial review ──────────────────────────


def test_refuses_preexisting_codeowners_no_data_loss():
    """BLOCKER: init must not overwrite a hand-authored CODEOWNERS."""
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        (t / ".github").mkdir()
        original = "*.py @security-team\ndocs/ @docs-team\n"
        (t / ".github/CODEOWNERS").write_text(original, encoding="utf-8")
        rc = _init(t)
        assert rc == 2, "init should refuse a repo with a pre-existing CODEOWNERS"
        assert (t / ".github/CODEOWNERS").read_text(encoding="utf-8") == original, \
            "pre-existing CODEOWNERS was clobbered"


def test_refuses_preexisting_gating_file_no_vacuous_green():
    """MAJOR: a pre-existing CLAUDE.md must block init, not be silently skipped
    while the repo is reported gated."""
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        (t / "CLAUDE.md").write_text("# my own contract\n", encoding="utf-8")
        assert _init(t) == 2
        assert (t / "CLAUDE.md").read_text(encoding="utf-8") == "# my own contract\n"
        assert not (t / ".harness/manifest.json").exists(), "init provisioned despite conflict"


def test_nongating_files_do_not_block():
    """A pre-existing README/LICENSE is fine — only gating files block."""
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        (t / "README.md").write_text("hi\n", encoding="utf-8")
        assert _init(t) == 0
        assert (t / "README.md").read_text(encoding="utf-8") == "hi\n"  # untouched


def test_copied_shell_scripts_are_lf():
    """Finding 3: shipped .sh must be LF, or POSIX CI breaks on CRLF."""
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        _init(t)
        sh = (t / ".harness/hooks/red-flag-attestation.sh").read_bytes()
        assert b"\r\n" not in sh, "shell script shipped with CRLF line endings"


def test_manifest_has_overall_status():
    """Finding 7: manifest must self-describe success, not imply it by presence."""
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        _init(t)
        m = json.loads((t / ".harness/manifest.json").read_text(encoding="utf-8"))
        assert m["status"] == "ok"
        assert "\\" not in m["engine"]["source"], "engine source path not portable"


def test_raising_phase_becomes_fail_not_crash():
    """Finding 5: a phase that raises is recorded as fail and still journaled."""
    from sdlc_init.executor import InitContext, PhaseResult, run
    from sdlc_init.manifest import InitManifest
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        ctx = InitContext(
            manifest=InitManifest("D", "@t", t, ENGINE),
            harness_dir=ENGINE / "harness", as_of="2026-01-01",
            subs={}, dry_run=False, log=lambda _m: None,
        )
        def _boom(_c):
            raise RuntimeError("kaboom")
        results = run(ctx, [_boom])
        assert results[0].status == "fail" and "kaboom" in results[0].detail
        assert (t / ".harness/init-journal.jsonl").exists(), "journal not written after failure"


# ── E0.9: PreToolUse reuse-injector wiring ────────────────────────────


def test_born_repo_ships_pretooluse_hook():
    """E0.9: init must wire the reuse injector — .claude/settings.json parses,
    a PreToolUse hook command references .harness/hooks/reuse_injector.py, and
    the injector script itself ships."""
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        assert _init(t) == 0
        settings_path = t / ".claude/settings.json"
        assert settings_path.exists(), ".claude/settings.json not shipped"
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        entries = settings["hooks"]["PreToolUse"]
        handlers = [h for entry in entries for h in entry.get("hooks", [])]
        assert any(
            h.get("command") == "python"
            and h.get("args") == [
                "-P",
                "${CLAUDE_PROJECT_DIR}/.harness/hooks/reuse_injector.py",
            ]
            for h in handlers
        ), f"no cwd-independent PreToolUse injector handler: {handlers}"
        assert (t / ".harness/hooks/reuse_injector.py").exists(), \
            "injector script not shipped to .harness/hooks/"


def test_preexisting_user_settings_preserved():
    """E0.9: a user-owned .claude/settings.json must be byte-unchanged
    (skip-if-exists), and the skipped hook wiring must be surfaced in the
    copy_harness phase detail — not silently omitted."""
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        (t / ".claude").mkdir(parents=True)
        settings_file = t / ".claude/settings.json"
        sentinel = b'{"hooks": {}, "sentinel": "user-owned"}\n'
        settings_file.write_bytes(sentinel)
        assert _init(t) == 0
        assert settings_file.read_bytes() == sentinel, \
            "user-owned settings.json was modified"
        m = json.loads((t / ".harness/manifest.json").read_text(encoding="utf-8"))
        copy = next(p for p in m["phases"] if p["name"] == "copy_harness")
        assert "settings.json" in copy["detail"] and "skip" in copy["detail"].lower(), \
            f"skipped hook wiring not surfaced in phase detail: {copy['detail']!r}"


# ── Wire-and-un-park: the engine-gates workflow is ACTIVE from birth ──


def test_engine_gates_workflow_active_and_placeholder_free():
    """engine-gates.yml (QG+CK on the vendored tools/qa engines) must ship
    active — it carries only {{BOOTSTRAP_DATE}}, which init always fills —
    while the stack-conditional workflows stay parked."""
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        assert _init(t) == 0
        workflows = [p for p in (t / ".github").rglob("*.yml")]
        active = {p.name for p in workflows if p.parent == t / hm.WORKFLOWS_DEST}
        parked = {p.name for p in workflows if p.parent == t / hm.WORKFLOWS_PARKED}
        assert "engine-gates.yml" in active, f"engine-gates.yml not active: {active}"
        assert "engine-gates.yml" not in parked, "engine-gates.yml was parked"
        assert "engine-gates.yml" not in hm.CONFIG_WORKFLOWS, (
            "engine-gates.yml must not be classified as a config workflow")
        assert hm.CONFIG_WORKFLOWS <= parked, f"expected {hm.CONFIG_WORKFLOWS} parked"
        assert not (hm.CONFIG_WORKFLOWS & active), "a config workflow shipped active"
        text = (t / hm.WORKFLOWS_DEST / "engine-gates.yml").read_text(encoding="utf-8")
        assert not _PLACEHOLDER.findall(text), "engine-gates.yml shipped a placeholder"
        assert "2026-01-01" in text, "{{BOOTSTRAP_DATE}} was not filled"


def test_bootstrap_parks_engine_gates_no_red_ci():
    """Bootstrap is copy-only — it never vendors tools/qa/, so engine-gates.yml
    (which invokes exactly those vendored engines) must be parked there, not
    active. Shipping it active guarantees a red first CI run ("can't open file
    tools/qa/quality-gate/quality_gate.py"). Anti-case: NO active workflow in a
    bootstrapped repo may reference the never-installed tools/qa/ engines."""
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        rc = main(["bootstrap", "--target", str(t), "--engine-root", str(ENGINE),
                   "--as-of", "2026-01-01"])
        assert rc == 0
        assert not (t / "tools/qa").exists(), "bootstrap must stay copy-only (no vendor)"
        active = {p.name for p in (t / hm.WORKFLOWS_DEST).glob("*.yml")}
        parked = {p.name for p in (t / hm.WORKFLOWS_PARKED).glob("*.yml")}
        assert "engine-gates.yml" not in active, (
            "bootstrap shipped engine-gates.yml active without vendoring the "
            "engines it runs — every bootstrapped repo's first push is red CI")
        assert "engine-gates.yml" in parked, f"engine-gates.yml not parked: {parked}"
        for wf in sorted((t / hm.WORKFLOWS_DEST).glob("*.yml")):
            assert "tools/qa/" not in wf.read_text(encoding="utf-8"), (
                f"active workflow {wf.name} references tools/qa/, which "
                f"bootstrap never installs")


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


# ── Review of #40, folding in #41 ────────────────────────────────────────────
#
# A phase that cannot install what the map declares must say so. Before this,
# `_install_files` skipped a missing source silently, so `sdlc init` exited 0
# and wrote a manifest claiming success for a repo with no CLAUDE.md in it.
# Driven through `main()` rather than by constructing a phase context, so what
# is proved is the behaviour of the command a user actually runs.

def _engine_copy(dest: Path) -> Path:
    """A complete, writable engine root that init can be pointed at."""
    for component in ("harness", "quality-gate", "cathedral-keeper"):
        shutil.copytree(ENGINE / component, dest / component,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return dest


def _init_from(engine: Path, target: Path) -> int:
    return main(["init", "--name", "Demo", "--owner", "@tester",
                 "--target", str(target), "--engine-root", str(engine),
                 "--as-of", "2026-01-01"])


def test_a_complete_engine_root_still_succeeds(tmp_path):
    """The planted failures below are only meaningful if the clean case passes."""
    engine = _engine_copy(tmp_path / "engine")
    assert _init_from(engine, tmp_path / "born") == 0
    assert (tmp_path / "born" / "CLAUDE.md").is_file()


def test_missing_mapped_template_fails_init_and_writes_nothing(tmp_path):
    """Issue #41: the reported symptom was exit 0 with no CLAUDE.md written.

    The pre-flight refuses before any phase runs, and it does so by raising
    rather than returning -- an unusable engine root must stop the command, not
    hand back a status a caller could ignore.
    """
    engine = _engine_copy(tmp_path / "engine")
    (engine / "harness" / "templates" / "CLAUDE.md.tmpl").unlink()
    target = tmp_path / "born"

    with pytest.raises(SystemExit) as excinfo:
        _init_from(engine, target)

    assert "harness/templates/CLAUDE.md.tmpl" in str(excinfo.value)
    assert not (target / "CLAUDE.md").exists()


def test_copy_harness_refuses_even_with_the_preflight_disabled(tmp_path,
                                                               capsys,
                                                               monkeypatch):
    """The #41 experiment, as a test.

    `missing_assets()` normally catches an absent source before any phase runs.
    Mutating it to a no-op is how the defect was found: init then ran to
    completion and reported `ok`. The copy phase must refuse on its own.
    """
    engine = _engine_copy(tmp_path / "engine")
    (engine / "harness" / "templates" / "CLAUDE.md.tmpl").unlink()
    monkeypatch.setattr(ea, "missing_assets", lambda root: [])
    target = tmp_path / "born"

    assert _init_from(engine, target) != 0
    output = _combined(capsys)
    assert "copy_harness" in output
    assert "harness/templates/CLAUDE.md.tmpl" in output
    assert not (target / "CLAUDE.md").exists()


def test_an_empty_mapped_directory_fails_init(tmp_path, capsys, monkeypatch):
    """A mapped directory that exists but holds nothing copies nothing.

    Distinct from an absent one: `Path.exists()` is true for an empty
    `harness/commands/` and a full one alike, so the fan-out produced a repo
    with no commands and reported `ok`.
    """
    engine = _engine_copy(tmp_path / "engine")
    for stale in (engine / "harness" / "commands").iterdir():
        stale.unlink()
    monkeypatch.setattr(ea, "missing_assets", lambda root: [])

    assert _init_from(engine, tmp_path / "born") != 0
    assert "harness/commands/" in _combined(capsys)
