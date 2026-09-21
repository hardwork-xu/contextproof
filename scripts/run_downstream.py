#!/usr/bin/env python3
"""Freeze, run and replay the bounded local downstream study. See docs/DOWNSTREAM.md."""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.metadata
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "src")]

from benchmarks.downstream.suite import (  # noqa: E402
    CONDITIONS, CONTEXT_TOKEN_CAP, MODEL_ID, MODEL_REVISION, OUTPUT_TOKEN_CAP,
    ROOT, build_inputs, digest,
)


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def profile(scratch: Path) -> str:
    # Allow standard interpreter/runtime reads, but hide other user files. Seatbelt
    # is the OS security boundary; the worker's AST/import gating is supplementary.
    scratch = scratch.resolve()
    paths = [scratch, Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve(),
             Path("/System"), Path("/usr"), Path("/dev")]
    permits = " ".join(f'(subpath {json.dumps(str(path))})' for path in paths)
    return (
        '(version 1) (allow default) (deny network*) (deny process-fork) '
        '(deny file-write*) '
        f'(allow file-write* (subpath {json.dumps(str(scratch))})) '
        '(deny file-read* (subpath "/Users") (subpath "/private/var/folders")) '
        f'(allow file-read* {permits})'
    )


def sandbox_command(scratch: Path, script: Path, *arguments: str) -> list[str]:
    if platform.system() != "Darwin" or not Path("/usr/bin/sandbox-exec").exists():
        raise RuntimeError("This harness requires macOS sandbox-exec; no unsandboxed fallback")
    return ["/usr/bin/sandbox-exec", "-p", profile(scratch), str(Path(sys.executable).resolve()),
            "-I", "-B", str(script), *arguments]


def sandbox_check(work: Path) -> dict:
    """Check genuine OS denial using unrestricted probe code, before any model code."""
    with tempfile.TemporaryDirectory(dir=work) as folder:
        scratch = Path(folder)
        outside = work / "sandbox-outside-sentinel"
        outside.write_text("sandbox read sentinel")
        probe = scratch / "probe.py"
        probe.write_text(
            "import json, os, pathlib, socket\n"
            f"outside=pathlib.Path({str(outside)!r})\n"
            "results={}\n"
            "for name, action in [('outside_read', outside.read_text), "
            "('outside_write', lambda: outside.write_text('FAIL')), "
            "('network', lambda: socket.create_connection(('127.0.0.1', 9), timeout=1)), "
            "('fork', os.fork)]:\n"
            "    try:\n"
            "        action(); results[name]='ALLOWED'\n"
            "    except PermissionError as exc:\n"
            "        results[name]='denied: '+str(exc)\n"
            "pathlib.Path(__file__).with_name('allowed.txt').write_text('allowed')\n"
            "results['scratch_write']='allowed'\n"
            "print(json.dumps(results))\n"
        )
        completed = subprocess.run(sandbox_command(scratch, probe), text=True, capture_output=True,
                                   timeout=10, env={"PATH": "/usr/bin:/bin", "PYTHONHASHSEED": "0"})
        outside.unlink(missing_ok=True)
        if completed.returncode:
            raise RuntimeError(f"sandbox probe failed ({completed.returncode}): {completed.stderr}")
        checks = json.loads(completed.stdout)
        if any(not checks[key].startswith("denied:")
               for key in ("outside_read", "outside_write", "network", "fork")):
            raise RuntimeError(f"sandbox did not enforce its boundary: {checks}")
        return {"checked_at": now(), "checks": checks, "profile": profile(Path("SCRATCH")),
                "mechanism": "macOS Seatbelt sandbox-exec", "wall_timeout_seconds": 10,
                "cpu_limit_seconds": 3, "file_size_limit_bytes": 1048576,
                "open_file_limit": 64}


def extract_code(response: str) -> str:
    blocks = re.findall(r"```(?:python)?\s*\n(.*?)```", response, flags=re.DOTALL)
    return (blocks[0] if blocks else response).strip() + "\n"


def evaluate(task: dict, code: str, work: Path) -> dict:
    with tempfile.TemporaryDirectory(dir=work) as folder:
        scratch = Path(folder)
        worker = scratch / "worker.py"
        worker.write_bytes((ROOT / "sandbox_worker.py").read_bytes())
        payload = scratch / "payload.json"
        write_json(payload, {"task": task, "code": code})
        start = time.perf_counter()
        try:
            completed = subprocess.run(
                sandbox_command(scratch, worker, str(payload)), text=True, capture_output=True,
                timeout=10, cwd=scratch,
                env={"PATH": "/usr/bin:/bin", "PYTHONHASHSEED": "0"})
            result = json.loads(completed.stdout) if completed.returncode == 0 else {
                "passed": False, "error_type": "WorkerProcessError"}
            result.update(returncode=completed.returncode, stdout=completed.stdout,
                          stderr=completed.stderr)
        except subprocess.TimeoutExpired as exc:
            result = {"passed": False, "error_type": "WallTimeout", "error": str(exc)}
        except json.JSONDecodeError as exc:
            result = {"passed": False, "error_type": "WorkerProtocolError", "error": str(exc),
                      "stdout": completed.stdout, "stderr": completed.stderr}
        result["execution_seconds"] = time.perf_counter() - start
        return result


