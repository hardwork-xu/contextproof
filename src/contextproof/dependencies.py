"""Conservative one-hop Python dependency witnesses, independent of text receipts.

No code is imported or executed. ``unchanged`` means the supported static
bindings and directly referenced definitions have identical source text; it
does not establish runtime behavior, transitive freshness, or equivalence.
"""

from __future__ import annotations

import ast
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Any

from .evidence import _bundle_error, _entry_error, _json, _safe_parts, sha256
from .index import _root_path, iter_source_files, read_source_bytes, snapshot_id, source_lines


KIND = "contextproof.dependency-witnesses"
SCOPE = "python-direct-static"
GUARANTEE = (
    "identity of supported direct Python source dependencies and import bindings only; "
    "no runtime, transitive, or semantic-equivalence guarantee"
)
_ANCHOR_KEYS = ("id", "path", "symbol", "kind", "start_line", "end_line", "text",
                "text_sha256", "file_sha256")
_DECLARATIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _digest(value: dict) -> str:
    return sha256(_json({key: item for key, item in value.items() if key != "id"}))


def _span(node: ast.AST) -> tuple[int, int]:
    decorators = getattr(node, "decorator_list", [])
    return (min([node.lineno, *(item.lineno for item in decorators)]),
            node.end_lineno or node.lineno)


def _stored_names(node: ast.AST) -> set[str]:
    return {item.id for item in ast.walk(node)
            if isinstance(item, ast.Name) and isinstance(item.ctx, (ast.Store, ast.Del))}


def _dotted(node: ast.AST) -> list[str] | None:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    return [node.id, *reversed(parts)] if isinstance(node, ast.Name) else None


def _unresolved(reason: str) -> dict:
    return {"status": "unresolved", "reason": reason}


