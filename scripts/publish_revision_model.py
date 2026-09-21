#!/usr/bin/env python3
"""Export a completed private inference run with explicit, score-neutral redaction."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmarks.revision_baselines.privacy import public_value  # noqa: E402
from benchmarks.revision_model import sha, write_json  # noqa: E402


def sanitize(value):
    value = public_value(value)
    if isinstance(value, dict):
        return {key: "<REDACTED_LOCAL_SESSION>" if key in {"thread_id", "session_id"}
                else sanitize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    return value


def export(source, target):
    source, target = source.resolve(strict=True), target.absolute()
    if source.is_relative_to(ROOT):
        raise ValueError("raw inference records must be stored outside the Git checkout")
    if target.exists():
        raise ValueError("refusing to overwrite an existing public export")
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
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(output, encoding="utf-8")
        records[str(relative)] = {"private_sha256": sha(raw), "public_sha256": sha(output.encode()),
                                  "changed_by_export": raw != output.encode()}
    write_json(target / "publication.json", {
        "policy": "Private local paths and session identifiers replaced; JSON formatting normalized. "
                  "Answers, correctness, failures, usage and timings preserved. Original full records "
                  "remain in the maintainer's private archive outside Git.",
        "files": records})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    args = parser.parse_args()
    export(args.source, args.target)


if __name__ == "__main__":
    main()
