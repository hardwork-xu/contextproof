#!/usr/bin/env python3
"""Freeze equal-budget source conditions before inspecting held-out model answers."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmarks.revision_baselines.adapter import (  # noqa: E402
    archex_context, archex_environment, prepare_retrieval_corpus, supplied_anchor_context, task_query,
)
from benchmarks.revision_model import canonical, sha, write_json  # noqa: E402
from benchmarks.revision_tasks.suite import load_frozen  # noqa: E402
from contextproof.evidence import make_bundle, render_bundle  # noqa: E402
from contextproof.graph import build_graph  # noqa: E402
from contextproof.graph_payload import render_graph_context  # noqa: E402
from contextproof.index import build_index  # noqa: E402
from contextproof.revisions import read_worktree  # noqa: E402

PREFIXES = {"packaging": ["src/packaging"], "httpx": ["httpx"],
            "pluggy": ["src/pluggy"], "attrs": ["src/attr", "src/attrs"]}
BUDGET = 16000
OUTPUT = ROOT / "benchmarks/revision_tasks/model-inputs"


def graph_anchors(task):
    records = []
    for anchor in task["source_anchors"]["after"]:
        matches = anchor["matches"] or [{**anchor, "text": "# unavailable source\n",
                                        "start_line": 1, "end_line": 1}]
        for match in matches:
            source = match["text"]
            record = {key: match[key] for key in ("path", "symbol", "start_line", "end_line", "text")}
            record.update(text_sha256=sha(source.encode()),
                          kind="class" if any(line.lstrip().startswith("class ") for line in source.splitlines()[:5])
                          else "function")
            record["id"] = sha(canonical(record).encode())
            records.append(record)
    return records


def main():
    if OUTPUT.exists():
        raise ValueError("input directory already exists; never overwrite a frozen input set")
    protocol, tasks = load_frozen(ROOT / "benchmarks/revision_tasks/frozen")
    corpora, snapshots, revisions = {}, {}, {}
    for repository, roots in protocol["source_roots"].items():
        for side, root in roots.items():
            key = (repository, side)
            corpus = prepare_retrieval_corpus((ROOT / root).resolve(),
                                             ROOT / "work/revision-corpora" / repository / side,
                                             PREFIXES[repository])
            corpora[key] = corpus
            snapshots[key] = build_index(Path(corpus["root"]))
            revisions[key] = read_worktree(Path(corpus["root"]))
    records, diagnostics = [], []
    for task in tasks:
        query = task_query(task)
        current = (task["repository"], "after")
        methods = {"no_context": {"rendered": "", "consumed": 0, "status": "intentional_no_source"},
                   "stale_anchors": supplied_anchor_context(task, "before", BUDGET),
                   "fresh_anchors": supplied_anchor_context(task, "after", BUDGET)}
        start = time.perf_counter()
        bundle = make_bundle(snapshots[current], query, budget=BUDGET, method="bm25", tokenizer="bytes")
        methods["fresh_bm25"] = {"rendered": render_bundle(bundle), "consumed": bundle["consumed"],
                                 "retrieval_seconds": time.perf_counter() - start,
                                 "snapshot_id": bundle["snapshot_id"]}
        start = time.perf_counter()
        revision = revisions[current]
        graph = build_graph(revision.texts, revision.snapshot_id, graph_anchors(task), max_depth=4, max_nodes=256)
        methods["graph_current"] = {**render_graph_context(graph, BUDGET),
                                     "retrieval_seconds": time.perf_counter() - start}
        for condition, result in methods.items():
            records.append({"task_id": task["id"], "condition": condition, "context": result["rendered"]})
            diagnostics.append({"task_id": task["id"], "condition": condition,
                                **{key: value for key, value in result.items() if key != "rendered"}})
    def external(task):
        result = archex_context(corpora[(task["repository"], "after")]["root"], task_query(task), BUDGET)
        return task, result
    with ThreadPoolExecutor(max_workers=2) as pool:
        for task, result in pool.map(external, tasks):
            if result["status"] == "unavailable":
                write_json(ROOT / "work/revision/archex-prepare-failure.json", result)
                raise ValueError("external tool unavailable; preserve failure, fix setup before freezing")
            records.append({"task_id": task["id"], "condition": "archex", "context": result["rendered"]})
            diagnostics.append({"task_id": task["id"], "condition": "archex",
                                **{key: value for key, value in result.items() if key != "rendered"}})
            print(json.dumps({"prepared": task["id"], "archex_bytes": result["consumed"]}), flush=True)
    records.sort(key=lambda row: (row["task_id"], row["condition"]))
    if any(len(row["context"].encode()) > BUDGET for row in records):
        raise ValueError("prepared evidence violates the shared cap")
    config = {"task_manifest_sha256": protocol["tasks_sha256"], "budget_utf8_bytes": BUDGET,
              "conditions": sorted({row["condition"] for row in records}),
              "context_records_sha256": sha(canonical(records).encode()),
              "selection": "same production-only Python source corpus and upstream-derived anchor hints",
              "excluded": ["tests", "testing", "documentation", "changelogs", "versions", "oracle answers"],
              "corpora": {f"{repo}/{side}": {key: value for key, value in corpus.items() if key != "root"}
                          for (repo, side), corpus in corpora.items()},
              "archex_environment": archex_environment(ROOT / "work/archex-venv/bin/python"),
              "implementation_sha256": {str(path.relative_to(ROOT)): sha(path.read_bytes())
                                        for folder in (ROOT / "src/contextproof", ROOT / "benchmarks/revision_baselines")
                                        for path in sorted(folder.glob("*.py"))}}
    write_json(OUTPUT / "contexts.json", records)
    write_json(OUTPUT / "diagnostics.json", diagnostics)
    write_json(OUTPUT / "protocol.json", config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
