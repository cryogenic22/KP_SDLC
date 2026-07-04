"""E13.0a — Wire the dormant qg packs (duplicates, contextual size, complexity).

Market Zero loop provenance, stated honestly:
- RED before the wiring (failed on the unmodified engine): renamed-body
  clone detection, same-name/different-body false-positive kill, trivial-
  stub guard, function_size context limits, file_size subdir globs, web
  complexity counting branch keywords inside strings.
- Pin/guard tests (passed before and after; they freeze the contract the
  swap must preserve): no double counting, file_size and max_complexity
  rule-id/severity/message contracts, pack findings reaching PRS.
- Post-review regressions (from the independent adversarial review):
  brace-less arrow must not swallow the rest of the file, identical
  ts<->js bodies must group under one web namespace, bare basename
  exception patterns must keep matching at any depth.

Each test runs the real engine end-to-end over a temp fixture repo, so it
proves the packs are reachable from `qg check` — not merely importable by
tests (the vacuous-coverage failure this change removes).
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quality_gate import QualityGate  # noqa: E402


CLONE_BODY = """    total = 0
    for entry in entries:
        if entry.get("active"):
            total += entry["price"] * entry["qty"]
    return total
"""


def _run_gate(files: dict[str, str], override: dict | None = None):
    """Write fixture files into a temp root, run the engine, return issues."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for rel, content in files.items():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        if override is not None:
            (root / ".quality-gate.json").write_text(
                json.dumps(override), encoding="utf-8"
            )
        gate = QualityGate(root_dir=str(root), quiet=True)
        # Explicit paths, like every engine-level test here: temp roots are
        # outside the git repo, so git-based file discovery would find nothing.
        result = gate.run(paths=[str(root / rel) for rel in files])
        return list(result.issues or [])


def _rule_issues(issues, rule):
    return [i for i in issues if i.rule == rule]


# ── Duplicates: body-hash semantics ──────────────────────────────────


def test_renamed_body_clone_detected():
    """A clone with a new name must be flagged (the agentic failure mode)."""
    issues = _run_gate({
        "billing.py": "def compute_invoice_total(entries):\n" + CLONE_BODY,
        "reports.py": "def summarize_cart_value(entries):\n" + CLONE_BODY,
    })
    dups = _rule_issues(issues, "no_duplicate_code")
    assert dups, "renamed-body clone across files was not detected"


def test_same_name_different_body_not_flagged():
    """Same public name with genuinely different logic is not a duplicate."""
    issues = _run_gate({
        "a.py": (
            "def validate(payload):\n"
            "    if not payload:\n"
            "        raise ValueError(\"empty payload\")\n"
            "    return payload\n"
        ),
        "b.py": (
            "def validate(record):\n"
            "    allowed = {\"name\", \"email\", \"age\"}\n"
            "    extra = set(record) - allowed\n"
            "    if extra:\n"
            "        raise KeyError(str(sorted(extra)))\n"
            "    return sorted(record)\n"
        ),
    })
    dups = _rule_issues(issues, "no_duplicate_code")
    assert not dups, f"name collision alone flagged as duplicate: {dups[0].message}"


def test_trivial_stub_not_flagged():
    """Tiny stubs (health checks, protocol stubs) must not fire (min-size guard)."""
    issues = _run_gate({
        "svc_a.py": "def ping():\n    return \"ok\"\n",
        "svc_b.py": "def ping():\n    return \"ok\"\n",
    })
    dups = _rule_issues(issues, "no_duplicate_code")
    assert not dups, "trivial 2-line stub was flagged as duplicate code"


def test_no_double_counting():
    """One clone group yields exactly one finding — not one per mechanism."""
    clone = "def normalize_key(value):\n" + CLONE_BODY.replace("entries", "value")
    issues = _run_gate({
        "x.py": clone,
        "y.py": clone,
    })
    dups = _rule_issues(issues, "no_duplicate_code")
    assert len(dups) == 1, (
        f"expected exactly 1 duplicate finding for one clone group, got {len(dups)}"
    )


# ── Context exclusions ───────────────────────────────────────────────


def _long_function(name: str, lines: int) -> str:
    body = "\n".join(f"    step_{i} = {i}" for i in range(lines - 2))
    return f"def {name}():\n{body}\n    return step_0\n"


def test_function_size_context_limit_for_tests():
    """context_limits.test raises the bar for test files; product keeps default."""
    override = {
        "rules": {
            "function_size": {
                "enabled": True,
                "severity": "error",
                "max_lines": 50,
                "context_limits": {"test": {"max_lines": 200}},
            }
        }
    }
    issues = _run_gate(
        {
            "tests/test_flow.py": _long_function("test_full_flow", 60),
            "service.py": _long_function("run_service", 60),
        },
        override=override,
    )
    sizes = _rule_issues(issues, "function_size")
    flagged_files = {i.file.replace("\\", "/") for i in sizes}
    assert "service.py" in flagged_files, "60-line product function must be flagged"
    assert not any("test_flow" in f for f in flagged_files), (
        "60-line test function flagged despite context_limits.test.max_lines=200"
    )


