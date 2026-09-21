"""Run the pinned external public API in its separate dependency environment.

This file is our adapter, not vendored archex source. One JSON request arrives
on stdin; one JSON result is written to stdout. Library console output goes to
stderr. No model is invoked and no repository code is imported or executed.
"""

from contextlib import redirect_stdout
from dataclasses import asdict
import hashlib
from importlib import metadata
import json
from pathlib import Path
import sys
import time
import traceback


VERSION = "0.31.2"
SOURCES = [
    "https://pypi.org/project/archex/0.31.2/",
    "https://github.com/Mathews-Tom/archex/tree/v0.31.2",
    "https://github.com/Mathews-Tom/archex/blob/v0.31.2/src/archex/api.py",
    "https://github.com/Mathews-Tom/archex/blob/v0.31.2/src/archex/models.py",
]


def environment():
    version = metadata.version("archex")
    if version != VERSION:
        raise ValueError(f"external baseline requires archex=={VERSION}, found {version}")
    distribution = metadata.distribution("archex")
    files = {}
    for relative in distribution.files or []:
        name = str(relative)
        if name.startswith("archex/") and name.endswith(".py"):
            files[name] = hashlib.sha256(distribution.locate_file(relative).read_bytes()).hexdigest()
    return {
        "package": "archex", "version": version, "python": sys.version,
        "source_urls": SOURCES, "installed_source_sha256": dict(sorted(files.items())),
        "source_manifest_sha256": hashlib.sha256(json.dumps(
            files, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "dependencies": dict(sorted((item.metadata["Name"], item.version)
                                    for item in metadata.distributions() if item.metadata["Name"])),
    }


def query_context(request):
    from archex import query
    from archex.models import Config, IndexConfig, PipelineTiming, RepoSource

    if metadata.version("archex") != VERSION:
        raise ValueError("archex version mismatch")
    root = Path(request["root"]).resolve(strict=True)
    cache_dir = Path(request["cache_dir"]).resolve()
    budget = request["budget_bytes"]
    if type(budget) is not int or budget <= 0:
        raise ValueError("budget_bytes must be a positive integer")
    cache_dir.mkdir(parents=True, exist_ok=True)
    config = Config(languages=["python"], cache=True, cache_dir=str(cache_dir))
    index = IndexConfig(bm25=True, vector=False, splade=False, rerank=False,
                        allow_remote_code=False)
    # A fixed conservative initial conversion, then measured byte feedback.
    # No generated answer, gold result, source relevance or success is consulted.
    native_budget = max(1, budget // 6)
    attempts = []
    started = time.perf_counter()
    final = None
    for _ in range(12):
        timing = PipelineTiming()
        attempt_start = time.perf_counter()
        bundle = query(RepoSource(local_path=str(root)), request["query"],
                       token_budget=native_budget, explicit_token_budget=True,
                       config=config, index_config=index, timing=timing, refresh=True)
        rendered = bundle.to_prompt(format="xml")
        consumed = len(rendered.encode("utf-8"))
        receipt = bundle.receipt.model_dump(mode="json") if bundle.receipt else None
        chunks = [{"path": item.chunk.file_path, "start_line": item.chunk.start_line,
                   "end_line": item.chunk.end_line,
                   "text_sha256": hashlib.sha256(item.chunk.content.encode()).hexdigest()}
                  for item in bundle.chunks]
        attempts.append({"native_token_budget": native_budget, "rendered_utf8_bytes": consumed,
                         "query_wall_seconds": time.perf_counter() - attempt_start,
                         "pipeline_timing": asdict(timing), "chunks": chunks,
                         "reported_tokens": bundle.token_count})
        if consumed <= budget:
            complete = bool(chunks) and bool(receipt) and receipt["context_complete"] == "complete"
            final = {"rendered": rendered, "consumed": consumed, "within_budget": True,
                     "complete": complete, "receipt": receipt, "chunks": chunks,
                     "status": "ok" if chunks else "no_source_returned",
                     "native_token_budget": native_budget}
            break
        if native_budget == 1:
            break
        native_budget = max(1, min(native_budget - 1, int(native_budget * budget / consumed * 0.85)))
    if final is None:
        final = {"rendered": "", "consumed": 0, "within_budget": True, "complete": False,
                 "receipt": None, "chunks": [], "status": "cannot_fit_native_render",
                 "native_token_budget": native_budget}
    return {"method": "archex_query", "package_version": VERSION, "unit": "utf-8-bytes",
            "budget": budget, "format": "xml", **final, "attempts": attempts,
            "query_wall_seconds": time.perf_counter() - started,
            "configuration": {"config": config.model_dump(mode="json"),
                              "index": index.model_dump(mode="json"),
                              "explicit_token_budget": True, "refresh": True},
            "budget_policy": "native=max(1,byte_cap//6); reduce on measured overflow; never truncate output",
            "completeness_scope": "external tool receipt; not task relevance or functional correctness"}


def main():
    request = json.load(sys.stdin)
    try:
        with redirect_stdout(sys.stderr):
            result = environment() if request["operation"] == "environment" else query_context(request)
        json.dump({"ok": True, "result": result}, sys.stdout, ensure_ascii=False, allow_nan=False)
    except Exception as exc:
        json.dump({"ok": False, "error_type": type(exc).__name__, "error": str(exc),
                   "traceback": traceback.format_exc()}, sys.stdout, ensure_ascii=False)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
