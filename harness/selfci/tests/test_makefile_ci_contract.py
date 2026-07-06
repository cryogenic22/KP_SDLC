"""Makefile CI contract: the targets self-CI leans on must actually work.

Three guarantees:
- the `sarif` target passes an output path to --sarif (bare --sarif is an
  argparse error — quality_gate.py exits 2 before scanning anything);
- the `sarif` target creates that path's parent directory first
  (.quality-reports/ is gitignored and `make clean` deletes it, and
  quality_gate.py opens --sarif without makedirs — so without the mkdir a
  fresh checkout crashes with FileNotFoundError after the whole scan);
- `make test` (the blocking CI step) covers the harness suites too, via a
  `test-harness` prerequisite that loops the structural-floor, process and
  selfci test files exactly like the other suite targets.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]  # repo root
_MAKEFILE = _ROOT / "Makefile"

_SARIF_PATH_RE = re.compile(r"--sarif[ \t]+(\S+)")


def _makefile_text() -> str:
    """Makefile text, CRLF-normalized."""
    return _MAKEFILE.read_text(encoding="utf-8").replace("\r\n", "\n")


def _recipe(target: str, text: str) -> str:
    """Return the tab-indented recipe lines of a Makefile target ('' if absent)."""
    lines = text.split("\n")
    target_re = re.compile(rf"^{re.escape(target)}:")
    for i, line in enumerate(lines):
        if target_re.match(line):
            body = []
            for follow in lines[i + 1:]:
                if follow.startswith("\t"):
                    body.append(follow)
                else:
                    break
            return "\n".join(body)
    return ""


def test_sarif_target_passes_output_path():
    """`make sarif` must pass a path to --sarif: quality_gate.py declares
    --sarif with a required argument, so a bare flag exits 2 (live bug)."""
    recipe = _recipe("sarif", _makefile_text())
    assert recipe, "Makefile has no 'sarif' target"
    assert "quality_gate.py" in recipe, "sarif target no longer invokes quality_gate.py"
    m = _SARIF_PATH_RE.search(recipe)
    assert m, (
        "sarif recipe passes bare --sarif with no output path — argparse "
        "requires one argument, so the target exits 2 before scanning"
    )
    path = m.group(1)
    assert not path.startswith("-"), (
        f"--sarif is followed by another flag ({path!r}), not an output path"
    )


def test_sarif_target_creates_output_dir():
    """`make sarif` must mkdir the --sarif path's parent before scanning:
    .quality-reports/ is gitignored, absent on a fresh clone, and deleted by
    `make clean`; quality_gate.py opens --sarif with no makedirs, so without
    the mkdir the target dies FileNotFoundError after the entire scan."""
    recipe = _recipe("sarif", _makefile_text())
    assert recipe, "Makefile has no 'sarif' target"
    m = _SARIF_PATH_RE.search(recipe)
    path = m.group(1) if m else ""
    assert path and not path.startswith("-"), "sarif recipe passes no --sarif output path"
    parent = path.rpartition("/")[0]
    if not parent:
        return  # output lands in the repo root: nothing to create
    gate_pos = recipe.find("quality_gate.py")
    assert re.search(rf"mkdir -p {re.escape(parent)}(\s|$)", recipe[:gate_pos]), (
        f"sarif recipe never runs 'mkdir -p {parent}' before quality_gate.py — "
        "the directory is gitignored and `make clean` removes it, so a fresh "
        "checkout crashes with FileNotFoundError: '{}/qg.sarif'".format(parent)
    )


def test_make_test_covers_harness_tests():
    """The blocking `make test` must run the harness suites: a test-harness
    prerequisite whose recipe loops structural-floor, process and selfci
    test files and propagates failure like the other suite targets."""
    text = _makefile_text()
    m = re.search(r"^test:([^\n]*)", text, flags=re.MULTILINE)
    assert m, "Makefile has no 'test' target"
    prereqs = m.group(1).split("##")[0].split()
    assert "test-harness" in prereqs, (
        f"'test' prerequisites {prereqs} do not include test-harness — "
        "harness suites never run in CI's blocking step"
    )

    recipe = _recipe("test-harness", text)
    assert recipe, "Makefile has no 'test-harness' target"
    for tests_dir in (
        "harness/structural-floor/tests",
        "harness/process/tests",
        "harness/selfci/tests",
    ):
        assert f"{tests_dir}/test_*.py" in recipe, (
            f"test-harness recipe does not loop {tests_dir}/test_*.py"
        )
    # Anti-case: without this guard the loop swallows failures (green make
    # over red tests) — same propagation idiom as the other suite targets.
    assert '[ "$$failed" -eq 0 ]' in recipe, (
        "test-harness recipe does not propagate failures "
        '(missing the [ "$$failed" -eq 0 ] guard)'
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
