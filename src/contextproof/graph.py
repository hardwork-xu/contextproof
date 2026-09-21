"""Bounded transitive Python source witnesses over immutable source mappings.

This is an inspectable closure of the existing conservative static resolver.
It records source identity, not runtime behavior or semantic equivalence. Source
providers own corpus filtering and snapshot provenance. No repository code runs.
"""

from __future__ import annotations

import ast
from collections import defaultdict, deque
from collections.abc import Mapping
import hashlib
import json
from typing import Any

from .dependencies import _Corpus, _overall
from .evidence import _safe_parts, sha256
from .index import source_lines

KIND = "contextproof.evidence-graph"
SCOPE = "python-transitive-static"
RESOLVER_VERSION = 2
GUARANTEE = (
    "observed source and import-binding identity in a bounded static Python closure only; "
    "unresolved and truncated frontiers prevent freshness; no runtime or semantic guarantee"
)



def _bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _hash(value: Any) -> str:
    return hashlib.sha256(_bytes(value)).hexdigest()


def canonical_graph_bytes(graph: dict) -> bytes:
    """Canonical full artifact, including its integrity seal."""
    return _bytes(graph)


def _seal(graph: dict) -> dict:
    graph["id"] = _hash({key: value for key, value in graph.items() if key != "id"})
    return graph


def node_id(record: dict) -> str:
    """Stable within a path/symbol identity; source text and lines are separate."""
    return _hash([record["path"], record["symbol"], record["kind"]])


def _fingerprint(record: dict) -> str:
    return _hash([record["path"], record["symbol"], record["kind"], record["text_sha256"]])


def _edge_id(source: str, expression: str, operation: str) -> str:
    return _hash([source, expression, operation])


def _frontier(node: str | None, reason: str, kind: str, depth: int) -> dict:
    return {"node_id": node, "reason": reason, "kind": kind, "depth": depth}


def _sort_records(records: list[dict]) -> list[dict]:
    return [json.loads(value) for value in sorted({_bytes(record) for record in records})]


def _record(corpus: _Corpus, path: str, symbol: str, kind: str, owner: ast.AST) -> dict:
    if not isinstance(owner, ast.Module):
        return corpus.record(path, symbol, kind, owner)
    text = corpus.texts[path]
    return {"path": path, "symbol": symbol, "kind": kind, "start_line": 1,
            "end_line": max(1, len(source_lines(text))), "text": text,
            "text_sha256": sha256(text)}


def _owner(corpus: _Corpus, path: str, symbol: str) -> tuple[str, ast.AST | None, str]:
    if path not in corpus.texts:
        return "missing", None, "anchor source file is absent"
    if path not in corpus.trees:
        return "unresolved", None, "unsupported language or source cannot be parsed"
    if symbol == "<module>" and not corpus.texts[path]:
        return "missing", None, "anchor module has no source text"
    matches = ([corpus.trees[path]] if symbol == "<module>"
               else corpus.definitions[path].get(symbol, []))
    if not matches:
        return "missing", None, "anchor declaration is absent"
    if len(matches) != 1:
        return "unresolved", None, "anchor declaration is ambiguous"
    return "unchanged", matches[0], "unique static declaration"


def _walk(graph: dict, root: str | None) -> tuple[list[str], list[dict]]:
    """Compute a single anchor's bounded closure, even when graph roots overlap."""
    if root is None:
        return [], []
    by_source: dict[str, list[dict]] = defaultdict(list)
    for edge in graph["edges"].values():
        by_source[edge["source"]].append(edge)
    queue = deque([(root, 0)])
    seen: set[str] = set()
    frontier: list[dict] = []
    while queue:
        key, depth = queue.popleft()
        if key in seen:
            continue
        seen.add(key)
        node = graph["nodes"].get(key)
        if node is None:
            frontier.append(_frontier(key, "node budget exhausted", "truncated", depth))
            continue
        if node["kind"] in {"constant", "import"}:
            continue
        if depth >= graph["policy"]["max_depth"]:
            frontier.append(_frontier(key, "maximum expansion depth reached", "truncated", depth))
            continue
        for edge in sorted(by_source.get(key, []), key=lambda edge: edge["id"]):
            if edge["status"] != "resolved":
                frontier.append(_frontier(key, edge["reason"], edge["status"], depth))
            for binding in edge["bindings"]:
                if binding in graph["nodes"]:
                    seen.add(binding)
            if edge["target"] is not None:
                queue.append((edge["target"], depth + 1))
    return sorted(seen & graph["nodes"].keys()), _sort_records(frontier)


