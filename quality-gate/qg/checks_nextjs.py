"""Next.js / React technology pack — 4 rules.

Rules:
  useeffect_dependency_array  WARNING  Incorrect useEffect deps
  server_client_boundary      ERROR    Client hooks in server components
  missing_error_boundary      INFO     page.tsx without error.tsx
  unoptimised_images          WARNING  Raw <img> instead of next/image
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from qg.context import RuleContext, rule_config

# ── helpers ────────────────────────────────────────────────────────

_CLIENT_HOOKS = {
    "useState", "useEffect", "useRef", "useContext", "useReducer",
    "useCallback", "useMemo", "useLayoutEffect", "useImperativeHandle",
    "useSyncExternalStore", "useTransition", "useDeferredValue",
}

_CLIENT_EVENT_HANDLERS = {
    "onClick", "onChange", "onSubmit", "onBlur", "onFocus",
    "onKeyDown", "onKeyUp", "onMouseEnter", "onMouseLeave",
}


def _enabled(ctx: RuleContext, rule: str) -> bool:
    cfg = rule_config(ctx, rule)
    return cfg.get("enabled", True) is not False


def _severity(ctx: RuleContext, rule: str, default: str) -> str:
    cfg = rule_config(ctx, rule)
    return str(cfg.get("severity", default)).lower()


def _is_app_dir_file(ctx: RuleContext) -> bool:
    """Check if file is inside an app/ directory (Next.js App Router)."""
    rel = str(ctx.file_path).replace("\\", "/")
    return "/app/" in rel or rel.startswith("app/")


def _has_use_client(content: str) -> bool:
    """Check if file has 'use client' directive at the top."""
    for line in content.splitlines()[:5]:
        stripped = line.strip().strip(";")
        if stripped in ('"use client"', "'use client'"):
            return True
    return False


# ── public entry point ─────────────────────────────────────────────

def check_nextjs_patterns(ctx: RuleContext) -> None:
    if ctx.language not in ("typescript", "javascript"):
        return

    _check_useeffect_dependency_array(ctx)
    _check_server_client_boundary(ctx)
    _check_missing_error_boundary(ctx)
    _check_unoptimised_images(ctx)


# ── rule implementations ──────────────────────────────────────────

def _check_useeffect_dependency_array(ctx: RuleContext) -> None:
    """Flag useEffect with missing or empty dependency arrays."""
    rule = "useeffect_dependency_array"
    if not _enabled(ctx, rule):
        return
    sev = _severity(ctx, rule, "warning")

    if "useEffect" not in ctx.content:
        return

    # Pattern 1: useEffect(() => { ... }) — no dependency array at all
    # This is tricky to detect perfectly with regex. We look for useEffect(
    # followed by arrow or function, and count parens to find closing.
    # Simpler heuristic: find lines with useEffect( and check if the
    # matching ); on same/next lines has [] before it.

    # Pattern 2: useEffect(() => { ... }, []) — empty array
    empty_deps_pat = re.compile(r"useEffect\s*\(\s*(?:\(\)|[^)]*=>)", re.MULTILINE)

    for i, line in enumerate(ctx.lines, 1):
        if "useEffect(" not in line:
            continue

        # Check for missing dependency array: useEffect(fn) with no second arg
        # Look ahead for the closing of useEffect
        window = "\n".join(ctx.lines[i - 1:min(i + 10, len(ctx.lines))])

        # Count balanced parens to find the useEffect closing
        # Simple heuristic: if the closing ); doesn't have , [...] before it
        no_deps = re.search(r"useEffect\s*\([^,]*\)\s*;?", window, re.DOTALL)
        if no_deps:
            # Make sure it's not a false positive with arrow function
            match_text = no_deps.group(0)
            if "=>" in match_text and "," not in match_text.split("=>", 1)[1]:
                ctx.add_issue(
                    line=i,
                    rule=rule,
                    severity=sev,
                    message="useEffect without dependency array. Runs on every render.",
                    suggestion="Add a dependency array: useEffect(() => { ... }, [deps])",
                )
                continue

        # Check for empty deps with external references
        if re.search(r",\s*\[\s*\]\s*\)", window):
            ctx.add_issue(
                line=i,
                rule=rule,
                severity="info",  # downgrade: empty deps may be intentional
                message="useEffect with empty dependency array []. Ensure no external state is referenced.",
                suggestion="If the effect uses props or state, add them to the dependency array.",
            )


def _check_useeffect_missing_deps(
    *,
    file_path: Path,
    lines: list[str],
    add_issue,
    severity: str = "warning",
) -> None:
    """Standalone check: flag useEffect calls with no dependency array.

    Detects: useEffect(() => { ... }) — closing ) with no , [...] before it.
    Passes: useEffect(() => { ... }, []) and useEffect(() => { ... }, [dep]).

    This is a more robust implementation than the regex in
    _check_useeffect_dependency_array, using brace/paren counting.
    """
    content = "\n".join(lines)
    if "useEffect" not in content:
        return

    i = 0
    while i < len(lines):
        line = lines[i]
        if "useEffect(" not in line:
            i += 1
            continue

        # Found a useEffect call. Scan forward to find the matching closing ).
        # Track brace depth (for the callback body) and look for , [ after it.
        start_line = i
        # Collect the full useEffect(...) span
        paren_depth = 0
        found_open = False
        has_comma_bracket = False
        j = i
        while j < len(lines):
            for ch in lines[j]:
                if ch == '(':
                    paren_depth += 1
                    found_open = True
                elif ch == ')':
                    paren_depth -= 1
                    if found_open and paren_depth == 0:
                        # Found the end. Check if there's , [...] in the span.
                        span = "\n".join(lines[i:j + 1])
                        # Look for a comma followed by [ (the deps array)
                        # after the callback body
                        if re.search(r",\s*\[", span):
                            has_comma_bracket = True
                        j = len(lines)  # break outer
                        break
            j += 1

        if found_open and not has_comma_bracket:
            add_issue(
                line=start_line + 1,
                rule="useeffect_missing_deps",
                severity=severity,
                message="useEffect without dependency array. Runs on every render.",
                suggestion="Add a dependency array: useEffect(() => { ... }, [deps])",
            )

        i = start_line + 1


def _check_server_client_boundary(ctx: RuleContext) -> None:
    """Flag client hooks/events in server components (no 'use client')."""
    rule = "server_client_boundary"
    if not _enabled(ctx, rule):
        return
    sev = _severity(ctx, rule, "error")

    if not _is_app_dir_file(ctx):
        return
    if _has_use_client(ctx.content):
        return

    # Check for client-only APIs
    for i, line in enumerate(ctx.lines, 1):
        for hook in _CLIENT_HOOKS:
            # Match import { useState } or direct usage useState(
            if re.search(rf"\b{hook}\b", line):
                # Confirm it's actual usage, not just a comment
                stripped = line.strip()
                if stripped.startswith("//") or stripped.startswith("/*"):
                    continue
                ctx.add_issue(
                    line=i,
                    rule=rule,
                    severity=sev,
                    message=f"Client hook '{hook}' used in server component (missing 'use client' directive).",
                    suggestion="Add '\"use client\"' as the first line of the file.",
                )
                return  # One finding per file is sufficient

        for handler in _CLIENT_EVENT_HANDLERS:
            if f"{handler}=" in line or f"{handler} =" in line:
                stripped = line.strip()
                if stripped.startswith("//") or stripped.startswith("/*"):
                    continue
                ctx.add_issue(
                    line=i,
                    rule=rule,
                    severity=sev,
                    message=f"Event handler '{handler}' in server component (missing 'use client' directive).",
                    suggestion="Add '\"use client\"' as the first line of the file.",
                )
                return


def _check_missing_error_boundary(ctx: RuleContext) -> None:
    """Flag page.tsx without a sibling error.tsx."""
    rule = "missing_error_boundary"
    if not _enabled(ctx, rule):
        return
    sev = _severity(ctx, rule, "info")

    if not _is_app_dir_file(ctx):
        return
    if ctx.file_path.name not in ("page.tsx", "page.jsx", "page.ts", "page.js"):
        return

    # Check for error.tsx at same level or any parent within app/
    check_dir = ctx.file_path.parent
    found_error = False
    while True:
        for ext in (".tsx", ".jsx", ".ts", ".js"):
            if (check_dir / f"error{ext}").exists():
                found_error = True
                break
        if found_error:
            break
        rel = str(check_dir).replace("\\", "/")
        if rel.endswith("/app") or "/app" not in rel:
            break
        check_dir = check_dir.parent

    if not found_error:
        ctx.add_issue(
            line=1,
            rule=rule,
            severity=sev,
            message=f"Page component without error boundary. No error.tsx found in directory tree.",
            suggestion="Create error.tsx in the same directory to handle component errors gracefully.",
        )


def _check_unoptimised_images(ctx: RuleContext) -> None:
    """Flag raw <img> tags in Next.js app files."""
    rule = "unoptimised_images"
    if not _enabled(ctx, rule):
        return
    sev = _severity(ctx, rule, "warning")

    if not _is_app_dir_file(ctx):
        # Also check pages/ directory
        rel = str(ctx.file_path).replace("\\", "/")
        if "/pages/" not in rel:
            return

    img_pat = re.compile(r"<img\b", re.IGNORECASE)

    for i, line in enumerate(ctx.lines, 1):
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("/*"):
            continue
        if img_pat.search(line):
            ctx.add_issue(
                line=i,
                rule=rule,
                severity=sev,
                message="Raw <img> tag. Use next/image <Image> for automatic optimisation.",
                suggestion='import Image from "next/image"; <Image src="..." width={} height={} />',
            )
