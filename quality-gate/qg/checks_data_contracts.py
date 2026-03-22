"""
Data Contract & Schema Validation Checks (DATA-*)

Data quality is the #1 failure mode in production AI systems.
These rules enforce schema validation on external data boundaries:

- DATA-SCHEMA-NO-VALIDATION: External JSON parsed without schema validation
- DATA-RAW-DICT-ACCESS: Direct dict["key"] on unvalidated API responses
- DATA-PIPELINE-NO-RETRY: Celery/Airflow tasks without retry configuration
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

# Patterns for early-exit relevance check
_RELEVANT_PATTERNS = re.compile(
    r"json\.loads|\.json\(\)|@app\.task|PythonOperator\("
)

# ── Patterns for DATA-SCHEMA-NO-VALIDATION ──────────────────────────────

# Matches json.loads(response...) or json.loads(resp...) — external data
_JSON_LOADS_EXTERNAL = re.compile(
    r"json\.loads\s*\(\s*response"
)

# Matches <var> = response.json()
_RESPONSE_JSON = re.compile(
    r"=\s*\w+\.json\(\)"
)

# Matches json.loads on file-read patterns (internal data — don't flag)
_JSON_LOADS_FILE = re.compile(
    r"json\.loads\s*\(\s*\w+\.read\(\)"
)

# Validation patterns that indicate proper schema handling
_VALIDATION_PATTERNS = re.compile(
    r"model_validate|parse_obj|BaseModel|validate\s*\(|schema"
)

# ── Patterns for DATA-RAW-DICT-ACCESS ───────────────────────────────────

# Captures: <var> = response.json() or <var> = json.loads(response...)
_DATA_VAR_ASSIGNMENT = re.compile(
    r"(\w+)\s*=\s*(?:response\.json\(\)|.*\.json\(\)|json\.loads\s*\(\s*response)"
)

# Matches direct dict access: var["key"]
_DICT_BRACKET_ACCESS = re.compile(
    r'(\w+)\["[^"]+"\]'
)

# ── Patterns for DATA-PIPELINE-NO-RETRY ─────────────────────────────────

# Celery task decorator without arguments or without retry keywords
_CELERY_TASK_BARE = re.compile(r"@app\.task\s*$")
_CELERY_TASK_WITH_ARGS = re.compile(r"@app\.task\(([^)]*)\)")
_CELERY_RETRY_KEYWORDS = re.compile(r"max_retries|autoretry_for|\bretry\b")

# Airflow PythonOperator
_AIRFLOW_PYTHON_OP = re.compile(r"PythonOperator\(")


def check_data_contracts(
    *,
    file_path: Path,
    content: str,
    lines: list[str],
    add_issue: Callable,
) -> None:
    """Run all DATA-* checks on the given file content."""

    # Early exit if file has no relevant patterns
    if not _RELEVANT_PATTERNS.search(content):
        return

    _check_schema_no_validation(lines=lines, content=content, add_issue=add_issue)
    _check_raw_dict_access(lines=lines, content=content, add_issue=add_issue)
    _check_pipeline_no_retry(lines=lines, content=content, add_issue=add_issue)


# ═══════════════════════════════════════════════════════════════════════════
# DATA-SCHEMA-NO-VALIDATION
# ═══════════════════════════════════════════════════════════════════════════

def _check_schema_no_validation(
    *, lines: list[str], content: str, add_issue: Callable
) -> None:
    """Flag json.loads(response...) or response.json() not followed by validation."""

    for i, line in enumerate(lines):
        lineno = i + 1

        # Check for json.loads on file reads — skip those
        if _JSON_LOADS_FILE.search(line):
            continue

        # Check if this line contains external JSON parsing
        is_external_json = (
            _JSON_LOADS_EXTERNAL.search(line) or _RESPONSE_JSON.search(line)
        )
        if not is_external_json:
            continue

        # Look ahead ~10 lines for validation
        lookahead_end = min(i + 11, len(lines))
        lookahead = "\n".join(lines[i + 1 : lookahead_end])

        if _VALIDATION_PATTERNS.search(lookahead):
            continue

        add_issue(
            line=lineno,
            rule="DATA-SCHEMA-NO-VALIDATION",
            severity="warning",
            message="External JSON parsed without schema/Pydantic validation.",
            suggestion=(
                "Validate with Pydantic (model_validate) or jsonschema "
                "(validate) immediately after parsing."
            ),
        )


# ═══════════════════════════════════════════════════════════════════════════
# DATA-RAW-DICT-ACCESS
# ═══════════════════════════════════════════════════════════════════════════

def _check_raw_dict_access(
    *, lines: list[str], content: str, add_issue: Callable
) -> None:
    """Flag direct data['key'] access on variables that came from response.json() / json.loads(response...)."""

    # First pass: collect variable names assigned from external JSON
    external_vars: set[str] = set()
    for line in lines:
        # Skip file-read patterns
        if _JSON_LOADS_FILE.search(line):
            continue
        m = _DATA_VAR_ASSIGNMENT.search(line)
        if m:
            external_vars.add(m.group(1))

    if not external_vars:
        return

    # Second pass: find bracket access on those variables
    for i, line in enumerate(lines):
        lineno = i + 1
        for m in _DICT_BRACKET_ACCESS.finditer(line):
            var_name = m.group(1)
            if var_name in external_vars:
                add_issue(
                    line=lineno,
                    rule="DATA-RAW-DICT-ACCESS",
                    severity="warning",
                    message=f'Direct dict["key"] access on unvalidated API response variable `{var_name}`.',
                    suggestion="Use .get() with a default value for safer access.",
                )
                # Only flag once per line per variable
                break


# ═══════════════════════════════════════════════════════════════════════════
# DATA-PIPELINE-NO-RETRY
# ═══════════════════════════════════════════════════════════════════════════

def _check_pipeline_no_retry(
    *, lines: list[str], content: str, add_issue: Callable
) -> None:
    """Flag Celery tasks and Airflow PythonOperator without retry config."""

    for i, line in enumerate(lines):
        lineno = i + 1

        # Celery: @app.task without retry params
        if _CELERY_TASK_BARE.search(line.strip()):
            add_issue(
                line=lineno,
                rule="DATA-PIPELINE-NO-RETRY",
                severity="warning",
                message="Celery task without retry configuration.",
                suggestion=(
                    "Add retry config: @app.task(bind=True, max_retries=3, "
                    "default_retry_delay=60)"
                ),
            )
            continue

        m = _CELERY_TASK_WITH_ARGS.search(line)
        if m:
            args_text = m.group(1)
            if not _CELERY_RETRY_KEYWORDS.search(args_text):
                add_issue(
                    line=lineno,
                    rule="DATA-PIPELINE-NO-RETRY",
                    severity="warning",
                    message="Celery task without retry configuration.",
                    suggestion=(
                        "Add retry config: @app.task(bind=True, max_retries=3, "
                        "default_retry_delay=60)"
                    ),
                )
            continue

        # Airflow: PythonOperator without retries
        if _AIRFLOW_PYTHON_OP.search(line):
            # Look ahead for the closing paren to capture all arguments
            lookahead_end = min(i + 15, len(lines))
            block = "\n".join(lines[i : lookahead_end])
            # Find the complete PythonOperator(...) call
            paren_depth = 0
            op_text = ""
            for j in range(i, lookahead_end):
                op_text += lines[j] + "\n"
                paren_depth += lines[j].count("(") - lines[j].count(")")
                if paren_depth <= 0:
                    break

            if "retries" not in op_text:
                add_issue(
                    line=lineno,
                    rule="DATA-PIPELINE-NO-RETRY",
                    severity="warning",
                    message="Airflow PythonOperator without retries parameter.",
                    suggestion="Add retries=3 to the PythonOperator arguments.",
                )
