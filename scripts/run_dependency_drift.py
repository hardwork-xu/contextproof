#!/usr/bin/env python3
"""Observe direct-dependency invalidation on the preregistered diverse drift corpus."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import platform
import statistics
import time

from contextproof.dependencies import capture_witnesses, verify_witnesses
from contextproof.evidence import make_bundle, verify_bundle
from contextproof.index import build_index
from contextproof.models import Snapshot

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(repetitions=3):
    samples_file = ROOT / "benchmarks/v1/samples.json"
    samples = json.loads(samples_file.read_text())["samples"]
    names = sorted({row["repository"] for row in samples})
    observations, rows = [], []
    for name in names:
        before = ROOT / "work/v1-drift/sources" / name / "before"
        after = before.parent / "after"
        snapshot = build_index(before)
        selected = [row for row in samples if row["repository"] == name]
        chunk_map = {(chunk.path, chunk.start_line, chunk.end_line): chunk
                     for chunk in snapshot.chunks}
        chunks = [chunk_map[(row["path"], row["start_line"], row["end_line"])] for row in selected]
        subset = Snapshot(snapshot.id, snapshot.files, chunks, [], {})
        query = " ".join(sorted({chunk.symbol for chunk in chunks}))
        bundle = make_bundle(subset, query, budget=250000, method="bm25")
        if {entry["id"] for entry in bundle["entries"]} != {chunk.id for chunk in chunks}:
            raise RuntimeError("diagnostic batch omitted a preregistered sample")
        capture_times, verify_times = [], []
        for _ in range(repetitions):
            started = time.perf_counter()
            witnesses = capture_witnesses(bundle, before)
            capture_times.append(time.perf_counter() - started)
            started = time.perf_counter()
            checked = verify_witnesses(witnesses, after)
            verify_times.append(time.perf_counter() - started)
        if checked.get("error"):
            raise RuntimeError(checked["error"])
        source = verify_bundle(bundle, after)
        source_by_id = {item["entry_id"]: item["status"] for item in source["results"]}
        dep_by_id = {item["entry_id"]: item for item in checked["results"]}
        for sample, chunk in zip(selected, chunks):
            dep = dep_by_id[chunk.id]
            source_status = source_by_id[chunk.id]
            recoverable = source_status in {"valid", "relocated"}
            anchor_status = dep["anchor_status"]
            reference_changed = any(ref["status"] in {"changed", "missing"}
                                    for ref in dep["references"])
            rows.append({"sample_id": sample["sample_id"], "repository": name,
                         "split": sample["split"], "path": sample["path"],
                         "source_status": source_status, "dependency_status": dep["status"],
                         "anchor_status": anchor_status,
                         "text_recoverable": recoverable,
                         "additionally_flagged": recoverable and dep["status"] in {"changed", "missing"},
                         "direct_reference_flag": recoverable and anchor_status == "unchanged"
                         and reference_changed,
                         "anchor_flag": recoverable and anchor_status in {"changed", "missing"},
                         "needs_review": recoverable and dep["status"] == "unresolved",
                         "reference_statuses": dict(Counter(ref["status"] for ref in dep["references"]))})
        observations.append({"repository": name, "repetitions": repetitions,
                             "capture_seconds": capture_times, "verify_seconds": verify_times,
                             "capture_median_seconds": statistics.median(capture_times),
                             "verify_median_seconds": statistics.median(verify_times),
                             "witness_json_bytes": len(json.dumps(witnesses, ensure_ascii=False).encode()),
                             "source_bundle_json_bytes": len(json.dumps(bundle, ensure_ascii=False).encode()),
                             "source_rendered_bytes": bundle["consumed"]})
        print(f"{name}: {len(selected)} dependency observations", flush=True)
    quality = {"samples": len(rows), "text_recoverable": sum(row["text_recoverable"] for row in rows),
               "additionally_flagged": sum(row["additionally_flagged"] for row in rows),
               "direct_reference_flags": sum(row["direct_reference_flag"] for row in rows),
               "anchor_flags": sum(row["anchor_flag"] for row in rows),
               "needs_review": sum(row["needs_review"] for row in rows),
               "dependency_statuses": dict(sorted(Counter(row["dependency_status"] for row in rows).items())),
               "rows": rows}
    return {"protocol": "All frozen v1 drift samples, no selection by dependency outcome. "
            "Batch diagnostic bundle budget=250000 UTF-8 bytes; this is not a retrieval budget experiment. "
            "Source-text acceptance vs direct-static witness invalidation; additional flags are "
            "observations, not independently labeled correctness or semantic staleness.",
            "provenance": {"samples_sha256": digest(samples_file),
                           "implementation_sha256": hashlib.sha256(b"".join(
                               path.name.encode() + path.read_bytes()
                               for path in sorted((ROOT / "src/contextproof").glob("*.py")))).hexdigest(),
                           "runner_sha256": digest(Path(__file__))},
            "quality": quality, "observations": {"python": platform.python_version(),
            "platform": platform.platform(), "repositories": observations}}


def markdown(result):
    quality = result["quality"]
    lines = ["# Dependency diagnostics on natural version drift", "", result["protocol"], "",
             f"Evaluated {quality['samples']} frozen samples. Exact text remained recoverable for "
             f"{quality['text_recoverable']}; the sidecar additionally flagged "
             f"{quality['additionally_flagged']} as changed/missing and marked "
             f"{quality['needs_review']} as unresolved for review.", "",
             f"Of the additional flags, {quality['anchor_flags']} concern the anchor itself "
             "(including file movement that the source-text verifier can relocate). "
             f"Only {quality['direct_reference_flags']} have an unchanged anchor and a "
             "changed/missing direct reference. Anchor flags must not be counted as detections "
             "of changed dependencies behind unchanged callers.", "",
             "| Repository | Samples | Recoverable text | Additional flags | Anchor flags | Direct-reference flags | Needs review |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for name in sorted({row["repository"] for row in quality["rows"]}):
        rows = [row for row in quality["rows"] if row["repository"] == name]
        lines.append(f"| {name} | {len(rows)} | {sum(r['text_recoverable'] for r in rows)} | "
                     f"{sum(r['additionally_flagged'] for r in rows)} | "
                     f"{sum(r['anchor_flag'] for r in rows)} | "
                     f"{sum(r['direct_reference_flag'] for r in rows)} | "
                     f"{sum(r['needs_review'] for r in rows)} |")
    lines += ["", "Reference annotation in the drift study labels exact text, not dependency behavior. "
              "Therefore this experiment does not estimate true-positive dependency detection or "
              "over-invalidation in natural code. Labeled controlled cases provide those contract checks.",
              "", "Three repeated per-repository capture/verify measurements and sidecar sizes are in "
              "[the raw report](dependency-drift.json). Sidecars are outside the source-context budget.", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "benchmarks/v1/results/dependency-drift")
    parser.add_argument("--check", type=Path)
    args = parser.parse_args()
    result = run()
    if args.check and result["quality"] != json.loads(args.check.read_text())["quality"]:
        raise RuntimeError("dependency drift quality changed")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix(".json").write_text(json.dumps(result, indent=2) + "\n")
    args.output.with_suffix(".md").write_text(markdown(result))


if __name__ == "__main__":
    main()
