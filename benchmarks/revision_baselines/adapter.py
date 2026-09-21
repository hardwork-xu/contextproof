"""Parent-side adapter: exact external output, real failures, immutable receipts."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from .corpus import prepare_retrieval_corpus  # noqa: F401 - public preparation API
from .privacy import public_record


WORKER = Path(__file__).with_name("archex_worker.py")
PROJECT = Path(__file__).resolve().parents[2]


def _invoke(request, python, *, timeout=300, runtime_directory=None):
    runtime = Path(runtime_directory or PROJECT / "work/revision-baseline-runtime").resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    # Local auxiliary caches only; usage metrics and trace collection remain off.
    env.update(ARCHEX_USAGE_METRICS="off", ARCHEX_USAGE_TRACE="off",
               TIKTOKEN_CACHE_DIR=str(runtime / "tiktoken"),
               XDG_CACHE_HOME=str(runtime / "cache"))
    start = time.perf_counter()
    try:
        process = subprocess.run([str(python), str(WORKER)], input=json.dumps(request),
                                 capture_output=True, text=True, timeout=timeout,
                                 cwd=PROJECT, env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error_type": type(exc).__name__, "error": str(exc),
                "process_wall_seconds": time.perf_counter() - start}
    try:
        result = json.loads(process.stdout)
    except json.JSONDecodeError:
        result = {"ok": False, "error_type": "InvalidWorkerOutput", "stdout": process.stdout}
    result.update(returncode=process.returncode, stderr=process.stderr,
                  process_wall_seconds=time.perf_counter() - start)
    return result


def archex_environment(python, *, runtime_directory=None):
    """Read actual installed version, dependencies and code hashes before runs."""
    return public_record(_invoke({"operation": "environment"}, python,
                                 runtime_directory=runtime_directory), "archex-environment")


def archex_context(root, query, budget_bytes=16000, *, python=None, cache_dir=None,
                   runtime_directory=None, timeout=300):
    """Return the external tool's actual XML within the shared byte cap.

    Query/index time excludes process startup; process_wall_seconds includes it.
    Any installation or tool failure is explicit and never scored as empty valid
    context. No output is byte- or character-truncated to fit the cap.
    """
    root = Path(root).resolve(strict=True)
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a nonempty string")
    if type(budget_bytes) is not int or budget_bytes <= 0:
        raise ValueError("budget_bytes must be a positive integer")
    python = Path(python or PROJECT / "work/archex-venv/bin/python")
    identity = hashlib.sha256(str(root).encode()).hexdigest()[:20]
    cache_dir = Path(cache_dir or PROJECT / "work/revision-baseline-cache" / identity)
    response = _invoke({"operation": "query", "root": str(root), "query": query,
                        "budget_bytes": budget_bytes, "cache_dir": str(cache_dir.resolve())},
                       python, timeout=timeout, runtime_directory=runtime_directory)
    if not response["ok"]:
        return public_record({"method": "archex_query", "status": "unavailable", "rendered": "",
                              "consumed": 0, "budget": budget_bytes, "unit": "utf-8-bytes",
                              "complete": False, "within_budget": True, "failure": response},
                             "archex-failure")
    result = response["result"]
    result["process_wall_seconds"] = response["process_wall_seconds"]
    result["stderr"] = response["stderr"]
    result["rendered_sha256"] = hashlib.sha256(result["rendered"].encode()).hexdigest()
    if len(result["rendered"].encode("utf-8")) != result["consumed"] or result["consumed"] > budget_bytes:
        raise ValueError("external adapter violated the measured byte cap")
    result["raw_rendered_sha256"] = result["rendered_sha256"]
    result["raw_rendered_bytes"] = result["consumed"]
    result = public_record(result, "archex-query")
    result["consumed"] = len(result["rendered"].encode("utf-8"))
    result["rendered_sha256"] = hashlib.sha256(result["rendered"].encode()).hexdigest()
    if result["consumed"] > budget_bytes:
        raise ValueError("portable-path redaction exceeded the model payload budget")
    return result


def task_query(task):
    """Same deterministic public probe and anchor hints, no expected outcome."""
    hints = " ".join(f"{item['path']} {item['symbol']}" for item in task["anchors"])
    return f"Explain the behavior of this Python probe using repository source. {hints}\n{task['code']}"


def supplied_anchor_context(task, side="after", budget_bytes=16000):
    """A matched-information baseline: exact supplied symbols, no dependency graph.

    Completeness concerns the supplied declarations only. It does not establish
    dependency completeness or whether these hints suffice to answer the probe.
    """
    if type(budget_bytes) is not int or budget_bytes <= 0:
        raise ValueError("budget_bytes must be a positive integer")
    candidates = []
    missing = []
    ambiguous = []
    seen = set()

    def identity(item):
        return (item["path"], item["symbol"], item["start_line"], item["end_line"],
                item["text_sha256"])

    for item in task["source_anchors"][side]:
        if not item.get("matches"):
            missing.append({"path": item["path"], "symbol": item["symbol"],
                            "reason": "missing"})
        else:
            if len(item["matches"]) > 1:
                ambiguous.append({"path": item["path"], "symbol": item["symbol"],
                                  "physical_declarations": len(item["matches"])})
            for record in item["matches"]:
                key = identity(record)
                if key not in seen:
                    candidates.append(record)
                    seen.add(key)
    selected = []

    def payload(entries):
        included = {identity(item) for item in entries}
        omitted = [{key: item[key] for key in ("path", "symbol", "start_line", "end_line")}
                   for item in candidates if identity(item) not in included]
        return json.dumps({"kind": "supplied-anchor-source", "scope": "supplied-declarations-only",
                           "complete": bool(entries) and not (missing or omitted),
                           "missing": missing, "omitted": omitted, "source": entries,
                           "ambiguous_symbols": ambiguous,
                           "ambiguity_policy": "all physical declarations; no runtime binding selection"},
                          sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    for candidate in candidates:
        trial = [*selected, candidate]
        if len(payload(trial).encode("utf-8")) <= budget_bytes:
            selected = trial
    rendered = payload(selected)
    if len(rendered.encode("utf-8")) > budget_bytes:
        rendered = ""
    complete = bool(rendered) and json.loads(rendered)["complete"]
    return {"method": "supplied_anchor_source", "rendered": rendered,
            "consumed": len(rendered.encode("utf-8")), "budget": budget_bytes,
            "unit": "utf-8-bytes", "complete": complete, "within_budget": True,
            "status": "ok" if rendered else "cannot_fit_metadata",
            "rendered_sha256": hashlib.sha256(rendered.encode()).hexdigest(),
            "completeness_scope": "supplied declarations only; not dependency or task sufficiency"}
