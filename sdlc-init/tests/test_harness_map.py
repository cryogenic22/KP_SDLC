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