def _scope_locals(owner: ast.AST) -> tuple[set[str], set[str]]:
    """Lexical function bindings, without leaking nested-scope stores outward."""
    local: set[str] = set()
    uncertain: set[str] = set()
    if not isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        return local, uncertain
    args = owner.args
    local.update(arg.arg for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs])
    local.update(arg.arg for arg in [args.vararg, args.kwarg] if arg)
    globals_: set[str] = set()

    pending = list(owner.body if isinstance(owner.body, list) else [owner.body])
    while pending:
        node = pending.pop()
        if isinstance(node, _DECLARATIONS):
            local.add(node.name)
            continue
        if isinstance(node, ast.Lambda):
            continue
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            # Comprehensions have their own scope, except assignment expressions.
            # Treat overlapping names as unknown instead of applying runtime rules.
            uncertain.update(_stored_names(node))
            continue
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            local.add(node.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            local.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            local.add(node.name)
        elif isinstance(node, ast.Global):
            globals_.update(node.names)
        elif isinstance(node, ast.Nonlocal):
            uncertain.update(node.names)
        pending.extend(ast.iter_child_nodes(node))
    return local - globals_, uncertain


class _Corpus:
    """One safe source scan and one AST parse per eligible Python file."""

    def __init__(self, root: Path):
        self.root = _root_path(root)
        self.unavailable: set[str] = set()
        texts: dict[str, str] = {}
        for absolute in iter_source_files(self.root):
            path = absolute.relative_to(self.root).as_posix()
            raw = read_source_bytes(self.root, absolute)
            if raw is None:
                self.unavailable.add(path)
            else:
                texts[path] = raw.decode("utf-8")
        self._load_texts(texts)

    @classmethod
    def from_texts(cls, texts: dict[str, str], parsed_cache: dict | None = None) -> "_Corpus":
        """Build the same static corpus from already validated immutable source.

        No filesystem reads occur. The provider owns source allowlisting and
        snapshot consistency; path traversal is still rejected here.
        """
        corpus = cls.__new__(cls)
        corpus.root = None
        corpus.unavailable = set()
        for path, source in texts.items():
            _safe_parts(path)
            if not isinstance(source, str):
                raise ValueError("source corpus values must be text")
        corpus._load_texts(texts, parsed_cache)
        return corpus

    def _load_texts(self, texts: dict[str, str], parsed_cache: dict | None = None) -> None:
        self.texts = dict(sorted(texts.items()))
        self.trees: dict[str, ast.Module] = {}
        self.modules: dict[str, list[str]] = defaultdict(list)
        self.bindings: dict[str, dict[str, list[dict]]] = {}
        self.definitions: dict[str, dict[str, list[ast.AST]]] = {}
        self.wildcards: set[str] = set()
        for path, source in self.texts.items():
            if Path(path).suffix.lower() not in {".py", ".pyi"}:
                continue
            parts = list(Path(path).with_suffix("").parts)
            if parts[-1] == "__init__":
                parts.pop()
            names = {".".join(parts)}
            if len(parts) > 1 and parts[0] == "src":
                names.add(".".join(parts[1:]))
            for name in sorted(names - {""}):
                self.modules[name].append(path)
            cache_key = (path, sha256(source))
            tree = parsed_cache.get(cache_key) if parsed_cache is not None else None
            if tree is None:
                try:
                    tree = ast.parse(source, filename=path)
                except (SyntaxError, ValueError, RecursionError):
                    continue
                if parsed_cache is not None:
                    parsed_cache[cache_key] = tree
            self.trees[path] = tree
            self._index(path, tree)
        self.snapshot_id = snapshot_id({path: sha256(text)
                                        for path, text in self.texts.items()})

    def _index(self, path: str, tree: ast.Module) -> None:
        bindings: dict[str, list[dict]] = defaultdict(list)
        definitions: dict[str, list[ast.AST]] = defaultdict(list)

        pending: list[tuple[ast.AST, tuple[str, ...]]] = [(tree, ())]
        while pending:
            node, parents = pending.pop()
            scope = parents
            if isinstance(node, _DECLARATIONS):
                scope = (*parents, node.name)
                definitions[".".join(scope)].append(node)
            pending.extend((child, scope) for child in reversed(list(ast.iter_child_nodes(node))))
        for node in tree.body:
            if isinstance(node, _DECLARATIONS):
                bindings[node.name].append({"kind": "definition", "node": node})
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname or alias.name.split(".")[0]
                    bindings[name].append({"kind": "module", "node": node,
                                           "module": alias.name if alias.asname else name})
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == "*":
                        self.wildcards.add(path)
                        continue
                    bindings[alias.asname or alias.name].append({
                        "kind": "import", "node": node, "module": node.module or "",
                        "level": node.level, "name": alias.name,
                    })
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    for name in _stored_names(target):
                        bindings[name].append({"kind": "constant", "node": node})
            else:
                # Conditional definitions/imports, assignment expressions, and
                # rebinding are deliberately not interpreted as executed paths.
                names = _stored_names(node)
                for child in ast.walk(node):
                    if isinstance(child, _DECLARATIONS):
                        names.add(child.name)
                    elif isinstance(child, (ast.Import, ast.ImportFrom)):
                        names.update(alias.asname or alias.name.split(".")[0]
                                     for alias in child.names)
                for name in names:
                    bindings[name].append({"kind": "dynamic", "node": node})
        self.bindings[path] = dict(bindings)
        self.definitions[path] = dict(definitions)

    def record(self, path: str, symbol: str, kind: str, node: ast.AST) -> dict:
        start, end = _span(node)
        text = "".join(source_lines(self.texts[path])[start - 1:end])
        return {"path": path, "symbol": symbol, "kind": kind,
                "start_line": start, "end_line": end, "text": text,
                "text_sha256": sha256(text)}

    def _absolute_module(self, path: str, binding: dict) -> str | None:
        level = binding.get("level", 0)
        if not level:
            return binding["module"]
        parts = list(Path(path).with_suffix("").parts)
        parts.pop()  # Both module.py and __init__.py live in their parent package.
        if parts and parts[0] == "src":
            parts.pop(0)
        if level > len(parts):
            return None
        base = parts[:len(parts) - level + 1]
        return ".".join([*base, *filter(None, binding["module"].split("."))])

    def resolve_module(self, module: str, attrs: list[str], seen: set[tuple[str, str]]) -> dict:
        if len(attrs) > 128:
            return _unresolved("qualified expression exceeds the static resolution depth limit")
        if not attrs:
            return _unresolved("a module value has no bounded definition witness")
        # A qualified imported module may be a namespace package without init.py.
        # Never guess a submodule over a same-named explicit package binding.
        candidates = self.modules.get(module, [])
        if len(candidates) > 1:
            return _unresolved("ambiguous repository module")
        if len(candidates) == 1:
            path = candidates[0]
            if path not in self.trees:
                return _unresolved("repository module cannot be parsed")
            if attrs[0] in self.bindings[path]:
                return self.resolve_name(path, attrs[0], attrs[1:], seen)
        child = f"{module}.{attrs[0]}" if module else attrs[0]
        if len(attrs) > 1 and (child in self.modules or any(
                key.startswith(child + ".") for key in self.modules)):
            return self.resolve_module(child, attrs[1:], seen)
        if not candidates:
            return _unresolved("external or unavailable import")
        return _unresolved("imported name is absent or supplied dynamically")

    def resolve_name(self, path: str, name: str, attrs: list[str],
                     seen: set[tuple[str, str]] | None = None) -> dict:
        seen = set() if seen is None else seen
        if len(seen) >= 128:
            return _unresolved("import chain exceeds the static resolution depth limit")
        key = (path, name)
        if key in seen:
            return _unresolved("cyclic re-export binding")
        seen = seen | {key}
        bindings = self.bindings.get(path, {}).get(name, [])
        if path in self.wildcards:
            return _unresolved("wildcard import may shadow this binding")
        if not bindings:
            return _unresolved("name is not a static repository binding (possibly builtin/external)")
        if len(bindings) != 1:
            return _unresolved("ambiguous or rebound name")
        binding = bindings[0]
        kind = binding["kind"]
        if kind in {"definition", "constant"}:
            if attrs:
                return _unresolved("object/class attribute dispatch is not statically resolved")
            node = binding["node"]
            if kind == "constant":
                # Only simple literal assignments receive constant witnesses.
                # Expressions such as CONFIG = load() contain hidden inputs.
                try:
                    ast.literal_eval(node.value)
                except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
                    return _unresolved("global assignment is not a literal constant")
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if any(not isinstance(target, ast.Name) for target in targets):
                    return _unresolved("destructuring assignment is not a direct constant binding")
            target_kind = ("constant" if kind == "constant" else
                           "class" if isinstance(node, ast.ClassDef) else "function")
            return {"status": "resolved", "reason": "unique static repository binding",
                    "target": self.record(path, name, target_kind, node), "bindings": []}
        if kind == "dynamic":
            return _unresolved("conditional or dynamic module binding")
        module = self._absolute_module(path, binding)
        if module is None:
            return _unresolved("relative import escapes the known package")
        ref_attrs = attrs if kind == "module" else [binding["name"], *attrs]
        result = self.resolve_module(module, ref_attrs, seen)
        if result["status"] == "resolved":
            result["bindings"].insert(0, self.record(path, name, "import", binding["node"]))
        return result

    def anchor_state(self, anchor: dict) -> tuple[str, dict | None]:
        path = anchor["path"]
        current = self.root
        if current is not None:
            for part in _safe_parts(path):
                current = current / part
                if current.is_symlink():
                    return "invalid", None
        if path not in self.texts:
            return ("invalid" if path in self.unavailable or (
                current is not None and current.exists()) else "missing"), None
        if path not in self.trees:
            return "unresolved", None
        symbol = anchor["symbol"]
        if symbol == "<module>":
            nodes = [self.trees[path]]
        else:
            nodes = self.definitions[path].get(symbol, [])
        if not nodes:
            return "missing", None
        if len(nodes) != 1:
            return "unresolved", None
        owner = nodes[0]
        lines = source_lines(self.texts[path])
        lower, upper = (1, len(lines)) if isinstance(owner, ast.Module) else _span(owner)
        original_lines = source_lines(anchor["text"])
        width = len(original_lines)
        matches = [(offset + 1, offset + width)
                   for offset in range(lower - 1, upper - width + 1)
                   if lines[offset:offset + width] == original_lines]
        old = (anchor["start_line"], anchor["end_line"])
        if old in matches:
            start, end = old
        elif len(matches) == 1:
            start, end = matches[0]
        elif len(matches) > 1:
            return "unresolved", None
        else:
            return "changed", None
        return "unchanged", {"owner": owner, "start": start, "end": end}

    def references(self, anchor: dict, located: dict) -> list[dict]:
        owner = located["owner"]
        path = anchor["path"]
        start, end = located["start"], located["end"]
        local, uncertain = _scope_locals(owner)
        if isinstance(owner, ast.ClassDef):
            uncertain.update(_stored_names(owner))
            uncertain.update(item.name for item in owner.body if isinstance(item, _DECLARATIONS))
        symbol_parts = anchor["symbol"].split(".")
        for width in range(1, len(symbol_parts)):
            ancestors = self.definitions[path].get(".".join(symbol_parts[:width]), [])
            for ancestor in ancestors:
                outer_local, outer_uncertain = _scope_locals(ancestor)
                uncertain.update(outer_local | outer_uncertain)
        # Decorators, defaults, and annotations are evaluated outside the body's
        # parameter/local scope (annotation evaluation itself remains runtime-dependent).
        outside_local_scope: set[int] = set()
        if isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef)):
            outside_local_scope.update(id(item) for item in ast.walk(owner.args))
            for expression in [*owner.decorator_list, owner.returns]:
                if expression is not None:
                    outside_local_scope.update(id(item) for item in ast.walk(expression))

        nodes = [node for node in ast.walk(owner)
                 if start <= getattr(node, "lineno", 0) <= end]
        references: dict[tuple[str, str], dict] = {}
        suppressed: set[int] = set()

        def add(node: ast.AST, operation: str) -> None:
            dotted = _dotted(node)
            if dotted:
                expression = ".".join(dotted)
            else:
                try:
                    expression = ast.unparse(node)
                except RecursionError:
                    expression = "<dynamic-expression-exceeds-rendering-depth>"
            if dotted and dotted[0] in uncertain:
                result = _unresolved("closure or comprehension scope requires runtime resolution")
            elif dotted and dotted[0] in local and id(node) not in outside_local_scope:
                if operation == "read" and len(dotted) == 1:
                    return
                result = _unresolved("local value, parameter, or closure requires runtime resolution")
            elif dotted:
                result = self.resolve_name(path, dotted[0], dotted[1:])
            else:
                result = _unresolved("dynamic expression requires runtime resolution")
            references[(expression, operation)] = {
                "expression": expression, "operation": operation, **result,
            }

        for node in nodes:
            if isinstance(node, ast.Call):
                add(node.func, "call")
                # Keep nested calls, but do not double-count a call's name as a read.
                suppressed.update(id(item) for item in ast.walk(node.func)
                                  if isinstance(item, (ast.Name, ast.Attribute)))
        for node in nodes:
            if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
                if id(node) not in suppressed:
                    add(node, "read")
                suppressed.update(id(item) for item in ast.walk(node)
                                  if isinstance(item, (ast.Name, ast.Attribute)))
        for node in nodes:
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                if id(node) not in suppressed:
                    add(node, "read")
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                # Import statements do not contain ast.Name load nodes. Preserve
                # them when they are themselves part of the selected evidence.
                for alias in node.names:
                    name = alias.asname or alias.name.split(".")[0]
                    if alias.name == "*":
                        references[("*", "scope")] = {
                            "expression": "*", "operation": "scope",
                            **_unresolved("selected wildcard import has unbounded bindings"),
                        }
                    else:
                        synthetic_name = ast.Name(id=name, ctx=ast.Load())
                        if name in local:
                            references[(name, "read")] = {
                                "expression": name, "operation": "read",
                                **_unresolved("function-local imports require lexical/runtime resolution"),
                            }
                        else:
                            add(synthetic_name, "read")
        return [references[key] for key in sorted(references)]


