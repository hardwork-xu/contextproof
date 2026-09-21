"""Trusted worker, launched under macOS Seatbelt; AST gating is defense in depth."""

from __future__ import annotations

import ast
import builtins
import importlib
import json
import random
import resource
import sys
import traceback
import types
from pathlib import Path

SAFE_MODULES = {"math", "typing", "collections", "itertools", "functools", "string",
                "statistics", "heapq", "bisect"}
SAFE_BUILTINS = {
    "abs", "all", "any", "bool", "chr", "dict", "divmod", "enumerate", "filter", "float",
    "frozenset", "int", "isinstance", "issubclass", "iter", "len", "list", "map", "max",
    "min", "next", "ord", "pow", "range", "repr", "reversed", "round", "set", "slice",
    "sorted", "str", "sum", "tuple", "zip", "ValueError", "TypeError", "Exception",
    "ArithmeticError", "ZeroDivisionError", "AssertionError", "StopIteration",
}


def validate_code(source: str, repository_modules: set[str]) -> ast.Module:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.ClassDef, ast.AsyncFunctionDef, ast.Global, ast.Nonlocal)):
            raise ValueError(f"unsupported generated syntax: {type(node).__name__}")
        if isinstance(node, (ast.Name, ast.Attribute)):
            name = node.id if isinstance(node, ast.Name) else node.attr
            if name.startswith("_"):
                raise ValueError("private and dunder access is prohibited")
        if isinstance(node, ast.Import):
            if any(alias.name not in SAFE_MODULES | repository_modules for alias in node.names):
                raise ValueError("import outside frozen allowlist")
        if isinstance(node, ast.ImportFrom):
            if node.level or node.module not in SAFE_MODULES | repository_modules:
                raise ValueError("import outside frozen allowlist")
            if any(alias.name.startswith("_") or alias.name == "*" for alias in node.names):
                raise ValueError("wildcard/private import is prohibited")
    return tree


def execute(payload: dict) -> dict:
    task, code = payload["task"], payload["code"]
    modules = {}
    for path, source in task["after_files"].items():
        name = Path(path).stem
        module = types.ModuleType(name)
        exec(compile(source, path, "exec"), module.__dict__)
        modules[name] = module
    # Stale imports are syntactically allowed, but cannot resolve at execution.
    tree = validate_code(code, {"request_api", "current_api"})

    def restricted_import(name, globals=None, locals=None, fromlist=(), level=0):
        if level:
            raise ImportError("relative import is prohibited")
        if name in modules:
            return modules[name]
        if name in SAFE_MODULES:
            return importlib.import_module(name)
        raise ImportError(f"module {name!r} is absent from current repository")

    safe = {name: getattr(builtins, name) for name in SAFE_BUILTINS}
    safe["__import__"] = restricted_import
    namespace = {"__builtins__": safe, "__name__": "candidate"}
    exec(compile(tree, "candidate.py", "exec"), namespace)
    candidate = namespace[task["entry_point"]]
    calls = []

    class Request:
        def __init__(self, arguments):
            self._arguments = arguments
            self._calls = 0

        def decode(self, version):
            if version != task["decoder_version"]:
                raise ValueError("request decoder version is obsolete")
            self._calls += 1
            return self._arguments

    def adapted_candidate(*arguments):
        request = Request(arguments)
        result = candidate(request)
        assert request._calls > 0, "repository request decoder was not called"
        calls.append(request._calls)
        return result

    test_namespace = {}
    random.seed(0)
    exec(compile(task["test"], "upstream_tests.py", "exec"), test_namespace)
    test_namespace["check"](adapted_candidate)
    return {"passed": True, "test_invocations": len(calls), "decoder_calls": sum(calls)}


def main() -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (3, 3))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    payload = json.loads(Path(sys.argv[1]).read_text())
    try:
        result = execute(payload)
    except BaseException as exc:
        result = {"passed": False, "error_type": type(exc).__name__, "error": str(exc),
                  "traceback": traceback.format_exc(limit=8)}
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
