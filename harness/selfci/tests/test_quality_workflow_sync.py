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


# ── Semantic predicates over the RENDERED workflow ────────────────────
# Assert the GUARANTEE (a real install command; a smoke loop that aggregates and
# exits nonzero), not merely that a label mentions it — so replacing the command
# with `true`, or `exit $rc` with `exit 0`, fails closed instead of passing.

# A real `pip install .[dev]` RUN line (indented, standalone). NOT the step's
# `name:` label, which also carries the text `(pip install .[dev])` but ends in a
# `)`, so the end-anchored match excludes it.
_INSTALL_RUN_RE = re.compile(r"(?m)^[ \t]+pip install \.\[dev\]\s*$")


def _smoke_step(workflow: str) -> str:
    """The 'Console entry points resolve (smoke)' step, sliced from its `- name:`
    header to the next 6-space-indented step boundary ('' if absent)."""
    marker = "- name: Console entry points resolve (smoke)"
    i = workflow.find(marker)
    if i == -1:
        return ""
    rest = workflow[i + len(marker):]
    nxt = re.search(r"\n      - ", rest)
    return rest[: nxt.start()] if nxt else rest


def _install_is_real(workflow: str) -> bool:
    """True iff the workflow runs `pip install .[dev]` as an actual command line,
    not only inside a step label."""
    return _INSTALL_RUN_RE.search(workflow) is not None


# The smoke step's load-bearing commands, as EXACT normalized (stripped) lines in
# required order: init, the -h probe, the `|| rc=1` aggregation and `exit $rc`.
# Substring membership was defeatable — `echo "exit $rc"` or `... || echo rc=1`
# keep the text but drop the effect. Exact standalone-line matching rejects both.
_SMOKE_REQUIRED_LINES = (
    "rc=0",
    "for cmd in sdlc-schemas rv ee g1 g2 kp-observatory; do",
    'if "$cmd" -h > /dev/null 2>&1; then ec=0; else ec=$?; fi',
    '[ "$ec" -eq 0 ] || rc=1',
    "exit $rc",
)


def _smoke_step_lines(workflow: str) -> list[str]:
    """Stripped, non-empty lines of the smoke step (its `- name:`/`run:` block)."""
    stripped = (ln.strip() for ln in _smoke_step(workflow).split("\n"))
    return [ln for ln in stripped if ln]


def _ordered_subsequence(required: tuple, lines: list) -> bool:
    """True iff every `required` entry appears as an EXACT line, in order."""
    it = iter(lines)
    return all(any(req == ln for ln in it) for req in required)


def _smoke_propagates_failure(workflow: str) -> bool:
    """True iff the smoke step has the exact init / `"$cmd" -h` / `|| rc=1` /
    `exit $rc` lines in order — so a masked variant (`exit 0`, echoed) fails."""
    return _ordered_subsequence(_SMOKE_REQUIRED_LINES, _smoke_step_lines(workflow))


def test_mechanical_installs_deps_before_smoke_and_suites():
    """The mechanical job must run a REAL `pip install .[dev]` command (the
    component suites run via `python -m pytest <dir>`, so a bare runner without
    pytest errors), and it must precede both the entry-point smoke and the
    blocking `make test`. Matching the actual run line — not the step's
    `(pip install .[dev])` label — means replacing the command with `true` fails
    this contract instead of passing on the label alone."""
    rendered = render(_tmpl_text())
    assert _install_is_real(rendered), (
        "mechanical job has no real `pip install .[dev]` run command "
        "(a step label mentioning it is not enough)"
    )
    install = _INSTALL_RUN_RE.search(rendered).start()
    smoke = rendered.find("Console entry points resolve (smoke)")
    make_test = rendered.find("run: make test")
    assert smoke != -1, "mechanical job never runs the entry-point smoke"
    assert make_test != -1, "mechanical job never runs `make test`"
    assert install < smoke < make_test, (
        "order must be install → smoke → `make test`; got positions "
        f"install={install}, smoke={smoke}, make_test={make_test}"
    )


def test_install_contract_rejects_masked_install():
    """Anti-case (teeth): replacing the real install command with `true` — while
    keeping the step label — must FAIL the real-install predicate (Major #2)."""
    rendered = render(_tmpl_text())
    assert _install_is_real(rendered)  # positive control
    masked = _INSTALL_RUN_RE.sub("          true", rendered, count=1)
    assert "pip install .[dev])" in masked, "label should survive (that is the trap)"
    assert not _install_is_real(masked), (
        "predicate accepted a workflow whose install command is `true` — it is "
        "matching the step label, not the command"
    )


def test_mechanical_smokes_gate_entrypoints():
    """The mechanical job must exercise the installed gate console entry points
    (sdlc-schemas/rv/ee/g1/g2/kp-observatory resolve) after install — a packaging
    break that leaves an entry point unresolvable is invisible to source-run unit
    tests — AND the loop must propagate failure (aggregate + nonzero exit)."""
    rendered = render(_tmpl_text())
    assert "Console entry points resolve (smoke)" in rendered
    assert "for cmd in sdlc-schemas rv ee g1 g2 kp-observatory" in rendered, (
        "entry-point smoke does not exercise all component console scripts "
        "(incl. kp-observatory, whose suite is fixture-only)"
    )
    assert _smoke_propagates_failure(rendered), (
        'smoke step does not aggregate + exit nonzero ("$cmd" -h, rc=1, '
        "exit $rc) — an unresolvable entry point would be masked"
    )


def test_smoke_contract_rejects_masked_failure():
    """Anti-case (teeth): every way to keep the smoke text but drop its EFFECT
    must FAIL the propagation predicate — a bare `exit 0`, an echoed exit
    (`echo "exit $rc"`), and an echoed aggregation (`|| echo rc=1`). The last two
    are the reviewer's escalation: substring membership passed them because the
    literal `exit $rc` / `rc=1` text survives inside the echo."""
    rendered = render(_tmpl_text())
    assert _smoke_propagates_failure(rendered)  # positive control
    for label, masked in (
        ("exit 0", rendered.replace("exit $rc", "exit 0")),
        ('echo "exit $rc"', rendered.replace("exit $rc", 'echo "exit $rc"')),
        ("|| echo rc=1", rendered.replace("|| rc=1", "|| echo rc=1")),
    ):
        assert not _smoke_propagates_failure(masked), (
            f"predicate accepted a smoke loop masked with `{label}` — it is "
            "matching text, not exact effect-bearing lines"
        )


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