def capture_witnesses(bundle: dict, root: Path) -> dict:
    """Capture a checksummed sidecar for a valid bundle at its exact snapshot.

    Raises ValueError for malformed bundles or a changed snapshot. Unresolvable
    Python dependencies and unsupported languages are explicitly retained.
    The sidecar is separate from the bundle's rendered context budget.
    """
    error = _bundle_error(bundle)
    if error:
        raise ValueError(error)
    corpus = _Corpus(root)
    if corpus.snapshot_id != bundle["snapshot_id"]:
        raise ValueError("capture requires the bundle's exact current source snapshot; rebuild it")
    entries = []
    for entry in bundle["entries"]:
        anchor = {key: deepcopy(entry[key]) for key in _ANCHOR_KEYS}
        status, located = corpus.anchor_state(anchor)
        if status not in {"unchanged", "unresolved"}:
            raise ValueError("bundle source does not match its claimed snapshot")
        references = corpus.references(anchor, located) if located else [{
            "expression": anchor["symbol"], "operation": "scope", "status": "unresolved",
            "reason": "unsupported language, parse failure, or ambiguous source scope",
        }]
        entries.append({"entry_id": entry["id"], "anchor": anchor, "references": references})
    sidecar = {"schema_version": 1, "kind": KIND, "scope": SCOPE,
               "bundle_id": bundle["id"], "snapshot_id": bundle["snapshot_id"],
               "guarantee": GUARANTEE, "entries": entries}
    sidecar["id"] = _digest(sidecar)
    return sidecar


