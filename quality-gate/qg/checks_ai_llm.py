"""
AI/LLM-Specific Code Quality Checks

Catches common mistakes when working with LLMs and AI APIs:
- Missing await on async calls
- API calls without timeout/retry
- Unbounded token usage
- Prompt injection vulnerabilities
- Missing error handling for LLM responses
- Synchronous blocking in async context
- Missing rate limit handling
- Missing fallback/graceful degradation

These are critical for production AI systems.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any, Callable

from .types import Severity, parse_severity

AddIssue = Callable[..., None]


def _rule(config: dict[str, Any], name: str) -> dict[str, Any]:
    return (config.get("rules", {}) or {}).get(name, {}) or {}


def _enabled(config: dict[str, Any], name: str, *, default: bool) -> bool:
    return bool(_rule(config, name).get("enabled", default))


# ═══════════════════════════════════════════════════════════════════════════
# 1. Missing await on async LLM calls
# ═══════════════════════════════════════════════════════════════════════════

def check_missing_await(
    *,
    file_path: Path,
    content: str,
    language: str,
    config: dict[str, Any],
    add_issue: AddIssue,
) -> None:
    """
    Detect async function calls that are missing await.

    Common patterns:
    - openai.chat.completions.create() without await
    - anthropic.messages.create() without await
    - generate_image_bytes() without await (when async)
    """
    name = "missing_await"
    if not _enabled(config, name, default=True):
        return

    if language != "python":
        return

    severity = parse_severity(_rule(config, name).get("severity"), default=Severity.ERROR)

    # Patterns that are commonly async and often forgotten
    async_call_patterns = [
        r'(?<!await\s)(?<!await\()openai\.[^(]+\.create\s*\(',
        r'(?<!await\s)(?<!await\()anthropic\.[^(]+\.create\s*\(',
        r'(?<!await\s)(?<!await\()client\.chat\.completions\.create\s*\(',
        r'(?<!await\s)(?<!await\()client\.messages\.create\s*\(',
        r'(?<!await\s)(?<!await\()aiohttp\.[^(]+\(',
        r'(?<!await\s)(?<!await\()session\.(get|post|put|delete)\s*\(',
        r'(?<!await\s)(?<!await\()asyncio\.sleep\s*\(',
    ]

    lines = content.splitlines()
    for i, line in enumerate(lines, 1):
        # Skip if line has await
        if 'await ' in line or 'await(' in line:
            continue
        # Skip comments
        stripped = line.lstrip()
        if stripped.startswith('#'):
            continue

        for pattern in async_call_patterns:
            if re.search(pattern, line):
                add_issue(
                    line=i,
                    rule="missing_await",
                    severity=severity,
                    message="Async call may be missing 'await'. This will return a coroutine, not the result.",
                    snippet=line.strip()[:60],
                    suggestion="Add 'await' before the async call, or ensure this is intentional.",
                )
                break


# ═══════════════════════════════════════════════════════════════════════════
# 2. LLM API calls without timeout
# ═══════════════════════════════════════════════════════════════════════════

def check_llm_timeout(
    *,
    content: str,
    lines: list[str],
    language: str,
    config: dict[str, Any],
    add_issue: AddIssue,
) -> None:
    """
    Detect LLM/AI API calls without explicit timeout.

    LLM calls can hang indefinitely. Always specify timeout.
    """
    name = "llm_timeout"
    if not _enabled(config, name, default=True):
        return

    if language != "python":
        return

    severity = parse_severity(_rule(config, name).get("severity"), default=Severity.WARNING)

    # Patterns for LLM API calls
    llm_call_patterns = [
        (r'openai\.[^(]+\.create\s*\(', 'OpenAI'),
        (r'anthropic\.[^(]+\.create\s*\(', 'Anthropic'),
        (r'client\.chat\.completions\.create\s*\(', 'OpenAI'),
        (r'client\.messages\.create\s*\(', 'Anthropic'),
        (r'gemini\.[^(]+\.generate', 'Gemini'),
        (r'model\.generate_content\s*\(', 'Gemini'),
        (r'requests\.(get|post)\s*\(', 'requests'),
        (r'httpx\.(get|post|AsyncClient)', 'httpx'),
    ]

    for i, line in enumerate(lines, 1):
        # Skip comments
        stripped = line.lstrip()
        if stripped.startswith('#'):
            continue

        for pattern, api_name in llm_call_patterns:
            if re.search(pattern, line):
                # Check if timeout is specified in this line or nearby
                context = '\n'.join(lines[max(0, i-3):min(len(lines), i+5)])
                if 'timeout' not in context.lower():
                    add_issue(
                        line=i,
                        rule="llm_timeout",
                        severity=severity,
                        message=f"{api_name} API call without explicit timeout. Call may hang indefinitely.",
                        snippet=line.strip()[:50],
                        suggestion=f"Add timeout parameter: timeout=30 or use a context manager with timeout.",
                    )
                break


# ═══════════════════════════════════════════════════════════════════════════
# 3. LLM calls without retry logic
# ═══════════════════════════════════════════════════════════════════════════

def check_llm_retry(
    *,
    content: str,
    lines: list[str],
    language: str,
    config: dict[str, Any],
    add_issue: AddIssue,
) -> None:
    """
    Detect LLM API calls without retry mechanism.

    LLM APIs have transient failures. Use tenacity, backoff, or custom retry.
    """
    name = "llm_retry"
    if not _enabled(config, name, default=True):
        return

    if language != "python":
        return

    severity = parse_severity(_rule(config, name).get("severity"), default=Severity.WARNING)

    # Check if file has retry imports
    has_retry_lib = any(lib in content for lib in [
        'from tenacity import',
        'import tenacity',
        'from backoff import',
        'import backoff',
        '@retry',
        '@backoff',
        'Retry(',
        'retry_if_',
    ])

    if has_retry_lib:
        return  # File has retry mechanism

    # Look for LLM calls
    llm_patterns = [
        r'openai\.[^(]+\.create\s*\(',
        r'anthropic\.[^(]+\.create\s*\(',
        r'client\.chat\.completions\.create',
        r'client\.messages\.create',
        r'generate_content\s*\(',
    ]

    for i, line in enumerate(lines, 1):
        for pattern in llm_patterns:
            if re.search(pattern, line):
                add_issue(
                    line=i,
                    rule="llm_retry",
                    severity=severity,
                    message="LLM API call without retry mechanism. Transient failures will crash the application.",
                    snippet=line.strip()[:50],
                    suggestion="Use tenacity or backoff library: @retry(stop=stop_after_attempt(3), wait=wait_exponential())",
                )
                return  # Only warn once per file


# ═══════════════════════════════════════════════════════════════════════════
# 4. Unbounded token/context usage
# ═══════════════════════════════════════════════════════════════════════════

def check_unbounded_tokens(
    *,
    content: str,
    lines: list[str],
    language: str,
    config: dict[str, Any],
    add_issue: AddIssue,
) -> None:
    """
    Detect LLM calls without max_tokens limit.

    Without max_tokens, responses can be unexpectedly long and expensive.
    """
    name = "unbounded_tokens"
    if not _enabled(config, name, default=True):
        return

    if language != "python":
        return

    severity = parse_severity(_rule(config, name).get("severity"), default=Severity.WARNING)

    for i, line in enumerate(lines, 1):
        # Look for completion/message create calls
        if re.search(r'\.create\s*\(', line) and ('completion' in content.lower() or 'message' in content.lower()):
            # Check surrounding context for max_tokens
            start = max(0, i - 5)
            end = min(len(lines), i + 10)
            context = '\n'.join(lines[start:end])

            if 'max_tokens' not in context and 'max_output_tokens' not in context:
                if any(api in context for api in ['openai', 'anthropic', 'chat.completions', 'messages.create']):
                    add_issue(
                        line=i,
                        rule="unbounded_tokens",
                        severity=severity,
                        message="LLM call without max_tokens limit. Response length is unbounded.",
                        snippet=line.strip()[:50],
                        suggestion="Add max_tokens parameter to control response length and cost.",
                    )
                    return  # Only warn once


# ═══════════════════════════════════════════════════════════════════════════
# 5. Raw f-string prompt construction (injection risk)
# ═══════════════════════════════════════════════════════════════════════════

def check_prompt_injection_risk(
    *,
    content: str,
    lines: list[str],
    language: str,
    config: dict[str, Any],
    add_issue: AddIssue,
) -> None:
    """
    Detect raw user input interpolation in prompts.

    User input directly in prompts can lead to prompt injection attacks.
    """
    name = "prompt_injection_risk"
    if not _enabled(config, name, default=True):
        return

    if language != "python":
        return

    severity = parse_severity(_rule(config, name).get("severity"), default=Severity.WARNING)

    # Risky patterns: user input directly in prompt strings
    risky_patterns = [
        (r'f["\'].*\{user_input\}', 'user_input in f-string prompt'),
        (r'f["\'].*\{request\.[^}]+\}', 'request data in f-string prompt'),
        (r'f["\'].*\{query\}', 'query variable in f-string prompt'),
        (r'\.format\s*\([^)]*user', '.format() with user data'),
        (r'prompt\s*\+\s*user', 'string concatenation with user input'),
        (r'%\s*\(.*user.*\)', '% formatting with user data'),
    ]

    in_prompt_context = False
    for i, line in enumerate(lines, 1):
        lower_line = line.lower()

        # Track if we're in a prompt-related context
        if any(kw in lower_line for kw in ['prompt', 'system_message', 'user_message', 'content=']):
            in_prompt_context = True

        if in_prompt_context or 'prompt' in lower_line:
            for pattern, description in risky_patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    add_issue(
                        line=i,
                        rule="prompt_injection_risk",
                        severity=severity,
                        message=f"Potential prompt injection risk: {description}.",
                        snippet=line.strip()[:50],
                        suggestion="Sanitize user input or use structured message formats. Consider input validation.",
                    )
                    break

        # Reset context on blank lines or function definitions
        if not line.strip() or line.strip().startswith('def ') or line.strip().startswith('class '):
            in_prompt_context = False


# ═══════════════════════════════════════════════════════════════════════════
# 6. Blocking calls in async context
# ═══════════════════════════════════════════════════════════════════════════

def check_blocking_in_async(
    *,
    file_path: Path,
    content: str,
    language: str,
    config: dict[str, Any],
    add_issue: AddIssue,
) -> None:
    """
    Detect blocking calls inside async functions.

    Blocking calls (time.sleep, requests.get) in async code block the event loop.
    """
    name = "blocking_in_async"
    if not _enabled(config, name, default=True):
        return

    if language != "python":
        return

    severity = parse_severity(_rule(config, name).get("severity"), default=Severity.ERROR)

    try:
        tree = ast.parse(content, filename=str(file_path))
    except SyntaxError:
        return

    blocking_calls = {
        'time.sleep': 'asyncio.sleep',
        'requests.get': 'aiohttp or httpx async client',
        'requests.post': 'aiohttp or httpx async client',
        'requests.put': 'aiohttp or httpx async client',
        'requests.delete': 'aiohttp or httpx async client',
        'open': 'aiofiles.open',
        'input': 'async input library',
    }

    class AsyncBlockingVisitor(ast.NodeVisitor):
        def __init__(self):
            self.in_async = False
            self.issues = []

        def visit_AsyncFunctionDef(self, node):
            old_in_async = self.in_async
            self.in_async = True
            self.generic_visit(node)
            self.in_async = old_in_async

        def visit_Call(self, node):
            if not self.in_async:
                self.generic_visit(node)
                return

            call_name = self._get_call_name(node)
            if call_name in blocking_calls:
                self.issues.append((
                    getattr(node, 'lineno', 1),
                    call_name,
                    blocking_calls[call_name],
                ))
            self.generic_visit(node)

        def _get_call_name(self, node):
            if isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Name):
                    return f"{node.func.value.id}.{node.func.attr}"
                elif isinstance(node.func.value, ast.Attribute):
                    return f"{node.func.value.attr}.{node.func.attr}"
            elif isinstance(node.func, ast.Name):
                return node.func.id
            return ""

    visitor = AsyncBlockingVisitor()
    visitor.visit(tree)

    for line_no, call_name, suggestion in visitor.issues:
        add_issue(
            line=line_no,
            rule="blocking_in_async",
            severity=severity,
            message=f"Blocking call '{call_name}' inside async function. This blocks the event loop.",
            suggestion=f"Use async alternative: {suggestion}",
        )


# ═══════════════════════════════════════════════════════════════════════════
# 7. Missing error handling for LLM responses
# ═══════════════════════════════════════════════════════════════════════════

def check_llm_response_handling(
    *,
    content: str,
    lines: list[str],
    language: str,
    config: dict[str, Any],
    add_issue: AddIssue,
) -> None:
    """
    Detect LLM API calls without proper error handling.

    LLM responses can fail, return empty, or have unexpected structure.
    """
    name = "llm_response_handling"
    if not _enabled(config, name, default=True):
        return

    if language != "python":
        return

    severity = parse_severity(_rule(config, name).get("severity"), default=Severity.WARNING)

    # Check if there's a try block around LLM calls
    llm_call_patterns = [
        r'\.create\s*\(',
        r'\.generate_content\s*\(',
        r'generate_image',
        r'\.complete\s*\(',
    ]

    in_try_block = False
    try_depth = 0

    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        if stripped.startswith('try:'):
            in_try_block = True
            try_depth += 1
        elif stripped.startswith('except') or stripped.startswith('finally:'):
            if try_depth > 0:
                try_depth -= 1
            if try_depth == 0:
                in_try_block = False

        if not in_try_block:
            for pattern in llm_call_patterns:
                if re.search(pattern, line):
                    # Check if it's actually an LLM-related call
                    context = '\n'.join(lines[max(0, i-5):min(len(lines), i+3)])
                    if any(api in context.lower() for api in ['openai', 'anthropic', 'gemini', 'llm', 'completion', 'message']):
                        add_issue(
                            line=i,
                            rule="llm_response_handling",
                            severity=severity,
                            message="LLM API call without try/except. API errors will crash the application.",
                            snippet=stripped[:50],
                            suggestion="Wrap in try/except and handle APIError, RateLimitError, etc.",
                        )
                        return  # Only warn once per file


# ═══════════════════════════════════════════════════════════════════════════
# 8. Missing rate limit handling (429)
# ═══════════════════════════════════════════════════════════════════════════

def check_rate_limit_handling(
    *,
    content: str,
    language: str,
    config: dict[str, Any],
    add_issue: AddIssue,
) -> None:
    """
    Check if code handles rate limiting (429 errors).

    LLM APIs have rate limits. Code should handle 429 with exponential backoff.
    """
    name = "rate_limit_handling"
    if not _enabled(config, name, default=True):
        return

    if language != "python":
        return

    severity = parse_severity(_rule(config, name).get("severity"), default=Severity.WARNING)

    # Check if file uses LLM APIs
    has_llm_calls = any(api in content for api in [
        'openai', 'anthropic', 'gemini',
        'chat.completions', 'messages.create',
        'generate_content', 'generate_image'
    ])

    if not has_llm_calls:
        return

    # Check if rate limit handling exists
    has_rate_limit_handling = any(pattern in content for pattern in [
        'RateLimitError',
        '429',
        'rate_limit',
        'retry_after',
        'backoff',
        'tenacity',
        'exponential',
        'too_many_requests',
        'TooManyRequests',
    ])

    if not has_rate_limit_handling:
        add_issue(
            line=1,
            rule="rate_limit_handling",
            severity=severity,
            message="File uses LLM APIs but has no rate limit handling (429 errors).",
            suggestion="Add exponential backoff: @retry(retry=retry_if_exception_type(RateLimitError), wait=wait_exponential())",
        )


# ═══════════════════════════════════════════════════════════════════════════
# 9. Hardcoded model names
# ═══════════════════════════════════════════════════════════════════════════

def check_hardcoded_model(
    *,
    lines: list[str],
    language: str,
    config: dict[str, Any],
    add_issue: AddIssue,
) -> None:
    """
    Detect hardcoded LLM model names.

    Model names should be configurable for easy updates and A/B testing.
    """
    name = "hardcoded_model"
    if not _enabled(config, name, default=False):  # Disabled by default, opt-in
        return

    if language != "python":
        return

    severity = parse_severity(_rule(config, name).get("severity"), default=Severity.WARNING)

    model_patterns = [
        (r'["\']gpt-4[^"\']*["\']', 'OpenAI GPT-4'),
        (r'["\']gpt-3\.5[^"\']*["\']', 'OpenAI GPT-3.5'),
        (r'["\']claude-[^"\']+["\']', 'Anthropic Claude'),
        (r'["\']gemini-[^"\']+["\']', 'Google Gemini'),
        (r'["\']o1-[^"\']+["\']', 'OpenAI o1'),
    ]

    for i, line in enumerate(lines, 1):
        # Skip if it's likely a config or constant definition
        if '=' in line and any(kw in line.upper() for kw in ['MODEL', 'DEFAULT', 'CONFIG', 'CONST']):
            continue
        # Skip comments
        if line.strip().startswith('#'):
            continue

        for pattern, model_name in model_patterns:
            if re.search(pattern, line):
                # Only flag if it's in a function call, not a constant
                if 'model=' in line or 'model:' in line:
                    add_issue(
                        line=i,
                        rule="hardcoded_model",
                        severity=severity,
                        message=f"Hardcoded {model_name} model name. Should be configurable.",
                        snippet=line.strip()[:50],
                        suggestion="Use environment variable or config: model=os.getenv('LLM_MODEL', 'default')",
                    )
                    break


# ═══════════════════════════════════════════════════════════════════════════
# 10. Missing graceful degradation
# ═══════════════════════════════════════════════════════════════════════════

def check_graceful_degradation(
    *,
    content: str,
    language: str,
    config: dict[str, Any],
    add_issue: AddIssue,
) -> None:
    """
    Check if LLM-dependent code has fallback behavior.

    AI features should degrade gracefully when LLM is unavailable.
    """
    name = "graceful_degradation"
    if not _enabled(config, name, default=False):  # Disabled by default, opt-in
        return

    if language != "python":
        return

    severity = parse_severity(_rule(config, name).get("severity"), default=Severity.WARNING)

    # Check if file uses LLM APIs
    has_llm_calls = any(api in content for api in [
        'openai', 'anthropic', 'gemini',
        'chat.completions', 'messages.create',
    ])

    if not has_llm_calls:
        return

    # Check if there's fallback logic
    has_fallback = any(pattern in content.lower() for pattern in [
        'fallback',
        'default_response',
        'cached_response',
        'else:',
        'return none',
        'return {}',
        'return []',
        'graceful',
        'degrade',
    ])

    if not has_fallback:
        add_issue(
            line=1,
            rule="graceful_degradation",
            severity=severity,
            message="LLM-dependent code without apparent fallback behavior.",
            suggestion="Add fallback logic for when LLM is unavailable (cache, default response, or skip).",
        )


# ═══════════════════════════════════════════════════════════════════════════
# 11. JSON parsing without validation
# ═══════════════════════════════════════════════════════════════════════════

def check_json_response_validation(
    *,
    content: str,
    lines: list[str],
    language: str,
    config: dict[str, Any],
    add_issue: AddIssue,
) -> None:
    """
    Detect JSON parsing of LLM responses without schema validation.

    LLM JSON output can be malformed. Always validate with Pydantic or similar.
    """
    name = "json_response_validation"
    if not _enabled(config, name, default=True):
        return

    if language != "python":
        return

    severity = parse_severity(_rule(config, name).get("severity"), default=Severity.WARNING)

    # Check for json.loads usage
    for i, line in enumerate(lines, 1):
        if 'json.loads' in line or 'json.load(' in line:
            # Check surrounding context for LLM-related code
            start = max(0, i - 10)
            end = min(len(lines), i + 5)
            context = '\n'.join(lines[start:end])

            is_llm_context = any(api in context.lower() for api in [
                'response', 'completion', 'message', 'content',
                'openai', 'anthropic', 'gemini', 'llm'
            ])

            has_validation = any(val in context for val in [
                'pydantic', 'BaseModel', 'model_validate',
                'TypeAdapter', 'parse_obj', 'schema',
                'try:', 'JSONDecodeError', 'ValidationError'
            ])

            if is_llm_context and not has_validation:
                add_issue(
                    line=i,
                    rule="json_response_validation",
                    severity=severity,
                    message="Parsing JSON from LLM response without schema validation.",
                    snippet=line.strip()[:50],
                    suggestion="Use Pydantic model_validate() or wrap in try/except JSONDecodeError.",
                )


# ═══════════════════════════════════════════════════════════════════════════
# 12. Large prompt without chunking awareness
# ═══════════════════════════════════════════════════════════════════════════

def check_large_prompt_handling(
    *,
    content: str,
    lines: list[str],
    language: str,
    config: dict[str, Any],
    add_issue: AddIssue,
) -> None:
    """
    Detect patterns that might send unbounded content to LLMs.

    Large documents should be chunked or summarized before sending to LLMs.
    """
    name = "large_prompt_handling"
    if not _enabled(config, name, default=True):
        return

    if language != "python":
        return

    severity = parse_severity(_rule(config, name).get("severity"), default=Severity.WARNING)

    # Risky patterns: reading entire files into prompts
    risky_patterns = [
        (r'\.read\(\).*content', 'Reading entire file into prompt'),
        (r'open\([^)]+\)\.read\(\)', 'Reading file without size check'),
        (r'document.*content.*\+', 'Concatenating document content'),
        (r'for.*in.*documents.*content', 'Iterating all documents into prompt'),
    ]

    for i, line in enumerate(lines, 1):
        for pattern, description in risky_patterns:
            if re.search(pattern, line, re.IGNORECASE):
                # Check if there's chunking logic nearby
                context = '\n'.join(lines[max(0, i-10):min(len(lines), i+10)])
                has_chunking = any(chunk in context.lower() for chunk in [
                    'chunk', 'split', 'truncate', 'max_length',
                    'token_count', 'tiktoken', 'limit', '[:',
                ])

                if not has_chunking:
                    add_issue(
                        line=i,
                        rule="large_prompt_handling",
                        severity=severity,
                        message=f"{description}. May exceed token limits.",
                        snippet=line.strip()[:50],
                        suggestion="Add chunking, truncation, or token counting before sending to LLM.",
                    )
                    break


# ═══════════════════════════════════════════════════════════════════════════
# Main entry point - run all AI/LLM checks
# ═══════════════════════════════════════════════════════════════════════════

def check_ai_llm_patterns(
    *,
    file_path: Path,
    content: str,
    lines: list[str],
    language: str,
    config: dict[str, Any],
    add_issue: AddIssue,
) -> None:
    """Run all AI/LLM-specific checks."""

    check_missing_await(
        file_path=file_path, content=content, language=language,
        config=config, add_issue=add_issue
    )
    check_llm_timeout(
        content=content, lines=lines, language=language,
        config=config, add_issue=add_issue
    )
    check_llm_retry(
        content=content, lines=lines, language=language,
        config=config, add_issue=add_issue
    )
    check_unbounded_tokens(
        content=content, lines=lines, language=language,
        config=config, add_issue=add_issue
    )
    check_prompt_injection_risk(
        content=content, lines=lines, language=language,
        config=config, add_issue=add_issue
    )
    check_blocking_in_async(
        file_path=file_path, content=content, language=language,
        config=config, add_issue=add_issue
    )
    check_llm_response_handling(
        content=content, lines=lines, language=language,
        config=config, add_issue=add_issue
    )
    check_rate_limit_handling(
        content=content, language=language,
        config=config, add_issue=add_issue
    )
    check_hardcoded_model(
        lines=lines, language=language,
        config=config, add_issue=add_issue
    )
    check_graceful_degradation(
        content=content, language=language,
        config=config, add_issue=add_issue
    )
    check_json_response_validation(
        content=content, lines=lines, language=language,
        config=config, add_issue=add_issue
    )
    check_large_prompt_handling(
        content=content, lines=lines, language=language,
        config=config, add_issue=add_issue
    )
