#!/usr/bin/env python3
"""Measure hand-specified static dependency cases without executing fixture code."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import statistics
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from benchmarks.dependency_cases import CASES  # noqa: E402
from contextproof.dependencies import capture_witnesses, verify_witnesses  # noqa: E402
from contextproof.evidence import make_bundle, render_bundle, verify_bundle  # noqa: E402
from contextproof.index import build_index  # noqa: E402
from contextproof.models import Snapshot  # noqa: E402


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def write_sources(root: Path, files: dict) -> None:
    for name, source in files.items():
        path = root / name
        if source is None:
            path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source, encoding="utf-8")


def subject_bundle(root: Path, path: str = "app.py", symbol: str = "subject") -> dict:
    snapshot = build_index(root)
    chunks = [chunk for chunk in snapshot.chunks if chunk.path == path and chunk.symbol == symbol]
    if not chunks:
        raise RuntimeError(f"Fixture subject absent: {path}:{symbol}")
    selected = Snapshot(snapshot.id, snapshot.files, chunks, [], {})
    return make_bundle(selected, symbol, budget=1000000, method="bm25")


def measured(operation, repeats: int) -> tuple[object, list[float]]:
    samples = []
    results = []
    for _ in range(repeats):
        start = time.perf_counter_ns()
        result = operation()
        samples.append((time.perf_counter_ns() - start) / 1_000_000)
        results.append(result)
    if any(result != results[0] for result in results):
        raise RuntimeError("Repeated operation changed its deterministic result")
    return results[0], samples


def timings(samples: list[float]) -> dict:
    return {"samples_ms": [round(sample, 6) for sample in samples],
            "median_ms": round(statistics.median(samples), 6),
            "min_ms": round(min(samples), 6), "max_ms": round(max(samples), 6)}


def controlled(root: Path, repeats: int) -> dict:
    results = []
    for case in CASES:
        directory = root / case.name
        directory.mkdir()
        write_sources(directory, case.before)
        bundle = subject_bundle(directory, case.path, case.symbol)
        witnesses, capture_ms = measured(lambda: capture_witnesses(bundle, directory), repeats)
        bundle_bytes = len(render_bundle(bundle).encode())
        witness_bytes = len(canonical(witnesses))
        write_sources(directory, case.after)
        report, verify_ms = measured(lambda: verify_witnesses(witnesses, directory), repeats)
        exact, exact_ms = measured(lambda: verify_bundle(bundle, directory), repeats)
        exact_usable = all(entry["status"] in {"valid", "relocated"} for entry in exact["results"])
        results.append({
            "case": case.name, "category": case.category, "fixture_sha256": digest(canonical(asdict(case))),
            "expected": case.expected, "observed": report["status"],
            "correct": case.expected == report["status"], "fresh": report["fresh"],
            "exact_text_usable": exact_usable,
            "exact_text_statuses": [entry["status"] for entry in exact["results"]],
            "bundle_id": bundle["id"], "witness_id": witnesses["id"],
            "reference_count": sum(len(entry["references"]) for entry in witnesses["entries"]),
            "resolved_reference_count": sum(reference["status"] == "resolved"
                                             for entry in witnesses["entries"] for reference in entry["references"]),
            "bundle_rendered_utf8_bytes": bundle_bytes, "sidecar_json_utf8_bytes": witness_bytes,
            "additional_bytes_ratio": round(witness_bytes / bundle_bytes, 6),
            "capture": timings(capture_ms), "verify_dependencies": timings(verify_ms),
            "verify_exact_text": timings(exact_ms),
        })
    stale_cases = [row for row in results if row["expected"] in {"changed", "missing", "invalid"}]
    summary = {
        "case_count": len(results), "correct_status_count": sum(row["correct"] for row in results),
        "expected_counts": dict(sorted(Counter(row["expected"] for row in results).items())),
        "observed_counts": dict(sorted(Counter(row["observed"] for row in results).items())),
        "explicitly_stale_cases": len(stale_cases),
        "dependency_unsafe_accepts_on_stale_cases": sum(row["fresh"] for row in stale_cases),
        "exact_text_unsafe_accepts_on_stale_cases": sum(row["exact_text_usable"] for row in stale_cases),
        "unresolved_cases": sum(row["observed"] == "unresolved" for row in results),
        "unresolved_cases_accepted_as_fresh": sum(row["fresh"] for row in results
                                                   if row["expected"] == "unresolved"),
        "median_capture_ms_across_cases": round(statistics.median(row["capture"]["median_ms"] for row in results), 6),
        "median_dependency_verify_ms_across_cases": round(statistics.median(row["verify_dependencies"]["median_ms"]
                                                                          for row in results), 6),
        "median_sidecar_json_bytes": statistics.median(row["sidecar_json_utf8_bytes"] for row in results),
        "median_additional_bytes_ratio": statistics.median(row["additional_bytes_ratio"] for row in results),
    }
    return {"summary": summary, "cases": results}


def scaling(root: Path, repeats: int, sizes: list[int]) -> list[dict]:
    results = []
    for count in sizes:
        directory = root / f"scale-{count}"
        directory.mkdir()
        files = {"app.py": "from helpers import helper\ndef subject():\n    return helper()\n",
                 "helpers.py": "def helper():\n    return 1\n"}
        files.update({f"filler_{number:05}.py": f"def value_{number}():\n    return {number}\n"
                      for number in range(count - 2)})
        write_sources(directory, files)
        bundle = subject_bundle(directory)
        witnesses, capture_ms = measured(lambda: capture_witnesses(bundle, directory), repeats)
        report, verify_ms = measured(lambda: verify_witnesses(witnesses, directory), repeats)
        exact, exact_ms = measured(lambda: verify_bundle(bundle, directory), repeats)
        if not report["fresh"] or not exact["valid"]:
            raise RuntimeError("Unchanged scaling fixture was not fresh")
        results.append({"python_files": len(files),
                        "source_utf8_bytes": sum(len(source.encode()) for source in files.values()),
                        "selected_entries": len(bundle["entries"]),
                        "captured_direct_references": sum(len(entry["references"]) for entry in witnesses["entries"]),
                        "capture": timings(capture_ms), "verify_dependencies": timings(verify_ms),
                        "verify_exact_text": timings(exact_ms)})
    return results


def markdown(report: dict) -> str:
    summary = report["controlled"]["summary"]
    lines = ["# Direct dependency witness benchmark", "",
             "Controlled static source transformations, with expected labels specified independently in "
             "`benchmarks/dependency_cases.py`. Repository fixture code is never executed.", "",
             f"- Correct declared statuses: **{summary['correct_status_count']}/{summary['case_count']}**.",
             f"- Explicitly stale cases: **{summary['explicitly_stale_cases']}**; accepted as fresh by dependency "
             f"verification: **{summary['dependency_unsafe_accepts_on_stale_cases']}**; still usable under "
             f"exact-text-only verification: **{summary['exact_text_unsafe_accepts_on_stale_cases']}**.",
             f"- Unresolved cases: **{summary['unresolved_cases']}**; accepted as fresh: "
             f"**{summary['unresolved_cases_accepted_as_fresh']}**.",
             f"- Repetitions per measured operation: **{report['repeats']}**. Medians below include a "
             "complete safe source scan; indexing and fixture setup are excluded.",
             f"- Median serialized sidecar: **{summary['median_sidecar_json_bytes']:g} bytes**, "
             f"an additional **{summary['median_additional_bytes_ratio']:.2f}×** the original rendered bundle. "
             "The sidecar is out of band and is not included in that bundle's model-context budget.", "",
             "## Per-case results", "",
             "| Case | Expected | Observed | Exact text usable | Capture ms | Dependency verify ms | Sidecar bytes |",
             "| --- | --- | --- | --- | ---: | ---: | ---: |"]
    for row in report["controlled"]["cases"]:
        lines.append(f"| {row['case']} | {row['expected']} | {row['observed']} | "
                     f"{str(row['exact_text_usable']).lower()} | {row['capture']['median_ms']:.3f} | "
                     f"{row['verify_dependencies']['median_ms']:.3f} | {row['sidecar_json_utf8_bytes']} |")
    lines += ["", "## Source scan scaling", "",
              "Each fixture selects one function with one direct imported helper; unrelated files increase. "
              "These small synthetic modules measure source scan/parse overhead, not real-world repository complexity.", "",
              "| Python files | Source bytes | Capture ms | Dependency verify ms | Exact-text verify ms |",
              "| ---: | ---: | ---: | ---: | ---: |"]
    for row in report["scaling"]:
        lines.append(f"| {row['python_files']} | {row['source_utf8_bytes']} | {row['capture']['median_ms']:.3f} | "
                     f"{row['verify_dependencies']['median_ms']:.3f} | {row['verify_exact_text']['median_ms']:.3f} |")
    lines += ["", "## Interpretation and reproducibility", "",
              "`unchanged` is a bounded one-hop source/binding claim. The `one_hop_boundary` case intentionally "
              "leaves a grandchild edit undetected. Dynamic, external, ambiguous and unsupported resolution "
              "abstains. Perfect agreement on these designed cases is not an unbiased semantic-accuracy estimate "
              "and does not establish coding-agent task success.", "",
              "Run `python scripts/run_dependency_benchmarks.py --repeats 7`. JSON includes all timing samples, "
              "fixture and implementation SHA-256 values, deterministic quality digest, payload bytes and environment. "
              "Wall-clock measurements vary by host and run; status/quality results should reproduce.", "",
              f"Generated: {report['generated_at']}. Python {report['environment']['python']}; "
              f"{report['environment']['system']} {report['environment']['machine']}.", "",
              f"Quality SHA-256: `{report['quality_sha256']}`.", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--scale-files", type=int, nargs="+", default=[10, 100, 500])
    parser.add_argument("--output", type=Path, default=ROOT / "benchmarks/results/dependencies.json")
    args = parser.parse_args()
    if args.repeats < 2 or any(size < 2 for size in args.scale_files):
        parser.error("use at least 2 repetitions and at least 2 source files")
    (ROOT / "work").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dependencies-", dir=ROOT / "work") as temporary:
        root = Path(temporary)
        controlled_result = controlled(root, args.repeats)
        scaling_result = scaling(root, args.repeats, args.scale_files)
    quality = [{key: row[key] for key in ("case", "fixture_sha256", "expected", "observed", "correct",
                                         "fresh", "exact_text_usable", "exact_text_statuses")}
               for row in controlled_result["cases"]]
    implementation_paths = ["src/contextproof/dependencies.py", "src/contextproof/evidence.py",
                            "src/contextproof/index.py", "benchmarks/dependency_cases.py",
                            "scripts/run_dependency_benchmarks.py"]
    report = {"schema_version": 1, "experiment": "controlled-direct-python-dependencies",
              "generated_at": datetime.now(timezone.utc).isoformat(), "repeats": args.repeats,
              "environment": {"python": platform.python_version(), "system": platform.system(),
                              "machine": platform.machine()},
              "implementation_sha256": {path: digest((ROOT / path).read_bytes()) for path in implementation_paths},
              "quality_sha256": digest(canonical(quality)), "controlled": controlled_result,
              "scaling": scaling_result}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    args.output.with_suffix(".md").write_text(markdown(report), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "quality_sha256": report["quality_sha256"],
                      "summary": controlled_result["summary"]}, indent=2))
    return 0 if all(row["correct"] for row in controlled_result["cases"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
