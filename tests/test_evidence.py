from copy import deepcopy
import pytest

from contextproof.evidence import (
    _bundle_id, count_tokens, make_bundle, render_bundle, repair_bundle, sha256, verify_bundle,
)
from contextproof.index import build_index


SOURCE = "def find_needle():\n    return 'evidence'\n"


@pytest.fixture
def evidence(tmp_path):
    (tmp_path / "module.py").write_text(SOURCE)
    snapshot = build_index(tmp_path)
    bundle = make_bundle(snapshot, "find_needle", budget=4000, method="bm25")
    assert len(bundle["entries"]) == 1
    return tmp_path, bundle


def statuses(report):
    return [item["status"] for item in report["results"]]


def test_exact_source_and_full_metadata_budget(evidence):
    root, bundle = evidence
    assert bundle["budget_unit"] == "utf8_bytes"
    rendered = render_bundle(bundle)
    assert len(rendered.encode("utf-8")) == bundle["consumed"] <= bundle["budget"]
    assert bundle["consumed"] > len(SOURCE.encode())
    assert bundle["entries"][0]["text_sha256"] == sha256(SOURCE)
    report = verify_bundle(bundle, root)
    assert statuses(report) == ["valid"]
    assert report["valid"] is True
    assert report["current_snapshot_id"] == build_index(root).id


def test_insertion_relocates_and_repairs_reference(evidence):
    root, bundle = evidence
    (root / "module.py").write_text("# new preamble\n\n" + SOURCE)
    report = verify_bundle(bundle, root)
    assert statuses(report) == ["relocated"]
    assert report["valid"] is False
    assert report["results"][0]["repaired"]["start_line"] == 3
    repaired = repair_bundle(bundle, root)
    assert repaired["provenance"]["previous_bundle_id"] == bundle["id"]
    assert repaired["snapshot_id"] == build_index(root).id
    assert statuses(verify_bundle(repaired, root)) == ["valid"]
    assert count_tokens(render_bundle(repaired)) <= repaired["consumed"] <= repaired["budget"]


def test_move_unique_exact_and_duplicate_ambiguity(evidence):
    root, bundle = evidence
    (root / "module.py").rename(root / "moved.py")
    report = verify_bundle(bundle, root)
    assert statuses(report) == ["relocated"]
    assert report["results"][0]["repaired"]["path"] == "moved.py"
    (root / "copy.py").write_text(SOURCE)
    report = verify_bundle(bundle, root)
    assert statuses(report) == ["ambiguous"]
    assert "repaired" not in report["results"][0]
    repaired = repair_bundle(bundle, root)
    assert repaired["entries"] == []
    assert repaired["invalidated"][0]["status"] == "ambiguous"


def test_original_location_valid_despite_copy(evidence):
    root, bundle = evidence
    (root / "copy.py").write_text(SOURCE)
    assert statuses(verify_bundle(bundle, root)) == ["valid"]


def test_edit_and_delete_do_not_repair_by_symbol_name(evidence):
    root, bundle = evidence
    (root / "module.py").write_text(SOURCE.replace("evidence", "changed"))
    report = verify_bundle(bundle, root)
    assert statuses(report) == ["modified"]
    assert "repaired" not in report["results"][0]
    (root / "module.py").unlink()
    assert statuses(verify_bundle(bundle, root)) == ["deleted"]


def test_tampered_text_and_metadata_fail_closed(evidence):
    root, bundle = evidence
    for field, value in [("text", "injected code"), ("path", "../outside.py"),
                         ("end_line", 999), ("file_sha256", "a" * 64)]:
        tampered = deepcopy(bundle)
        tampered["entries"][0][field] = value
        report = verify_bundle(tampered, root)
        assert statuses(report) == ["invalid"]
        assert not report["valid"]
        with pytest.raises(ValueError):
            repair_bundle(tampered, root)


def test_path_safety_after_resealing(evidence):
    root, bundle = evidence
    for path in ["../outside.py", "/tmp/outside.py", "./module.py", "a//module.py"]:
        tampered = deepcopy(bundle)
        tampered["entries"][0]["path"] = path
        tampered["id"] = _bundle_id(tampered)
        assert statuses(verify_bundle(tampered, root)) == ["invalid"]


def test_symlink_source_fails_even_with_safe_duplicate(evidence, tmp_path):
    root, bundle = evidence
    (root / "module.py").unlink()
    (root / "copy.py").write_text(SOURCE)
    (root / "module.py").symlink_to(root / "copy.py")
    assert statuses(verify_bundle(bundle, root)) == ["invalid"]


