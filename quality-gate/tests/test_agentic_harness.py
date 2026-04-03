"""TDD spec for Agentic Harness Policy Pack.

Derived from the Agentic System Design Principles document.
Each rule maps to a checklist item from Section 11.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qg.checks_agentic_harness import check_agentic_harness


def _run(code: str, filename: str = "agent.py") -> list[dict]:
    issues = []
    def add_issue(*, line, rule, severity, message, suggestion="", **kw):
        issues.append({"line": line, "rule": rule, "severity": severity, "message": message, "suggestion": suggestion})
    lines = code.splitlines()
    check_agentic_harness(file_path=Path(filename), content=code, lines=lines, add_issue=add_issue)
    return issues


# ── AGENT-PY-INLINE-TOOL-DEF ────────────────────────────────────────

def test_flags_tools_defined_in_prompt_string():
    """Tool definitions embedded in prompt strings → WARNING."""
    code = '''
system_prompt = """You have access to the following tools:
- search: searches the database
- delete: deletes a record
Use them wisely."""
response = client.chat.completions.create(messages=[{"role": "system", "content": system_prompt}])
'''
    issues = _run(code)
    assert any(i["rule"] == "AGENT-PY-INLINE-TOOL-DEF" for i in issues)


def test_passes_tools_from_registry():
    """Tools loaded from a registry → NOT flagged."""
    code = '''
tools = registry.get_tools(step="extraction")
response = client.chat.completions.create(messages=msgs, tools=tools)
'''
    issues = _run(code)
    assert not any(i["rule"] == "AGENT-PY-INLINE-TOOL-DEF" for i in issues)


# ── AGENT-PY-PROMPT-ONLY-PERMISSION ─────────────────────────────────

def test_flags_permission_in_prompt_only():
    """Permission enforcement only in prompt text → ERROR."""
    code = '''
system_prompt = """You must NEVER delete files. Only read operations are allowed.
Do not call any destructive tools."""
response = llm.invoke(system_prompt + user_input)
'''
    issues = _run(code)
    assert any(i["rule"] == "AGENT-PY-PROMPT-ONLY-PERMISSION" for i in issues)


def test_passes_harness_permission_check():
    """Permission check in code before tool execution → NOT flagged."""
    code = '''
if not permission_engine.check(tool_name, session.trust_tier):
    raise PermissionDenied(f"{tool_name} not allowed")
result = tool.execute(args)
'''
    issues = _run(code)
    assert not any(i["rule"] == "AGENT-PY-PROMPT-ONLY-PERMISSION" for i in issues)


# ── AGENT-PY-NO-SESSION-PERSISTENCE ─────────────────────────────────

def test_flags_agent_loop_without_checkpoint():
    """Agent loop with tool calls but no checkpoint/save → WARNING."""
    code = '''
while not task.is_complete():
    response = model.invoke(context)
    for tool_call in response.tool_calls:
        result = execute_tool(tool_call)
        task.record(result)
'''
    issues = _run(code)
    assert any(i["rule"] == "AGENT-PY-NO-SESSION-PERSISTENCE" for i in issues)


def test_passes_loop_with_checkpoint():
    """Agent loop with checkpoint after tool calls → NOT flagged."""
    code = '''
while not task.is_complete():
    response = model.invoke(context)
    for tool_call in response.tool_calls:
        result = execute_tool(tool_call)
        task.record(result)
    session_store.checkpoint(session)
'''
    issues = _run(code)
    assert not any(i["rule"] == "AGENT-PY-NO-SESSION-PERSISTENCE" for i in issues)


# ── AGENT-PY-STATE-CONFLATION ───────────────────────────────────────

def test_flags_workflow_state_in_messages():
    """Appending workflow state directly to conversation history → WARNING."""
    code = '''
messages.append({"role": "assistant", "content": f"Step {step} complete. Output: {step_output}"})
messages.append({"role": "user", "content": f"Current progress: {workflow_state}"})
response = llm.invoke(messages)
'''
    issues = _run(code)
    assert any(i["rule"] == "AGENT-PY-STATE-CONFLATION" for i in issues)


def test_passes_separate_workflow_context():
    """Workflow state injected as structured context → NOT flagged."""
    code = '''
context = build_turn_context(workflow_state, conversation_history)
response = llm.invoke(context)
'''
    issues = _run(code)
    assert not any(i["rule"] == "AGENT-PY-STATE-CONFLATION" for i in issues)


# ── AGENT-PY-NO-BUDGET-CHECK ────────────────────────────────────────

def test_flags_model_call_without_budget_check():
    """LLM call in a loop without token budget check → WARNING."""
    code = '''
for step in workflow.steps:
    context = build_context(step)
    tools = get_tools(step)
    response = model.invoke(context, tools=tools)
    process(response)
'''
    issues = _run(code)
    assert any(i["rule"] == "AGENT-PY-NO-BUDGET-CHECK" for i in issues)


def test_passes_with_budget_check():
    """Budget check before LLM call → NOT flagged."""
    code = '''
for step in workflow.steps:
    context = build_context(step)
    budget.check(estimate_tokens(context))
    response = model.invoke(context)
'''
    issues = _run(code)
    assert not any(i["rule"] == "AGENT-PY-NO-BUDGET-CHECK" for i in issues)


# ── AGENT-PY-UNVERIFIED-HANDOFF ─────────────────────────────────────

def test_flags_direct_output_handoff():
    """Passing tool output directly to next step without verification → WARNING."""
    code = '''
result = executor.run(task)
next_agent.process(result.output)
'''
    issues = _run(code)
    assert any(i["rule"] == "AGENT-PY-UNVERIFIED-HANDOFF" for i in issues)


def test_passes_verified_handoff():
    """Output verified before handoff → NOT flagged."""
    code = '''
result = executor.run(task)
verification = verifier.check(result.output, spec)
if verification.passed:
    next_agent.process(result.output)
'''
    issues = _run(code)
    assert not any(i["rule"] == "AGENT-PY-UNVERIFIED-HANDOFF" for i in issues)


# ── AGENT-PY-UNBOUNDED-HISTORY ──────────────────────────────────────

def test_flags_unbounded_message_append():
    """Messages list growing without windowing → WARNING."""
    code = '''
messages = []
while True:
    response = llm.invoke(messages)
    messages.append({"role": "assistant", "content": response})
    user_input = get_input()
    messages.append({"role": "user", "content": user_input})
'''
    issues = _run(code)
    assert any(i["rule"] == "AGENT-PY-UNBOUNDED-HISTORY" for i in issues)


def test_passes_windowed_history():
    """Messages windowed with slicing → NOT flagged."""
    code = '''
messages = []
while True:
    response = llm.invoke(messages[-MAX_TURNS:])
    messages.append({"role": "assistant", "content": response})
'''
    issues = _run(code)
    assert not any(i["rule"] == "AGENT-PY-UNBOUNDED-HISTORY" for i in issues)


# ── AGENT-PY-STATIC-TOOL-POOL ───────────────────────────────────────

def test_flags_same_tools_every_turn():
    """Same tool list sent on every turn of a multi-step workflow → INFO."""
    code = '''
all_tools = registry.get_all_tools()
for step in workflow.steps:
    context = build_context(step)
    response = model.invoke(context, tools=all_tools)
'''
    issues = _run(code)
    assert any(i["rule"] == "AGENT-PY-STATIC-TOOL-POOL" for i in issues)


def test_passes_step_specific_tools():
    """Tools selected per step → NOT flagged."""
    code = '''
for step in workflow.steps:
    tools = registry.get_tools(tags=step.required_tags)
    response = model.invoke(context, tools=tools)
'''
    issues = _run(code)
    assert not any(i["rule"] == "AGENT-PY-STATIC-TOOL-POOL" for i in issues)


# ── No False Positives ───────────────────────────────────────────────

def test_no_flags_on_non_agent_code():
    """Regular code without agent patterns → no findings."""
    code = '''
def calculate_total(items):
    return sum(item.price for item in items)

result = calculate_total(cart)
'''
    issues = _run(code)
    agent_issues = [i for i in issues if i["rule"].startswith("AGENT-PY")]
    assert len(agent_issues) == 0


# ── Teaching Suggestions ─────────────────────────────────────────────

def test_all_findings_have_suggestions():
    """Every AGENT-PY finding must teach the right pattern."""
    code = '''
system_prompt = """You have tools: search, delete. Never use delete."""
all_tools = registry.get_all_tools()
messages = []
while True:
    response = llm.invoke(messages, tools=all_tools)
    result = execute_tool(response.tool_call)
    next_agent.process(result)
    messages.append({"role": "assistant", "content": f"Done: {workflow_state}"})
'''
    issues = _run(code)
    agent_issues = [i for i in issues if i["rule"].startswith("AGENT-PY")]
    assert len(agent_issues) >= 3
    for i in agent_issues:
        assert len(i["suggestion"]) > 20, f"{i['rule']} missing teaching suggestion"


# ── Runner ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    passed = 0
    failed = 0
    tests = [(name, obj) for name, obj in sorted(globals().items()) if name.startswith("test_") and callable(obj)]
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