def build_graph(texts: Mapping[str, str], snapshot_id: str, anchors: list[dict], *,
                max_depth: int = 4, max_nodes: int = 256,
                parsed_cache: dict | None = None) -> dict:
    """Build current enclosing declarations and a deduplicated bounded closure.

    ``anchors`` retain original capture IDs and selected source text; changes to
    that selected text are reported separately from current declaration closure.
    ``parsed_cache`` is an optional trusted process-local AST cache keyed by
    (path, SHA256 text). The module catalog and all resolutions are rebuilt so
    additions and previously negative lookups cannot be hidden by that cache.
    """
    if not isinstance(snapshot_id, str) or not snapshot_id:
        raise ValueError("snapshot_id must be a nonempty provider identity")
    if type(max_depth) is not int or not 0 <= max_depth <= 128:
        raise ValueError("max_depth must be between 0 and 128")
    if type(max_nodes) is not int or not 1 <= max_nodes <= 100000:
        raise ValueError("max_nodes must be between 1 and 100000")
    if not isinstance(anchors, list) or not anchors:
        raise ValueError("at least one anchor is required")
    if any(not isinstance(anchor, dict) for anchor in anchors):
        raise ValueError("anchor must be an object")
    corpus = _Corpus.from_texts(dict(texts), parsed_cache=parsed_cache)
    graph = {"schema_version": 1, "kind": KIND, "scope": SCOPE, "guarantee": GUARANTEE,
             "snapshot_id": snapshot_id,
             "policy": {"max_depth": max_depth, "max_nodes": max_nodes, "resolver_version": RESOLVER_VERSION},
             "nodes": {}, "edges": {}, "anchors": [], "frontier": []}
    queue: deque[tuple[str, int]] = deque()
    seen_entries: set[str] = set()

    def add_node(record: dict) -> str | None:
        key = node_id(record)
        if key in graph["nodes"]:
            if graph["nodes"][key]["fingerprint"] != _fingerprint(record):
                raise ValueError("conflicting source records for the same graph identity")
            return key
        if len(graph["nodes"]) >= max_nodes:
            return None
        graph["nodes"][key] = {"id": key, **record, "fingerprint": _fingerprint(record)}
        return key

    for anchor in sorted(anchors, key=lambda value: str(value.get("id", ""))):
        if not isinstance(anchor, dict):
            raise ValueError("anchor must be an object")
        _safe_parts(anchor.get("path"))
        if any(not isinstance(anchor.get(key), str) or not anchor[key]
               for key in ("id", "symbol", "kind", "text", "text_sha256")):
            raise ValueError("anchor is missing identity or source text")
        if sha256(anchor["text"]) != anchor["text_sha256"]:
            raise ValueError("anchor source checksum mismatch")
        if (type(anchor.get("start_line")) is not int
                or type(anchor.get("end_line")) is not int
                or not 1 <= anchor["start_line"] <= anchor["end_line"]
                or len(source_lines(anchor["text"])) != anchor["end_line"] - anchor["start_line"] + 1):
            raise ValueError("invalid anchor source span")
        if anchor["id"] in seen_entries:
            raise ValueError("duplicate anchor entry id")
        seen_entries.add(anchor["id"])
        state, owner, reason = _owner(corpus, anchor["path"], anchor["symbol"])
        source_status, _ = corpus.anchor_state(anchor)
        result = {"entry_id": anchor["id"], "path": anchor["path"],
                  "symbol": anchor["symbol"], "kind": anchor["kind"], "node_id": None,
                  "source_status": source_status, "status": state, "reachable": [], "frontier": []}
        if owner is None:
            result["frontier"] = [_frontier(None, reason, state, 0)]
        else:
            kind = ("module" if isinstance(owner, ast.Module) else
                    "class" if isinstance(owner, ast.ClassDef) else "function")
            record = _record(corpus, anchor["path"], anchor["symbol"], kind, owner)
            result["node_id"] = node_id(record)
            if add_node(record) is not None:
                queue.append((result["node_id"], 0))
            else:
                result["status"] = "unresolved"
                result["frontier"] = [_frontier(result["node_id"], "node budget exhausted",
                                                "truncated", 0)]
        graph["anchors"].append(result)

    expanded: set[str] = set()
    while queue:
        key, depth = queue.popleft()
        if key in expanded or depth >= max_depth:
            continue
        expanded.add(key)
        record = graph["nodes"][key]
        if record["kind"] in {"import", "constant"}:
            continue
        state, owner, _ = _owner(corpus, record["path"], record["symbol"])
        if state != "unchanged":
            raise ValueError("resolved graph node no longer has a unique declaration")
        references = corpus.references(record, {"owner": owner, "start": record["start_line"],
                                                "end": record["end_line"]})
        for reference in references:
            edge_key = _edge_id(key, reference["expression"], reference["operation"])
            edge = {"id": edge_key, "source": key, "expression": reference["expression"],
                    "operation": reference["operation"], "status": reference["status"],
                    "reason": reference["reason"], "target": None, "bindings": []}
            if reference["status"] == "resolved":
                target = reference["target"]
                edge["target"] = node_id(target)
                target_added = add_node(target)
                complete = target_added is not None
                for binding in reference["bindings"]:
                    edge["bindings"].append(node_id(binding))
                    complete = (add_node(binding) is not None) and complete
                if not complete:
                    edge["status"] = "truncated"
                    edge["reason"] = "node budget exhausted"
                if target_added is not None:
                    queue.append((target_added, depth + 1))
            graph["edges"][edge_key] = edge

    for anchor in graph["anchors"]:
        reachable, frontier = _walk(graph, anchor["node_id"])
        anchor["reachable"] = reachable
        anchor["frontier"] = _sort_records([*anchor["frontier"], *frontier])
        if anchor["status"] == "unchanged" and anchor["frontier"]:
            anchor["status"] = "unresolved"
        graph["frontier"].extend(anchor["frontier"])
    graph["frontier"] = _sort_records(graph["frontier"])
    graph["nodes"] = dict(sorted(graph["nodes"].items()))
    graph["edges"] = dict(sorted(graph["edges"].items()))
    return _seal(graph)


