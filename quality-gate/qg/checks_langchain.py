"""
LangChain / LangGraph-Specific Code Quality Checks

Targets Python files importing from langchain, langchain_core,
langchain_openai, langgraph, or langsmith.

Phase 1 rules:
1. unbounded_graph_execution (ERROR)  — Graph/agent without recursion_limit
2. missing_callbacks          (WARNING) — invoke/stream without callbacks
3. hardcoded_model_name       (WARNING) — String literal model= parameter
4. missing_retry_fallback     (WARNING) — LLM call without .with_retry()
5. unstructured_output_parsing(WARNING) — Regex/split on LLM output
6. missing_token_tracking     (INFO)    — No token/cost tracking
7. prompt_injection_vector    (ERROR)  — f-string in PromptTemplate
"""

from __future__ import annotations

import ast
import re

from .context import RuleContext, rule_config


def _enabled(ctx: RuleContext, name: str, *, default: bool = True) -> bool:
    return bool(rule_config(ctx, name).get("enabled", default))


def _severity(ctx: RuleContext, name: str, *, default: str) -> str:
    return str(rule_config(ctx, name).get("severity") or default)


# ═══════════════════════════════════════════════════════════════════════════
# Shared helpers
# ═══════════════════════════════════════════════════════════════════════════

_LANGCHAIN_IMPORT_RE = re.compile(
    r"(?:from\s+(?:langchain|langchain_core|langchain_openai|langchain_anthropic"
    r"|langchain_community|langgraph|langsmith))|(?:import\s+(?:langchain|langgraph))"
)


def _has_langchain_imports(content: str) -> bool:
    return bool(_LANGCHAIN_IMPORT_RE.search(content))


