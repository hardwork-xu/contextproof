#!/usr/bin/env python3
"""Freeze corrected-graph inputs without changing any original inference cells."""

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmarks.revision_model import canonical, sha, write_json  # noqa: E402
from contextproof.graph import RESOLVER_VERSION, build_graph  # noqa: E402
from contextproof.graph_payload import render_graph_context  # noqa: E402
from contextproof.revisions import read_worktree  # noqa: E402
from scripts.prepare_revision_contexts import graph_anchors  # noqa: E402


def main():
    output = ROOT / "benchmarks/revision_tasks/scope-sensitivity-inputs"
    if output.exists():
        raise ValueError("refusing to overwrite frozen sensitivity inputs")
    if RESOLVER_VERSION != 2:
        raise ValueError("this amendment specifies resolver version 2")
    tasks = json.loads((ROOT / "benchmarks/revision_tasks/frozen/tasks.json").read_text())
    tasks = [task for task in tasks if task["split"] == "holdout"]
    originals = {row["task_id"]: row for row in json.loads(
        (ROOT / "benchmarks/revision_tasks/model-inputs/contexts.json").read_text())
        if row["condition"] == "graph_current"}
    contexts, diagnostics = [], []
    revisions = {name: read_worktree(ROOT / "work/revision-corpora" / name / "after")
                 for name in {task["repository"] for task in tasks}}
    for task in tasks:
        revision = revisions[task["repository"]]
        graph = build_graph(revision.texts, revision.snapshot_id, graph_anchors(task),
                            max_depth=4, max_nodes=256)
        payload = render_graph_context(graph, 16000)
        contexts.append({"task_id": task["id"], "condition": "graph_current", "context": payload["rendered"]})
        old = json.loads(originals[task["id"]]["context"])
        current = json.loads(payload["rendered"])
        old_text = sorted(node["text"] for node in old["nodes"])
        current_text = sorted(node["text"] for node in current["nodes"])
        diagnostics.append({"task_id": task["id"], "resolver_version": RESOLVER_VERSION,
                            "source_delivery_changed": old_text != current_text,
                            "original_graph_id": old["graph_id"],
                            **{key: value for key, value in payload.items() if key != "rendered"}})
    write_json(output / "contexts.json", contexts)
    write_json(output / "diagnostics.json", diagnostics)
    write_json(output / "protocol.json", {
        "resolver_version": 2, "budget_utf8_bytes": 16000, "tasks": 25,
        "condition": "graph_current", "model": "gpt-6-astra", "reasoning_effort": "medium",
        "semantic_attempts_per_task": 1, "parallel": 4,
        "context_records_sha256": sha(canonical(contexts).encode()),
        "source_delivery_changed_tasks": sum(row["source_delivery_changed"] for row in diagnostics),
        "original_protocol_commit": "0c6d0be9713971c36430c2f9f80cf24240e4e8da",
        "interpretation": "Exploratory sensitivity after independent correctness audit and partial "
                          "original outcomes. All original attempts retained; no baseline reruns, "
                          "no further prompt or retrieval-budget tuning.",
        "implementation_sha256": {str(path.relative_to(ROOT)): sha(path.read_bytes())
                                  for path in sorted((ROOT / "src/contextproof").glob("*.py"))}})


if __name__ == "__main__":
    main()