def _record_error(record: Any) -> str | None:
    if not isinstance(record, dict):
        return "dependency record must be an object"
    try:
        _safe_parts(record.get("path"))
    except ValueError as exc:
        return str(exc)
    text = record.get("text")
    if not isinstance(text, str) or not text.strip() or sha256(text) != record.get("text_sha256"):
        return "invalid dependency source checksum"
    start, end = record.get("start_line"), record.get("end_line")
    if any(not isinstance(item, int) or isinstance(item, bool) for item in (start, end)):
        return "invalid dependency source lines"
    if start <= 0 or end < start or end - start + 1 != len(source_lines(text)):
        return "invalid dependency source line span"
    if not isinstance(record.get("symbol"), str) or not record["symbol"]:
        return "invalid dependency symbol"
    if record.get("kind") not in {"function", "class", "constant", "import"}:
        return "invalid dependency kind"
    return None


def _sidecar_error(sidecar: Any) -> str | None:
    if not isinstance(sidecar, dict) or sidecar.get("schema_version") != 1:
        return "unsupported dependency witness schema"
    if sidecar.get("kind") != KIND or sidecar.get("scope") != SCOPE:
        return "unsupported dependency witness kind or scope"
    try:
        if sidecar.get("id") != _digest(sidecar):
            return "dependency witness integrity checksum mismatch"
    except (TypeError, ValueError, UnicodeError):
        return "dependency witness is not JSON serializable"
    for key in ("bundle_id", "snapshot_id"):
        value = sidecar.get(key)
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            return f"invalid dependency {key}"
    entries = sidecar.get("entries")
    if not isinstance(entries, list) or not entries:
        return "dependency witnesses contain no entries"
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            return "dependency entry must be an object"
        anchor = entry.get("anchor")
        error = _entry_error(anchor)
        if error:
            return error
        if not isinstance(anchor.get("symbol"), str) or not isinstance(anchor.get("kind"), str):
            return "missing anchor scope"
        if entry.get("entry_id") != anchor["id"] or anchor["id"] in seen:
            return "invalid or duplicate dependency entry id"
        seen.add(anchor["id"])
        if not isinstance(entry.get("references"), list):
            return "dependency references must be a list"
        reference_keys = set()
        for reference in entry["references"]:
            if not isinstance(reference, dict):
                return "dependency reference must be an object"
            if not isinstance(reference.get("expression"), str) or not reference["expression"]:
                return "invalid dependency expression"
            if not isinstance(reference.get("reason"), str) or not reference["reason"]:
                return "invalid dependency resolution reason"
            if reference.get("operation") not in {"call", "read", "scope"}:
                return "invalid dependency operation"
            key = (reference["expression"], reference["operation"])
            if key in reference_keys:
                return "duplicate dependency reference"
            reference_keys.add(key)
            if reference.get("status") == "resolved":
                error = _record_error(reference.get("target"))
                if error:
                    return error
                if not isinstance(reference.get("bindings"), list):
                    return "import bindings must be a list"
                for binding in reference["bindings"]:
                    error = _record_error(binding)
                    if error:
                        return error
            elif reference.get("status") != "unresolved":
                return "invalid captured resolution status"
    return None


