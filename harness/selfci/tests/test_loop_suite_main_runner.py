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
_EXIT_RE = re.compile(r"SystemExit|sys\.exit")


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


def _has_main_runner(text: str) -> bool:
    return bool(_MAIN_RE.search(text))


def _propagates_failure(text: str) -> bool:
    return bool(_EXIT_RE.search(text))


def _rel(path: Path) -> str:
    return path.relative_to(_ROOT).as_posix()


def test_every_fragile_loop_test_file_has_a_main_runner():
    """Every `python <file>`-loop test file must carry a failure-propagating
    `__main__` runner — else it imports, runs zero tests, and exits 0."""
    files = _fragile_loop_test_files()
    assert files, "found no `python <file>`-loop test files — has the Makefile idiom changed?"
    offenders = []
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        if not _has_main_runner(text):
            offenders.append(f'{_rel(path)}: no `if __name__ == "__main__":` runner')
        elif not _propagates_failure(text):
            offenders.append(f"{_rel(path)}: `__main__` runner never exits non-zero on failure")
    assert not offenders, (
        "these suites run via the Makefile `python <file>` loop, which imports a "
        "file and runs ZERO tests (exit 0 — vacuous green) unless it has a "
        "failure-propagating `__main__` runner:\n" + "\n".join(offenders)
    )


def test_main_runner_detector_has_teeth():
    """Anti-case: the detectors must accept a real runner and reject a
    fixture-only file (the exact shape that no-ops under `python <file>`)."""
    assert _has_main_runner('if __name__ == "__main__":\n    run()')
    assert _has_main_runner("if __name__ == '__main__':\n    run()")
    assert not _has_main_runner("def test_x():\n    assert True\n")
    assert _propagates_failure("raise SystemExit(1 if failed else 0)")
    assert _propagates_failure("    sys.exit(rc)")
    assert not _propagates_failure("print('done')\n")


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
