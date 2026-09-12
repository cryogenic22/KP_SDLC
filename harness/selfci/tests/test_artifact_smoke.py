"""The installed artifact actually works — the proof `-h` smoke never gave.

Issue #38: `pip install .` succeeded, `sdlc init` crashed with "engine_root has
no harness/ dir", and CI stayed green because the only install coverage was
entry-point `-h`. A green result has to prove the work executed, so this suite
drives the real binary out of a real wheel in a real venv, from a cwd outside
the checkout, and then plants a failure to prove the check is not vacuous.

It is deliberately not skippable. A conditional skip here would restore exactly
the silence that let #38 ship: the run would go green on a machine where the
artifact was never built.

Runtime is minutes, not seconds — it builds a wheel, creates a venv, and runs
the full born gate including the QG planted-red proof. That cost is the point.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_DRIVER = _ROOT / "harness" / "selfci" / "artifact_smoke.py"


def _load_driver():
    spec = importlib.util.spec_from_file_location("artifact_smoke", _DRIVER)
    module = importlib.util.module_from_spec(spec)
    sys.modules["artifact_smoke"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def smoke():
    return _load_driver()


@pytest.fixture(scope="module")
def installed(smoke, tmp_path_factory):
    """One wheel, one venv, shared by the checks below.

    Module-scoped because building and installing twice would double a
    multi-minute cost to prove nothing extra. The planted-negative check runs
    last and mutates the install, so it owns the teardown ordering by being the
    only test that writes to it.
    """
    workspace = tmp_path_factory.mktemp("artifact")
    wheel = smoke.build_wheel(_ROOT, workspace / "wheelhouse")
    venv = smoke.make_venv_with(wheel, workspace / "venv")
    return {"smoke": smoke, "workspace": workspace, "wheel": wheel, "venv": venv}


def test_wheel_carries_the_engine_payload(installed):
    """The wheel contains harness/ and the vendoring sources, not just packages."""
    import zipfile

    names = zipfile.ZipFile(installed["wheel"]).namelist()
    payload = [n for n in names if "/_payload/" in n]
    assert payload, "wheel carries no sdlc_init/_payload — the backend did not stage"

    # Spot-check one of each kind the old wheel was missing entirely.
    for probe in (
        "sdlc_init/_payload/harness/templates/CLAUDE.md.tmpl",
        "sdlc_init/_payload/harness/skills",
        "sdlc_init/_payload/quality-gate/quality-gate.config.json",
        "sdlc_init/_payload/cathedral-keeper/ck.py",
    ):
        assert any(n.startswith(probe) for n in names), f"wheel missing {probe}"


def test_payload_is_complete_against_the_harness_map(installed):
    """Every path `required_assets()` names is present in the installed package.

    This is the check that catches a template added to the map but not to the
    staging list, which is how a payload ships subtly incomplete.
    """
    smoke = installed["smoke"]
    package_dir = smoke.installed_payload_dir(installed["venv"])
    payload = package_dir / "_payload"
    assert payload.is_dir(), f"installed package has no _payload: {package_dir}"

    sys.path.insert(0, str(_ROOT / "sdlc-init"))
    try:
        from sdlc_init import engine_assets as ea
    finally:
        sys.path.pop(0)

    assert ea.missing_assets(payload) == []


def test_init_runs_from_outside_the_checkout(installed):
    """The #38 acceptance criterion, end to end."""
    smoke = installed["smoke"]
    workspace = installed["workspace"]
    manifest = smoke.check_init(
        installed["venv"], workspace / "outside", workspace / "born"
    )
    assert manifest["status"] == "ok"
    engine = manifest["engine"]
    assert engine["provenance"]["kind"] == "package"
    assert engine["provenance"]["payload_digest"].startswith("sha256:")
    assert engine["sha"] is None, "a released artifact must not invent a git SHA"
    assert engine["vendored"]["file_count"] > 0


def test_born_repo_carries_a_real_gate(installed):
    """The generated repo is born-gated, not merely populated."""
    born = installed["workspace"] / "born"
    manifest = json.loads((born / ".harness" / "manifest.json").read_text("utf-8"))
    phases = {p["name"]: p for p in manifest["phases"]}

    proof = phases.get("born_gated_proof")
    assert proof is not None, f"no born_gated_proof phase: {sorted(phases)}"
    assert proof["status"] == "ok", proof
    # The proof's own claim is that a planted fixture reddened QG. If that text
    # ever stops appearing, the gate has gone vacuous even though it is green.
    assert "planted" in proof.get("detail", ""), proof

    floor = phases.get("setup_floor")
    assert floor is not None and floor["status"] == "ok", floor
    assert (born / "tools" / "qa" / "quality-gate" / "quality_gate.py").is_file()


def test_bootstrap_runs_from_outside_the_checkout(installed):
    smoke = installed["smoke"]
    workspace = installed["workspace"]
    smoke.check_bootstrap(
        installed["venv"], workspace / "outside", workspace / "layered"
    )


def test_planted_missing_asset_makes_the_smoke_red(installed):
    """Remove one required asset; init must refuse and name it.

    Runs last: it mutates the shared install. Without this the six checks above
    would pass just as happily against a resolver that never verified anything.
    """
    smoke = installed["smoke"]
    workspace = installed["workspace"]
    message = smoke.check_planted_missing_asset(
        installed["venv"], workspace / "outside", workspace / "planted"
    )
    assert message  # check_planted_missing_asset raises on every failure mode