def _identity(record: dict) -> tuple:
    # Line movement alone is harmless; binding text and target identity are not.
    return record["path"], record["symbol"], record["kind"], record["text_sha256"]


def _reference_result(before: dict, after: dict | None, corpus: _Corpus) -> dict:
    item = {"expression": before["expression"], "operation": before["operation"]}
    if before["status"] == "unresolved":
        return {**item, "status": "unresolved", "reason": "capture was unresolved: " + before["reason"]}
    target = before["target"]
    path = target["path"]
    for binding in before["bindings"]:
        binding_path = binding["path"]
        candidate = corpus.root
        for part in _safe_parts(binding_path):
            candidate = candidate / part
            if candidate.is_symlink():
                return {**item, "status": "invalid", "reason": "import binding path contains a symlink"}
        if binding_path not in corpus.texts:
            status = "invalid" if binding_path in corpus.unavailable or candidate.exists() else "missing"
            return {**item, "status": status, "reason": "recorded import binding file is unavailable"}
    current = corpus.root
    for part in _safe_parts(path):
        current = current / part
        if current.is_symlink():
            return {**item, "status": "invalid", "reason": "dependency path contains a symlink"}
    if path not in corpus.texts:
        status = "invalid" if path in corpus.unavailable or current.exists() else "missing"
        return {**item, "status": status, "reason": "recorded dependency file is unavailable"}
    if path not in corpus.trees:
        return {**item, "status": "unresolved", "reason": "dependency source cannot be parsed"}
    if target["symbol"] not in corpus.bindings.get(path, {}):
        return {**item, "status": "missing", "reason": "recorded dependency definition is absent"}
    if after is None:
        return {**item, "status": "changed", "reason": "referenced expression is no longer present"}
    if after["status"] != "resolved":
        return {**item, "status": "unresolved", "reason": after["reason"]}
    same = (_identity(target) == _identity(after["target"])
            and [_identity(binding) for binding in before["bindings"]]
            == [_identity(binding) for binding in after["bindings"]])
    return {**item, "status": "unchanged" if same else "changed",
            "reason": "direct definition and bindings have identical text" if same
            else "dependency definition or import binding changed",
            "previous_target": deepcopy(target), "current_target": deepcopy(after["target"])}


