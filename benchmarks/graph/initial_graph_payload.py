"""Budgeted current source from a dependency graph, including its witnesses.

``complete`` describes delivery under the declared graph scope, never program
correctness or task sufficiency. Update payloads require the identified base;
they are not standalone full contexts. The budget covers every UTF-8 byte of
``rendered`` (JSON metadata, references, citations and source). API diagnostics
outside that string must be accounted separately by callers that transmit them.
"""

from __future__ import annotations

import json
from collections import deque

from .graph import compare_graphs, validate_graph


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False)


def _unique(records: list[dict]) -> list[dict]:
    return [json.loads(value) for value in sorted({_json(record) for record in records})]


def _anchor_record(anchor: dict) -> dict:
    return {key: anchor.get(key) for key in (
        "entry_id", "path", "symbol", "node_id", "source_status", "status")}


def _node_record(node: dict) -> dict:
    return {key: node[key] for key in (
        "id", "path", "symbol", "kind", "start_line", "end_line", "text_sha256", "text")}


def _render(graph: dict, *, budget: int, scope: str, anchors: list[dict],
            required: set[str], frontier: list[dict], priority: list[str] | None = None,
            before_id: str | None = None, deleted: list[dict] | None = None,
            causes: list[dict] | None = None) -> dict:
    if isinstance(budget, bool) or not isinstance(budget, int) or budget < 0:
        raise ValueError("budget must be a nonnegative integer in UTF-8 bytes")
    missing = required - graph["nodes"].keys()
    frontier = _unique([*frontier, *(
        {"node_id": node_id, "kind": "missing", "reason": "required current node unavailable"}
        for node_id in sorted(missing)
    )])
    available = required - missing
    selected: set[str] = set()
    ordered = list(dict.fromkeys([*(priority or []), *sorted(available)]))
    ordered = [node_id for node_id in ordered if node_id in available]
    deleted = sorted(deleted or [], key=lambda item: item["id"])
    anchors = sorted((_anchor_record(anchor) for anchor in anchors),
                     key=lambda item: item["entry_id"])
    references = [edge for _, edge in sorted(graph["edges"].items())
                  if edge["source"] in available]
    metadata = {
        "kind": "contextproof.graph-payload", "schema_version": 1,
        "scope": scope, "graph_id": graph["id"], "snapshot_id": graph["snapshot_id"],
        "base_graph_id": before_id, "requires_base": scope == "update",
        "coverage": "saved-anchor-static-closure" if scope == "full" else "required-update-nodes",
        "unit": "utf-8-bytes", "budget": budget, "anchors": anchors,
        "policy": graph["policy"],
        "guarantee": "current recorded source and static references; no behavior or task-sufficiency proof",
        "frontier": frontier, "deleted": deleted, "causes": _unique(causes or []),
    }

    def payload(included: set[str]) -> dict:
        return {
            **metadata,
            "complete": not (required - included) and not frontier,
            "omitted_nodes": sorted(required - included),
            "nodes": [_node_record(graph["nodes"][node_id]) for node_id in sorted(included)],
            # Each emitted source carries its current references. Update references
            # may point into the explicitly identified retained base graph.
            "references": [edge for edge in references if edge["source"] in included],
        }

    for node_id in ordered:
        candidate = selected | {node_id}
        if len(_json(payload(candidate)).encode("utf-8")) <= budget:
            selected = candidate
    value = payload(selected)
    rendered = _json(value)
    minimum_budget = len(_json(payload(set())).encode("utf-8"))
    status = "complete" if value["complete"] else "incomplete"
    if len(rendered.encode("utf-8")) > budget:
        # Even the explicit omission manifest cannot fit. Never emit truncated
        # JSON or hide a failure behind a misleading complete flag.
        rendered = ""
        selected = set()
        value = payload(selected)
        status = "budget_too_small"
    return {
        "kind": metadata["kind"], "schema_version": 1, "scope": scope,
        "graph_id": graph["id"], "base_graph_id": before_id,
        "requires_base": scope == "update", "coverage": metadata["coverage"],
        "complete": bool(rendered) and value["complete"], "status": status,
        "rendered": rendered, "consumed": len(rendered.encode("utf-8")),
        "budget": budget, "unit": "utf-8-bytes", "minimum_budget": minimum_budget,
        "included_nodes": sorted(selected), "omitted_nodes": sorted(required - selected),
        "frontier": frontier, "deleted": deleted,
    }