def validate_graph(graph: dict) -> None:
    """Validate artifact integrity and internal references; not an authenticity check."""
    try:
        if (not isinstance(graph, dict) or graph.get("schema_version") != 1
                or graph.get("kind") != KIND or graph.get("scope") != SCOPE
                or graph.get("guarantee") != GUARANTEE):
            raise ValueError("unsupported evidence graph schema")
        if graph.get("id") != _hash({key: value for key, value in graph.items() if key != "id"}):
            raise ValueError("evidence graph integrity mismatch")
        policy = graph["policy"]
        if policy.get("resolver_version") != RESOLVER_VERSION:
            raise ValueError("unsupported graph resolver version; recapture with the current resolver")
        if (type(policy["max_depth"]) is not int
                or not 0 <= policy["max_depth"] <= 128 or type(policy["max_nodes"]) is not int
                or not 1 <= policy["max_nodes"] <= 100000):
            raise ValueError("invalid evidence graph policy")
        if not isinstance(graph["snapshot_id"], str) or not graph["snapshot_id"]:
            raise ValueError("invalid graph snapshot identity")
        nodes, edges, anchors = graph["nodes"], graph["edges"], graph["anchors"]
        if not isinstance(nodes, dict) or len(nodes) > policy["max_nodes"] or not isinstance(edges, dict):
            raise ValueError("invalid graph node or edge collection")
        for key, record in nodes.items():
            _safe_parts(record["path"])
            if (record.get("id") != key or node_id(record) != key
                    or record.get("fingerprint") != _fingerprint(record)
                    or sha256(record["text"]) != record["text_sha256"]
                    or record["kind"] not in {"function", "class", "constant", "import", "module"}
                    or not isinstance(record["symbol"], str) or not record["symbol"]
                    or type(record["start_line"]) is not int or type(record["end_line"]) is not int
                    or not 1 <= record["start_line"] <= record["end_line"]
                    or len(source_lines(record["text"])) != record["end_line"] - record["start_line"] + 1):
                raise ValueError("invalid graph source record")
        for key, edge in edges.items():
            if (edge.get("id") != key or edge["source"] not in nodes
                    or _edge_id(edge["source"], edge["expression"], edge["operation"]) != key
                    or edge["operation"] not in {"call", "read", "scope"}
                    or not isinstance(edge["expression"], str) or not edge["expression"]
                    or not isinstance(edge["reason"], str) or not edge["reason"]
                    or edge["status"] not in {"resolved", "unresolved", "truncated"}
                    or not isinstance(edge["bindings"], list)):
                raise ValueError("invalid graph edge")
            if edge["status"] == "resolved" and (
                    edge["target"] not in nodes or any(item not in nodes for item in edge["bindings"])):
                raise ValueError("resolved edge references absent source")
            if edge["status"] == "unresolved" and (edge["target"] is not None or edge["bindings"]):
                raise ValueError("unresolved edge contains resolved targets")
        if not isinstance(anchors, list) or not anchors:
            raise ValueError("graph has no anchors")
        seen = set()
        for anchor in anchors:
            _safe_parts(anchor["path"])
            if (anchor["entry_id"] in seen or not isinstance(anchor["entry_id"], str)
                    or anchor["source_status"] not in {"unchanged", "changed", "missing", "unresolved"}
                    or anchor["status"] not in {"unchanged", "missing", "unresolved"}):
                raise ValueError("invalid graph anchor")
            seen.add(anchor["entry_id"])
            root_record = nodes.get(anchor["node_id"])
            if root_record is not None and any(
                    root_record[key] != anchor[key] for key in ("path", "symbol")):
                raise ValueError("anchor scope does not match its graph node")
            if not anchor["entry_id"] or not isinstance(anchor["frontier"], list):
                raise ValueError("invalid graph anchor identity or frontier")
            for item in anchor["frontier"]:
                if (item["kind"] not in {"missing", "unresolved", "truncated"}
                        or not isinstance(item["reason"], str) or not item["reason"]
                        or type(item["depth"]) is not int or item["depth"] < 0
                        or (item["node_id"] is not None and not isinstance(item["node_id"], str))):
                    raise ValueError("invalid anchor frontier")
            if anchor["node_id"] is None and (
                    anchor["status"] == "unchanged" or not anchor["frontier"]):
                raise ValueError("unavailable anchor must preserve its frontier")
            reachable, frontier = _walk(graph, anchor["node_id"])
            if anchor["reachable"] != reachable:
                raise ValueError("anchor closure does not match graph edges")
            if any(item not in anchor["frontier"] for item in frontier):
                raise ValueError("anchor omits an unresolved or truncated frontier")
            if anchor["status"] == "unchanged" and (anchor["frontier"] or anchor["node_id"] not in nodes):
                raise ValueError("incomplete anchor cannot be unchanged")
            if anchor["status"] == "unresolved" and not anchor["frontier"]:
                raise ValueError("unresolved anchor must preserve its frontier")
        if graph["frontier"] != _sort_records([item for anchor in anchors for item in anchor["frontier"]]):
            raise ValueError("graph frontier does not match anchor frontiers")
    except (KeyError, TypeError, AttributeError, UnicodeError) as exc:
        raise ValueError("malformed evidence graph") from exc


