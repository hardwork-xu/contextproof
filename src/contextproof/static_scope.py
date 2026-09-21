"""Conservative scope guards shared by direct and transitive witnesses.

Unsupported syntax remains visible instead of resolving an expression through a
same-named but different lexical/module binding. No repository code is executed.
"""

import ast
from typing import Any

_DECLARATIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _stored_names(node: ast.AST) -> set[str]:
    return {item.id for item in ast.walk(node)
            if isinstance(item, ast.Name) and isinstance(item.ctx, (ast.Store, ast.Del))}


def module_lookup_uncertainty(corpus, module: str, attrs: list[str]) -> str | None:
    candidates = corpus.modules.get(module, [])
    if attrs and len(candidates) == 1:
        path = candidates[0]
        if path in corpus.wildcards:
            return "package wildcard may supply or shadow the requested attribute"
        bindings = corpus.bindings.get(path, {})
        if attrs[0] not in bindings and "__getattr__" in bindings:
            return "module __getattr__ may supply the requested attribute before submodule fallback"
    return None


def pattern_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, (ast.MatchAs, ast.MatchStar)) and child.name:
            names.add(child.name)
        elif isinstance(child, ast.MatchMapping) and child.rest:
            names.add(child.rest)
        for parameter in getattr(child, "type_params", []):
            if isinstance(getattr(parameter, "name", None), str):
                names.add(parameter.name)
    return names


def guard_module_bindings(corpus: Any) -> None:
    """Retain syntactic rebinding not represented by simple top-level assignment targets."""
    for path, tree in corpus.trees.items():
        pending = list(tree.body)
        while pending:
            node = pending.pop()
            names: set[str] = set()
            if isinstance(node, ast.NamedExpr):
                names.update(_stored_names(node.target))
            elif isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
                names.add(node.name)
            elif isinstance(node, ast.MatchMapping) and node.rest:
                names.add(node.rest)
            elif isinstance(node, ast.ExceptHandler) and node.name:
                names.add(node.name)
            if isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names):
                corpus.wildcards.add(path)
            for name in names:
                corpus.bindings[path].setdefault(name, []).append({"kind": "dynamic", "node": node})
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                # Definition-time expressions execute in the surrounding scope;
                # nested bodies do not. Parameters themselves do not bind here.
                pending.extend(item for item in [*node.args.defaults, *node.args.kw_defaults]
                               if item is not None)
                for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs,
                            *([node.args.vararg] if node.args.vararg else []),
                            *([node.args.kwarg] if node.args.kwarg else [])]:
                    if arg.annotation is not None:
                        pending.append(arg.annotation)
                if not isinstance(node, ast.Lambda):
                    pending.extend(node.decorator_list)
                    if node.returns is not None:
                        pending.append(node.returns)
                continue
            if isinstance(node, ast.ClassDef):
                pending.extend([*node.bases, *node.decorator_list, *(item.value for item in node.keywords)])
                continue
            pending.extend(ast.iter_child_nodes(node))


def guard_references(references: list[dict], owner: ast.AST, scope_locals,
                     start: int, end: int) -> list[dict]:
    """Do not resolve collapsed references through a conflicting lexical scope.

    The inherited resolver keys references by expression/operation rather than
    lexical occurrence. If a name is bound in a nested scope, aggregating its
    occurrences cannot establish one module binding. Retain that uncertainty.
    """
    uncertain = pattern_names(owner)
    for node in ast.walk(owner):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)) and node is not owner:
            local, ambiguous = scope_locals(node)
            # A partial direct witness can exclude the entire nested body. Its
            # local stores must not hide an outer global occurrence that is in
            # the selected span. Full declaration graphs include those nested
            # occurrences and retain the conflicting lexical scope.
            selected_loads = {child.id for child in ast.walk(node)
                              if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load)
                              and start <= getattr(child, "lineno", 0) <= end}
            uncertain.update((local | ambiguous) & selected_loads)
        elif isinstance(node, ast.ClassDef):
            uncertain.update(_stored_names(node))
            uncertain.update(child.name for child in node.body if isinstance(child, _DECLARATIONS))
            for child in ast.walk(node):
                if isinstance(child, (ast.Import, ast.ImportFrom)):
                    uncertain.update(alias.asname or alias.name.split(".")[0] for alias in child.names)
                elif isinstance(child, ast.ExceptHandler) and child.name:
                    uncertain.add(child.name)
    for reference in references:
        if reference["expression"].split(".", 1)[0] in uncertain:
            reference.pop("target", None)
            reference.pop("bindings", None)
            reference.update(status="unresolved", reason="aggregated reference intersects nested, pattern, or class-local bindings")
    return references
