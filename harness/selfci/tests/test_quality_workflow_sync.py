"""KP_SDLC dogfood: .github/workflows/quality.yml must be exactly what
harness/selfci/gen_quality_workflow.py renders from harness/ci/quality.yml.tmpl
+ ENGINE_PROFILE.

If test_committed_workflow_matches_render fails, the single-source pair has
drifted: run `python harness/selfci/gen_quality_workflow.py` and commit the
regenerated .github/workflows/quality.yml (never hand-edit the workflow).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[1]))  # harness/selfci (gen_quality_workflow.py)
_ROOT = _HERE.parents[3]                    # repo root

from gen_quality_workflow import ENGINE_PROFILE, check_sync, render

_TMPL = _ROOT / "harness" / "ci" / "quality.yml.tmpl"
_WORKFLOW = _ROOT / ".github" / "workflows" / "quality.yml"

# Same placeholder shape sdlc-init's executor guards against (executor.py).
_PLACEHOLDER = re.compile(r"\{\{[A-Z0-9_]+\}\}")


def _tmpl_text() -> str:
    """Tmpl text, CRLF-normalized (Windows checkouts under core.autocrlf)."""
    return _TMPL.read_text(encoding="utf-8").replace("\r\n", "\n")


def test_committed_workflow_matches_render():
    """The committed workflow equals the render, byte-for-byte modulo CRLF
    checkout translation — and the render itself is LF-only (CRLF in a .yml
    breaks POSIX CI)."""
    assert _WORKFLOW.exists(), (
        f"missing {_WORKFLOW} — run `python harness/selfci/gen_quality_workflow.py`"
    )
    rendered = render(_tmpl_text())
    assert "\r" not in rendered, "render() must emit LF-only output"
    on_disk = _WORKFLOW.read_bytes().decode("utf-8").replace("\r\n", "\n")
    assert on_disk == rendered, (
        ".github/workflows/quality.yml is OUT OF SYNC with quality.yml.tmpl + "
        "ENGINE_PROFILE — run `python harness/selfci/gen_quality_workflow.py` "
        "and commit the result"
    )


def test_check_mode_fails_on_tamper():
    """Anti-case (no vacuous green): check_sync must accept the exact render
    and reject a single flipped byte."""
    tmpl = _tmpl_text()
    rendered = render(tmpl)
    in_sync, _ = check_sync(tmpl, rendered)
    assert in_sync, "check_sync rejects its own exact render — gate is broken"

    mid = len(rendered) // 2
    flip = "#" if rendered[mid] != "#" else "@"
    tampered = rendered[:mid] + flip + rendered[mid + 1:]
    in_sync, msg = check_sync(tmpl, tampered)
    assert not in_sync, "check_sync accepted a tampered workflow — vacuous gate"
    assert msg, "check_sync must explain the drift, not fail silently"


def test_surface_job_verbatim_from_tmpl():
    """The rendered 'surface' job is the tmpl's surface job verbatim — this
    guards the single-source claim itself, independently of the generator's
    own slicing logic (the slice here is computed by this test, not by
    gen_quality_workflow)."""
    tmpl = _tmpl_text()
    idx = tmpl.index("\n  surface:")
    block = tmpl[idx + 1:]
    # Non-vacuous slice: it must be the real surface job, not an empty tail.
    assert block.startswith("  surface:"), "test's own tmpl slice is broken"
    assert "actions/github-script@v7" in block, "tmpl surface job lost its comment step"
    rendered = render(tmpl)
    assert block in rendered, (
        "rendered workflow's surface job is not verbatim-equal to the tmpl's "
        "surface job — the single-source claim is broken"
    )


def test_no_residual_placeholders_in_render():
    """No {{PLACEHOLDER}} survives into the rendered workflow (mirrors the
    sdlc-init executor's residual-placeholder anti-case)."""
    tmpl = _tmpl_text()
    # Anti-case first: the scanner must actually fire on the tmpl, which is
    # known to carry placeholders — otherwise this test is vacuous.
    assert _PLACEHOLDER.search(tmpl), (
        "placeholder scanner found nothing in the tmpl — scanner is vacuous"
    )
    rendered = render(tmpl)
    leftovers = sorted(set(_PLACEHOLDER.findall(rendered)))
    assert not leftovers, f"rendered workflow carries unfilled placeholders: {leftovers}"


def test_engine_paths_not_vendor_paths():
    """The engine render must call engine-repo paths, never the tools/qa/**
    vendor convention or the tmpl's uv-based steps that cannot run here."""
    rendered = render(_tmpl_text())
    assert ENGINE_PROFILE["INCLUDE_PROCESS"] is True, (
        "E0.3 shipped check_pr_template.py — the engine process job must be on"
    )
    assert "python harness/process/check_pr_template.py" in rendered
    assert ".github/scripts/check_pr_template.py" not in rendered
    assert "tools/qa/" not in rendered
    # E0.6: QG is blocking (check mode against the committed baseline);
    # a rendered audit-mode QG step would be a silent un-flip.
    assert (
        "python quality-gate/quality_gate.py --root . --mode check"
        " --baseline .quality-gate.baseline.json" in rendered
    )
    assert "--mode audit" not in rendered
    assert "python cathedral-keeper/ck.py analyze --root . --blast-radius --verbose" in rendered
    # E0.6: CK is blocking too — the workflow's last continue-on-error
    # mask is gone (only SARIF/artifact uploads may keep it).
    assert ENGINE_PROFILE["CK_BLOCKING"] is True
    assert "Cathedral Keeper (architecture, report-only)" not in rendered
    assert "uv sync" not in rendered
    assert "python harness/selfci/gen_quality_workflow.py --check" in rendered


def test_selfci_surface_is_qg_error_free():
    """The self-CI code must not itself add Quality Gate errors: E0.6 commits
    the QG baseline next, and an error born in the very PR that installs QG
    as self-CI would be enshrined in that baseline (Clean-as-You-Code)."""
    proc = subprocess.run(
        [
            sys.executable, str(_ROOT / "quality-gate" / "quality_gate.py"),
            "--root", str(_HERE.parents[1]), "--mode", "audit", "--json",
        ],
        capture_output=True, encoding="utf-8", errors="replace",
    )
    assert proc.returncode == 0, (
        f"QG audit of harness/selfci exited {proc.returncode}:\n{proc.stderr}"
    )
    data = json.loads(proc.stdout)
    # Anti-case: an empty scan would be vacuously green — require the
    # generator plus both test files to have actually been checked.
    files_checked = data["stats"]["files_checked"]
    assert files_checked >= 3, (
        f"QG scanned only {files_checked} file(s) under harness/selfci — vacuous"
    )
    errors = [i for i in data["issues"] if i.get("severity") == "error"]
    assert not errors, (
        "harness/selfci carries QG errors that E0.6's baseline would enshrine:\n"
        + "\n".join(
            f"  {i['file']}:{i['line']} {i['rule']} — {i['message']}"
            for i in errors
        )
    )


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