def render_graph_context(graph: dict, budget: int = 16000) -> dict:
    """Deliver current anchor and reachable source, or explicit incompleteness.

    Whole source declarations are preserved. ``budget_too_small`` with an empty
    rendering means even the omission manifest did not fit; the caller must
    handle this error instead of supplying an empty context as complete evidence.
    """
    validate_graph(graph)
    required: set[str] = set()
    roots = []
    frontier = list(graph["frontier"])
    for anchor in graph["anchors"]:
        required.update(anchor["reachable"])
        if anchor.get("node_id"):
            roots.append(anchor["node_id"])
            required.add(anchor["node_id"])
        else:
            frontier.append({"entry_id": anchor["entry_id"], "kind": "missing_anchor",
                             "reason": "saved anchor has no current source node"})
        frontier.extend(anchor.get("frontier", []))
    if not graph["anchors"]:
        frontier.append({"kind": "empty", "reason": "no source anchors were captured"})
    return _render(graph, budget=budget, scope="full", anchors=graph["anchors"],
                   required=required, frontier=frontier, priority=sorted(roots))


def render_graph_update(before: dict, after: dict, comparison: dict | None = None,
                        budget: int = 16000) -> dict:
    """Deliver changed current source and causal paths against an identified base.

    The update contains no obsolete source. Removed identities are explicit
    tombstones. It must be applied to the exact ``base_graph_id``; ``complete``
    means complete delivery of the required update, not a standalone full graph.
    A supplied comparison is checked against a recomputation to avoid silently
    accepting an incomplete or cross-bound comparison.
    """
    validate_graph(before)
    validate_graph(after)
    expected = compare_graphs(before, after)
    if comparison is not None and any(comparison.get(key) != expected.get(key)
                                      for key in ("before_id", "after_id", "results")):
        raise ValueError("comparison does not match the supplied graphs")
    affected = {item["entry_id"] for item in expected["results"]
                if item["status"] != "unchanged"}
    anchors = [anchor for anchor in after["anchors"] if anchor["entry_id"] in affected]
    required: set[str] = set()
    changed: set[str] = set()
    causes = []
    frontier = []
    for anchor in anchors:
        if anchor.get("node_id"):
            required.add(anchor["node_id"])
        frontier.extend(anchor.get("frontier", []))
    for result in expected["results"]:
        if result["entry_id"] not in affected:
            continue
        for cause in result.get("causes", []):
            causes.append({"entry_id": result["entry_id"], **cause})
            path = cause.get("path", [])
            required.update(node_id for node_id in path if node_id in after["nodes"])
            node_id = cause.get("node_id")
            if node_id in after["nodes"]:
                required.add(node_id)
                changed.add(node_id)
            for edge_id in cause.get("edges", []):
                edge = after["edges"].get(edge_id)
                if edge:
                    required.update(edge.get("bindings", []))
    # Import retargeting can make a comparison's explanatory path refer to the
    # old graph. Independently include every changed current node reachable from
    # affected anchors and a deterministic shortest current path to that node.
    reachable = {node_id for anchor in anchors for node_id in anchor["reachable"]}
    changed.update(node_id for node_id in reachable if node_id in after["nodes"] and (
        node_id not in before["nodes"]
        or after["nodes"][node_id]["fingerprint"] != before["nodes"][node_id]["fingerprint"]
    ))
    adjacency: dict[str, list[tuple[str, dict]]] = {}
    for _, edge in sorted(after["edges"].items()):
        for target in [edge.get("target"), *edge.get("bindings", [])]:
            if target in after["nodes"]:
                adjacency.setdefault(edge["source"], []).append((target, edge))
    roots = sorted(anchor["node_id"] for anchor in anchors if anchor.get("node_id"))
    queue = deque((root, [root], []) for root in roots)
    visited: set[str] = set()
    while queue:
        node_id, path, edges = queue.popleft()
        if node_id in visited:
            continue
        visited.add(node_id)
        if node_id in changed:
            required.update(path)
            for edge in edges:
                required.update(edge.get("bindings", []))
        for target, edge in adjacency.get(node_id, []):
            if target not in visited:
                queue.append((target, [*path, target], [*edges, edge]))
    required.update(changed)
    # Comparisons can report a path using old edge IDs after an import retarget.
    # Add the current binding chain for every selected current path edge as well.
    for edge in after["edges"].values():
        if edge["source"] in required and edge.get("target") in required:
            required.update(edge.get("bindings", []))
    deleted = [{"id": node_id, "path": node["path"], "symbol": node["symbol"],
                "kind": node["kind"], "reason": "absent from current evidence graph"}
               for node_id, node in before["nodes"].items() if node_id not in after["nodes"]]
    if not anchors and affected:
        frontier.append({"kind": "missing_anchor",
                         "reason": "an affected saved anchor has no current graph entry"})
    if not expected.get("fresh", False) and not affected:
        frontier.extend(after["frontier"])
    return _render(after, budget=budget, scope="update", anchors=anchors,
                   required=required, frontier=frontier,
                   priority=[*roots, *sorted(changed)], before_id=before["id"],
                   deleted=deleted, causes=causes)
