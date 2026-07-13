"""Guard the `python <file>` test loop against silent zero-test runs.

Several Makefile suite targets (test-qg/ck/reporting/init/harness) execute each
test file with `python "$f"` in a shell loop. That idiom IMPORTS the file and
runs whatever its `__main__` block runs — so a test file with test functions but
NO `if __name__ == "__main__":` runner imports cleanly, runs ZERO tests, and
exits 0: a vacuous green that ships a broken component. (This is the original
seed defect of the self-healing thread: observatory once ran 0/12 that way.)

This contract derives the loop dirs FROM the Makefile and asserts every
`test_*.py` in them carries a failure-propagating `__main__` runner, so a new
file that would no-op fails closed here instead of passing silently. Suites run
via `python -m pytest <dir>` need no runner (pytest exits 5 on zero collection),
so they are intentionally out of scope — only the fragile `python <file>` loop
is guarded.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_MAKEFILE = _ROOT / "Makefile"

_MAIN_RE = re.compile(r"""if\s+__name__\s*==\s*['"]__main__['"]\s*:""")
# A failure-capable exit: SystemExit/sys.exit whose argument is NOT literally 0,
# so an always-green `sys.exit(0)` / `SystemExit(0)` does not qualify.
_EXIT_RE = re.compile(r"(?:SystemExit|sys\.exit)\s*\(\s*(?!0\s*\))")


def _makefile_text() -> str:
    return _MAKEFILE.read_text(encoding="utf-8").replace("\r\n", "\n")


def _expand_dir_vars(text: str, makefile_text: str) -> str:
    """Expand `$(NAME_DIR)` using the Makefile's `NAME_DIR := value` definitions."""
    defs = dict(re.findall(r"^(\w+_DIR)\s*:=\s*(\S+)", makefile_text, flags=re.MULTILINE))
    return re.sub(r"\$\((\w+_DIR)\)", lambda m: defs.get(m.group(1), m.group(0)), text)


def _fragile_loop_globs(makefile_text: str) -> list[str]:
    """The test-file globs run by the `for f in ...; do ... python "$$f"` loop.
    Only loops whose body actually runs `python "$$f"` count (pytest targets use
    no `for f in`), so this captures exactly the fragile-idiom dirs."""
    globs: list[str] = []
    for m in re.finditer(r'for f in (.+?); do(.*?)done', makefile_text, flags=re.DOTALL):
        if 'python "$$f"' not in m.group(2):
            continue
        expanded = _expand_dir_vars(m.group(1), makefile_text)
        globs.extend(g for g in expanded.split() if g.endswith("test_*.py"))
    return globs


def _fragile_loop_test_files() -> list[Path]:
    """Resolve the fragile-loop globs to actual test files on disk."""
    files: list[Path] = []
    for glob in _fragile_loop_globs(_makefile_text()):
        files.extend(sorted(_ROOT.glob(glob)))
    return files


def _main_region(text: str) -> str:
    """Text from the `if __name__ == "__main__":` line to EOF ('' if absent)."""
    m = _MAIN_RE.search(text)
    return text[m.start():] if m else ""


def _runs_tests(region: str) -> bool:
    """Evidence the `__main__` block actually invokes the file's tests (the repo's
    runner iterates `globals()` for `test_*`), rather than just printing/exiting."""
    return "globals(" in region or "test_" in region


def _has_failure_capable_exit(region: str) -> bool:
    """The `__main__` block exits with a data-dependent / non-zero code on failure."""
    return bool(_EXIT_RE.search(region))


def _rel(path: Path) -> str:
    return path.relative_to(_ROOT).as_posix()


def test_every_fragile_loop_test_file_has_a_main_runner():
    """Every `python <file>`-loop test file must carry a `__main__` runner that
    ACTUALLY RUNS its tests AND exits non-zero on failure — else it imports, runs
    zero tests, and exits 0 (vacuous green). Checking mere presence of a
    `__main__` line is not enough; a `print(); sys.exit(0)` runner would slip."""
    files = _fragile_loop_test_files()
    assert files, "found no `python <file>`-loop test files — has the Makefile idiom changed?"
    offenders = []
    for path in files:
        region = _main_region(path.read_text(encoding="utf-8", errors="replace"))
        if not region:
            offenders.append(f'{_rel(path)}: no `if __name__ == "__main__":` runner')
        elif not _runs_tests(region):
            offenders.append(f"{_rel(path)}: `__main__` block does not run the tests (no test_/globals reference)")
        elif not _has_failure_capable_exit(region):
            offenders.append(f"{_rel(path)}: `__main__` runner has no failure-capable exit (only `exit(0)`?)")
    assert not offenders, (
        "these suites run via the Makefile `python <file>` loop, which imports a "
        "file and runs ZERO tests (exit 0 — vacuous green) unless it has a "
        "`__main__` runner that invokes the tests and exits non-zero on failure:\n"
        + "\n".join(offenders)
    )


def test_main_runner_detector_has_teeth():
    """Anti-case: accept a real runner; reject (a) a fixture-only file with no
    `__main__`, and (b) a `__main__` that runs no tests and always exits 0 — the
    exact vacuous-green shapes the guard claims to forbid."""
    real = (
        'if __name__ == "__main__":\n'
        '    for name, fn in [(n, o) for n, o in globals().items() if n.startswith("test_")]:\n'
        '        fn()\n'
        '    raise SystemExit(1 if failed else 0)\n'
    )
    region = _main_region(real)
    assert region and _runs_tests(region) and _has_failure_capable_exit(region)
    # (a) no __main__ at all → would no-op under `python <file>`
    assert not _main_region("def test_x():\n    assert True\n")
    # (b) __main__ that prints and always exits 0 → still vacuous, must fail
    fake_region = _main_region('if __name__ == "__main__":\n    print("ok")\n    sys.exit(0)\n')
    assert fake_region, "sanity: the fake still has a __main__ line"
    assert not (_runs_tests(fake_region) and _has_failure_capable_exit(fake_region)), (
        "a __main__ that runs no tests and exits 0 must not pass the guard"
    )
    assert not _has_failure_capable_exit('if __name__ == "__main__":\n    sys.exit(0)')
    assert _has_failure_capable_exit("raise SystemExit(1 if failed else 0)")


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
