"""Fix Integration for HTML Reports.

Combines deterministic fixes (from fix-engine) and optional LLM fixes
into a unified fix suggestion layer for the report.

Feature toggle:
- Deterministic fixes: always on (zero cost, zero dep)
- LLM fixes: opt-in via --llm-fixes flag + ANTHROPIC_API_KEY/OPENAI_API_KEY
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def get_deterministic_fix(rule_id: str, finding: dict, file_content: str) -> Optional[dict]:
    """Try to get a deterministic fix from the fix-engine registry.

    Returns dict with {rule, file, line, original, replacement, explanation, confidence, category, diff}
    or None if no fix available.
    """
    try:
        fe_path = str(Path(__file__).resolve().parents[1] / "fix-engine")
        if fe_path not in sys.path:
            sys.path.insert(0, fe_path)

        from fe.registry import get_fix
    except ImportError:
        return None

    fix_fn = get_fix(rule_id)
    if fix_fn is None:
        return None

    try:
        patch = fix_fn(finding, file_content, {})
        if patch is None:
            return None

        return {
            "type": "deterministic",
            "rule": patch.rule_id,
            "file": patch.file_path,
            "line": patch.line,
            "original": patch.original,
            "replacement": patch.replacement,
            "explanation": patch.explanation,
            "confidence": patch.confidence,
            "category": patch.category,
            "diff": getattr(patch, "diff", ""),
            "badge": "auto-fix",
            "badge_color": "#16a34a",
            "badge_icon": "&#x1F527;",
        }
    except Exception:
        return None


def get_llm_fix(finding: dict, file_content: str, config: dict) -> Optional[dict]:
    """Try to get an LLM-generated fix suggestion.

    Returns dict with suggestion or None if LLM not available/fails.
    """
    try:
        fe_path = str(Path(__file__).resolve().parents[1] / "fix-engine")
        if fe_path not in sys.path:
            sys.path.insert(0, fe_path)

        from fe.llm_fixes import generate_llm_fix, is_llm_available
    except ImportError:
        return None

    if not is_llm_available():
        return None

    try:
        suggestion = generate_llm_fix(finding=finding, file_content=file_content, config=config)
        if suggestion is None:
            return None

        return {
            "type": "llm",
            "rule": suggestion.rule_id,
            "file": suggestion.file_path,
            "line": suggestion.line,
            "original": suggestion.original_code,
            "replacement": suggestion.suggested_code,
            "explanation": suggestion.explanation,
            "confidence": suggestion.confidence,
            "provider": suggestion.provider,
            "model": suggestion.model,
            "tokens_used": suggestion.tokens_used,
            "badge": "ai-suggestion",
            "badge_color": "#8b5cf6",
            "badge_icon": "&#x1F916;",
        }
    except Exception:
        return None


def get_fix_for_finding(
    finding: dict,
    file_content: str,
    *,
    enable_llm: bool = False,
    config: Optional[dict] = None,
) -> Optional[dict]:
    """Get the best available fix for a finding.

    Priority: deterministic fix > LLM fix > None

    Args:
        finding: QG issue dict with rule, file, line, message
        file_content: Full text of the source file
        enable_llm: Whether to try LLM fixes for complex rules
        config: Optional config for LLM settings
    """
    # Always try deterministic first (free, fast, reliable)
    det_fix = get_deterministic_fix(finding.get("rule", ""), finding, file_content)
    if det_fix is not None:
        return det_fix

    # Try LLM if enabled and no deterministic fix exists
    if enable_llm:
        return get_llm_fix(finding, file_content, config or {})

    return None


def enrich_findings_with_fixes(
    findings: List[dict],
    root_dir: str,
    *,
    enable_llm: bool = False,
    config: Optional[dict] = None,
    max_llm_fixes: int = 20,
) -> List[dict]:
    """Enrich a list of findings with fix suggestions.

    Modifies findings in-place, adding a 'fix' key with the fix dict.
    Returns the list of findings that got fixes.
    """
    fixed = []
    llm_count = 0

    # Cache file contents to avoid re-reading
    file_cache: Dict[str, str] = {}

    for finding in findings:
        file_path = finding.get("file", "")
        if not file_path:
            continue

        # Read file content (cached)
        if file_path not in file_cache:
            full_path = os.path.join(root_dir, file_path)
            try:
                with open(full_path, encoding="utf-8", errors="ignore") as f:
                    file_cache[file_path] = f.read()
            except OSError:
                file_cache[file_path] = ""

        content = file_cache[file_path]
        if not content:
            continue

        # Check LLM budget
        use_llm = enable_llm and llm_count < max_llm_fixes

        fix = get_fix_for_finding(finding, content, enable_llm=use_llm, config=config)
        if fix:
            finding["fix"] = fix
            fixed.append(finding)
            if fix["type"] == "llm":
                llm_count += 1

    return fixed


def generate_fix_html(fix: dict) -> str:
    """Generate HTML for a fix suggestion in the report."""
    if fix is None:
        return ""

    badge_icon = fix.get("badge_icon", "")
    badge_color = fix.get("badge_color", "#6b7280")
    badge_text = "Auto-Fix" if fix["type"] == "deterministic" else "AI Suggestion"
    confidence = fix.get("confidence", "")

    # Format confidence display
    if isinstance(confidence, (int, float)):
        conf_display = f"{confidence:.0%}" if confidence <= 1 else f"{confidence}%"
    else:
        conf_display = str(confidence)

    replacement = fix.get("replacement", "").strip()
    explanation = fix.get("explanation", "")

    # Escape HTML
    import html as html_mod
    replacement_escaped = html_mod.escape(replacement)
    explanation_escaped = html_mod.escape(explanation)

    parts = [
        f'<div style="margin-top:8px;padding:10px 14px;border-radius:6px;',
        f'background:{"#f0fdf4" if fix["type"] == "deterministic" else "#f5f3ff"};',
        f'border:1px solid {"#bbf7d0" if fix["type"] == "deterministic" else "#ddd6fe"}">',
        f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">',
        f'<span style="background:{badge_color};color:white;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600">',
        f'{badge_icon} {badge_text}</span>',
        f'<span style="font-size:11px;color:#6b7280">Confidence: {conf_display}</span>',
    ]

    if fix["type"] == "llm":
        provider = fix.get("provider", "")
        model = fix.get("model", "")
        parts.append(f'<span style="font-size:11px;color:#6b7280">via {provider} ({model})</span>')

    parts.append('</div>')

    if explanation:
        parts.append(f'<div style="font-size:12px;color:#4b5563;margin-bottom:6px">{explanation_escaped}</div>')

    if replacement:
        parts.append(f'<pre style="background:#1e293b;color:#e2e8f0;padding:10px;border-radius:4px;font-size:12px;overflow-x:auto;margin:0">{replacement_escaped}</pre>')

    parts.append('</div>')
    return "".join(parts)
