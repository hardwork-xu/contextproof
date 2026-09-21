import json
from pathlib import Path
import uuid

import pytest

from benchmarks.revision_baselines.privacy import public_value
from benchmarks.revision_model import sha
from scripts.publish_revision_model import export


def test_runtime_log_redaction_preserves_answers_errors_timings_and_hash_lineage(tmp_path):
    source, previous, target = (tmp_path / name for name in ("raw", "previous", "current"))
    source.mkdir()
    identifier = str(uuid.UUID(int=123))
    retry = ("2026-09-21T11:02:18.361278Z  WARN codex_core::responses_retry: "
             "stream disconnected (3/5 in 777ms) turn_id=" + identifier
             + " retries=3 sampling_error=request timed out\n")
    snapshot = ("2026-09-21T11:03:16.108276Z  WARN codex_core::shell_snapshot: "
                f'Failed to delete "{Path.home()}/.codex/shell_snapshots/'
                + identifier + '.123456789.sh": No such file or directory\n')
    stderr = retry + snapshot + "model probe UUID literal: " + identifier + "\n"
    (source / "stderr.txt").write_text(stderr)
    (source / "prompt.txt").write_text(retry)
    (source / "response.json").write_text(json.dumps({"answer_json": identifier}))
    results = [{"correct": False, "record": {"answer": {"value": identifier},
                "usage": {"input_tokens": 500, "output_tokens": 20}, "wall_seconds": 1.25,
                "error": "request timed out", "returncode": 1}}]
    (source / "results.json").write_text(json.dumps(results))
    export(source, previous)

    # Recreate the earlier export's missed IDs while retaining its genuine raw
    # hash, then check that the repaired publication preserves both identities.
    old_stderr = public_value(stderr).encode()
    (previous / "stderr.txt").write_bytes(old_stderr)
    manifest = json.loads((previous / "publication.json").read_text())
    manifest["files"]["stderr.txt"]["public_sha256"] = sha(old_stderr)
    (previous / "publication.json").write_text(json.dumps(manifest))
    previous_manifest_hash = sha((previous / "publication.json").read_bytes())
    export(source, target, previous)

    for name in ("prompt.txt", "response.json", "results.json"):
        assert (target / name).read_bytes() == (previous / name).read_bytes()
    assert json.loads((target / "results.json").read_text()) == results
    redacted = (target / "stderr.txt").read_text()
    assert redacted == (retry.replace(identifier, "<REDACTED_LOCAL_SESSION>")
                        + public_value(snapshot).replace(identifier + ".123456789",
                                                         "<REDACTED_LOCAL_SNAPSHOT>")
                        + "model probe UUID literal: " + identifier + "\n")
    published = json.loads((target / "publication.json").read_text())
    record = published["files"]["stderr.txt"]
    assert record["private_sha256"] == sha((source / "stderr.txt").read_bytes())
    assert record["public_sha256"] == sha((target / "stderr.txt").read_bytes())
    assert record["previous_public_sha256"] == [sha(old_stderr)]
    assert published["previous_publication_sha256"] == previous_manifest_hash


def test_republication_rejects_changed_private_experiment_records(tmp_path):
    source, previous, target = (tmp_path / name for name in ("raw", "previous", "current"))
    source.mkdir()
    (source / "response.json").write_text('{"answer_json":"original answer"}')
    export(source, previous)
    (source / "response.json").write_text('{"answer_json":"changed answer"}')
    with pytest.raises(ValueError, match="private source differs"):
        export(source, target, previous)
