#!/usr/bin/env python3
"""Freeze and run real external retrieval/source-check baselines; no models."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import sys
import time

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "src"))

from benchmarks.revision_baselines.adapter import (  # noqa: E402
    archex_context, archex_environment, prepare_retrieval_corpus,
    supplied_anchor_context, task_query,
)
from benchmarks.revision_baselines.diagnostics import (  # noqa: E402
    diagnose_saved_bundle, git_changed_files,
)
from benchmarks.revision_baselines.privacy import public_record  # noqa: E402
from benchmarks.revision_tasks.suite import load_frozen  # noqa: E402
from contextproof.evidence import make_bundle, render_bundle  # noqa: E402
from contextproof.index import build_index  # noqa: E402


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_public(path, value, label):
    result = public_record(value, label)
    path.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frozen", type=Path, default=PROJECT / "benchmarks/revision_tasks/frozen")
    parser.add_argument("--sources", type=Path, required=True,
                        help="local archive source root containing REPOSITORY/before and after")
    parser.add_argument("--work", type=Path, default=PROJECT / "work/revision-baselines")
    parser.add_argument("--output", type=Path, required=True,
                        help="new output directory; existing results are never overwritten")
    parser.add_argument("--archex-python", type=Path,
                        default=PROJECT / "work/archex-venv/bin/python")
    parser.add_argument("--budget", type=int, default=16000)
    parser.add_argument("--split", choices=["all", "development", "holdout"], default="all")
    parser.add_argument("--repeats", type=int, default=1)
    args = parser.parse_args()
    if args.budget <= 0 or args.repeats <= 0:
        parser.error("budget and repeats must be positive")
    if args.output.exists():
        parser.error("output directory already exists; preserve it and choose a new directory")
    task_protocol, tasks = load_frozen(args.frozen)
    tasks = [task for task in tasks if args.split == "all" or task["split"] == args.split]
    environment = archex_environment(args.archex_python, runtime_directory=args.work / "runtime")
    if not environment["ok"]:
        raise RuntimeError("pinned archex is unavailable: " + json.dumps(environment))
    args.output.mkdir(parents=True)
    manifest = json.loads((PROJECT / "benchmarks/v1/manifest.json").read_text())
    repositories = {row["name"]: row for row in manifest["repositories"]}
    corpora = {}
    for name in sorted({task["repository"] for task in tasks}):
        corpora[name] = {}
        for side in ("before", "after"):
            corpora[name][side] = prepare_retrieval_corpus(
                args.sources / name / side, args.work / "corpora" / name / side,
                repositories[name]["prefixes"])
    implementations = [Path(__file__), *sorted((PROJECT / "benchmarks/revision_baselines").glob("*.py"))]
    protocol = {
        "schema_version": 1, "frozen_at": datetime.now(timezone.utc).isoformat(),
        "study": "real external retrieval plus source-invalidation diagnostics",
        "tasks_sha256": task_protocol["tasks_sha256"],
        "task_protocol_sha256": digest(args.frozen / "protocol.json"),
        "task_ids": [task["id"] for task in tasks], "byte_cap": args.budget,
        "repeats": args.repeats, "environment": environment,
        "python": sys.version, "platform": platform.platform(), "corpora": corpora,
        "implementation_sha256": {path.relative_to(PROJECT).as_posix(): digest(path)
                                    for path in implementations},
        "methods": ["archex_query", "supplied_anchor_source", "fresh_bm25", "v1_exact_source",
                    "v1_one_hop", "git_changed_file", "whole_file_hash"],
        "configuration": {"archex": "public query API, BM25, native XML, refresh=True, explicit budget",
                          "native_budget": "byte_cap//6, measured proportional reduction on overflow",
                          "source_policy": "identical production Python allowlist for all retrievers",
                          "query": "probe source plus all supplied anchor names/paths; no oracle value",
                          "forbidden": "no code truncation, no model calls, no gold-driven parameter selection"},
        "timing": "external query time and process startup time are separate; first per-corpus query may be cold",
        "limitations": "diagnostic convenience tasks; different completeness predicates; no superiority inferred from bytes alone",
    }
    write_public(args.output / "protocol.json", protocol, "baseline-protocol")
    git_reports = {name: git_changed_files(values["before"]["root"], values["after"]["root"])
                   for name, values in corpora.items()}
    results = []
    for task in tasks:
        name = task["repository"]
        query = task_query(task)
        before = Path(corpora[name]["before"]["root"])
        after = Path(corpora[name]["after"]["root"])
        old_index = build_index(before, args.work / "contextproof" / f"{name}-before.sqlite3")
        old_bundle = make_bundle(old_index, query, budget=args.budget, method="bm25")
        diagnostics = diagnose_saved_bundle(old_bundle, before, after, git_report=git_reports[name])
        for repetition in range(args.repeats):
            started = time.perf_counter()
            index = build_index(after, args.work / "contextproof" / f"{name}-after.sqlite3")
            fresh = make_bundle(index, query, budget=args.budget, method="bm25")
            rendered = render_bundle(fresh)
            bm25 = {"rendered": rendered, "consumed": len(rendered.encode()),
                    "wall_seconds": time.perf_counter() - started, "stats": index.stats,
                    "omitted_count": fresh["omitted_count"],
                    "completeness_scope": "ranked chunks fitting budget; no task-sufficiency guarantee"}
            external = archex_context(after, query, args.budget, python=args.archex_python,
                                       cache_dir=args.work / "archex-cache" / name,
                                       runtime_directory=args.work / "runtime")
            row = {"task_id": task["id"], "repository": name, "split": task["split"],
                   "repetition": repetition, "query": query, "diagnostics": diagnostics,
                   "archex": external, "fresh_bm25": bm25,
                   "supplied_anchors": supplied_anchor_context(task, "after", args.budget)}
            published = write_public(args.output / f"{task['id']}-{repetition}.json", row,
                                     "baseline-result")
            results.append({"task_id": task["id"], "repetition": repetition,
                            "file": f"{task['id']}-{repetition}.json",
                            "archex_status": external["status"], "archex_bytes": external["consumed"],
                            "archex_complete": external["complete"],
                            "archex_query_seconds": external.get("query_wall_seconds"),
                            "bm25_bytes": bm25["consumed"],
                            "result_sha256": digest(args.output / f"{task['id']}-{repetition}.json")})
            print(json.dumps({key: results[-1][key] for key in
                              ("task_id", "repetition", "archex_status", "archex_bytes")}), flush=True)
            del published
    write_public(args.output / "summary.json", {"results": results,
                 "interpretation": "actual external output and costs; no model success or semantic accuracy measured"},
                 "baseline-summary")


if __name__ == "__main__":
    main()
