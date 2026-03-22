"""LLM-Assisted Fix Suggestions.

Feature-toggled module that generates code fix suggestions for complex
findings that can't be deterministically fixed. Uses stdlib urllib to
call LLM APIs — no external dependencies.

Toggle: Set ANTHROPIC_API_KEY or OPENAI_API_KEY env var to enable.
When no key is present, all functions return None gracefully.
"""

from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True, slots=True)
class LLMFixSuggestion:
    """An LLM-generated fix suggestion."""

    rule_id: str
    file_path: str
    line: int
    original_code: str
    suggested_code: str
    explanation: str
    confidence: str           # "high", "medium", "low"
    provider: str             # "anthropic" | "openai"
    model: str                # e.g., "claude-sonnet-4-5-20250514"
    tokens_used: int


def is_llm_available() -> bool:
    """Check if an LLM API key is configured."""
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY"))


def get_provider() -> Optional[str]:
    """Return the configured provider name, or None."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    return None


def generate_llm_fix(
    *,
    finding: Dict[str, Any],
    file_content: str,
    config: Optional[Dict[str, Any]] = None,
) -> Optional[LLMFixSuggestion]:
    """Generate an LLM fix suggestion for a complex finding.

    Returns None if:
    - No API key configured
    - The finding isn't complex enough to warrant LLM help
    - The API call fails

    The prompt is carefully structured to produce minimal, focused fixes
    without over-engineering or adding unnecessary code.
    """
    provider = get_provider()
    if not provider:
        return None

    cfg = config or {}
    rule_id = finding.get("rule", "")
    file_path = finding.get("file", "")
    line = int(finding.get("line", 1))
    message = finding.get("message", "")
    suggestion = finding.get("suggestion", "")

    # Extract context: the problematic code + surrounding lines
    lines = file_content.splitlines()
    start = max(0, line - 5)
    end = min(len(lines), line + 20)
    code_context = "\n".join(f"{i+1}: {lines[i]}" for i in range(start, end))

    prompt = _build_prompt(
        rule_id=rule_id,
        message=message,
        suggestion=suggestion,
        code_context=code_context,
        file_path=file_path,
        line=line,
    )

    try:
        if provider == "anthropic":
            return _call_anthropic(prompt, finding=finding, config=cfg)
        elif provider == "openai":
            return _call_openai(prompt, finding=finding, config=cfg)
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, KeyError, TimeoutError):
        return None

    return None


def generate_llm_fixes_batch(
    *,
    findings: List[Dict[str, Any]],
    file_contents: Dict[str, str],
    config: Optional[Dict[str, Any]] = None,
    max_fixes: int = 20,
) -> List[LLMFixSuggestion]:
    """Generate LLM fixes for a batch of findings.

    Only processes complex findings (function_size, max_complexity, etc.)
    that don't have deterministic fixes. Caps at max_fixes to control cost.
    """
    if not is_llm_available():
        return []

    # Rules that benefit from LLM-assisted fixes
    complex_rules = {
        "function_size", "max_complexity", "file_size",
        "no_duplicate_code", "dead_variable", "dead_parameters",
        "nested_collection_iteration", "nested_enumeration",
        "unvalidated_parameters", "missing_auth_middleware",
    }

    eligible = [f for f in findings if f.get("rule") in complex_rules]
    eligible = eligible[:max_fixes]

    results = []
    for finding in eligible:
        file_path = finding.get("file", "")
        content = file_contents.get(file_path, "")
        if not content:
            continue

        fix = generate_llm_fix(finding=finding, file_content=content, config=config)
        if fix:
            results.append(fix)

    return results


def _build_prompt(
    *,
    rule_id: str,
    message: str,
    suggestion: str,
    code_context: str,
    file_path: str,
    line: int,
) -> str:
    """Build a focused prompt for code fix generation."""
    return f"""You are a senior Python engineer fixing a code quality issue.

RULE: {rule_id}
FILE: {file_path}
LINE: {line}
ISSUE: {message}
HINT: {suggestion}

CODE CONTEXT (line numbers shown):
```python
{code_context}
```

Provide ONLY the fixed code snippet. Requirements:
1. Fix the specific issue identified — nothing else
2. Preserve the existing code style and indentation
3. Do not add comments explaining the fix
4. Do not refactor surrounding code
5. Keep the fix minimal and focused
6. Return ONLY the replacement code, no markdown fences

FIXED CODE:"""


def _call_anthropic(
    prompt: str,
    *,
    finding: Dict[str, Any],
    config: Dict[str, Any],
) -> Optional[LLMFixSuggestion]:
    """Call Anthropic API via urllib."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    model = config.get("llm_model", "claude-sonnet-4-5-20250514")
    max_tokens = config.get("llm_max_tokens", 1024)

    payload = json.dumps({
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode("utf-8"))

    suggested_code = body["content"][0]["text"].strip()
    tokens = body.get("usage", {}).get("input_tokens", 0) + body.get("usage", {}).get("output_tokens", 0)

    # Extract original code from file
    file_content = ""  # Would need to be passed in for full context
    original_line = finding.get("message", "")

    return LLMFixSuggestion(
        rule_id=finding.get("rule", ""),
        file_path=finding.get("file", ""),
        line=int(finding.get("line", 1)),
        original_code=original_line,
        suggested_code=suggested_code,
        explanation=f"AI-suggested fix for {finding.get('rule', '')}: {finding.get('message', '')[:100]}",
        confidence="medium",
        provider="anthropic",
        model=model,
        tokens_used=tokens,
    )


def _call_openai(
    prompt: str,
    *,
    finding: Dict[str, Any],
    config: Dict[str, Any],
) -> Optional[LLMFixSuggestion]:
    """Call OpenAI API via urllib."""
    api_key = os.environ.get("OPENAI_API_KEY", "")
    model = config.get("llm_model", "gpt-4o")
    max_tokens = config.get("llm_max_tokens", 1024)

    payload = json.dumps({
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode("utf-8"))

    suggested_code = body["choices"][0]["message"]["content"].strip()
    tokens = body.get("usage", {}).get("total_tokens", 0)

    return LLMFixSuggestion(
        rule_id=finding.get("rule", ""),
        file_path=finding.get("file", ""),
        line=int(finding.get("line", 1)),
        original_code=finding.get("message", ""),
        suggested_code=suggested_code,
        explanation=f"AI-suggested fix for {finding.get('rule', '')}: {finding.get('message', '')[:100]}",
        confidence="medium",
        provider="openai",
        model=model,
        tokens_used=tokens,
    )
