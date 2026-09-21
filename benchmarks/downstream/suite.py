"""Deterministic inputs and conservative context policy; never reads solutions."""

from __future__ import annotations

import ast
import hashlib
import json
import tempfile
import time
from pathlib import Path

from contextproof.evidence import make_bundle, render_bundle, repair_bundle, verify_bundle
from contextproof.index import build_index

ROOT = Path(__file__).resolve().parent
CONDITIONS = ("reuse", "fresh", "verify_repair_refresh")
DRIFTS = ("symbol_rename", "signature_change", "file_move", "unchanged")
CONTEXT_TOKEN_CAP = 1024
OUTPUT_TOKEN_CAP = 384
MODEL_ID = "mlx-community/Qwen2.5-Coder-1.5B-Instruct-4bit"
MODEL_REVISION = "b3252a2f97102b1fb1571fec2c9b27219a8536be"
SYSTEM = (
    "You are implementing a Python function in a small repository. "
    "Follow the repository API contract and the functional specification exactly. "
    "Output only complete Python code, with any imports and helper functions needed. "
    "Do not output tests, explanations, or a main block."
)


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_tasks() -> list[dict]:
    tasks = json.loads((ROOT / "upstream/tasks.json").read_text())
    assert [task["task_id"] for task in tasks] == [f"HumanEval/{i}" for i in range(20)]
    assert all("canonical_solution" not in task for task in tasks)
    return tasks


def adapt_task(task: dict) -> dict:
    """The first function is the task entry; original docstrings/tests are preserved."""
    number = int(task["task_id"].split("/")[1])
    function = next(node for node in ast.parse(task["prompt"]).body
                    if isinstance(node, ast.FunctionDef) and node.name == task["entry_point"])
    arguments = [arg.arg for arg in function.args.args]
    doc = (f'    """Decode arguments for {task["entry_point"]}.\n\n'
           f'    Returns a tuple in this order: {", ".join(arguments)}.\n')
    before_text = ('def unpack_request(request):\n' + doc
                   + '    Call unpack_request(request).\n    """\n'
                   + '    return request.decode("v1")\n')
    after_text = before_text
    after_path = "request_api.py"
    decoder = "v1"
    if number % 4 == 0:
        after_text = before_text.replace("unpack_request", "decode_request").replace('"v1"', '"v2"')
        decoder = "v2"
    elif number % 4 == 1:
        after_text = ('def unpack_request(request, *, version):\n' + doc
                      + '    Call unpack_request(request, version="v2").\n    """\n'
                      + '    return request.decode(version)\n')
        decoder = "v2"
    elif number % 4 == 2:
        after_path = "current_api.py"
    return {
        **task, "drift": DRIFTS[number % 4], "arguments": arguments,
        "before_files": {"request_api.py": before_text},
        "after_files": {after_path: after_text}, "decoder_version": decoder,
        "query": f'{task["entry_point"]} decode arguments request tuple',
    }


def user_prompt(task: dict, context: str) -> str:
    return (
        f'Implement `{task["entry_point"]}(request)` in candidate.py.\n'
        "The input is an opaque Request object, not the original positional arguments. "
        "Import the repository helper shown in the evidence and call it to decode request "
        "into a tuple of original arguments; then implement the algorithm yourself. "
        "The decoder must be called on every invocation. The request layout is private. "
        "Import a helper from the module indicated by its .py file path. "
        "Preserve the specified return value and change only the entry-point input signature. "
        "You may use Python standard-library math, typing, collections, itertools, functools, "
        "string, statistics, heapq, and bisect. No I/O or third-party packages.\n\n"
        "Original functional specification (the examples describe unpacked arguments):\n"
        + task["prompt"] + "\nRepository source evidence:\n" + context
    )


def build_inputs(tokenizer, scratch: Path) -> list[dict]:
    """Freeze complete bundles, policies and prompts BEFORE generating any completion."""
    rows = []
    for original in read_tasks():
        task = adapt_task(original)
        with tempfile.TemporaryDirectory(dir=scratch) as folder:
            root = Path(folder)
            for name, source in task["before_files"].items():
                (root / name).write_text(source)
            before = build_index(root)
            saved = make_bundle(before, task["query"], budget=4000, method="bm25")
            for path in root.glob("*.py"):
                path.unlink()
            for name, source in task["after_files"].items():
                (root / name).write_text(source)
            for condition in CONDITIONS:
                start = time.perf_counter()
                policy = {"refresh_count": 0, "repair_count": 0}
                if condition == "reuse":
                    bundle = saved
                elif condition == "fresh":
                    bundle = make_bundle(build_index(root), task["query"], 4000, "bm25")
                    policy["refresh_count"] = 1
                else:
                    report = verify_bundle(saved, root)
                    policy["verification"] = report
                    if report["valid"]:
                        bundle = saved
                    else:
                        repaired = repair_bundle(saved, root)
                        policy["repair_count"] = 1
                        policy["repair"] = repaired
                        if repaired["invalidated"] or repaired["budget_omitted"]:
                            bundle = make_bundle(build_index(root), task["query"], 4000, "bm25")
                            policy["refresh_count"] = 1
                        else:
                            bundle = repaired
                policy["context_seconds"] = time.perf_counter() - start
                context = render_bundle(bundle)
                tokens = len(tokenizer.encode(context, add_special_tokens=False))
                if tokens > CONTEXT_TOKEN_CAP:
                    raise ValueError("complete evidence exceeds frozen native-token budget")
                messages = [{"role": "system", "content": SYSTEM},
                            {"role": "user", "content": user_prompt(task, context)}]
                rendered = tokenizer.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=True)
                rows.append({
                    "task": task, "condition": condition, "bundle": bundle, "policy": policy,
                    "messages": messages, "rendered_prompt": rendered,
                    "context_tokens": tokens, "context_token_cap": CONTEXT_TOKEN_CAP,
                    "prompt_tokens": len(tokenizer.encode(rendered, add_special_tokens=False)),
                })
    return rows