def test_file_size_exception_glob_matches_subdir():
    """`**/*.generated.*` exceptions must match files in subdirectories."""
    big = "\n".join(f"ROW_{i} = {i}" for i in range(900))
    issues = _run_gate({"api/client.generated.py": big + "\n"})
    sizes = _rule_issues(issues, "file_size")
    assert not sizes, (
        "generated file in a subdirectory was not exempted: " + sizes[0].message
        if sizes else ""
    )


# ── Complexity: strings must not count as branches ───────────────────


def test_web_complexity_ignores_strings():
    """Branch keywords inside string literals are not complexity."""
    strings = ",\n".join(
        f'    "if you retry && wait, case {i} resolves if the cache clears"'
        for i in range(12)
    )
    content = (
        "export function pickMessage(kind: string) {\n"
        "  const messages = [\n" + strings + "\n  ];\n"
        "  return messages[0];\n"
        "}\n"
    )
    issues = _run_gate({"notes.ts": content})
    complexity = _rule_issues(issues, "max_complexity")
    assert not complexity, (
        "complexity counted branch keywords inside string literals: "
        + complexity[0].message
    )


# ── Post-review regressions (adversarial review findings) ────────────

TS_CLONE = (
    "export function formatPrice(value) {\n"
    "  const rounded = Math.round(value * 100) / 100;\n"
    "  const label = \"$\" + rounded.toFixed(2);\n"
    "  return label;\n"
    "}\n"
)


def test_web_clone_survives_braceless_arrow():
    """A brace-less arrow above a clone must not disable detection below it."""
    issues = _run_gate({
        "pricing.ts": "export const double = (x) => x * 2;\n" + TS_CLONE,
        "invoice.ts": TS_CLONE.replace("formatPrice", "renderPrice"),
    })
    dups = _rule_issues(issues, "no_duplicate_code")
    assert dups, (
        "brace-less arrow swallowed the rest of the file — clone below it missed"
    )


def test_ts_js_identical_clone_flagged():
    """An identical body in .ts and .js is a real duplicate (one web namespace)."""
    issues = _run_gate({
        "new/pricing.ts": TS_CLONE,
        "legacy/pricing.js": TS_CLONE,
    })
    dups = _rule_issues(issues, "no_duplicate_code")
    assert dups, "identical ts/js bodies were not grouped as duplicates"


def test_file_size_exception_basename_pattern():
    """Bare basename exception patterns keep matching files in subdirs."""
    override = {
        "rules": {
            "file_size": {
                "enabled": True,
                "max_lines": 800,
                "warning_lines": 500,
                "exceptions": ["legacy.*"],
            }
        }
    }
    big = "\n".join(f"ROW_{i} = {i}" for i in range(900))
    issues = _run_gate({"app/legacy.py": big + "\n"}, override=override)
    sizes = _rule_issues(issues, "file_size")
    assert not sizes, "basename exception pattern stopped matching in a subdir"


# ── Stability: rule ids, severities, message contracts ───────────────


def test_oversize_file_contract_stable():
    """file_size keeps its rule id, error severity, and message shape."""
    big = "\n".join(f"VALUE_{i} = {i}" for i in range(900))
    issues = _run_gate({"monolith.py": big + "\n"})
    sizes = _rule_issues(issues, "file_size")
    assert len(sizes) == 1
    issue = sizes[0]
    assert issue.severity.value == "error"
    assert "File has 900 lines (max: 800)" in issue.message


def test_pack_findings_count_in_prs():
    """Pack-emitted errors must reach PRS scoring (severity enum normalized).

    qg packs use qg.types.Severity, the engine compares with its own enum;
    the bridge must normalize or errors silently stop counting. Two errors
    (file_size + function_size) => PRS 80 < 85 => prs_score fires.
    """
    filler = "\n".join(f"PAD_{i} = {i}" for i in range(840))
    content = filler + "\n" + _long_function("giant_handler", 60)
    issues = _run_gate({"monolith.py": content})
    rules = {i.rule for i in issues}
    assert "file_size" in rules and "function_size" in rules
    assert "prs_score" in rules, (
        "pack-emitted errors did not reach PRS scoring (severity enum mismatch?)"
    )


def test_complexity_contract_stable():
    """max_complexity keeps its rule id, warning severity, and message shape."""
    branches = "\n".join(
        f"    if flags[{i}]:\n        acc += {i}" for i in range(12)
    )
    content = f"def tangled(flags, acc):\n{branches}\n    return acc\n"
    issues = _run_gate({"logic.py": content})
    complexity = _rule_issues(issues, "max_complexity")
    assert len(complexity) == 1
    issue = complexity[0]
    assert issue.severity.value == "warning"
    assert "has complexity 13 (max: 10)" in issue.message


# ── Runner ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    passed = 0
    failed = 0
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
        except Exception as e:  # noqa: BLE001 — report, don't crash the runner
            failed += 1
            print(f"  ERROR {name}: {e}")

    print(f"\n{passed} passed, {failed} failed out of {len(tests)} tests")
    raise SystemExit(1 if failed else 0)
