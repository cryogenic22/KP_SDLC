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

# Each pytest-idiom suite target mapped to the ONE tests dir it must run. Pinning
# the exact path (not just "contains python -m pytest") rejects a remap — pointing
# test-runtime-verify at schemas/tests so one suite runs twice and another never
# runs — and, with the unmasked-command predicate below, a trailing `|| true`
# that would swallow a red suite. COMPLETENESS (no on-disk suite left unwired) is
# guarded separately and disk-derived by test_every_component_suite_on_disk_is_wired.
_PYTEST_SUITE_PATHS = {
    "test-schemas": "schemas/tests",
    "test-runtime-verify": "runtime-verify/tests",
    "test-eval-engine": "eval-engine/tests",
    "test-input-gate": "input-gate/tests",
    "test-contract-gate": "contract-gate/tests",
    "test-observatory": "observatory/tests",
    "test-fix-engine": "fix-engine/tests",
}

# Top-level `<component>/tests/` dirs that hold a suite but are intentionally NOT
# run by `make test`. Keep EMPTY unless there is a documented reason: every entry
# is a hole in durable regression protection and must cite why it is safe.
_UNWIRED_SUITE_ALLOWLIST: tuple[str, ...] = ()


def _suite_command_ok(cmd: str, expected_dir: str) -> bool:
    """True iff `cmd` is EXACTLY ``python -m pytest <expected_dir>/ -q`` — its own
    suite, nothing appended. Rejects a suite remap (wrong dir) and a failure mask
    (a trailing ``|| true`` / ``; true`` leaves extra tokens the fullmatch forbids)."""
    return re.fullmatch(rf"python -m pytest {re.escape(expected_dir)}/? -q", cmd or "") is not None


def _pytest_command_lines(target: str, makefile_text: str) -> list[str]:
    """The stripped, Make-var-expanded lines of ``target``'s recipe that invoke
    pytest (there must be exactly one for a well-formed suite target)."""
    recipe = _expand_make_vars(_recipe(target, makefile_text), makefile_text)
    return [ln.strip() for ln in recipe.split("\n") if "pytest" in ln]


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


def _test_prereqs(text):
    """The full `test:` prerequisite list, joining Make backslash-continuations
    (the `test` target spans several lines once the component suites are added).
    Collapse ``\\``-continuations to one logical line first, then read it."""
    joined = re.sub(r"\\\n\s*", " ", text)
    m = re.search(r"^test:([^\n]*)", joined, flags=re.MULTILINE)
    if not m:
        return []
    return m.group(1).split("##")[0].split()


def test_pytest_suite_targets_run_their_own_suite_unmasked():
    """The blocking `make test` must ACTUALLY RUN each merged component suite,
    against its OWN tests dir, with failures un-masked — not merely mention
    `python -m pytest` somewhere in the recipe.

    The old 'contains python -m pytest' + '/tests/' check let two silent-green
    vectors through: (a) a remap — pointing test-runtime-verify at schemas/tests,
    so one suite runs twice and runtime-verify never runs — and (b) a trailing
    `|| true` that swallows a red suite. Pinning each target to `python -m pytest
    <its own dir>/ -q` as the SOLE command closes both. `python -m pytest` is
    still load-bearing over the `python <file>` loop: it collects+runs every test
    regardless of a `__main__` runner (two observatory files are fixture-only)
    and exits 5 on zero collection, so an empty/renamed dir also fails closed."""
    text = _makefile_text()
    prereqs = _test_prereqs(text)
    assert prereqs, "could not parse the 'test' target prerequisites"
    for target, expected in _PYTEST_SUITE_PATHS.items():
        assert target in prereqs, (
            f"'test' prerequisites {prereqs} omit {target} — that component "
            "suite never runs in CI's blocking step"
        )
        cmds = _pytest_command_lines(target, text)
        assert len(cmds) == 1, (
            f"{target} must run exactly one pytest command, got {cmds} — a second "
            "pytest line (or none) breaks the one-suite-per-target contract"
        )
        assert _suite_command_ok(cmds[0], expected), (
            f"{target} runs {cmds[0]!r}, not the exact unmasked "
            f"`python -m pytest {expected}/ -q` — a remap to another suite's dir "
            "or a trailing `|| true` (failure mask) would otherwise pass silently"
        )


