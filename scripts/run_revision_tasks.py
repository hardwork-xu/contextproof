#!/usr/bin/env python3
"""Prepare or replay genuine repository-behavior oracles; never invokes a model.

Requires macOS Seatbelt. All code execution denies network, process creation and
all file writes. Dependencies are copied into the scratch area, never installed
into the project. Source archives are verified against the frozen v1 manifest.
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from benchmarks.revision_tasks.suite import digest, source_records  # noqa: E402
from benchmarks.revision_tasks.tasks import TASKS  # noqa: E402

BENCH = REPO / "benchmarks/revision_tasks"
IMPORT_NAMES = {"attrs": "attrs", "packaging": "packaging", "httpx": "httpx", "pluggy": "pluggy"}
DEPENDENCIES = ("anyio", "certifi", "httpcore", "h11", "idna", "typing_extensions")


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def file_manifest(root: Path) -> dict:
    return {path.relative_to(root).as_posix(): digest(path.read_bytes())
            for path in sorted(root.rglob("*")) if path.is_file() and "__pycache__" not in path.parts}


def profile(allowed: list[Path]) -> str:
    paths = [*allowed, Path(sys.prefix), Path(sys.base_prefix), Path("/System"),
             Path("/usr"), Path("/dev")]
    permits = " ".join(f'(subpath {json.dumps(str(path.resolve()))})' for path in paths)
    return (
        '(version 1) (allow default) (deny network*) (deny process-fork) '
        '(deny file-write*) '
        '(deny file-read* (subpath "/Users") (subpath "/private/var/folders")) '
        f'(allow file-read* {permits})'
    )


def run_isolated(script: Path, args: list[str], allowed: list[Path]) -> subprocess.CompletedProcess:
    if platform.system() != "Darwin" or not Path("/usr/bin/sandbox-exec").exists():
        raise RuntimeError("macOS Seatbelt required; no unsandboxed execution fallback")
    command = ["/usr/bin/sandbox-exec", "-p", profile(allowed), str(Path(sys.executable).resolve()),
               "-I", "-B", str(script), *args]
    return subprocess.run(command, text=True, capture_output=True, timeout=12,
                          cwd=script.parent,
                          env={"PATH": "/usr/bin:/bin", "PYTHONHASHSEED": "0", "LANG": "C.UTF-8"})


def sandbox_check(work: Path) -> dict:
    with tempfile.TemporaryDirectory(dir=work) as directory:
        scratch = Path(directory)
        sentinel = work / "outside-read-sentinel.txt"
        sentinel.write_text("must not be readable inside the probe")
        probe = scratch / "sandbox_probe.py"
        probe.write_text(
            "import json, os, pathlib, socket\n"
            f"outside = pathlib.Path({str(sentinel)!r})\n"
            "results = {}\n"
            "operations = [('outside_read', outside.read_text), "
            "('outside_write', lambda: outside.write_text('FAIL')), "
            "('inside_write', lambda: pathlib.Path('forbidden.txt').write_text('FAIL')), "
            "('network', lambda: socket.socket().connect(('127.0.0.1', 9))), "
            "('fork', os.fork)]\n"
            "for name, action in operations:\n"
            "    try:\n"
            "        action(); results[name] = 'ALLOWED'\n"
            "    except PermissionError as error:\n"
            "        results[name] = 'denied: ' + str(error)\n"
            "print(json.dumps(results))\n"
        )
        completed = run_isolated(probe, [], [scratch])
        sentinel.unlink()
        if completed.returncode:
            raise RuntimeError(f"sandbox preflight failed: {completed.stderr}")
        checks = json.loads(completed.stdout)
        if len(checks) != 5 or any(not value.startswith("denied:") for value in checks.values()):
            raise RuntimeError(f"sandbox boundary did not deny all operations: {checks}")
        for name in ("outside_read", "outside_write"):
            checks[name] = "denied: [Errno 1] Operation not permitted: <outside-read-sentinel>"
        return {"mechanism": "macOS Seatbelt", "checked_at": now(), "checks": checks,
                "writes": "all denied, including scratch", "network": "denied",
                "process_creation": "denied", "cpu_limit_seconds": 5,
                "wall_timeout_seconds": 12}


def extract_repository(repository: dict, side: str, archive_dir: Path, work: Path) -> Path:
    version = repository["versions"][side]
    archive = archive_dir / f'{repository["name"]}-{version["commit"]}.tar.gz'
    if digest(archive.read_bytes()) != version["archive_sha256"]:
        raise ValueError(f"upstream archive digest mismatch: {archive.name}")
    destination = work / "sources" / repository["name"] / side
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as bundle:
        for member in bundle.getmembers():
            if not member.isfile():
                continue
            name = member.name.split("/", 1)[-1]
            relative = Path(name)
            if not name or relative.is_absolute() or ".." in relative.parts:
                raise ValueError("unsafe archive member")
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(bundle.extractfile(member).read())
    return destination


def copy_dependencies(site_packages: Path, sniffio_wheel: Path, work: Path) -> dict:
    destination = work / "dependencies"
    destination.mkdir(parents=True, exist_ok=True)
    versions = {}
    for name in DEPENDENCIES:
        source = site_packages / name
        if source.is_dir():
            shutil.copytree(source, destination / name, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            source = site_packages / f"{name}.py"
            if not source.is_file():
                raise RuntimeError(f"missing dependency {name} in {site_packages}")
            shutil.copy2(source, destination / source.name)
        distributions = list(importlib.metadata.distributions(path=[str(site_packages)]))
        for distribution in distributions:
            if distribution.metadata["Name"].replace("-", "_").lower() == name:
                versions[name] = distribution.version
                break
    with zipfile.ZipFile(sniffio_wheel) as wheel:
        for member in wheel.infolist():
            relative = Path(member.filename)
            if member.is_dir():
                continue
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("unsafe wheel member")
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(wheel.read(member))
    versions["sniffio"] = "1.3.1"
    return {"versions": versions, "files": file_manifest(destination),
            "sniffio_wheel_sha256": digest(sniffio_wheel.read_bytes()),
            "sniffio_distribution": "https://pypi.org/project/sniffio/1.3.1/"}


def oracle(task: dict, root: Path, work: Path) -> dict:
    with tempfile.TemporaryDirectory(dir=work) as directory:
        scratch = Path(directory)
        worker = scratch / "oracle_worker.py"
        shutil.copyfile(BENCH / "oracle_worker.py", worker)
        paths = [root / "src", root, work / "dependencies"]
        payload = scratch / "payload.json"
        write_json(payload, {"code": task["code"], "import_paths": [str(path) for path in paths],
                             "import_name": IMPORT_NAMES[task["repository"]]})
        start = time.perf_counter()
        completed = run_isolated(worker, [str(payload)], [scratch, root, work / "dependencies"])
        if completed.returncode:
            raise RuntimeError(f'oracle worker failed for {task["id"]}: {completed.stderr}')
        answer = json.loads(completed.stdout)
        if "harness_error" in answer:
            raise RuntimeError(f'oracle import failed for {task["id"]}: {answer}')
        return {"answer": answer, "seconds": time.perf_counter() - start,
                "stdout": completed.stdout, "stderr": completed.stderr,
                "returncode": completed.returncode}


def origin(task: dict, repository: dict, roots: dict) -> dict:
    after_commit = repository["versions"]["after"]["commit"]
    test = task["upstream_test"]
    test_path = roots[(repository["name"], "after")] / test["path"]
    if not test_path.is_file():
        raise RuntimeError(f"missing cited upstream file {test_path}")
    record = None
    if test_path.suffix == ".py":
        records = source_records(roots[(repository["name"], "after")], test["path"])
        record = next((item for item in records if item["symbol"] == test["symbol"]), None)
        if record is None:
            matches = [item for item in records
                       if item["symbol"].split(".")[-1] == test["symbol"].split(".")[-1]]
            if len(matches) == 1:
                record = matches[0]
        if record is None:
            raise RuntimeError(f'cited upstream test symbol not found: {task["id"]}: {test}')
    url = f'{repository["repository"]}/blob/{after_commit}/{test["path"]}'
    if record:
        url += f'#L{record["start_line"]}'
    return {"test_url": url, "test_file_sha256": digest(test_path.read_bytes()),
            "test_symbol": record["symbol"] if record else test["symbol"],
            "adaptation": "A bounded behavior probe of upstream test/changelog behavior; not a verbatim upstream test.",
            "issue_url": (f'{repository["repository"]}/issues/{task["upstream_issue"]}'
                          if task["upstream_issue"] else None)}


def prepare(args):
    work, output = args.work.resolve(), args.output.resolve()
    work.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    if (output / "protocol.json").exists():
        raise RuntimeError("protocol already frozen; use a new output directory")
    upstream = json.loads((REPO / "benchmarks/v1/manifest.json").read_text())
    names = {task["repository"] for task in TASKS}
    repositories = {entry["name"]: entry for entry in upstream["repositories"] if entry["name"] in names}
    roots = {(name, side): extract_repository(entry, side, args.archives, work)
             for name, entry in repositories.items() for side in ("before", "after")}
    dependencies = copy_dependencies(args.site_packages.resolve(), args.sniffio_wheel.resolve(), work)
    boundary = sandbox_check(work)
    rows, oracles = [], []
    for task in TASKS:
        repository = repositories[task["repository"]]
        row = {**task, "provenance": origin(task, repository, roots), "source_anchors": {}}
        for side in ("before", "after"):
            root = roots[(task["repository"], side)]
            anchors = []
            for anchor in task["anchors"]:
                matches = [record for record in source_records(root, anchor["path"])
                           if record["symbol"] == anchor["symbol"]]
                anchors.append({**anchor, "matches": matches, "present": bool(matches)})
            row["source_anchors"][side] = anchors
        if not any(anchor["present"] for anchor in row["source_anchors"]["after"]):
            raise RuntimeError(f'no current source anchor for {task["id"]}')
        answer_row = {"id": task["id"], "executions": {}}
        for side in ("before", "after"):
            runs = [oracle(task, roots[(task["repository"], side)], work) for _ in range(2)]
            if runs[0]["answer"] != runs[1]["answer"]:
                raise RuntimeError(f'non-deterministic oracle: {task["id"]} {side}')
            answer_row[side] = runs[0]["answer"]
            answer_row["executions"][side] = runs
        answer_row["behavior_changed"] = answer_row["before"] != answer_row["after"]
        rows.append(row)
        oracles.append(answer_row)
        print(json.dumps({"id": task["id"], "before": answer_row["before"],
                          "after": answer_row["after"], "changed": answer_row["behavior_changed"]}), flush=True)
    write_json(output / "tasks.json", rows)
    write_json(output / "oracles.json", oracles)
    source_files = [BENCH / "tasks.py", BENCH / "suite.py", BENCH / "oracle_worker.py", Path(__file__)]
    protocol = {
        "schema_version": 1, "frozen_at": now(),
        "study": "real upstream revision behavioral audit",
        "primary_outcome": "exact JSON value or exception class for the after snapshot",
        "independence_unit": "upstream change family; controls have separate families",
        "selection": "manually chosen upstream behavioral changes and unchanged controls before any model outputs; a diagnostic sample, not random repository prevalence",
        "splits": {"development": 5, "holdout": 25},
        "development_gate": {"condition": "fresh targeted source", "minimum_correct": 4,
                             "total": 5, "failure_action": "stop heldout model evaluation; report capability or context construction failure"},
        "heldout_policy": "No task removal, prompt tuning, answer editing or model-based filtering after protocol freeze.",
        "oracle_policy": "two isolated executions per task per snapshot; require identical JSON; import failures abort preparation",
        "scope": "code behavior prediction, not generated patch execution or issue resolution",
        "python": sys.version, "platform": platform.platform(),
        "environment": {"PYTHONHASHSEED": "0", "warning_filter": "ignore unless explicitly captured"},
        "sandbox": boundary, "dependencies": dependencies,
        "repositories": repositories,
        "source_roots": {name: {side: os.path.relpath(roots[(name, side)], REPO)
                                for side in ("before", "after")}
                         for name in sorted(names)},
        "source_roots_base": "ContextProof project root",
        "source_manifests": {name: {side: file_manifest(roots[(name, side)]) for side in ("before", "after")}
                             for name in sorted(names)},
        "tasks_sha256": digest((output / "tasks.json").read_bytes()),
        "oracles_sha256": digest((output / "oracles.json").read_bytes()),
        "implementation_sha256": {str(path.relative_to(REPO)): digest(path.read_bytes()) for path in source_files},
    }
    write_json(output / "protocol.json", protocol)
    print(json.dumps({"frozen": str(output), "tasks": len(rows),
                      "observed_changes": sum(row["behavior_changed"] for row in oracles),
                      "tasks_sha256": protocol["tasks_sha256"]}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare"])
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=BENCH / "frozen")
    parser.add_argument("--archives", type=Path, default=REPO / "work/v1-drift/archives")
    parser.add_argument("--site-packages", type=Path, required=True)
    parser.add_argument("--sniffio-wheel", type=Path, required=True)
    prepare(parser.parse_args())


if __name__ == "__main__":
    main()
