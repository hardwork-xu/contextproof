"""Post-run harness controls; canonical solutions NEVER enter model inputs."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path

from benchmarks.downstream.suite import ROOT, adapt_task
from scripts.run_downstream import evaluate, now, sandbox_check, write_json

SOURCE_SHA256 = "b796127e635a67f93fb35c04f4cb03cf06f38c8072ee7cee8833d7bee06979ef"


def oracle_code(task: dict, original: dict, current: bool) -> str:
    """Keep original algorithm unchanged and wrap its call with an API decoder."""
    files = task["after_files"] if current else task["before_files"]
    module = Path(next(iter(files))).stem
    decoder = "decode_request" if current and task["drift"] == "symbol_rename" else "unpack_request"
    parameters = 'request, version="v2"' if current and task["drift"] == "signature_change" else "request"
    return (original["prompt"] + original["canonical_solution"]
            + f'\nreference_algorithm = {task["entry_point"]}\n'
            + f'from {module} import {decoder} as decode_arguments\n'
            + f'def {task["entry_point"]}(request):\n'
            + f'    return reference_algorithm(*decode_arguments({parameters}))\n')


def run(source: Path, work: Path, output: Path) -> dict:
    raw = source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        raise ValueError("wrong upstream archive; controls require pinned original HumanEval bytes")
    inputs = (output / "inputs.json").read_bytes()
    model_results = (output / "results.jsonl").read_bytes()
    if len(model_results.splitlines()) != 60:
        raise ValueError("oracle controls are only run AFTER all frozen model attempts")
    sandbox_check(work)
    originals = sorted((json.loads(line) for line in gzip.decompress(raw).decode().splitlines()),
                       key=lambda task: int(task["task_id"].split("/")[1]))[:20]
    results = []
    for original in originals:
        task = adapt_task({key: value for key, value in original.items() if key != "canonical_solution"})
        for current in (True, False):
            code = oracle_code(task, original, current)
            evaluation = evaluate(task, code, work)
            results.append({"task_id": task["task_id"], "drift": task["drift"],
                            "control": "correct_current_api" if current else "obsolete_api",
                            "code_sha256": hashlib.sha256(code.encode()).hexdigest(),
                            "expected_pass": current or task["drift"] == "unchanged",
                            "evaluation": evaluation})
    assert inputs == (output / "inputs.json").read_bytes()
    assert model_results == (output / "results.jsonl").read_bytes()
    report = {"executed_at": now(), "timing": "post-model-run harness validation",
              "canonical_solutions_in_model_inputs": False, "source_sha256": SOURCE_SHA256,
              "all_controls_match_expectation": all(row["expected_pass"] == row["evaluation"]["passed"]
                                                    for row in results),
              "correct_current_api_passed": sum(row["evaluation"]["passed"] for row in results
                                                if row["control"] == "correct_current_api"),
              "obsolete_api_passed": sum(row["evaluation"]["passed"] for row in results
                                         if row["control"] == "obsolete_api"),
              "results": results}
    write_json(output / "oracle_controls.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-gzip", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "results")
    args = parser.parse_args()
    report = run(args.source_gzip, args.work, args.output)
    print(json.dumps({key: value for key, value in report.items() if key != "results"}))
