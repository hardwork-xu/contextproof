#!/usr/bin/env python3
"""Run source-only controlled, drift, cache, and retrieval experiments.

No upstream code is imported, installed, built, or executed. Downloads are pinned
by commit and SHA-256 and remain in ignored work/. See docs/EVALUATION.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import tarfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from benchmarks.oracles import (  # noqa: E402
    ACCEPTABLE, EXPECTED, SOURCE, binary_metrics, file_hash_accepts,
    path_line_accepts, retrieval_metrics, transform,
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def prepare_sources(manifest: dict, work: Path, download: bool) -> dict:
    roots = {}
    destination = work / "upstreams"
    destination.mkdir(parents=True, exist_ok=True)
    for repository in manifest["repositories"]:
        for side, version in repository["versions"].items():
            name = f"{repository['name']}-{version['commit']}"
            archive = destination / f"{name}.tar.gz"
            if not archive.exists():
                if not download:
                    raise RuntimeError(f"Missing {archive.name}; rerun with --download")
                subprocess.run([
                    "curl", "--fail", "--location", "--silent", "--show-error",
                    "--connect-timeout", "30", "--max-time", "180",
                    "--output", str(archive), version["archive_url"],
                ], check=True)
            if sha256(archive.read_bytes()) != version["archive_sha256"]:
                raise RuntimeError(f"Archive digest mismatch: {archive.name}")
            output = destination / name
            if output.exists():
                shutil.rmtree(output)
            output.mkdir()
            # Extract regular files only. Never trust archive paths or symlinks.
            with tarfile.open(archive, "r:gz") as tar:
                for member in tar:
                    path = PurePosixPath(member.name)
                    if path.is_absolute() or ".." in path.parts:
                        raise RuntimeError(f"Unsafe archive member: {member.name}")
                    if not path.parts or path.parts[0] != name:
                        raise RuntimeError(f"Unexpected archive prefix: {member.name}")
                    if not member.isfile():
                        continue
                    target = output.joinpath(*path.parts[1:])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    stream = tar.extractfile(member)
                    if stream is None:
                        raise RuntimeError(f"Unreadable archive member: {member.name}")
                    target.write_bytes(stream.read())
            roots[(repository["name"], side)] = output
    return roots


def singleton_bundle(snapshot, chunk, make_bundle):
    from contextproof.models import Snapshot
    selected = Snapshot(snapshot.id, snapshot.files, [chunk], [], {})
    return make_bundle(
        selected, query=chunk.symbol or chunk.path, budget=8000,
        method="bm25", tokenizer="bytes",
    )


def controlled_experiment(work: Path) -> dict:
    from contextproof.evidence import make_bundle, repair_bundle, verify_bundle
    from contextproof.index import build_index
    controlled = work / "controlled"
    if controlled.exists():
        shutil.rmtree(controlled)
    before = controlled / "before"
    before.mkdir(parents=True)
    (before / "subject.py").write_text(SOURCE, encoding="utf-8")
    snapshot = build_index(before)
    chunk = next(c for c in snapshot.chunks if c.symbol == "stable_total")
    bundle = singleton_bundle(snapshot, chunk, make_bundle)
    if len(bundle["entries"]) != 1:
        raise RuntimeError("Controlled bundle must contain one complete chunk")
    rows = []
    for case, expected in EXPECTED.items():
        after = controlled / case
        candidate = transform(case, after, bundle)
        entry = candidate["entries"][0]
        report = verify_bundle(candidate, after)
        status = report["results"][0]["status"]
        repair_error = None
        try:
            repaired = repair_bundle(candidate, after)
            repaired_entries = repaired.get("entries", [])
            repaired_report = verify_bundle(repaired, after)
        except ValueError as error:
            if expected != "invalid":
                raise
            repair_error = str(error)
            repaired_entries = []
            repaired_report = {"summary": {}, "results": []}
        rows.append({
            "case": case, "expected_status": expected, "observed_status": status,
            "status_correct": status == expected,
            "expected_accept": expected in ACCEPTABLE,
            "predictions": {
                "path_line_exact": path_line_accepts(entry, after),
                "file_hash": file_hash_accepts(entry, after),
                "contextproof": status in ACCEPTABLE,
            },
            "repair_error": repair_error,
            "repair_retained_entries": len(repaired_entries),
            "repair_remaining_statuses": repaired_report["summary"],
            "repair_contract_met": (
                len(repaired_entries) == (1 if expected in ACCEPTABLE else 0)
                and len(repaired_report["results"]) == len(repaired_entries)
                and all(r["status"] == "valid" for r in repaired_report["results"])
            ),
        })
    return {
        "oracle": "Independent fixed transformation labels; accept means untampered exact text at an unambiguous recoverable location, never semantic equivalence.",
        "cases": rows,
        "status_accuracy": sum(row["status_correct"] for row in rows) / len(rows),
        "repair_contract_accuracy": sum(row["repair_contract_met"] for row in rows) / len(rows),
        "metrics": {
            method: binary_metrics(
                [row["expected_accept"] for row in rows],
                [row["predictions"][method] for row in rows],
            )
            for method in ("path_line_exact", "file_hash", "contextproof")
        },
    }


def sample_chunks(snapshot, root: Path, size: int = 40):
    from contextproof.index import source_lines
    source_files = {
        path: (root / path).read_bytes().decode("utf-8")
        for path in snapshot.files if path.startswith("src/") and path.endswith(".py")
    }
    eligible = [
        chunk for chunk in snapshot.chunks
        if chunk.path in source_files
        and 3 <= len(source_lines(chunk.text))
        and len(chunk.text.encode("utf-8")) <= 6000
        and sum(text.count(chunk.text) for text in source_files.values()) == 1
    ]
    def key(chunk):
        return sha256(
            (chunk.path + "\0" + chunk.symbol + "\0" + chunk.text).encode("utf-8")
        )
    eligible.sort(key=key)
    return eligible[:size], len(eligible)


def natural_experiment(name: str, snapshot, before: Path, after: Path) -> dict:
    from contextproof.evidence import make_bundle, verify_bundle
    selected, eligible_count = sample_chunks(snapshot, before)
    rows = []
    excluded = []
    for chunk in selected:
        bundle = singleton_bundle(snapshot, chunk, make_bundle)
        if not bundle["entries"]:
            excluded.append({"path": chunk.path, "symbol": chunk.symbol, "reason": "8000-byte budget"})
            continue
        entry = bundle["entries"][0]
        report = verify_bundle(bundle, after)
        rows.append({
            "path": chunk.path, "symbol": chunk.symbol,
            "start_line": chunk.start_line, "end_line": chunk.end_line,
            "text_sha256": sha256(chunk.text.encode("utf-8")),
            "status": report["results"][0]["status"],
            "path_line_exact_accept": path_line_accepts(entry, after),
            "file_hash_accept": file_hash_accepts(entry, after),
        })
    return {
        "repository": name, "eligible_count": eligible_count,
        "sampled_count": len(selected), "evaluated_count": len(rows),
        "budget_excluded": excluded,
        "status_counts": dict(sorted(Counter(row["status"] for row in rows).items())),
        "baseline_accept_counts": {
            "path_line_exact": sum(row["path_line_exact_accept"] for row in rows),
            "file_hash": sum(row["file_hash_accept"] for row in rows),
        },
        "samples": rows,
    }


def retrieval_experiment(name: str, snapshot, queries: list[dict]) -> list[dict]:
    from contextproof.evidence import make_bundle, render_bundle
    rows = []
    for query in queries:
        for method in ("bm25", "graph"):
            for budget in (2000, 4000, 8000):
                bundle = make_bundle(snapshot, query["query"], budget, method, "bytes")
                paths = [entry["path"] for entry in bundle["entries"]]
                cost = len(render_bundle(bundle).encode("utf-8"))
                rows.append({
                    "repository": name, "query_id": query["id"],
                    "method": method, "budget_bytes": budget,
                    "rendered_bytes": cost, "reported_consumed": bundle["consumed"],
                    "within_budget": cost <= budget,
                    "reported_cost_matches": cost == bundle["consumed"],
                    "entry_count": len(paths), "returned_files": paths,
                    **retrieval_metrics(query["relevant_files"], paths),
                })
    return rows


def summarize_retrieval(rows: list[dict]) -> list[dict]:
    summaries = []
    for method in ("bm25", "graph"):
        for budget in (2000, 4000, 8000):
            selected = [row for row in rows if row["method"] == method and row["budget_bytes"] == budget]
            summaries.append({
                "method": method, "budget_bytes": budget, "queries": len(selected),
                "hit_rate": sum(row["hit"] for row in selected) / len(selected),
                "mean_file_recall": sum(row["file_recall"] for row in selected) / len(selected),
                "mean_reciprocal_rank": sum(row["reciprocal_rank"] for row in selected) / len(selected),
                "budget_violations": sum(not row["within_budget"] for row in selected),
                "accounting_mismatches": sum(not row["reported_cost_matches"] for row in selected),
            })
    return summaries


def implementation_digest() -> str:
    paths = sorted([
        *ROOT.glob("src/contextproof/*.py"), *ROOT.glob("benchmarks/*.py"),
        ROOT / "scripts/run_benchmarks.py", ROOT / "benchmarks/manifest.json",
        ROOT / "benchmarks/queries.json",
    ])
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.relative_to(ROOT).as_posix().encode() + b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def markdown_report(result: dict) -> str:
    q = result["quality"]
    lines = [
        "# Measured evaluation", "",
        "Generated by `python scripts/run_benchmarks.py --download`. "
        "See [protocol](../../docs/EVALUATION.md) and [full JSON](latest.json).", "",
        "## Controlled transformations", "",
        "Seven deterministic cases. These test exact-text provenance behavior, "
        "not semantic correctness or an independently sampled error rate.", "",
        "| Case | Expected | Observed | Repair contract |",
        "| --- | --- | --- | --- |",
    ]
    for row in q["controlled"]["cases"]:
        lines.append(f"| {row['case']} | {row['expected_status']} | {row['observed_status']} | {row['repair_contract_met']} |")
    lines += ["", "| Acceptance baseline | TP | FP | TN | FN |", "| --- | ---: | ---: | ---: | ---: |"]
    for method, scores in q["controlled"]["metrics"].items():
        lines.append(f"| {method} | {scores['true_positive']} | {scores['false_positive']} | {scores['true_negative']} | {scores['false_negative']} |")
    lines += [
        "", "## Natural version drift", "",
        "Status counts are system observations without independent ground truth. "
        "They are not accuracy, recall, or successful repair rates.", "",
        "| Repository | Eligible / sampled | Status counts | Old path+line accepts | Old file hash accepts |",
        "| --- | ---: | --- | ---: | ---: |",
    ]
    for row in q["natural_drift"]:
        counts = ", ".join(f"{key}: {value}" for key, value in row["status_counts"].items())
        baselines = row["baseline_accept_counts"]
        lines.append(f"| {row['repository']} | {row['eligible_count']} / {row['evaluated_count']} | {counts} | {baselines['path_line_exact']} | {baselines['file_hash']} |")
    lines += [
        "", "## Exploratory retrieval smoke test", "",
        "Fourteen author-written file-label queries, before revisions only. "
        "Labels are narrow and often include exact symbols. Results do not support "
        "claims of general retrieval quality or graph superiority.", "",
        "| Method | Full rendered byte budget | Hit rate | Mean file recall | MRR | Budget violations |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in q["retrieval_summary"]:
        lines.append(f"| {row['method']} | {row['budget_bytes']} | {row['hit_rate']:.3f} | {row['mean_file_recall']:.3f} | {row['mean_reciprocal_rank']:.3f} | {row['budget_violations']} |")
    lines += [
        "", "## Local indexing observations", "",
        "Single cold-cache and immediate warm-cache runs; wall-clock measurements "
        "depend on the environment and are not a throughput benchmark.", "",
        "| Repository | Cold seconds | Warm seconds | Cold parsed | Warm parsed / reused |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for row in result["observations"]["indexing"]:
        lines.append(f"| {row['repository']} | {row['cold_seconds']:.6f} | {row['warm_seconds']:.6f} | {row['cold_stats'].get('parsed')} | {row['warm_stats'].get('parsed')} / {row['warm_stats'].get('reused')} |")
    lines += [
        "", f"Measured at: {result['observations']['generated_at_utc']}. "
        f"Python {result['observations']['python']}; {result['observations']['platform']}.", "",
        "No upstream source was executed. No LLM was called. No semantic-equivalence "
        "or task-completion claim is made. All three repositories belong to the "
        "Pallets ecosystem, so this is a deliberately small and correlated sample.", "",
    ]
    return "\n".join(lines)


def run(download: bool, output: Path, check: Path | None = None) -> dict:
    from contextproof.index import build_index
    manifest = json.loads((ROOT / "benchmarks/manifest.json").read_text())
    queries = json.loads((ROOT / "benchmarks/queries.json").read_text())["repositories"]
    work = ROOT / "work"
    roots = prepare_sources(manifest, work, download)
    quality = {"controlled": controlled_experiment(work), "natural_drift": [], "retrieval": []}
    timings = []
    cache = work / "benchmark-cache"
    if cache.exists():
        shutil.rmtree(cache)
    cache.mkdir()
    for repository in manifest["repositories"]:
        name = repository["name"]
        before, after = roots[(name, "before")], roots[(name, "after")]
        cache_path = cache / f"{name}.sqlite3"
        start = time.perf_counter()
        snapshot = build_index(before, cache_path)
        cold = time.perf_counter() - start
        start = time.perf_counter()
        warm = build_index(before, cache_path)
        warm_time = time.perf_counter() - start
        timings.append({
            "repository": name, "cold_seconds": cold, "warm_seconds": warm_time,
            "cold_stats": snapshot.stats, "warm_stats": warm.stats,
        })
        quality["natural_drift"].append(natural_experiment(name, snapshot, before, after))
        quality["retrieval"].extend(retrieval_experiment(name, snapshot, queries[name]))
        print(f"Evaluated {name}: {len(snapshot.chunks)} chunks", flush=True)
    quality["retrieval_summary"] = summarize_retrieval(quality["retrieval"])
    result = {
        "schema_version": 1,
        "provenance": {
            "manifest_sha256": sha256((ROOT / "benchmarks/manifest.json").read_bytes()),
            "queries_sha256": sha256((ROOT / "benchmarks/queries.json").read_bytes()),
            "implementation_sha256": implementation_digest(),
        },
        "quality": quality,
        "observations": {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "python": platform.python_version(), "platform": platform.platform(),
            "machine": platform.machine(), "indexing": timings,
        },
    }
    if check:
        previous = json.loads(check.read_text())
        if previous["quality"] != quality:
            raise RuntimeError("Deterministic quality fields differ from comparison report")
        print("Deterministic quality fields match the comparison report.", flush=True)
    output.mkdir(parents=True, exist_ok=True)
    (output / "latest.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    (output / "latest.md").write_text(markdown_report(result))
    print(f"Reports written to {output}", flush=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true", help="Fetch missing frozen source archives")
    parser.add_argument("--output", type=Path, default=ROOT / "benchmarks/results")
    parser.add_argument("--check", type=Path, help="Compare only deterministic quality fields to a previous JSON report")
    args = parser.parse_args()
    run(args.download, args.output, args.check)


if __name__ == "__main__":
    main()