def compare_graphs(before: dict, after: dict) -> dict:
    """Explain observed changes along captured dependency paths.

    An unresolved capture cannot become fresh by later resolving. Added edges,
    bindings and targets are changes, while line movement alone is harmless.
    """
    if (isinstance(before, dict) and isinstance(after, dict)
            and isinstance(before.get("policy"), dict) and isinstance(after.get("policy"), dict)
            and before["policy"].get("resolver_version") != after["policy"].get("resolver_version")):
        raise ValueError("cannot compare different graph resolver versions; recapture the baseline")
    validate_graph(before)
    validate_graph(after)
    if before["policy"] != after["policy"]:
        raise ValueError("cannot compare evidence graphs with different policies")
    old_anchors = {anchor["entry_id"]: anchor for anchor in before["anchors"]}
    new_anchors = {anchor["entry_id"]: anchor for anchor in after["anchors"]}
    old_edges: dict[str, list[dict]] = defaultdict(list)
    new_edges: dict[str, list[dict]] = defaultdict(list)
    for edge in before["edges"].values():
        old_edges[edge["source"]].append(edge)
    for edge in after["edges"].values():
        new_edges[edge["source"]].append(edge)
    results = []
    for entry_id in sorted(old_anchors.keys() | new_anchors.keys()):
        old, new = old_anchors.get(entry_id), new_anchors.get(entry_id)
        causes: list[dict] = []

        def cause(kind: str, reason: str, node: str | None, path: list[str], edges: list[str]):
            causes.append({"kind": kind, "reason": reason, "node_id": node,
                           "path": path, "edges": edges})

        if old is None:
            cause("changed", "new anchor was not captured", new["node_id"], [], [])
        elif new is None:
            cause("missing", "captured anchor is absent from current graph", old["node_id"], [], [])
        elif old["node_id"] != new["node_id"]:
            kind = ("changed" if new["node_id"] in after["nodes"] else
                    "missing" if new["status"] == "missing" else "unresolved")
            cause(kind, "anchor identity changed or is unavailable", old["node_id"], [], [])
        elif new["status"] == "missing":
            cause("missing", "anchor declaration is absent", old["node_id"], [], [])
        if old and new and old["node_id"] == new["node_id"]:
            root = old["node_id"]
            pending = deque([(root, [root] if root else [], [], 0)])
            seen = set()
            while pending:
                key, path, edge_path, depth = pending.popleft()
                if key is None or key in seen:
                    continue
                seen.add(key)
                previous, current = before["nodes"].get(key), after["nodes"].get(key)
                if previous is None:
                    continue
                if current is None:
                    kind = "unresolved" if new["status"] == "unresolved" else "missing"
                    cause(kind, "recorded source identity is unavailable", key, path, edge_path)
                    continue
                if previous["fingerprint"] != current["fingerprint"]:
                    cause("changed", "definition or binding source changed", key, path, edge_path)
                if depth >= before["policy"]["max_depth"]:
                    continue
                for edge in sorted(old_edges.get(key, []), key=lambda item: item["id"]):
                    edge_id = edge["id"]
                    current_edge = after["edges"].get(edge_id)
                    next_edges = [*edge_path, edge_id]
                    if current_edge is None:
                        cause("changed", "captured reference is absent", key, path, next_edges)
                        continue
                    if edge["status"] == "unresolved":
                        cause("unresolved", "captured reference was unresolved: " + edge["reason"],
                              key, path, next_edges)
                        continue
                    if edge["status"] == "truncated" or current_edge["status"] != "resolved":
                        cause("unresolved", current_edge["reason"], key, path, next_edges)
                        continue
                    if (edge["target"] != current_edge["target"]
                            or edge["bindings"] != current_edge["bindings"]):
                        cause("changed", "reference target or import binding identity changed",
                              key, path, next_edges)
                        continue
                    for binding in edge["bindings"]:
                        pending.append((binding, [*path, binding], next_edges, depth))
                    if edge["target"] is not None:
                        pending.append((edge["target"], [*path, edge["target"]], next_edges, depth + 1))
                known = {edge["id"] for edge in old_edges.get(key, [])}
                for edge in new_edges.get(key, []):
                    if edge["id"] not in known:
                        cause("changed", "new reference was not captured", key, path,
                              [*edge_path, edge["id"]])
            for anchor, prefix in ((old, "captured"), (new, "current")):
                for item in anchor["frontier"]:
                    cause("unresolved" if item["kind"] != "missing" else "missing",
                          prefix + " frontier: " + item["reason"], item["node_id"], [], [])
        causes = _sort_records(causes)
        status = _overall([item["kind"] for item in causes])
        results.append({"entry_id": entry_id, "status": status, "causes": causes})
    status = _overall([result["status"] for result in results])
    return {"schema_version": 1, "before_id": before["id"], "after_id": after["id"],
            "scope": SCOPE, "guarantee": GUARANTEE, "status": status,
            "fresh": status == "unchanged", "results": results}
