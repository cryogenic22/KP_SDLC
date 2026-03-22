"""AI-Generated Code Detection + Teaching Rules.

Detects patterns common in unreviewed AI-generated code and teaches
the right approach through suggestions. The goal is not to penalize
AI usage — it's to ensure AI-generated code meets the same standard
as human-written code.

Rules:
- AI-PY-OVER-COMMENTING: Comments that restate the next line of code
- AI-PY-VERBOSE-NOOP-HANDLER: try/except that does nothing (raise, pass)
- AI-PY-EXCESSIVE-DOCSTRING: Docstrings longer than the function body
- AI-PY-REDUNDANT-TYPE-CHECK: isinstance() on type-hinted parameters
- AI-PY-GENERIC-NAMES: Functions dominated by generic variable names
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, List


# Generic variable names that suggest copy-paste / no domain context
_GENERIC_NAMES = {
    "data", "result", "temp", "tmp", "output", "ret", "val", "value",
    "res", "obj", "item", "element", "info", "stuff", "thing",
}

# Minimum generic names in a single function to trigger
_GENERIC_THRESHOLD = 4

# Words that make a comment "meaningful" (explains why, not what)
_MEANINGFUL_WORDS = re.compile(
    r"\b(?:because|since|per|required|workaround|hack|todo|fixme|"
    r"note|caveat|bug|issue|ticket|see|ref|docs|section|spec|"
    r"contract|amendment|compliance|legacy|deprecated|temporary|"
    r"optimization|performance|security|safety|race condition|"
    r"thread|concurrent|atomic|idempotent|backward|compat)\b",
    re.IGNORECASE,
)


def check_ai_code_quality(
    *,
    file_path: Path,
    content: str,
    lines: List[str],
    add_issue: Callable,
) -> None:
    """Run AI code quality detection and teaching checks."""
    _check_over_commenting(lines=lines, add_issue=add_issue)
    _check_verbose_noop_handler(lines=lines, add_issue=add_issue)
    _check_excessive_docstring(lines=lines, add_issue=add_issue)
    _check_redundant_type_check(lines=lines, content=content, add_issue=add_issue)
    _check_generic_names(lines=lines, add_issue=add_issue)


def _check_over_commenting(*, lines: List[str], add_issue: Callable) -> None:
    """AI-PY-OVER-COMMENTING: Comments that restate the next line."""
    for i in range(len(lines) - 1):
        stripped = lines[i].strip()
        if not stripped.startswith("#"):
            continue

        comment_text = stripped.lstrip("#").strip().lower()
        if len(comment_text) < 5:
            continue

        # Skip meaningful comments (explain why, not what)
        if _MEANINGFUL_WORDS.search(comment_text):
            continue

        # Get next non-empty line
        next_line = ""
        for j in range(i + 1, min(i + 3, len(lines))):
            if lines[j].strip():
                next_line = lines[j].strip().lower()
                break

        if not next_line or next_line.startswith("#"):
            continue

        # Check if comment is a restatement of the code
        # Extract key tokens from the code line
        code_tokens = set(re.findall(r'[a-z_]+', next_line))
        comment_tokens = set(re.findall(r'[a-z_]+', comment_text))

        # Remove very common words
        noise = {"the", "a", "an", "to", "is", "of", "in", "and", "or", "it", "for", "on", "as", "at", "by", "this", "that", "with", "from"}
        comment_clean = comment_tokens - noise
        code_clean = code_tokens - noise - {"self", "return", "def", "class", "if", "else", "elif", "while", "for", "import", "from", "not", "true", "false", "none"}

        if len(comment_clean) < 2:
            continue

        # Restatement detection:
        # 1. >60% of comment words appear in the code, OR
        # 2. Comment is a verb+noun that describes the assignment (e.g., "Set the value" → value = 5)
        overlap = comment_clean & code_clean
        is_restatement = len(overlap) >= max(2, len(comment_clean) * 0.6)

        # Check for "verb the variable" pattern: the comment's nouns match a variable in the code
        if not is_restatement and len(overlap) >= 1 and len(comment_clean) <= 4:
            # Short comment with at least one code token match → likely restatement
            verbs = {"set", "get", "create", "make", "initialize", "init", "define",
                     "declare", "assign", "update", "increment", "decrement", "add",
                     "remove", "delete", "check", "calculate", "compute", "call",
                     "return", "print", "import", "load", "save", "store", "fetch",
                     "send", "receive", "open", "close", "start", "stop", "run",
                     "execute", "process", "handle", "convert", "parse", "format"}
            comment_verbs = comment_clean & verbs
            comment_nouns = comment_clean - verbs
            # If comment = verb + code_token, it's restating
            if comment_verbs and comment_nouns and comment_nouns.issubset(code_clean):
                is_restatement = True

        if is_restatement:
            add_issue(
                line=i + 1,
                rule="AI-PY-OVER-COMMENTING",
                severity="info",
                message=f"Comment restates the code. AI-generated code often adds comments that describe what the code does rather than why.",
                suggestion="Delete this comment, or replace it with WHY context: a business reason, a bug reference, a non-obvious constraint. Good comments answer 'why is this here?' not 'what does this line do?'.",
            )


def _check_verbose_noop_handler(*, lines: List[str], add_issue: Callable) -> None:
    """AI-PY-VERBOSE-NOOP-HANDLER: try/except that does nothing useful."""
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()

        # Look for except lines
        if not stripped.startswith("except"):
            i += 1
            continue

        except_indent = len(lines[i]) - len(lines[i].lstrip())

        # Scan except body
        body_lines = []
        j = i + 1
        while j < len(lines):
            if not lines[j].strip():
                j += 1
                continue
            line_indent = len(lines[j]) - len(lines[j].lstrip())
            if line_indent <= except_indent and lines[j].strip():
                break
            body_lines.append(lines[j].strip())
            j += 1

        # Check if body is just "raise" or "pass" (with optional comments)
        meaningful = [l for l in body_lines if l and not l.startswith("#")]

        is_noop = False
        if len(meaningful) == 1:
            if meaningful[0] == "raise" or meaningful[0] == "pass":
                is_noop = True
            elif meaningful[0].startswith("pass") and "#" in meaningful[0]:
                is_noop = True  # pass  # ignore errors

        if is_noop:
            action = meaningful[0].split()[0]  # "raise" or "pass"
            add_issue(
                line=i + 1,
                rule="AI-PY-VERBOSE-NOOP-HANDLER",
                severity="warning",
                message=f"Exception handler only does `{action}` — this is a no-op pattern common in AI-generated code.",
                suggestion=f"Either remove the try/except entirely (if `{action}` is the intent), or add meaningful handling: log the error, emit a metric, set a fallback value, or translate to a domain-specific exception.",
            )

        i = j


def _check_excessive_docstring(*, lines: List[str], add_issue: Callable) -> None:
    """AI-PY-EXCESSIVE-DOCSTRING: Docstrings longer than function body."""
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped.startswith("def "):
            i += 1
            continue

        func_indent = len(lines[i]) - len(lines[i].lstrip())
        func_line = i

        # Find docstring
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1

        if j >= len(lines):
            i = j
            continue

        first_body = lines[j].strip()
        if not (first_body.startswith('"""') or first_body.startswith("'''")):
            i = j
            continue

        # Count docstring lines
        quote = first_body[:3]
        doc_start = j
        if first_body.endswith(quote) and len(first_body) > 6:
            # Single-line docstring
            doc_end = j
        else:
            doc_end = j + 1
            while doc_end < len(lines):
                if quote in lines[doc_end]:
                    break
                doc_end += 1

        doc_lines = doc_end - doc_start + 1

        # Count body lines (after docstring, until next def/class at same indent or dedent)
        body_start = doc_end + 1
        body_end = body_start
        while body_end < len(lines):
            line = lines[body_end]
            if not line.strip():
                body_end += 1
                continue
            line_indent = len(line) - len(line.lstrip())
            if line_indent <= func_indent and line.strip() and not line.strip().startswith("#"):
                break
            body_end += 1

        body_code_lines = sum(
            1 for k in range(body_start, body_end)
            if lines[k].strip() and not lines[k].strip().startswith("#")
        )

        # Flag if docstring is longer than body (with minimum thresholds)
        if doc_lines > 3 and body_code_lines > 0 and doc_lines > body_code_lines * 2:
            add_issue(
                line=doc_start + 1,
                rule="AI-PY-EXCESSIVE-DOCSTRING",
                severity="info",
                message=f"Docstring ({doc_lines} lines) is longer than function body ({body_code_lines} lines). AI tools tend to generate verbose docstrings that add noise.",
                suggestion="Trim to a one-line summary. If the function needs a long docstring to explain, the function is probably doing too much. Good rule: docstring should be shorter than the code it documents.",
            )

        i = body_end


