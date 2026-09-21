"""Actually executed Git/file and v1 checks, with distinct guarantees.

These methods diagnose saved source evidence. They are not substitutes for
executed model outcomes or independently labeled semantic change accuracy.
"""

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import time

from contextproof.dependencies import capture_witnesses, verify_witnesses
from contextproof.evidence import verify_bundle
from contextproof.index import iter_source_files, read_source_bytes


def git_changed_files(before_root, after_root, *, git_executable=None):
    """Use real Git no-index comparison of the two frozen directory snapshots."""
    before, after = Path(before_root).resolve(strict=True), Path(after_root).resolve(strict=True)
    git = git_executable or os.environ.get("CONTEXTPROOF_GIT") or shutil.which("git")
    if not git:
        return {"status": "unavailable", "reason": "Git executable unavailable"}
    started = time.perf_counter()
    command = [git, "--no-pager", "diff", "--no-index", "--no-renames", "--name-status", "-z",
               "--", str(before), str(after)]
    try:
        result = subprocess.run(command, capture_output=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "unavailable", "reason": str(exc)}
    if result.returncode not in {0, 1}:
        return {"status": "unavailable", "reason": result.stderr.decode(errors="replace"),
                "returncode": result.returncode}
    changed = set()
    records = result.stdout.split(b"\0")
    if records and not records[-1]:
        records.pop()
    if len(records) % 2:
        raise ValueError("unexpected Git no-rename name-status output")
    for raw in records[1::2]:
        path = Path(os.fsdecode(raw))
        for root in (before, after):
            try:
                changed.add(path.relative_to(root).as_posix())
                break
            except ValueError:
                pass
        else:
            raise ValueError(f"Git returned a path outside both frozen roots: {path}")
    eligible = {path.relative_to(root).as_posix() for root in (before, after)
                for path in iter_source_files(root)}
    changed &= eligible
    return {"status": "ok", "changed_files": sorted(changed),
            "wall_seconds": time.perf_counter() - started,
            "command": ["git", "diff", "--no-index", "--no-renames", "--name-status", "-z",
                        "--", "<before>", "<after>"],
            "scope": "Git directory diff filtered to eligible source paths; no symbol/dependency claim"}


def diagnose_saved_bundle(bundle, before_root, after_root, *, git_report=None):
    """Apply every baseline to exactly the same captured source bundle."""
    before, after = Path(before_root), Path(after_root)
    git_report = git_report or git_changed_files(before, after)
    changed = set(git_report.get("changed_files", []))
    started = time.perf_counter()
    file_rows = []
    for entry in bundle["entries"]:
        raw = read_source_bytes(after, after / entry["path"])
        identical = raw is not None and hashlib.sha256(raw).hexdigest() == entry["file_sha256"]
        file_rows.append({"entry_id": entry["id"], "path": entry["path"], "accept": identical})
    file_time = time.perf_counter() - started
    started = time.perf_counter()
    source = verify_bundle(bundle, after)
    source_time = time.perf_counter() - started
    started = time.perf_counter()
    witnesses = capture_witnesses(bundle, before) if bundle["entries"] else None
    capture_time = time.perf_counter() - started
    started = time.perf_counter()
    dependency = verify_witnesses(witnesses, after) if witnesses else {
        "fresh": False, "summary": {}, "results": [], "reason": "no captured source"}
    dependency_time = time.perf_counter() - started
    git_rows = [{"entry_id": entry["id"], "path": entry["path"],
                 "accept": entry["path"] not in changed} for entry in bundle["entries"]]
    return {
        "bundle_id": bundle["id"], "entries": len(bundle["entries"]),
        "git_changed_file": {**git_report, "results": git_rows if git_report["status"] == "ok" else []},
        "whole_file_hash": {"results": file_rows, "wall_seconds": file_time,
                            "scope": "byte identity of each saved entry's whole file"},
        "v1_exact_source": {"wall_seconds": source_time, "valid": source["valid"],
                            "summary": source["summary"], "results": [
                                {"entry_id": item["entry_id"], "status": item["status"],
                                 "recoverable": item["status"] in {"valid", "relocated"}}
                                for item in source["results"]]},
        "v1_one_hop": {"capture_seconds": capture_time, "verify_seconds": dependency_time,
                       "fresh": dependency["fresh"], "summary": dependency["summary"],
                       "results": [{"entry_id": item["entry_id"], "status": item["status"]}
                                   for item in dependency["results"]]},
        "interpretation": "different declared predicates; no semantic ground truth or accuracy score",
    }
