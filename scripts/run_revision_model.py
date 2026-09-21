#!/usr/bin/env python3
"""Prepare, freeze, run and score source-conditioned real revision probes."""

import argparse
import json
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmarks.revision_baselines.adapter import supplied_anchor_context  # noqa: E402
from benchmarks.revision_model import canonical, run_jobs, sha, write_json  # noqa: E402
from benchmarks.revision_tasks.suite import load_frozen  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split", choices=("development", "holdout"), default="development")
    parser.add_argument("--model", default="gpt-6-astra")
    parser.add_argument("--parallel", type=int, default=2)
    parser.add_argument("--contexts", type=Path)
    parser.add_argument("--budget", type=int, default=16000)
    args = parser.parse_args()
    if args.output.absolute().is_relative_to(ROOT):
        parser.error("raw model output must be stored outside the Git checkout; export sanitized records later")
    protocol, tasks = load_frozen(ROOT / "benchmarks/revision_tasks/frozen")
    tasks = [task for task in tasks if task["split"] == args.split]
    if args.split == "holdout" and args.contexts is None:
        parser.error("holdout requires previously frozen contexts and model protocol")
    records = json.loads(args.contexts.read_text()) if args.contexts else [
        {"task_id": task["id"], "condition": "fresh_anchors",
         "context": supplied_anchor_context(task, "after", args.budget)["rendered"]} for task in tasks]
    args.output.mkdir(parents=True, exist_ok=True)
    config = {"model": args.model, "reasoning_effort": "medium", "budget_bytes": args.budget,
              "task_manifest_sha256": protocol["tasks_sha256"], "split": args.split,
              "semantic_attempts_per_cell": 1, "transport_retries": "CLI defaults; raw errors retained",
              "transport": "HTTPS via documented custom provider; unchanged authenticated OpenAI endpoint",
              "seed_for_job_order": 230921, "parallel": args.parallel,
              "qualification": "at least 4/5 development fresh-anchor exact answers before holdout",
              "contexts_sha256": sha(canonical(records).encode())}
    frozen = args.output / "run-config.json"
    if frozen.exists() and json.loads(frozen.read_text()) != config:
        raise ValueError("run config changed; use a new explicitly named run directory")
    write_json(frozen, config)
    lookup = {task["id"]: task for task in tasks}
    jobs = [{"task": lookup[row["task_id"]], "context": row["context"],
             "condition": row["condition"], "directory": args.output / "attempts" /
             f"{row['task_id']}__{row['condition']}"} for row in records if row["task_id"] in lookup]
    if any(len(job["context"].encode()) > args.budget for job in jobs):
        raise ValueError("evidence exceeds shared byte budget")
    random.Random(230921).shuffle(jobs)
    oracles = {row["id"]: row for row in json.loads(
        (ROOT / "benchmarks/revision_tasks/frozen/oracles.json").read_text())}
    results = []
    for job, record in run_jobs(jobs, parallel=args.parallel, codex=args.codex, model=args.model):
        expected = oracles[job["task"]["id"]]
        row = {"task_id": job["task"]["id"], "condition": job["condition"],
               "family": job["task"]["family"], "repository": job["task"]["repository"],
               "correct": record["valid_completion"] and canonical(record["answer"]) == canonical(expected["after"]),
               "matches_old": record["valid_completion"] and canonical(record["answer"]) == canonical(expected["before"]),
               "behavior_changed": expected["behavior_changed"], "record": record}
        results.append(row)
        write_json(args.output / "results.json", sorted(results, key=lambda row: (row["task_id"], row["condition"])))
        print(json.dumps({key: row[key] for key in ("task_id", "condition", "correct")}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
