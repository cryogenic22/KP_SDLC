"""
AI Code Smell Detection

Technology-agnostic rules that detect structural patterns characteristic
of AI-generated code: dead variables, redundant computation, O(n²) loops,
and unused parameters.  Applies to all Python files.

Phase 1 rules:
1. dead_variable           (WARNING) — Assigned but never read
2. nested_enumeration      (WARNING) — O(n²) nested loops on static collections
3. linear_search_in_loop   (WARNING) — ``if x in list`` inside loop
4. redundant_recomputation (WARNING) — Same pure call repeated in function
5. dead_parameters         (WARNING) — Function params never used in body

Phase 4 rules:
6. excessive_defensive_checks (INFO) — Too many isinstance/hasattr/None checks per function
7. over_abstraction           (INFO) — ABC/Protocol with only one implementation (per-file)
8. redundant_containment_check(INFO) — Containment checks in bottom-up tree processing
9. code_to_complexity_ratio   (INFO) — Private-to-public function ratio too high
"""

from __future__ import annotations

import ast
from collections import defaultdict

from .context import RuleContext, rule_config


def _enabled(ctx: RuleContext, name: str, *, default: bool = True) -> bool:
    return bool(rule_config(ctx, name).get("enabled", default))


def _severity(ctx: RuleContext, name: str, *, default: str) -> str:
    return str(rule_config(ctx, name).get("severity") or default)


def _parse_tree(ctx: RuleContext) -> ast.AST | None:
    try:
        return ast.parse(ctx.content, filename=str(ctx.file_path))
    except SyntaxError:
        return None