def _check_redundant_type_check(*, lines: List[str], content: str, add_issue: Callable) -> None:
    """AI-PY-REDUNDANT-TYPE-CHECK: isinstance() on type-hinted parameters."""
    # Find function definitions with type hints
    func_pattern = re.compile(r"def\s+\w+\s*\(([^)]*)\)")
    isinstance_pattern = re.compile(r"isinstance\s*\(\s*(\w+)\s*,")

    for i, line in enumerate(lines):
        match = func_pattern.search(line)
        if not match:
            continue

        params = match.group(1)
        # Extract typed parameter names
        typed_params = set()
        for param in params.split(","):
            param = param.strip()
            if ":" in param:
                name = param.split(":")[0].strip().lstrip("*")
                if name and name != "self":
                    typed_params.add(name)

        if not typed_params:
            continue

        # Scan function body for isinstance checks on typed params
        func_indent = len(line) - len(line.lstrip())
        for j in range(i + 1, min(i + 30, len(lines))):
            if lines[j].strip() and not lines[j].strip().startswith("#"):
                body_indent = len(lines[j]) - len(lines[j].lstrip())
                if body_indent <= func_indent and lines[j].strip():
                    break

            ist_match = isinstance_pattern.search(lines[j])
            if ist_match and ist_match.group(1) in typed_params:
                add_issue(
                    line=j + 1,
                    rule="AI-PY-REDUNDANT-TYPE-CHECK",
                    severity="info",
                    message=f"isinstance() check on type-hinted parameter '{ist_match.group(1)}'. AI-generated code often adds defensive checks that duplicate the type system.",
                    suggestion="Remove the isinstance check — the type hint already documents the contract. Validate at system boundaries (user input, API responses), not inside typed internal functions. Use mypy/pyright to enforce types statically.",
                )


