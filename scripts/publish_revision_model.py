#!/usr/bin/env python3
"""Export a completed private inference run with explicit, score-neutral redaction."""

import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmarks.revision_baselines.privacy import public_value  # noqa: E402
from benchmarks.revision_model import sha, write_json  # noqa: E402


UUID = r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}"
RUNTIME_LOG = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\S+\s+(?:TRACE|DEBUG|INFO|WARN|ERROR)\s+codex_[\w:]+:")
SNAPSHOT = re.compile(
    r"(?P<prefix>\.codex[/\\]shell_snapshots[/\\])" + UUID
    + r"(?:\.\d+)?(?P<extension>\.[A-Za-z0-9_-]+)?(?=[\s\"')]|$)", re.I)
RUNTIME_ID = re.compile(r"(?P<prefix>\b(?:thread_id|session_id|turn_id)=)" + UUID + r"\b", re.I)


def sanitize_stderr(text):
    """Redact runtime IDs only in diagnostic lines; retain error text and timing."""
    output = []
    for line in text.splitlines(keepends=True):
        if RUNTIME_LOG.match(line):
            line = SNAPSHOT.sub(lambda match: match["prefix"] + "<REDACTED_LOCAL_SNAPSHOT>"
                                + (match["extension"] or ""), line)
            line = RUNTIME_ID.sub(r"\g<prefix><REDACTED_LOCAL_SESSION>", line)
        output.append(line)
    return "".join(output)


def sanitize(value):
    value = public_value(value)
    if isinstance(value, dict):
        return {key: "<REDACTED_LOCAL_SESSION>" if key in {"thread_id", "session_id"}
                else sanitize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    return value


def export(source, target, previous=None):
    source, target = source.resolve(strict=True), target.absolute()
    if source.is_relative_to(ROOT):
        raise ValueError("raw inference records must be stored outside the Git checkout")
    if target.exists():
        raise ValueError("refusing to overwrite an existing public export")
    previous_raw = None
    previous_records = {}
    if previous is not None:
        previous_raw = (previous / "publication.json").read_bytes()
        previous_records = json.loads(previous_raw)["files"]
    records = {}
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        if path.suffix not in {".json", ".jsonl", ".txt"}:
            raise ValueError(f"unexpected raw artifact type: {relative}")
        raw = path.read_bytes()
        text = raw.decode("utf-8")
        if path.suffix == ".json":
            original = json.loads(text)
            value = sanitize(original)
            if path.name == "results.json":
                for before, after in zip(original, value, strict=True):
                    assert before["correct"] == after["correct"]
                    assert before["record"]["answer"] == after["record"]["answer"]
                    assert before["record"]["usage"] == after["record"]["usage"]
            output = json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
        elif path.suffix == ".jsonl":
            output = "\n".join(json.dumps(sanitize(json.loads(line)), sort_keys=True,
                                          ensure_ascii=False) for line in text.splitlines()) + "\n"
        else:
            output = public_value(text)
            if path.name == "stderr.txt":
                output = sanitize_stderr(output)
        record = {"private_sha256": sha(raw), "public_sha256": sha(output.encode()),
                  "changed_by_export": raw != output.encode()}
        earlier = previous_records.get(str(relative))
        if earlier is not None:
            if earlier["private_sha256"] != record["private_sha256"]:
                raise ValueError("private source differs from the previous publication manifest")
            if sha((previous / relative).read_bytes()) != earlier["public_sha256"]:
                raise ValueError("previous public file differs from its publication manifest")
            history = list(earlier.get("previous_public_sha256", []))
            if earlier["public_sha256"] != record["public_sha256"]:
                history.append(earlier["public_sha256"])
            if history:
                record["previous_public_sha256"] = list(dict.fromkeys(history))
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(output, encoding="utf-8")
        records[str(relative)] = record
    if not previous_records.keys() <= records.keys():
        raise ValueError("private source is missing previously published artifacts")
    manifest = {
        "redaction_version": 2,
        "policy": "Private local paths and session identifiers replaced; JSON formatting normalized. "
                  "Runtime diagnostic IDs and shell-snapshot filenames redacted in stderr only. "
                  "Answers, correctness, failures, usage and timings preserved. Original full records "
                  "remain in the maintainer's private archive outside Git.",
        "files": records}
    if previous_raw is not None:
        manifest["previous_publication_sha256"] = sha(previous_raw)
    write_json(target / "publication.json", manifest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("--previous-export", type=Path,
                        help="Verify the prior export and retain its original/public hashes")
    args = parser.parse_args()
    export(args.source, args.target, args.previous_export)


if __name__ == "__main__":
    main()
