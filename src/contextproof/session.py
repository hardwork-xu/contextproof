"""A portable capture/check/refresh workflow over source and dependency evidence.

Context artifacts contain a bounded source bundle and an out-of-band dependency
sidecar. Neither byte identity nor static witnesses imply semantic correctness.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .dependencies import _ANCHOR_KEYS, capture_witnesses, verify_witnesses
from .evidence import make_bundle, repair_bundle, verify_bundle
from .index import build_index

KIND = "contextproof.context"


def _digest(context):
    content = {key: value for key, value in context.items() if key != "id"}
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _wrap(bundle, dependencies, receipt=None):
    context = {"kind": KIND, "schema_version": 1, "bundle": bundle,
               "dependencies": dependencies}
    if receipt is not None:
        context["refresh_receipt"] = receipt
    context["id"] = _digest(context)
    return context


def validate_context(context):
    """Check internal binding; hashes are integrity checks, not signatures."""
    if not isinstance(context, dict) or context.get("kind") != KIND:
        raise ValueError("expected a ContextProof context artifact from 'capture'")
    if context.get("schema_version") != 1 or context.get("id") != _digest(context):
        raise ValueError("context schema or integrity mismatch")
    bundle, dependencies = context.get("bundle"), context.get("dependencies")
    if not isinstance(bundle, dict):
        raise ValueError("context has no source bundle")
    if dependencies is not None:
        if not isinstance(dependencies, dict):
            raise ValueError("dependency sidecar must be an object")
        if dependencies.get("bundle_id") != bundle.get("id"):
            raise ValueError("dependency sidecar belongs to a different bundle")
        if dependencies.get("snapshot_id") != bundle.get("snapshot_id"):
            raise ValueError("dependency sidecar belongs to a different snapshot")
        entries, witnesses = bundle.get("entries"), dependencies.get("entries")
        if not isinstance(entries, list) or not isinstance(witnesses, list):
            raise ValueError("source and dependency entries must be lists")
        by_id = {}
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
                raise ValueError("invalid source entry")
            if entry["id"] in by_id:
                raise ValueError("duplicate source entry id")
            by_id[entry["id"]] = entry
        seen = set()
        for witness in witnesses:
            if not isinstance(witness, dict) or not isinstance(witness.get("entry_id"), str):
                raise ValueError("invalid dependency entry")
            entry_id = witness["entry_id"]
            if entry_id not in by_id or entry_id in seen:
                raise ValueError("dependency sidecar has an extra or duplicate entry")
            anchor = witness.get("anchor")
            if not isinstance(anchor, dict) or any(
                key not in anchor or key not in by_id[entry_id]
                or anchor[key] != by_id[entry_id][key] for key in _ANCHOR_KEYS
            ):
                raise ValueError("dependency anchor does not match its source entry")
            seen.add(entry_id)
        if seen != set(by_id):
            raise ValueError("dependency sidecar does not cover every source entry")


def capture_context(root: Path, query: str, budget=4000, method="bm25", tokenizer="bytes"):
    snapshot = build_index(root)
    bundle = make_bundle(snapshot, query, budget=budget, method=method, tokenizer=tokenizer)
    witnesses = capture_witnesses(bundle, root) if bundle["entries"] else None
    return _wrap(bundle, witnesses)


def check_context(context: dict, root: Path) -> dict:
    validate_context(context)
    source = verify_bundle(context["bundle"], root)
    if context["dependencies"] is None:
        dependencies = {"fresh": False, "summary": {"unresolved": 1}, "results": [],
                        "reason": "no dependency evidence was captured"}
    else:
        dependencies = verify_witnesses(context["dependencies"], root)
    recoverable = bool(source["results"]) and all(
        item["status"] in {"valid", "relocated"} for item in source["results"]
    )
    snapshot_consistent = bool(source.get("current_snapshot_id")) and (
        source.get("current_snapshot_id") == dependencies.get("current_snapshot_id")
    )
    can_reuse = source["valid"] and dependencies["fresh"] and snapshot_consistent
    can_repair = recoverable and dependencies["fresh"] and snapshot_consistent
    if can_reuse:
        recommendation = "reuse"
    elif can_repair:
        recommendation = "repair"
    elif source["valid"] and set(dependencies["summary"]) <= {"unchanged", "unresolved"}:
        recommendation = "review"
    else:
        recommendation = "retrieve"
    return {"context_id": context["id"], "source": source, "dependencies": dependencies,
            "can_reuse": can_reuse, "can_repair": can_repair,
            "snapshot_consistent": snapshot_consistent,
            "recommendation": recommendation,
            "guarantee": "exact source text and captured direct static dependencies only; "
            "unresolved references require review; behavior and completeness are not proved"}


def refresh_context(context: dict, root: Path) -> dict:
    """Repair if both contracts permit it; otherwise retrieve from current source.

Requery does not resolve unsupported dynamic dependencies. The returned artifact
keeps those limitations explicit when checked again.
    """
    assessment = check_context(context, root)
    old = context["bundle"]
    operation = "retrieved"
    if assessment["can_repair"]:
        bundle = repair_bundle(old, root)
        if bundle["entries"]:
            sidecar = capture_witnesses(bundle, root)
            updated = _wrap(bundle, sidecar)
            operation = "repaired"
        else:
            updated = capture_context(root, old["query"], old["budget"], old["method"],
                                      old["tokenizer"])
    else:
        updated = capture_context(root, old["query"], old["budget"], old["method"],
                                  old["tokenizer"])
    receipt = {"previous_context_id": context["id"], "operation": operation,
               "previous_recommendation": assessment["recommendation"],
               "source_statuses": assessment["source"]["summary"],
               "dependency_statuses": assessment["dependencies"]["summary"]}
    return _wrap(updated["bundle"], updated["dependencies"], receipt)