def test_disallowed_source_not_used_for_relocation(evidence):
    root, bundle = evidence
    (root / "module.py").unlink()
    (root / ".env").write_text(SOURCE)
    (root / "generated.py").write_text("# @generated\n" + SOURCE)
    assert statuses(verify_bundle(bundle, root)) == ["deleted"]


def test_empty_and_malformed_bundles_fail_closed(evidence):
    root, bundle = evidence
    for malformed in [None, {}, {"schema_version": 1, "entries": "bad"}]:
        report = verify_bundle(malformed, root)
        assert not report["valid"]
        assert "error" in report
    empty = make_bundle(build_index(root), "notfoundanywhere")
    assert empty["entries"] == []
    assert not verify_bundle(empty, root)["valid"]


def test_whole_payload_budget_excludes_oversized_chunks(evidence):
    root, original = evidence
    # Changing a four-digit budget to three digits also shrinks the header.
    # Leave enough margin that header digit changes cannot admit the snippet.
    budget = original["consumed"] - 20
    bundle = make_bundle(build_index(root), "find_needle", budget=budget, method="bm25")
    assert bundle["entries"] == []
    assert bundle["omitted_count"] == 1
    assert len(render_bundle(bundle).encode()) <= budget
    with pytest.raises(ValueError, match="metadata"):
        make_bundle(build_index(root), "find_needle", budget=10)
    with pytest.raises(ValueError):
        make_bundle(build_index(root), "find_needle", budget=True)


def test_utf8_and_embedded_fences_are_budgeted(tmp_path):
    source = "说明 needle\n```python\nprint('你好')\n```\n"
    (tmp_path / "notes.md").write_text(source)
    bundle = make_bundle(build_index(tmp_path), "needle", budget=4000)
    rendered = render_bundle(bundle)
    assert "````\n" in rendered
    assert count_tokens(rendered) == len(rendered.encode("utf-8"))
    assert count_tokens(rendered) > len(rendered)


def test_crlf_and_no_final_newline_remain_exact(tmp_path):
    for raw in [b"def needle():\r\n    return 2\r\n", b"def needle():\n    return 2"]:
        (tmp_path / "module.py").write_bytes(raw)
        bundle = make_bundle(build_index(tmp_path), "needle")
        assert bundle["entries"][0]["text"].encode() == raw
        assert statuses(verify_bundle(bundle, tmp_path)) == ["valid"]


@pytest.mark.parametrize("embedded", ["\u2028", "\u2029", "\x0b", "\x0c", "\x85"])
def test_unicode_text_separators_do_not_shift_source_line_numbers(tmp_path, embedded):
    # These characters can occur inside Python strings but are not editor or
    # Python parser line endings. str.splitlines() would count extra lines.
    selected = f"def needle():\n    return 'left{embedded}right'\n"
    source = f"label = 'left{embedded}right'\n\n" + selected
    path = tmp_path / "module.py"
    path.write_text(source)
    bundle = make_bundle(build_index(tmp_path), "needle", method="bm25")
    entry = bundle["entries"][0]
    assert entry["start_line"] == 3
    assert entry["end_line"] == 4
    assert entry["text"] == selected
    assert statuses(verify_bundle(bundle, tmp_path)) == ["valid"]
    path.write_text("# inserted\n" + source)
    report = verify_bundle(bundle, tmp_path)
    assert statuses(report) == ["relocated"]
    assert report["results"][0]["repaired"]["start_line"] == 4
    repaired = repair_bundle(bundle, tmp_path)
    assert statuses(verify_bundle(repaired, tmp_path)) == ["valid"]


def test_unknown_tokenizer_rejected():
    with pytest.raises(ValueError):
        count_tokens("hello", "pretend-tokenizer")


@pytest.mark.parametrize("encoding", ["cl100k_base", "o200k_base"])
def test_optional_tokenizers_count_exact_complete_payload(evidence, encoding):
    tiktoken = pytest.importorskip("tiktoken")
    root, _ = evidence
    bundle = make_bundle(build_index(root), "find_needle", budget=1000, tokenizer=encoding)
    actual = len(tiktoken.get_encoding(encoding).encode(render_bundle(bundle), disallowed_special=()))
    assert bundle["budget_unit"] == "tokens"
    assert actual == bundle["consumed"] <= bundle["budget"]
    assert bundle["entries"]
    assert statuses(verify_bundle(bundle, root)) == ["valid"]


def test_render_rejects_malformed_source_metadata(evidence):
    _, bundle = evidence
    for malformed in [{}, {"schema_version": 1, "entries": []}]:
        with pytest.raises(ValueError):
            render_bundle(malformed)
    bundle["entries"][0]["text"] = "forged"
    with pytest.raises(ValueError, match="text_sha256"):
        render_bundle(bundle)