def prepare(model_path: Path, work: Path, output: Path) -> None:
    from transformers import AutoTokenizer

    if (output / "protocol.json").exists():
        raise RuntimeError("frozen protocol already exists; use a new output directory")
    tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
    rows = build_inputs(tokenizer, work)
    write_json(output / "inputs.json", rows)
    code_files = [Path(__file__), ROOT / "suite.py", ROOT / "sandbox_worker.py"]
    code_files += sorted((REPO / "src/contextproof").glob("*.py"))
    protocol = {
        "schema_version": 1, "frozen_at": now(), "study": "adapted HumanEval API drift",
        "upstream_repository": "https://github.com/openai/human-eval",
        "upstream_revision": "6d43fb980f9fee3c892a914eda09951f772ad10d",
        "upstream_gzip_sha256": "b796127e635a67f93fb35c04f4cb03cf06f38c8072ee7cee8833d7bee06979ef",
        "selection": "first 20 IDs numerically, HumanEval/0 through HumanEval/19",
        "drift_assignment": "ID modulo 4: symbol rename, signature change, file move, unchanged",
        "conditions": list(CONDITIONS), "attempts_per_cell": 1, "cell_count": 60,
        "model_id": MODEL_ID, "model_revision": MODEL_REVISION,
        "temperature": 0.0, "seed": 0, "context_token_cap": CONTEXT_TOKEN_CAP,
        "output_token_cap": OUTPUT_TOKEN_CAP, "tokenizer": "model-native Qwen tokenizer",
        "evidence_byte_cap": 4000, "retrieval": "ContextProof BM25",
        "ordering": "task ID ascending, conditions in listed order; no prompt cache reuse",
        "primary_outcome": "all original functional assertions AND decoder-call contract pass",
        "failure_policy": "no retries or edited completions; failures remain in denominator",
        "refresh_policy": "verify; retain valid; repair exact moves; refresh any invalidated or budget-omitted evidence",
        "scope_limit": "Artificial API adaptation, not unmodified HumanEval or real issue resolution",
        "inputs_sha256": digest((output / "inputs.json").read_bytes()),
        "tasks_sha256": digest((ROOT / "upstream/tasks.json").read_bytes()),
        "source_sha256": {str(path.relative_to(REPO)): digest(path.read_bytes())
                          for path in code_files},
        "sandbox_preflight": sandbox_check(work),
    }
    write_json(output / "protocol.json", protocol)
    print(json.dumps({"prepared": len(rows), "max_context_tokens": max(
        row["context_tokens"] for row in rows), "inputs_sha256": protocol["inputs_sha256"]}))


