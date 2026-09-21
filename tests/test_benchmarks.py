"""Check benchmark ground truth and metric arithmetic independently of the engine."""

import hashlib

import pytest

from benchmarks.oracles import (
    EXPECTED,
    SOURCE,
    binary_metrics,
    file_hash_accepts,
    path_line_accepts,
    retrieval_metrics,
    transform,
)


def fixture_bundle():
    lines = SOURCE.splitlines(keepends=True)
    return {"entries": [{
        "path": "subject.py", "start_line": 4, "end_line": 9,
        "text": "".join(lines[3:9]),
        "file_sha256": hashlib.sha256(SOURCE.encode()).hexdigest(),
    }]}


def test_metric_confusion_matrix_and_undefined_cases():
    result = binary_metrics([True, True, False, False], [True, False, True, False])
    assert result == {
        "n": 4, "true_positive": 1, "false_positive": 1,
        "true_negative": 1, "false_negative": 1,
        "precision": 0.5, "recall": 0.5, "accuracy": 0.5,
    }
    assert binary_metrics([], [])["accuracy"] is None
    assert binary_metrics([False], [False])["precision"] is None
    assert binary_metrics([False], [False])["recall"] is None
    with pytest.raises(ValueError):
        binary_metrics([True], [])


def test_file_relevance_counts_unique_labels_and_entry_rank():
    result = retrieval_metrics(["a.py", "b.py", "a.py"], ["x.py", "a.py", "a.py"])
    assert result == {
        "file_recall": 0.5, "hit": True,
        "reciprocal_rank": 0.5, "first_relevant_entry_rank": 2,
    }
    assert retrieval_metrics(["a.py"], ["x.py"])["reciprocal_rank"] == 0
    assert retrieval_metrics([], [])["file_recall"] is None


@pytest.mark.parametrize("case", list(EXPECTED))
def test_transformations_have_independent_exact_text_oracle(tmp_path, case):
    original = fixture_bundle()
    candidate = transform(case, tmp_path, original)
    reference = original["entries"][0]["text"]
    occurrences = sum(path.read_text().count(reference) for path in tmp_path.rglob("*.py"))
    expected_counts = {
        "unchanged": 1, "insert_lines": 1, "move_file": 1,
        "edit_target": 0, "delete_file": 0, "duplicate_displaced": 2,
        "tamper_bundle": 1,
    }
    assert occurrences == expected_counts[case]
    assert original == fixture_bundle()
    if case == "tamper_bundle":
        assert candidate["entries"][0]["text"] != reference
        assert file_hash_accepts(candidate["entries"][0], tmp_path)
        assert not path_line_accepts(candidate["entries"][0], tmp_path)
    elif case == "unchanged":
        assert path_line_accepts(candidate["entries"][0], tmp_path)
        assert file_hash_accepts(candidate["entries"][0], tmp_path)
    else:
        assert not path_line_accepts(candidate["entries"][0], tmp_path)
        assert not file_hash_accepts(candidate["entries"][0], tmp_path)


@pytest.mark.parametrize("separator", ["\v", "\f", "\x85", "\u2028", "\u2029"])
@pytest.mark.parametrize("newline", ["\n", "\r", "\r\n"])
def test_path_line_oracle_keeps_unicode_separators_inside_editor_lines(
    tmp_path, separator, newline
):
    text = "prefix" + separator + "still first line" + newline + "wanted" + newline
    (tmp_path / "subject.py").write_bytes(text.encode("utf-8"))
    entry = {
        "path": "subject.py", "start_line": 2, "end_line": 2,
        "text": "wanted" + newline,
    }
    assert path_line_accepts(entry, tmp_path)