def _check_generic_names(*, lines: List[str], add_issue: Callable) -> None:
    """AI-PY-GENERIC-NAMES: Functions with too many generic variable names."""
    func_pattern = re.compile(r"^\s*def\s+(\w+)\s*\(")
    assign_pattern = re.compile(r"^\s+(\w+)\s*=")

    i = 0
    while i < len(lines):
        match = func_pattern.match(lines[i])
        if not match:
            i += 1
            continue

        func_name = match.group(1)
        func_indent = len(lines[i]) - len(lines[i].lstrip())

        # Collect variable names in function body
        generic_found = set()
        j = i + 1
        while j < len(lines):
            line = lines[j]
            if not line.strip():
                j += 1
                continue
            line_indent = len(line) - len(line.lstrip())
            if line_indent <= func_indent and line.strip():
                break

            var_match = assign_pattern.match(line)
            if var_match:
                name = var_match.group(1).lower()
                if name in _GENERIC_NAMES:
                    generic_found.add(name)

            j += 1

        if len(generic_found) >= _GENERIC_THRESHOLD:
            add_issue(
                line=i + 1,
                rule="AI-PY-GENERIC-NAMES",
                severity="info",
                message=f"Function '{func_name}' uses {len(generic_found)} generic variable names ({', '.join(sorted(generic_found))}). This pattern is common in AI-generated code that lacks domain context.",
                suggestion=f"Rename variables to reflect the domain: instead of 'data' use 'invoice_data', instead of 'result' use 'validation_result'. When prompting AI, include your project's naming conventions and domain glossary in the context.",
            )

        i = j