def append_event(path: Path, event: dict) -> None:
    with path.open("a") as stream:
        stream.write(json.dumps(event, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def run(model_path: Path, work: Path, output: Path) -> None:
    import mlx.core as mx
    from mlx_lm import load, stream_generate
    from mlx_lm.sample_utils import make_sampler

    protocol = json.loads((output / "protocol.json").read_text())
    raw_inputs = (output / "inputs.json").read_bytes()
    if digest(raw_inputs) != protocol["inputs_sha256"]:
        raise RuntimeError("frozen input checksum mismatch")
    if (output / "attempts.jsonl").exists():
        raise RuntimeError("attempt log exists; no silent reruns or overwritten attempts")
    sandbox = sandbox_check(work)
    model_files = {path.name: {"sha256": digest(path.read_bytes()), "bytes": path.stat().st_size}
                   for path in sorted(model_path.iterdir()) if path.is_file()}
    if "model.safetensors" not in model_files:
        raise RuntimeError("pinned model download is incomplete")
    write_json(output / "environment.json", {
        "recorded_at": now(), "python": sys.version, "platform": platform.platform(),
        "machine": platform.machine(), "packages": dict(sorted(
            (distribution.metadata["Name"], distribution.version)
            for distribution in importlib.metadata.distributions())),
        "model_files": model_files, "model_id": MODEL_ID, "model_revision": MODEL_REVISION,
        "download_endpoint": "https://hf-mirror.com (pinned Hugging Face mirror)",
        "sandbox": sandbox,
    })
    model, tokenizer = load(str(model_path))
    mx.random.seed(0)
    sampler = make_sampler(temp=0.0)
    rows = json.loads(raw_inputs)
    for index, row in enumerate(rows):
        key = f'{row["task"]["task_id"]}:{row["condition"]}'
        start = time.perf_counter()
        record = {"cell": key, "task_id": row["task"]["task_id"],
                  "drift": row["task"]["drift"], "condition": row["condition"],
                  "attempt": 1, "started_at": now(), "input_index": index,
                  "context_tokens": row["context_tokens"], "prompt_tokens": row["prompt_tokens"]}
        append_event(output / "attempts.jsonl", {**record, "event": "started"})
        parts, token_ids = [], []
        try:
            final = None
            for response in stream_generate(model, tokenizer, row["rendered_prompt"],
                                            max_tokens=OUTPUT_TOKEN_CAP, sampler=sampler):
                parts.append(response.text)
                token_ids.append(response.token)
                final = response
            record.update(response="".join(parts), generation_token_ids=token_ids,
                          generation_tokens=final.generation_tokens if final else 0,
                          generation_seconds=time.perf_counter() - start,
                          finish_reason=final.finish_reason if final else "empty",
                          model_prompt_tokens=final.prompt_tokens if final else None,
                          prompt_tps=final.prompt_tps if final else None,
                          generation_tps=final.generation_tps if final else None)
            record["code"] = extract_code(record["response"])
            record["evaluation"] = evaluate(row["task"], record["code"], work)
        except Exception as exc:
            record.update(response="".join(parts), generation_token_ids=token_ids,
                          generation_tokens=len(token_ids),
                          generation_seconds=time.perf_counter() - start,
                          generation_error=f"{type(exc).__name__}: {exc}",
                          evaluation={"passed": False, "error_type": "GenerationError"})
        record["finished_at"] = now()
        append_event(output / "attempts.jsonl", {**record, "event": "finished"})
        append_event(output / "results.jsonl", record)
        print(json.dumps({"completed": index + 1, "cell": key,
                          "passed": record["evaluation"]["passed"],
                          "tokens": record["generation_tokens"],
                          "seconds": round(record["generation_seconds"], 2)}), flush=True)
        mx.clear_cache()
    summarize(output)


def summarize(output: Path) -> dict:
    rows = [json.loads(line) for line in (output / "results.jsonl").read_text().splitlines()]
    results = {}
    for condition in CONDITIONS:
        selected = [row for row in rows if row["condition"] == condition]
        results[condition] = {
            "completed": len(selected), "passed": sum(row["evaluation"]["passed"] for row in selected),
            "failed": sum(not row["evaluation"]["passed"] for row in selected),
            "generation_tokens": sum(row["generation_tokens"] for row in selected),
            "prompt_tokens": sum(row["prompt_tokens"] for row in selected),
            "generation_seconds": sum(row["generation_seconds"] for row in selected),
            "failure_types": dict(Counter(row["evaluation"].get("error_type", "unknown")
                                          for row in selected if not row["evaluation"]["passed"])),
            "by_drift": {drift: {"passed": sum(row["evaluation"]["passed"] for row in selected
                                               if row["drift"] == drift),
                                  "total": sum(row["drift"] == drift for row in selected)}
                         for drift in sorted({row["drift"] for row in selected})},
        }
    summary = {"completed_cells": len(rows), "expected_cells": 60, "conditions": results,
               "results_sha256": digest((output / "results.jsonl").read_bytes()),
               "claim": "executed functional success on an artificial API-adaptation study only"}
    write_json(output / "summary.json", summary)
    return summary


def replay(work: Path, output: Path) -> None:
    sandbox_check(work)
    inputs = json.loads((output / "inputs.json").read_text())
    rows = [json.loads(line) for line in (output / "results.jsonl").read_text().splitlines()]
    replayed = []
    for row in rows:
        if "code" not in row:
            continue
        result = evaluate(inputs[row["input_index"]]["task"], row["code"], work)
        replayed.append({"cell": row["cell"], "evaluation": result,
                         "matches_recorded_pass": result["passed"] == row["evaluation"]["passed"]})
    write_json(output / "replay.json", {"replayed_at": now(), "cells": replayed,
                                       "all_match": all(row["matches_recorded_pass"] for row in replayed)})
    print(json.dumps({"replayed": len(replayed), "all_match": all(
        row["matches_recorded_pass"] for row in replayed)}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "run", "summarize", "sandbox-check", "replay"])
    parser.add_argument("--model", type=Path)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "results")
    args = parser.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)
    if args.command == "prepare":
        prepare(args.model, args.work, args.output)
    elif args.command == "run":
        run(args.model, args.work, args.output)
    elif args.command == "summarize":
        print(json.dumps(summarize(args.output), indent=2))
    elif args.command == "replay":
        replay(args.work, args.output)
    else:
        print(json.dumps(sandbox_check(args.work), indent=2))


if __name__ == "__main__":
    main()