def _attr_chain(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _attr_chain(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _parse_tree(ctx: RuleContext) -> ast.AST | None:
    try:
        return ast.parse(ctx.content, filename=str(ctx.file_path))
    except SyntaxError:
        return None


# LLM class names whose invocations we care about
_LLM_CLASSES = frozenset({
    "ChatOpenAI", "ChatAnthropic", "AzureChatOpenAI", "ChatCohere",
    "ChatVertexAI", "ChatGoogleGenerativeAI", "ChatBedrock",
    "OpenAI", "Anthropic",
})

# Invocation methods on chains/llms/agents
_INVOKE_METHODS = frozenset({
    "invoke", "ainvoke", "stream", "astream", "batch", "abatch",
})


# ═══════════════════════════════════════════════════════════════════════════
# 1. unbounded_graph_execution
# ═══════════════════════════════════════════════════════════════════════════

def _check_unbounded_graph_execution(ctx: RuleContext, tree: ast.AST) -> None:
    """StateGraph.compile() without recursion_limit, AgentExecutor without max_iterations."""
    name = "unbounded_graph_execution"
    if not _enabled(ctx, name, default=True):
        return
    severity = _severity(ctx, name, default="error")

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        chain = _attr_chain(node.func)

        # Check .compile() calls (on StateGraph instances)
        if chain.endswith(".compile"):
            has_limit = any(
                kw.arg in ("recursion_limit", "interrupt_before", "interrupt_after")
                for kw in (node.keywords or [])
            )
            if not has_limit:
                ctx.add_issue(
                    file=str(ctx.file_path),
                    line=getattr(node, "lineno", 1),
                    rule=name,
                    severity=severity,
                    message="Graph .compile() without recursion_limit. Can enter infinite loops burning tokens.",
                    suggestion="Add recursion_limit= to .compile() (e.g. recursion_limit=25).",
                )

        # Check AgentExecutor instantiation
        if chain == "AgentExecutor" or chain.endswith(".AgentExecutor"):
            has_max = any(kw.arg == "max_iterations" for kw in (node.keywords or []))
            if not has_max:
                ctx.add_issue(
                    file=str(ctx.file_path),
                    line=getattr(node, "lineno", 1),
                    rule=name,
                    severity=severity,
                    message="AgentExecutor without max_iterations. Can run unbounded loops.",
                    suggestion="Add max_iterations= parameter (e.g. max_iterations=10).",
                )


# ═══════════════════════════════════════════════════════════════════════════
# 2. missing_callbacks
# ═══════════════════════════════════════════════════════════════════════════

def _check_missing_callbacks(ctx: RuleContext, tree: ast.AST) -> None:
    """.invoke/.stream calls without callbacks parameter."""
    name = "missing_callbacks"
    if not _enabled(ctx, name, default=True):
        return
    if ctx.is_test:
        return
    severity = _severity(ctx, name, default="warning")

    # Quick content check for invoke/stream patterns
    if not any(f".{m}" in ctx.content for m in _INVOKE_METHODS):
        return

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in _INVOKE_METHODS:
            continue

        # Check for callbacks in kwargs or config kwarg containing callbacks
        has_callbacks = False
        for kw in (node.keywords or []):
            if kw.arg == "callbacks":
                has_callbacks = True
                break
            if kw.arg == "config":
                # Check if config dict contains "callbacks"
                if isinstance(kw.value, ast.Dict):
                    for key in kw.value.keys:
                        if isinstance(key, ast.Constant) and key.value == "callbacks":
                            has_callbacks = True
                            break
        if has_callbacks:
            continue

        ctx.add_issue(
            file=str(ctx.file_path),
            line=getattr(node, "lineno", 1),
            rule=name,
            severity=severity,
            message=f".{node.func.attr}() call without callbacks. No observability in production.",
            suggestion="Pass callbacks= or config={'callbacks': [...]} for tracing and cost tracking.",
        )


# ═══════════════════════════════════════════════════════════════════════════
# 3. hardcoded_model_name
# ═══════════════════════════════════════════════════════════════════════════

def _check_hardcoded_model_name(ctx: RuleContext, tree: ast.AST) -> None:
    """LLM class instantiation with string literal model= parameter."""
    name = "hardcoded_model_name"
    if not _enabled(ctx, name, default=True):
        return
    if ctx.is_test:
        return
    severity = _severity(ctx, name, default="warning")

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = _attr_chain(node.func)
        short = callee.split(".")[-1] if callee else ""
        if short not in _LLM_CLASSES:
            continue

        for kw in (node.keywords or []):
            if kw.arg in ("model", "model_name"):
                if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    ctx.add_issue(
                        file=str(ctx.file_path),
                        line=getattr(node, "lineno", 1),
                        rule=name,
                        severity=severity,
                        message=f"Hardcoded model name '{kw.value.value}' in {short}(). Makes switching impossible without code changes.",
                        suggestion="Use a config variable: model=settings.LLM_MODEL or os.environ['LLM_MODEL'].",
                    )
                break  # only check model= once per call

        # Also check first positional arg (some classes accept model as pos arg)
        if node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                model_val = first.value
                if any(p in model_val.lower() for p in ("gpt", "claude", "gemini", "llama", "mistral")):
                    ctx.add_issue(
                        file=str(ctx.file_path),
                        line=getattr(node, "lineno", 1),
                        rule=name,
                        severity=severity,
                        message=f"Hardcoded model name '{model_val}' in {short}().",
                        suggestion="Use a config variable: model=settings.LLM_MODEL.",
                    )


# ═══════════════════════════════════════════════════════════════════════════
# 4. missing_retry_fallback
# ═══════════════════════════════════════════════════════════════════════════

def _check_missing_retry_fallback(ctx: RuleContext, tree: ast.AST) -> None:
    """LLM .invoke/.ainvoke calls not wrapped in .with_retry() or .with_fallback()."""
    name = "missing_retry_fallback"
    if not _enabled(ctx, name, default=True):
        return
    if ctx.is_test:
        return
    severity = _severity(ctx, name, default="warning")

    # Heuristic: check if .with_retry or .with_fallback appear in the content
    has_retry = ".with_retry" in ctx.content or ".with_fallback" in ctx.content
    if has_retry:
        return  # file-level pass — at least some retry logic exists

    # Check for tenacity/backoff decorators as alternative
    if "tenacity" in ctx.content or "backoff" in ctx.content:
        return

    # Look for invoke/ainvoke calls on LLM-like objects
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in ("invoke", "ainvoke"):
            continue
        # Check if the call chain object might be an LLM
        obj_chain = _attr_chain(node.func.value)
        if obj_chain and any(obj_chain.endswith(c) for c in ("llm", "model", "chat", "chain")):
            ctx.add_issue(
                file=str(ctx.file_path),
                line=getattr(node, "lineno", 1),
                rule=name,
                severity=severity,
                message=f"LLM .{node.func.attr}() without .with_retry() or .with_fallback(). Transient API failures will crash the app.",
                suggestion="Wrap the LLM with .with_retry(stop_after_attempt=3).with_fallback([fallback_llm]).",
            )
            break  # one finding per file is enough


# ═══════════════════════════════════════════════════════════════════════════
# 5. unstructured_output_parsing
# ═══════════════════════════════════════════════════════════════════════════

def _check_unstructured_output_parsing(ctx: RuleContext, tree: ast.AST) -> None:
    """String splitting/regex on LLM output instead of structured parsing."""
    name = "unstructured_output_parsing"
    if not _enabled(ctx, name, default=True):
        return
    severity = _severity(ctx, name, default="warning")

    # Check if structured output parsing is already used
    if ".with_structured_output" in ctx.content:
        return
    if "PydanticOutputParser" in ctx.content or "JsonOutputParser" in ctx.content:
        return

    # Look for .content.split or json.loads(*.content*) patterns
    _FRAGILE_PATTERNS = [
        re.compile(r"\.content\.split\s*\("),
        re.compile(r"\.content\.strip\s*\("),
        re.compile(r'json\.loads\s*\(.*\.content'),
        re.compile(r"\.content\s*\.\s*replace\s*\("),
    ]

    for i, line in enumerate(ctx.lines, 1):
        for pat in _FRAGILE_PATTERNS:
            if pat.search(line):
                ctx.add_issue(
                    file=str(ctx.file_path),
                    line=i,
                    rule=name,
                    severity=severity,
                    message="LLM output parsed with string methods. Fragile and breaks when output varies.",
                    snippet=line.strip()[:120],
                    suggestion="Use .with_structured_output(PydanticModel) or PydanticOutputParser for deterministic parsing.",
                )
                break  # one per line


# ═══════════════════════════════════════════════════════════════════════════
# 6. missing_token_tracking
# ═══════════════════════════════════════════════════════════════════════════

def _check_missing_token_tracking(ctx: RuleContext, tree: ast.AST) -> None:
    """Files with LLM calls but no token/cost tracking mechanism."""
    name = "missing_token_tracking"
    if not _enabled(ctx, name, default=True):
        return
    if ctx.is_test:
        return
    severity = _severity(ctx, name, default="info")

    # Check if any invoke/ainvoke call exists
    has_invoke = any(f".{m}" in ctx.content for m in ("invoke", "ainvoke"))
    if not has_invoke:
        return

    # Check for token tracking mechanisms
    _TRACKING_INDICATORS = (
        "get_openai_callback",
        "token_usage",
        "total_tokens",
        "completion_tokens",
        "prompt_tokens",
        "total_cost",
        "langsmith",
        "LangSmithCallback",
        "CostCallback",
    )
    if any(ind in ctx.content for ind in _TRACKING_INDICATORS):
        return

    ctx.add_issue(
        file=str(ctx.file_path),
        line=1,
        rule=name,
        severity=severity,
        message="LLM invocations without token/cost tracking. Cost visibility is missing.",
        suggestion="Use get_openai_callback(), LangSmith callbacks, or custom token tracking.",
    )


# ═══════════════════════════════════════════════════════════════════════════
# 7. prompt_injection_vector
# ═══════════════════════════════════════════════════════════════════════════

def _check_prompt_injection_vector(ctx: RuleContext, tree: ast.AST) -> None:
    """f-strings or .format() inside PromptTemplate/ChatPromptTemplate construction."""
    name = "prompt_injection_vector"
    if not _enabled(ctx, name, default=True):
        return
    severity = _severity(ctx, name, default="error")

    _TEMPLATE_CLASSES = frozenset({
        "PromptTemplate", "ChatPromptTemplate",
        "SystemMessagePromptTemplate", "HumanMessagePromptTemplate",
    })
    _TEMPLATE_FACTORY_METHODS = frozenset({
        "from_template", "from_messages",
    })

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        # Detect PromptTemplate(template=f"...") or PromptTemplate.from_template(f"...")
        callee = _attr_chain(node.func)
        short = callee.split(".")[-1] if callee else ""
        is_template_class = short in _TEMPLATE_CLASSES
        is_factory = short in _TEMPLATE_FACTORY_METHODS

        # Check parent for factory calls: ChatPromptTemplate.from_messages(...)
        if isinstance(node.func, ast.Attribute):
            parent_chain = _attr_chain(node.func.value)
            parent_short = parent_chain.split(".")[-1] if parent_chain else ""
            if parent_short in _TEMPLATE_CLASSES and short in _TEMPLATE_FACTORY_METHODS:
                is_factory = True

        if not is_template_class and not is_factory:
            continue

        # Check all arguments for f-strings (JoinedStr in AST)
        for arg in list(node.args or []) + [kw.value for kw in (node.keywords or [])]:
            has_fstring = False
            for sub in ast.walk(arg):
                if isinstance(sub, ast.JoinedStr):
                    has_fstring = True
                    break
                # Also catch .format() calls
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
                    if sub.func.attr == "format":
                        has_fstring = True
                        break
            if has_fstring:
                ctx.add_issue(
                    file=str(ctx.file_path),
                    line=getattr(node, "lineno", 1),
                    rule=name,
                    severity=severity,
                    message="f-string or .format() in PromptTemplate construction. Prompt injection vulnerability.",
                    suggestion="Use template variables ({variable_name}) and pass values via .invoke({'variable_name': value}).",
                )
                break  # one per template call


# ═══════════════════════════════════════════════════════════════════════════
# Main entry point
# ═══════════════════════════════════════════════════════════════════════════

def check_langchain_patterns(ctx: RuleContext) -> None:
    """Run all LangChain/LangGraph-specific checks (langchain pack)."""
    if ctx.language != "python":
        return
    if not _has_langchain_imports(ctx.content):
        return
    tree = _parse_tree(ctx)
    if tree is None:
        return

    _check_unbounded_graph_execution(ctx, tree)
    _check_missing_callbacks(ctx, tree)
    _check_hardcoded_model_name(ctx, tree)
    _check_missing_retry_fallback(ctx, tree)
    _check_unstructured_output_parsing(ctx, tree)
    _check_missing_token_tracking(ctx, tree)
    _check_prompt_injection_vector(ctx, tree)