def _overall(statuses: list[str]) -> str:
    for status in ("invalid", "missing", "changed", "unresolved"):
        if status in statuses:
            return status
    return "unchanged"


def verify_witnesses(witnesses: dict, root: Path) -> dict:
    """Check current direct dependencies; unresolved capture never becomes fresh.

    All paths use the indexer's source allowlist, content checks, and no-symlink
    reads. An integrity hash detects alteration, but is not an authenticity
    signature. Pair the returned bundle_id with the intended source bundle.
    """
    report = {"schema_version": 1, "bundle_id": witnesses.get("bundle_id")
              if isinstance(witnesses, dict) else None,
              "snapshot_id": witnesses.get("snapshot_id") if isinstance(witnesses, dict) else None,
              "scope": SCOPE, "guarantee": GUARANTEE, "results": [], "summary": {}, "fresh": False}
    error = _sidecar_error(witnesses)
    if error:
        entries = witnesses.get("entries", []) if isinstance(witnesses, dict) else []
        if isinstance(entries, list):
            report["results"] = [{"entry_id": entry.get("entry_id")
                                  if isinstance(entry, dict) else None,
                                  "status": "invalid", "reason": error} for entry in entries]
        report.update(error=error, status="invalid", summary={"invalid": max(1, len(report["results"]))})
        return report
    corpus = _Corpus(root)
    report["current_snapshot_id"] = corpus.snapshot_id
    for entry in witnesses["entries"]:
        anchor = entry["anchor"]
        anchor_status, located = corpus.anchor_state(anchor)
        result = {"entry_id": entry["entry_id"], "path": anchor["path"],
                  "symbol": anchor["symbol"], "anchor_status": anchor_status, "references": []}
        current_refs = corpus.references(anchor, located) if located else []
        current_by_key = {(ref["expression"], ref["operation"]): ref for ref in current_refs}
        for reference in entry["references"]:
            current = current_by_key.get((reference["expression"], reference["operation"]))
            result["references"].append(_reference_result(reference, current, corpus))
        captured_keys = {(ref["expression"], ref["operation"]) for ref in entry["references"]}
        for key, reference in current_by_key.items():
            if key not in captured_keys:
                result["references"].append({"expression": reference["expression"],
                                             "operation": reference["operation"], "status": "changed",
                                             "reason": "new direct reference was not captured"})
        # If source scope is unavailable, an apparent missing expression is not
        # independent evidence of dependency mutation. Preserve the scope state.
        if located is None:
            result["status"] = anchor_status
        else:
            result["status"] = _overall([anchor_status, *(
                ref["status"] for ref in result["references"])])
        report["results"].append(result)
    report["summary"] = dict(sorted(Counter(item["status"] for item in report["results"]).items()))
    report["status"] = _overall([item["status"] for item in report["results"]])
    report["fresh"] = report["status"] == "unchanged"
    return report