def _attr_chain(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _attr_chain(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


# ═══════════════════════════════════════════════════════════════════════════
# 1. dead_variable
# ═══════════════════════════════════════════════════════════════════════════

class _ScopeAnalyser(ast.NodeVisitor):
    """Collect assigned and loaded names within a function scope."""

    def __init__(self) -> None:
        self.assigned: dict[str, int] = {}      # name → first assignment line
        self.loaded: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Store):
            if node.id not in self.assigned:
                self.assigned[node.id] = getattr(node, "lineno", 1)
        elif isinstance(node.ctx, (ast.Load, ast.Del)):
            self.loaded.add(node.id)
        self.generic_visit(node)

    # Don't descend into nested functions/classes — they are separate scopes
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        # The function *name* is assigned in the outer scope
        if node.name not in self.assigned:
            self.assigned[node.name] = getattr(node, "lineno", 1)
        self.loaded.add(node.name)  # treat nested def name as "used"

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if node.name not in self.assigned:
            self.assigned[node.name] = getattr(node, "lineno", 1)
        self.loaded.add(node.name)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if node.name not in self.assigned:
            self.assigned[node.name] = getattr(node, "lineno", 1)
        self.loaded.add(node.name)


def _check_dead_variable(ctx: RuleContext, tree: ast.AST) -> None:
    name = "dead_variable"
    if not _enabled(ctx, name, default=True):
        return
    severity = _severity(ctx, name, default="warning")

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        # Skip very short functions — false-positive risk
        if len(node.body) < 3:
            continue

        analyser = _ScopeAnalyser()
        for child in node.body:
            analyser.visit(child)

        for var, line in analyser.assigned.items():
            if var.startswith("_"):
                continue
            if var in analyser.loaded:
                continue
            ctx.add_issue(
                file=str(ctx.file_path),
                line=line,
                rule=name,
                severity=severity,
                message=f"Variable '{var}' is assigned but never read in '{node.name}'.",
                suggestion=f"Remove '{var}' if unused, or use it in place of redundant recomputation.",
            )


# ═══════════════════════════════════════════════════════════════════════════
# 2. nested_enumeration
# ═══════════════════════════════════════════════════════════════════════════

def _check_nested_enumeration(ctx: RuleContext, tree: ast.AST) -> None:
    """Nested for-loops where inner iterable doesn't change — O(n²) smell."""
    name = "nested_enumeration"
    if not _enabled(ctx, name, default=True):
        return
    severity = _severity(ctx, name, default="warning")

    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(func):
            if not isinstance(node, (ast.For, ast.AsyncFor)):
                continue
            outer_line = getattr(node, "lineno", 1)
            # Look for inner for loops
            for child in ast.walk(node):
                if child is node:
                    continue
                if not isinstance(child, (ast.For, ast.AsyncFor)):
                    continue
                inner_iter = _attr_chain(child.iter)
                if not inner_iter:
                    continue
                # Check if inner iterable is a simple name (not modified in outer loop)
                # This is a heuristic — we check that the iterable is a name/attr
                # and is not assigned inside the outer loop body
                outer_stores: set[str] = set()
                for s in ast.walk(node):
                    if isinstance(s, ast.Name) and isinstance(s.ctx, ast.Store):
                        outer_stores.add(s.id)
                root_name = inner_iter.split(".")[0]
                if root_name not in outer_stores:
                    ctx.add_issue(
                        file=str(ctx.file_path),
                        line=outer_line,
                        rule=name,
                        severity=severity,
                        message=(
                            f"Nested loop over '{inner_iter}' (line {getattr(child, 'lineno', '?')}) "
                            f"inside outer loop. O(n²) when a lookup/index would be O(n)."
                        ),
                        suggestion="Build an index (dict/set) from the inner collection before the outer loop.",
                    )
                    break  # one finding per outer loop


# ═══════════════════════════════════════════════════════════════════════════
# 3. linear_search_in_loop
# ═══════════════════════════════════════════════════════════════════════════

def _check_linear_search_in_loop(ctx: RuleContext, tree: ast.AST) -> None:
    """``if x in some_list`` inside a for loop where some_list is a list."""
    name = "linear_search_in_loop"
    if not _enabled(ctx, name, default=True):
        return
    severity = _severity(ctx, name, default="warning")

    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        # Collect names assigned from list constructors in this function
        list_vars: set[str] = set()
        for node in ast.walk(func):
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                tgt = node.targets[0]
                if isinstance(tgt, ast.Name):
                    val = node.value
                    if isinstance(val, (ast.List, ast.ListComp)):
                        list_vars.add(tgt.id)
                    elif isinstance(val, ast.Call) and _attr_chain(val.func) == "list":
                        list_vars.add(tgt.id)

        if not list_vars:
            continue

        # Find `if x in list_var` inside for loops
        for node in ast.walk(func):
            if not isinstance(node, (ast.For, ast.AsyncFor)):
                continue
            for child in ast.walk(node):
                if not isinstance(child, ast.Compare):
                    continue
                for op, comparator in zip(child.ops, child.comparators):
                    if not isinstance(op, ast.In):
                        continue
                    comp_name = _attr_chain(comparator)
                    if comp_name in list_vars:
                        ctx.add_issue(
                            file=str(ctx.file_path),
                            line=getattr(child, "lineno", 1),
                            rule=name,
                            severity=severity,
                            message=f"'in {comp_name}' inside loop — O(n) per check on a list. Total O(m×n).",
                            suggestion=f"Convert '{comp_name}' to a set before the loop for O(1) lookups.",
                        )


# ═══════════════════════════════════════════════════════════════════════════
# 4. redundant_recomputation
# ═══════════════════════════════════════════════════════════════════════════

def _call_sig(node: ast.Call) -> str | None:
    """Return a hashable string representing the call, or None if impure/complex."""
    func_chain = _attr_chain(node.func)
    if not func_chain:
        return None
    # Exclude obviously impure calls and calls whose results may differ
    # between invocations (DB queries, API calls, I/O operations).
    # Team Feedback #9: DB/API calls caused 480 false positives.
    _IMPURE = {
        # I/O and mutation
        "print", "input", "open", "write", "append", "extend", "update",
        "pop", "remove", "clear", "add", "discard", "send", "close",
        # Database operations (results change between calls)
        "get", "execute", "query", "fetch", "fetchone", "fetchall", "fetchmany",
        "commit", "rollback", "refresh", "flush", "merge", "delete", "scalar",
        "first", "all", "one", "one_or_none", "count",
        # HTTP/API calls
        "request", "post", "put", "patch",
        # Logging (side effects)
        "log", "info", "debug", "warning", "error", "critical", "exception",
    }
    short = func_chain.split(".")[-1]
    if short in _IMPURE:
        return None
    # Build a simplified argument signature
    parts = [func_chain]
    for arg in (node.args or []):
        c = _attr_chain(arg)
        if c:
            parts.append(c)
        elif isinstance(arg, ast.Constant):
            parts.append(repr(arg.value))
        else:
            return None  # complex arg — can't determine equality
    for kw in (node.keywords or []):
        key = kw.arg or "**"
        val = _attr_chain(kw.value)
        if val:
            parts.append(f"{key}={val}")
        elif isinstance(kw.value, ast.Constant):
            parts.append(f"{key}={kw.value.value!r}")
        else:
            return None
    return "|".join(parts)


def _check_redundant_recomputation(ctx: RuleContext, tree: ast.AST) -> None:
    """Same function call (with same args) appearing multiple times in a function."""
    name = "redundant_recomputation"
    if not _enabled(ctx, name, default=True):
        return
    severity = _severity(ctx, name, default="warning")

    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        call_sites: dict[str, list[int]] = defaultdict(list)
        for node in ast.walk(func):
            if not isinstance(node, ast.Call):
                continue
            sig = _call_sig(node)
            if sig:
                call_sites[sig].append(getattr(node, "lineno", 1))

        for sig, lines in call_sites.items():
            if len(lines) < 2:
                continue
            func_name = sig.split("|")[0]
            ctx.add_issue(
                file=str(ctx.file_path),
                line=lines[0],
                rule=name,
                severity=severity,
                message=(
                    f"'{func_name}(...)' called {len(lines)} times with identical "
                    f"args in '{func.name}' (lines {', '.join(str(l) for l in lines)})."
                ),
                suggestion="Compute once, store in a variable, and reuse.",
            )


# ═══════════════════════════════════════════════════════════════════════════
# 5. dead_parameters
# ═══════════════════════════════════════════════════════════════════════════

def _check_dead_parameters(ctx: RuleContext, tree: ast.AST) -> None:
    """Function parameters never referenced in the function body."""
    name = "dead_parameters"
    if not _enabled(ctx, name, default=True):
        return
    severity = _severity(ctx, name, default="warning")

    _EXEMPT = frozenset({"self", "cls"})

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        # Skip abstract methods, protocol stubs, and single-statement bodies
        if len(node.body) <= 1:
            continue
        # Skip if body is just `...` or `pass` (abstract/stub)
        if len(node.body) == 1:
            stmt = node.body[0]
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
                continue  # docstring only
            if isinstance(stmt, ast.Pass):
                continue

        # Check for @abstractmethod decorator
        is_abstract = False
        for d in (node.decorator_list or []):
            dname = _attr_chain(d)
            if "abstractmethod" in dname:
                is_abstract = True
                break
        if is_abstract:
            continue

        # Collect all parameter names
        args = node.args
        all_params: list[tuple[str, int]] = []
        for arg in args.args:
            all_params.append((arg.arg, getattr(arg, "lineno", getattr(node, "lineno", 1))))
        for arg in (args.kwonlyargs or []):
            all_params.append((arg.arg, getattr(arg, "lineno", getattr(node, "lineno", 1))))

        if not all_params:
            continue

        # Collect all loaded names in the function body
        loaded: set[str] = set()
        for child in node.body:
            for sub in ast.walk(child):
                if isinstance(sub, ast.Name) and isinstance(sub.ctx, (ast.Load, ast.Del)):
                    loaded.add(sub.id)

        for pname, pline in all_params:
            if pname in _EXEMPT:
                continue
            if pname.startswith("_"):
                continue
            # Skip *args and **kwargs
            if args.vararg and args.vararg.arg == pname:
                continue
            if args.kwarg and args.kwarg.arg == pname:
                continue
            if pname in loaded:
                continue

            ctx.add_issue(
                file=str(ctx.file_path),
                line=pline,
                rule=name,
                severity=severity,
                message=f"Parameter '{pname}' in '{node.name}' is never used in the function body.",
                suggestion=f"Remove '{pname}' if unneeded, or prefix with _ to mark as intentionally unused.",
            )


# ═══════════════════════════════════════════════════════════════════════════
# 6. excessive_defensive_checks
# ═══════════════════════════════════════════════════════════════════════════

_DEFENSIVE_CALLS = frozenset({"isinstance", "hasattr", "getattr"})


def _check_excessive_defensive_checks(ctx: RuleContext, tree: ast.AST) -> None:
    """Flag functions where >30% of statements are defensive checks."""
    name = "excessive_defensive_checks"
    if not _enabled(ctx, name, default=True):
        return
    severity = _severity(ctx, name, default="info")
    threshold_pct = 30

    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if len(func.body) < 5:
            continue

        total_stmts = 0
        defensive_count = 0

        for stmt in ast.walk(func):
            if isinstance(stmt, (ast.Expr, ast.Assign, ast.Return, ast.If,
                                 ast.AugAssign, ast.AnnAssign)):
                total_stmts += 1

            # isinstance / hasattr / getattr calls
            if isinstance(stmt, ast.Call):
                fn = _attr_chain(stmt.func)
                if fn in _DEFENSIVE_CALLS:
                    defensive_count += 1

            # `if x is None` / `if x is not None`
            if isinstance(stmt, ast.Compare):
                for op, comp in zip(stmt.ops, stmt.comparators):
                    if isinstance(op, (ast.Is, ast.IsNot)):
                        if isinstance(comp, ast.Constant) and comp.value is None:
                            defensive_count += 1

        if total_stmts < 5:
            continue
        pct = (defensive_count * 100) / total_stmts
        if pct > threshold_pct:
            ctx.add_issue(
                file=str(ctx.file_path),
                line=getattr(func, "lineno", 1),
                rule=name,
                severity=severity,
                message=(
                    f"Function '{func.name}' has {defensive_count} defensive checks "
                    f"out of ~{total_stmts} statements ({pct:.0f}%). "
                    "Indicates distrust of the data model."
                ),
                suggestion="Validate at system boundaries and trust internal types.",
            )


# ═══════════════════════════════════════════════════════════════════════════
# 7. over_abstraction (per-file approximation)
# ═══════════════════════════════════════════════════════════════════════════

def _check_over_abstraction(ctx: RuleContext, tree: ast.AST) -> None:
    """Flag ABC/Protocol classes with only one concrete subclass in the same file."""
    name = "over_abstraction"
    if not _enabled(ctx, name, default=True):
        return
    severity = _severity(ctx, name, default="info")

    abstract_classes: dict[str, int] = {}  # name → line
    concrete_bases: dict[str, int] = defaultdict(int)  # parent_name → count

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue

        # Check if this class is abstract
        is_abstract = False
        base_names: list[str] = []
        for base in node.bases:
            bname = _attr_chain(base)
            base_names.append(bname)
            if bname in ("ABC", "Protocol", "ABCMeta"):
                is_abstract = True

        # Check for @abstractmethod in methods
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for dec in item.decorator_list:
                    if "abstractmethod" in _attr_chain(dec):
                        is_abstract = True

        if is_abstract:
            abstract_classes[node.name] = getattr(node, "lineno", 1)
        else:
            for bname in base_names:
                concrete_bases[bname] += 1

    # Flag abstract classes with exactly 1 concrete subclass
    for abc_name, line in abstract_classes.items():
        sub_count = concrete_bases.get(abc_name, 0)
        if sub_count == 1:
            ctx.add_issue(
                file=str(ctx.file_path),
                line=line,
                rule=name,
                severity=severity,
                message=(
                    f"Abstract class '{abc_name}' has only 1 concrete subclass in this file. "
                    "Abstraction without polymorphism adds unnecessary indirection."
                ),
                suggestion="Remove the ABC and use the concrete class directly.",
            )


# ═══════════════════════════════════════════════════════════════════════════
# 8. redundant_containment_check
# ═══════════════════════════════════════════════════════════════════════════

def _check_redundant_containment_check(ctx: RuleContext, tree: ast.AST) -> None:
    """Flag containment checks in bottom-up tree processing patterns."""
    name = "redundant_containment_check"
    if not _enabled(ctx, name, default=True):
        return
    severity = _severity(ctx, name, default="info")

    tree_var_names = {"children", "child_sections", "descendants", "subtree", "parent"}

    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        # Detect bottom-up pattern: reversed() in for loop iterable + tree vars
        has_reversed_loop = False
        has_tree_vars = False
        containment_check_lines: list[int] = []

        for node in ast.walk(func):
            # Check for reversed() in for loop
            if isinstance(node, ast.For):
                if isinstance(node.iter, ast.Call):
                    fn = _attr_chain(node.iter.func)
                    if fn == "reversed":
                        has_reversed_loop = True

            # Check for tree variable names
            if isinstance(node, ast.Name) and node.id in tree_var_names:
                has_tree_vars = True

            # Check for `any(x in child.collection for child in ...)` pattern
            if isinstance(node, ast.Call):
                fn = _attr_chain(node.func)
                if fn == "any" and node.args:
                    arg = node.args[0]
                    if isinstance(arg, ast.GeneratorExp):
                        # Check if it's a containment check
                        elt = arg.elt
                        if isinstance(elt, ast.Compare):
                            for op in elt.ops:
                                if isinstance(op, ast.In):
                                    containment_check_lines.append(
                                        getattr(node, "lineno", 1)
                                    )

        if has_reversed_loop and has_tree_vars and containment_check_lines:
            ctx.add_issue(
                file=str(ctx.file_path),
                line=containment_check_lines[0],
                rule=name,
                severity=severity,
                message=(
                    f"Containment check in bottom-up tree processing in '{func.name}'. "
                    "Items assigned to children don't need re-checking."
                ),
                suggestion="Track assigned items in a set and skip them in subsequent iterations.",
            )


# ═══════════════════════════════════════════════════════════════════════════
# 9. code_to_complexity_ratio
# ═══════════════════════════════════════════════════════════════════════════

def _check_code_to_complexity_ratio(ctx: RuleContext, tree: ast.AST) -> None:
    """Flag modules with excessive private-to-public function ratio."""
    name = "code_to_complexity_ratio"
    if not _enabled(ctx, name, default=True):
        return
    severity = _severity(ctx, name, default="info")

    public_funcs = 0
    private_funcs = 0
    total_lines = len(ctx.lines)

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("_"):
                private_funcs += 1
            else:
                public_funcs += 1
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if item.name.startswith("_") and item.name != "__init__":
                        private_funcs += 1
                    elif not item.name.startswith("_"):
                        public_funcs += 1

    if public_funcs == 0:
        return

    ratio = private_funcs / public_funcs if public_funcs else 0
    avg_lines = total_lines / public_funcs if public_funcs else 0

    if ratio > 5:
        ctx.add_issue(
            file=str(ctx.file_path),
            line=1,
            rule=name,
            severity=severity,
            message=(
                f"Module has {private_funcs} private helpers for {public_funcs} public functions "
                f"(ratio {ratio:.1f}:1). May indicate over-engineering."
            ),
            suggestion="Consider simplifying — do these helpers pull their weight?",
        )
    elif avg_lines > 200:
        ctx.add_issue(
            file=str(ctx.file_path),
            line=1,
            rule=name,
            severity=severity,
            message=(
                f"Module averages {avg_lines:.0f} lines per public function "
                f"({total_lines} lines / {public_funcs} public functions). "
                "Implementation may be more complex than the task requires."
            ),
            suggestion="Look for opportunities to simplify or split the module.",
        )


# ═══════════════════════════════════════════════════════════════════════════
# Main entry point
# ═══════════════════════════════════════════════════════════════════════════

def check_ai_smell_patterns(ctx: RuleContext) -> None:
    """Run all AI code smell checks (ai_code_smells pack)."""
    if ctx.language != "python":
        return
    tree = _parse_tree(ctx)
    if tree is None:
        return

    # Phase 1
    _check_dead_variable(ctx, tree)
    _check_nested_enumeration(ctx, tree)
    _check_linear_search_in_loop(ctx, tree)
    _check_redundant_recomputation(ctx, tree)
    _check_dead_parameters(ctx, tree)
    # Phase 4
    _check_excessive_defensive_checks(ctx, tree)
    _check_over_abstraction(ctx, tree)
    _check_redundant_containment_check(ctx, tree)
    _check_code_to_complexity_ratio(ctx, tree)
