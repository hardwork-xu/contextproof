"""Lossless, sealed field deltas for materialized evidence graphs.

This reduces transport and storage bytes. It does not by itself reduce tokens
already present in an LLM conversation or prove semantic equivalence.
"""

from copy import deepcopy
import hashlib
import json

from .graph import validate_graph


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _digest(value):
    return hashlib.sha256(canonical({k: v for k, v in value.items() if k != "id"})).hexdigest()


def _map_delta(before, after):
    return {
        "remove": sorted(before.keys() - after.keys()),
        "add": {key: deepcopy(after[key]) for key in sorted(after.keys() - before.keys())},
        "patch": {
            key: {"remove": sorted(before[key].keys() - after[key].keys()),
                  "set": {field: deepcopy(value) for field, value in sorted(after[key].items())
                          if field not in before[key] or before[key][field] != value}}
            for key in sorted(before.keys() & after.keys()) if before[key] != after[key]
        },
    }


def make_graph_delta(before, after):
    """Encode changed map fields; movement does not retransmit unchanged text."""
    validate_graph(before)
    validate_graph(after)
    metadata = {key: deepcopy(value) for key, value in after.items()
                if key not in {"nodes", "edges", "id"}}
    result = {"schema_version": 1, "kind": "contextproof.graph-delta",
              "base_id": before["id"], "target_id": after["id"],
              "metadata": metadata,
              "nodes": _map_delta(before["nodes"], after["nodes"]),
              "edges": _map_delta(before["edges"], after["edges"])}
    result["id"] = _digest(result)
    return result


def _apply_map(before, delta):
    if not isinstance(delta, dict) or set(delta) != {"remove", "add", "patch"}:
        raise ValueError("invalid delta map")
    remove, add, patches = delta["remove"], delta["add"], delta["patch"]
    if (not isinstance(remove, list) or not all(isinstance(k, str) for k in remove)
            or len(remove) != len(set(remove)) or not isinstance(add, dict)
            or not isinstance(patches, dict)):
        raise ValueError("invalid delta operations")
    if (set(remove) - before.keys() or add.keys() & before.keys()
            or patches.keys() - before.keys() or set(remove) & patches.keys()):
        raise ValueError("delta operations do not match the base graph")
    result = deepcopy(before)
    for key in remove:
        del result[key]
    result.update(deepcopy(add))
    for key, patch in patches.items():
        if not isinstance(patch, dict) or set(patch) != {"remove", "set"}:
            raise ValueError("invalid field patch")
        fields, values = patch["remove"], patch["set"]
        if (not isinstance(fields, list) or not all(isinstance(f, str) for f in fields)
                or len(fields) != len(set(fields)) or not isinstance(values, dict)
                or set(fields) - result[key].keys() or set(fields) & values.keys()):
            raise ValueError("field patch does not match base node")
        for field in fields:
            del result[key][field]
        result[key].update(deepcopy(values))
    return result


def apply_graph_delta(before, delta):
    """Reject a wrong base, malformed operations, or a nonmatching target seal."""
    validate_graph(before)
    if (not isinstance(delta, dict) or delta.get("schema_version") != 1
            or delta.get("kind") != "contextproof.graph-delta"
            or delta.get("id") != _digest(delta)):
        raise ValueError("invalid graph delta schema or integrity")
    if delta.get("base_id") != before["id"]:
        raise ValueError("graph delta belongs to a different base")
    metadata = delta.get("metadata")
    if not isinstance(metadata, dict) or {"nodes", "edges", "id"} & metadata.keys():
        raise ValueError("invalid graph delta metadata")
    result = deepcopy(metadata)
    result["nodes"] = _apply_map(before["nodes"], delta.get("nodes"))
    result["edges"] = _apply_map(before["edges"], delta.get("edges"))
    result["id"] = delta.get("target_id")
    validate_graph(result)
    return result
