"""Check task selection, adaptation semantics and safe evaluation without a model."""

import json
import platform
from pathlib import Path

import pytest

from benchmarks.downstream.sandbox_worker import execute, validate_code
from benchmarks.downstream.suite import DRIFTS, adapt_task, digest, read_tasks
from scripts.run_downstream import evaluate, extract_code, sandbox_check


def test_frozen_first_twenty_have_no_canonical_solutions():
    tasks = [adapt_task(task) for task in read_tasks()]
    assert len(tasks) == 20
    assert {drift: sum(task["drift"] == drift for task in tasks) for drift in DRIFTS} == {
        drift: 5 for drift in DRIFTS}
    assert all("canonical_solution" not in task for task in tasks)
    moved = tasks[2]
    assert list(moved["before_files"].values()) == list(moved["after_files"].values())
    assert list(moved["before_files"]) != list(moved["after_files"])
    assert tasks[3]["before_files"] == tasks[3]["after_files"]


def correct_code():
    return (
        "from request_api import decode_request\n"
        "def has_close_elements(request):\n"
        "    numbers, threshold = decode_request(request)\n"
        "    return any(abs(a-b) < threshold for i,a in enumerate(numbers) "
        "for b in numbers[i+1:])\n"
    )


def test_original_functional_tests_execute_and_obsolete_import_fails():
    task = adapt_task(read_tasks()[0])
    assert execute({"task": task, "code": correct_code()})["passed"]
    with pytest.raises(ImportError):
        execute({"task": task, "code": correct_code().replace("decode_request", "unpack_request")})
    with pytest.raises(AssertionError):
        execute({"task": task, "code": correct_code().replace("abs(a-b) < threshold", "False")})


@pytest.mark.parametrize("source", [
    "import os\n", "x = ().__class__\n", "from math import *\n",
    "from typing import __builtins__\n", "class C: pass\n",
])
def test_generated_code_rejects_escape_mechanisms(source):
    with pytest.raises(ValueError):
        validate_code(source, {"request_api"})


def test_code_extraction_is_fixed_and_does_not_fix_generated_code():
    assert extract_code("```python\ndef x():\n    return 1\n```\n") == "def x():\n    return 1\n"
    assert extract_code("invalid prose") == "invalid prose\n"


@pytest.mark.skipif(platform.system() != "Darwin", reason="macOS Seatbelt integration")
def test_real_sandbox_denial_and_real_functional_execution(tmp_path):
    checks = sandbox_check(tmp_path)["checks"]
    assert all(checks[name].startswith("denied:")
               for name in ("outside_read", "outside_write", "network", "fork"))
    result = evaluate(adapt_task(read_tasks()[0]), correct_code(), tmp_path)
    assert result["passed"], json.dumps(result)
    result = evaluate(adapt_task(read_tasks()[0]), "import os\n", tmp_path)
    assert not result["passed"]
    assert result["error_type"] == "ValueError"


def test_published_study_is_complete_and_has_all_attempts():
    root = Path(__file__).resolve().parents[1] / "benchmarks/downstream/results"
    if not (root / "results.jsonl").exists():
        pytest.skip("study has not been run yet")
    results = [json.loads(line) for line in (root / "results.jsonl").read_text().splitlines()]
    events = [json.loads(line) for line in (root / "attempts.jsonl").read_text().splitlines()]
    assert len(results) == 60
    assert len({row["cell"] for row in results}) == 60
    assert len(events) == 120
    assert all(row["attempt"] == 1 for row in results)
    assert all(row["context_tokens"] <= 1024 and row["generation_tokens"] <= 384 for row in results)
    assert {event["event"] for event in events} == {"started", "finished"}
    assert all(row["prompt_tokens"] == row["model_prompt_tokens"] for row in results)
    assert all(len(row["generation_token_ids"]) == row["generation_tokens"] for row in results)
    for result in results:
        cell_events = [event for event in events if event["cell"] == result["cell"]]
        assert [event["event"] for event in cell_events] == ["started", "finished"]
        assert cell_events[1]["response"] == result["response"]


def test_publication_preserves_frozen_inputs_and_audits_every_file():
    root = Path(__file__).resolve().parents[1] / "benchmarks/downstream/results"
    if not (root / "publication.json").exists():
        pytest.skip("publication audit has not been created yet")
    publication = json.loads((root / "publication.json").read_text())
    protocol = json.loads((root / "protocol.json").read_text())
    assert publication["inputs_unchanged"]
    assert digest((root / "inputs.json").read_bytes()) == protocol["inputs_sha256"]
    assert publication["files"]["inputs.json"]["raw_sha256"] == protocol["inputs_sha256"]
    for name, hashes in publication["files"].items():
        assert digest((root / name).read_bytes()) == hashes["public_sha256"], name
        assert str(Path.home()) not in (root / name).read_text()


def test_all_tasks_have_current_api_positive_and_stale_api_controls():
    root = Path(__file__).resolve().parents[1] / "benchmarks/downstream/results"
    if not (root / "oracle_controls.json").exists():
        pytest.skip("post-run controls have not been executed yet")
    controls = json.loads((root / "oracle_controls.json").read_text())
    assert len(controls["results"]) == 40
    assert controls["correct_current_api_passed"] == 20
    assert controls["obsolete_api_passed"] == 5
    assert controls["all_controls_match_expectation"]
    assert not controls["canonical_solutions_in_model_inputs"]
    assert all(row["evaluation"]["passed"] == row["expected_pass"] for row in controls["results"])
