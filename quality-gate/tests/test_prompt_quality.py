"""TDD spec for Prompt Quality Gate rule pack (PROMPT-PY-*).

In agentic projects, prompts are the new business logic. These rules
enforce prompt hygiene: versioning, separation, structured output, injection.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qg.checks_prompt_quality import check_prompt_quality


def _run(code: str) -> list[dict]:
    issues = []

    def add_issue(*, line, rule, severity, message, suggestion="", **kw):
        issues.append({"line": line, "rule": rule, "severity": severity, "message": message})

    lines = code.splitlines()
    check_prompt_quality(file_path=Path("agent.py"), content=code, lines=lines, add_issue=add_issue)
    return issues


# ── PROMPT-PY-NO-VERSION ─────────────────────────────────────────────


def test_flags_prompt_without_version():
    """Prompt string assigned without version metadata → WARNING."""
    code = '''
SYSTEM_PROMPT = """You are a helpful assistant that extracts data from documents."""
'''
    issues = _run(code)
    assert any(i["rule"] == "PROMPT-PY-NO-VERSION" for i in issues)


def test_passes_prompt_with_version_comment():
    """Prompt with version comment → NOT flagged."""
    code = '''
# prompt_version: 2.1
SYSTEM_PROMPT = """You are a helpful assistant that extracts data from documents."""
'''
    issues = _run(code)
    assert not any(i["rule"] == "PROMPT-PY-NO-VERSION" for i in issues)


def test_passes_prompt_with_version_variable():
    """Prompt with version variable → NOT flagged."""
    code = '''
PROMPT_VERSION = "2.1"
SYSTEM_PROMPT = """You are a helpful assistant."""
'''
    issues = _run(code)
    assert not any(i["rule"] == "PROMPT-PY-NO-VERSION" for i in issues)


# ── PROMPT-PY-CONCAT-SYSTEM-USER ────────────────────────────────────


def test_flags_system_user_concat():
    """System + user prompt concatenated with + → WARNING."""
    code = '''
full_prompt = system_prompt + user_input
response = llm.invoke(full_prompt)
'''
    issues = _run(code)
    assert any(i["rule"] == "PROMPT-PY-CONCAT-SYSTEM-USER" for i in issues)


def test_flags_fstring_prompt_concat():
    """f-string mixing system and user content → WARNING."""
    code = '''
prompt = f"{system_prompt}\\n{user_query}"
'''
    issues = _run(code)
    assert any(i["rule"] == "PROMPT-PY-CONCAT-SYSTEM-USER" for i in issues)


def test_passes_separated_messages():
    """Proper messages=[{role: system}, {role: user}] → NOT flagged."""
    code = '''
messages = [
    {"role": "system", "content": system_prompt},
    {"role": "user", "content": user_input},
]
'''
    issues = _run(code)
    assert not any(i["rule"] == "PROMPT-PY-CONCAT-SYSTEM-USER" for i in issues)


# ── PROMPT-PY-NO-STRUCTURED-OUTPUT ──────────────────────────────────


def test_flags_json_expectation_without_schema():
    """LLM call with 'json' in prompt but no response_format → WARNING."""
    code = '''
prompt = "Return your answer as JSON with keys: name, age"
response = client.chat.completions.create(messages=[{"role": "user", "content": prompt}])
'''
    issues = _run(code)
    assert any(i["rule"] == "PROMPT-PY-NO-STRUCTURED-OUTPUT" for i in issues)


def test_passes_with_response_format():
    """LLM call with response_format → NOT flagged."""
    code = '''
prompt = "Return your answer as JSON"
response = client.chat.completions.create(
    messages=[{"role": "user", "content": prompt}],
    response_format={"type": "json_object"}
)
'''
    issues = _run(code)
    assert not any(i["rule"] == "PROMPT-PY-NO-STRUCTURED-OUTPUT" for i in issues)


# ── PROMPT-PY-INJECTION-VECTOR ───────────────────────────────────────


def test_flags_user_input_in_fstring_prompt():
    """f-string prompt with user_input variable → ERROR."""
    code = '''
prompt = f"Summarize this document: {user_input}"
response = llm.invoke(prompt)
'''
    issues = _run(code)
    inject = [i for i in issues if i["rule"] == "PROMPT-PY-INJECTION-VECTOR"]
    assert len(inject) >= 1
    assert inject[0]["severity"] == "error"


def test_passes_sanitized_input():
    """User input passed through sanitize function → NOT flagged."""
    code = '''
safe = sanitize_input(user_input)
prompt = f"Summarize: {safe}"
'''
    issues = _run(code)
    assert not any(i["rule"] == "PROMPT-PY-INJECTION-VECTOR" for i in issues)


# ── No False Positives ───────────────────────────────────────────────


def test_no_flags_on_normal_code():
    """Regular code without prompts → no findings."""
    code = '''
def add(a, b):
    return a + b

result = add(1, 2)
'''
    issues = _run(code)
    prompt_issues = [i for i in issues if i["rule"].startswith("PROMPT-PY")]
    assert len(prompt_issues) == 0


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
        except Exception as e:
            failed += 1
            print(f"  ERROR {name}: {e}")

    print(f"\n{passed} passed, {failed} failed out of {len(tests)} tests")
    raise SystemExit(1 if failed else 0)
