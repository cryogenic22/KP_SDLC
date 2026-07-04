"""End-to-end tests for `sdlc init` — a fresh directory must become a
born-gated repo. Each test runs the real CLI against a temp target and
inspects the result; nothing is mocked (the point is that init actually
provisions).
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

# An unfilled harness placeholder — NOT GitHub Actions' own ${{ ... }} syntax.
_PLACEHOLDER = re.compile(r"\{\{[A-Z_]+\}\}")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sdlc_init.cli import main
from sdlc_init import harness_map as hm

ENGINE = Path(__file__).resolve().parents[2]  # KP_SDLC checkout


def _init(target: Path, *extra: str) -> int:
    return main(["init", "--name", "Demo", "--owner", "@tester",
                 "--target", str(target), "--engine-root", str(ENGINE),
                 "--as-of", "2026-01-01", *extra])


def test_init_produces_born_gated_repo():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        assert _init(t) == 0

        # Harness judgment layer installed.
        assert (t / ".claude/skills/design-philosophy/SKILL.md").exists()
        assert (t / ".claude/commands/review.md").exists()
        assert (t / "CLAUDE.md").exists()

        # Placeholders filled — no {{...}} left in the operating contract.
        claude = (t / "CLAUDE.md").read_text(encoding="utf-8")
        assert "Demo" in claude and "{{" not in claude

        # Structural floor generated and in sync.
        assert (t / ".github/CODEOWNERS").exists()
        surface = (t / "protected-surface.txt").read_text(encoding="utf-8")
        assert "@tester" in surface and ".quality-gate.json" in surface

        # Engine pinned in the manifest.
        assert (t / ".harness/manifest.json").exists()
        assert (t / ".harness/init-journal.jsonl").exists()


def test_config_workflows_parked_active_ones_live():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        _init(t)
        active = {p.name for p in (t / hm.WORKFLOWS_DEST).glob("*.yml")}
        parked = {p.name for p in (t / hm.WORKFLOWS_PARKED).glob("*.yml")}
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
