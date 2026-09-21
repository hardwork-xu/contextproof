"""Publish diagnostics with local path prefixes removed; retain immutable originals."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from benchmarks.downstream.suite import ROOT, digest
from scripts.run_downstream import now, write_json


def publish(public: Path, private_archive: Path, workspace: Path) -> dict:
    public, private_archive, workspace = (path.resolve() for path in (public, private_archive, workspace))
    repo = ROOT.parents[1]
    if private_archive.is_relative_to(repo):
        raise ValueError("unredacted archive must be outside the public Git repository")
    if private_archive.exists():
        raise ValueError("private archive already exists; originals must never be overwritten")
    if (public / "publication.json").exists():
        raise ValueError("publication record already exists")
    shutil.copytree(public, private_archive)
    replacements = [(str(workspace), "<WORKSPACE>"), (str(Path.home()), "<USER_HOME>")]
    replacements.sort(key=lambda row: -len(row[0]))
    before_inputs = (public / "inputs.json").read_bytes()
    before_rows = [json.loads(line) for line in (public / "results.jsonl").read_text().splitlines()]
    raw_hashes = {}
    for source in sorted(private_archive.iterdir()):
        if source.suffix not in {".json", ".jsonl"}:
            continue
        raw = source.read_bytes()
        raw_hashes[source.name] = digest(raw)
        text = raw.decode()
        for prefix, placeholder in replacements:
            text = text.replace(prefix, placeholder)
        (public / source.name).write_text(text)
    if before_inputs != (public / "inputs.json").read_bytes():
        raise ValueError("input redaction is forbidden: exact model prompts must remain unchanged")
    after_rows = [json.loads(line) for line in (public / "results.jsonl").read_text().splitlines()]
    unchanged_fields = ["response", "code", "generation_token_ids", "generation_tokens",
                        "prompt_tokens", "model_prompt_tokens", "generation_seconds"]
    for before, after in zip(before_rows, after_rows, strict=True):
        assert all(before[key] == after[key] for key in unchanged_fields)
        assert before["evaluation"]["passed"] == after["evaluation"]["passed"]
    summary = json.loads((public / "summary.json").read_text())
    summary["raw_results_sha256"] = summary["results_sha256"]
    summary["results_sha256"] = digest((public / "results.jsonl").read_bytes())
    write_json(public / "summary.json", summary)
    protocol = json.loads((public / "protocol.json").read_text())
    protocol["path_redactions"] = {
        "note": "Post-run publication copy: local path prefixes in diagnostic strings replaced; frozen inputs unchanged.",
        "original_protocol_sha256": raw_hashes["protocol.json"],
        "source_hash_note": "Source hashes describe the pre-run preparation snapshot, not necessarily final repository files.",
    }
    write_json(public / "protocol.json", protocol)
    report = {
        "published_at": now(), "purpose": "local path privacy only; no model output or outcome changes",
        "placeholders": [replacement for _, replacement in replacements],
        "unredacted_originals": "byte-identical local archive outside public repository",
        "inputs_unchanged": True,
        "model_responses_token_ids_counts_latency_and_pass_outcomes_unchanged": True,
        "files": {name: {"raw_sha256": checksum,
                          "public_sha256": digest((public / name).read_bytes())}
                  for name, checksum in raw_hashes.items()},
    }
    write_json(public / "publication.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public", type=Path, default=ROOT / "results")
    parser.add_argument("--private-archive", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    result = publish(args.public, args.private_archive, args.workspace)
    print(json.dumps({"published_files": len(result["files"]), "inputs_unchanged": True}))