def test_pytest_suite_contract_rejects_remap_and_masking():
    """Anti-case (teeth for the above): the exact-command predicate must REJECT a
    remapped suite and a masked failure. A gate that accepts them is vacuous."""
    expected = "runtime-verify/tests"
    # Positive control: the honest command is accepted (both slash forms).
    assert _suite_command_ok("python -m pytest runtime-verify/tests/ -q", expected)
    assert _suite_command_ok("python -m pytest runtime-verify/tests -q", expected)
    # (a) remap — runs a DIFFERENT suite's dir:
    assert not _suite_command_ok("python -m pytest schemas/tests/ -q", expected)
    # (b) failure mask — a trailing `|| true` / `; true`:
    assert not _suite_command_ok("python -m pytest runtime-verify/tests/ -q || true", expected)
    assert not _suite_command_ok("python -m pytest runtime-verify/tests/ -q ; true", expected)


def _expand_make_vars(text: str, makefile_text: str) -> str:
    """Expand ``$(NAME_DIR)`` references using the Makefile's ``NAME_DIR := value``
    definitions, so a recipe like ``python -m pytest $(FE_DIR)/tests/`` resolves to
    a real on-disk path we can substring-match against."""
    defs = dict(re.findall(r"^(\w+_DIR)\s*:=\s*(\S+)", makefile_text, flags=re.MULTILINE))
    return re.sub(r"\$\((\w+_DIR)\)", lambda m: defs.get(m.group(1), m.group(0)), text)


def _ondisk_component_test_dirs() -> list[str]:
    """Every top-level ``<component>/tests/`` dir on disk holding ``test_*.py``, as
    repo-relative posix paths, minus the documented allowlist. (Harness suites live
    at ``harness/*/tests`` and are covered by test_make_test_covers_harness_tests.)"""
    dirs = []
    for tests_dir in sorted(_ROOT.glob("*/tests")):
        if not tests_dir.is_dir() or not any(tests_dir.glob("test_*.py")):
            continue
        rel = tests_dir.relative_to(_ROOT).as_posix()
        if rel not in _UNWIRED_SUITE_ALLOWLIST:
            dirs.append(rel)
    return dirs


def test_every_component_suite_on_disk_is_wired():
    """COMPLETENESS / anti-drift: every top-level ``<component>/tests/`` dir that
    holds ``test_*.py`` must be executed by the blocking ``make test``. A hardcoded
    target list only protects suites someone remembered to type; deriving the
    expected set from disk makes a newly-added-but-unwired component fail closed
    HERE instead of merging silently — the exact bug class of the ``fix-engine``
    gap (ADR 0001) that a hardcoded suite list (like _PYTEST_SUITE_PATHS) could
    never have caught on its own."""
    text = _makefile_text()
    prereqs = _test_prereqs(text)
    assert prereqs, "could not parse the 'test' target prerequisites"
    wired = _expand_make_vars(" ".join(_recipe(t, text) for t in prereqs), text)
    ondisk = _ondisk_component_test_dirs()
    assert ondisk, "found no on-disk component test dirs — has the repo layout changed?"
    for tests_dir in ondisk:
        assert tests_dir in wired, (
            f"{tests_dir}/ holds test_*.py but no `make test` target runs it — wire "
            f"it in (a `python -m pytest {tests_dir}/` target in the `test:` prereqs). "
            "Hardcoded suite lists can't catch this: see ADR 0001's fix-engine gap. "
            f"If the omission is deliberate, add '{tests_dir}' to "
            "_UNWIRED_SUITE_ALLOWLIST with a documented reason."
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
