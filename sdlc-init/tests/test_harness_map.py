"""Guard the single-source harness map against drift: every source it names
must exist in harness/, and every parked config-workflow must be a real CI
template. If someone renames or moves a template, these fail loudly instead of
init silently shipping a broken repo.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sdlc_init import harness_map as hm

HARNESS = Path(__file__).resolve().parents[2] / "harness"


def test_file_map_sources_exist():
    missing = [src for src, _ in hm.FILE_MAP if not (HARNESS / src).is_file()]
    assert not missing, f"FILE_MAP names non-existent harness sources: {missing}"


def test_dir_map_sources_exist():
    missing = [src for src, _ in hm.DIR_MAP if not (HARNESS / src).is_dir()]
    assert not missing, f"DIR_MAP names non-existent harness dirs: {missing}"


def test_config_workflows_are_real_ci_templates():
    ci = HARNESS / "ci"
    available = {p.name[:-5] for p in ci.glob("*.tmpl")}
    unknown = hm.CONFIG_WORKFLOWS - available
    assert not unknown, f"CONFIG_WORKFLOWS names non-existent workflows: {unknown}"


def test_every_placeholder_carrying_workflow_is_parked():
    """Reverse completeness (Finding 6): any CI template with a non-date
    placeholder must be in CONFIG_WORKFLOWS, or init would ship it active with
    an unfilled placeholder (caught only at runtime otherwise)."""
    import re
    placeholder = re.compile(r"\{\{[A-Z0-9_]+\}\}")
    for tmpl in (HARNESS / "ci").glob("*.tmpl"):
        names = set(placeholder.findall(tmpl.read_text(encoding="utf-8")))
        needs_config = names - {"{{BOOTSTRAP_DATE}}"}  # date is always substituted
        if needs_config:
            wf = tmpl.name[:-5]
            assert wf in hm.CONFIG_WORKFLOWS, (
                f"{wf} carries {needs_config} but is not in CONFIG_WORKFLOWS — "
                f"it would ship active with unfilled placeholders"
            )


def test_engine_vendor_map_sources_exist():
    """Vendor-map drift guard (mirrors test_file_map_sources_exist): every
    vendor source must exist under the ENGINE ROOT — note these are relative
    to the engine checkout, not to harness/."""
    engine = HARNESS.parent
    missing = [src for src, _ in hm.ENGINE_VENDOR_MAP if not (engine / src).is_file()]
    missing += [src for src, _ in hm.ENGINE_VENDOR_DIRS if not (engine / src).is_dir()]
    assert not missing, f"vendor map names non-existent engine sources: {missing}"


def test_engine_gates_tmpl_single_sources_gate_commands():
    """The engine-gates workflow and the born_gated_proof phase must run the
    IDENTICAL command lines — both consume the harness_map constants, so the
    local proof and the CI gate cannot drift apart."""
    tmpl = (HARNESS / "ci" / "engine-gates.yml.tmpl").read_text(encoding="utf-8")
    assert f"run: {hm.QG_GATE_CMD}" in tmpl, (
        "engine-gates.yml.tmpl QG step does not match harness_map.QG_GATE_CMD")
    assert f"run: {hm.CK_GATE_CMD}" in tmpl, (
        "engine-gates.yml.tmpl CK step does not match harness_map.CK_GATE_CMD")
    # The vendored QG defaults its root to tools/qa (script_dir.parent), which
    # mis-anchors excludes and root-config discovery — '--root .' is mandatory.
    assert "--root ." in hm.QG_GATE_CMD, "QG gate command lost the '--root .' anchor"
    assert "--config .quality-gate.json" in hm.QG_GATE_CMD


def test_skills_source_exists():
    assert (HARNESS / hm.SKILLS_SRC).is_dir()


def test_substitutions_cover_name_owner_date():
    subs = hm.substitutions(project_name="X", owner="@y", as_of="2026-01-01")
    assert subs["{{PROJECT_NAME}}"] == "X"
    assert subs["{{OWNER}}"] == "@y"
    assert subs["{{BOOTSTRAP_DATE}}"] == "2026-01-01"


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
