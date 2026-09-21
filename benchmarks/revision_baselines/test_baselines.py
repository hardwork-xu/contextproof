import hashlib
import json
from pathlib import Path

from contextproof.evidence import make_bundle
from contextproof.index import build_index

from .adapter import supplied_anchor_context
from .corpus import prepare_retrieval_corpus
from .diagnostics import diagnose_saved_bundle
from .privacy import public_value


def test_supplied_symbols_keep_both_property_declarations():
    records = [{"path": "pkg/api.py", "symbol": "A.value", "start_line": line,
                "end_line": line + 1, "text": text,
                "text_sha256": hashlib.sha256(text.encode()).hexdigest()}
               for line, text in [(2, "def value(self):\n    return self._value\n"),
                                  (5, "def value(self, value):\n    self._value = value\n")]]
    task = {"source_anchors": {"after": [{"path": "pkg/api.py", "symbol": "A.value",
                                         "matches": records}]}}
    result = supplied_anchor_context(task)
    payload = json.loads(result["rendered"])
    assert len(payload["source"]) == 2
    assert payload["ambiguous_symbols"][0]["physical_declarations"] == 2
    assert result["complete"]  # Complete physical source, not resolved runtime semantics.
    assert result["consumed"] == len(result["rendered"].encode())
    assert not supplied_anchor_context(task, budget_bytes=1)["complete"]


def test_shared_retrieval_corpus_excludes_tests_docs_and_prefix_neighbors(tmp_path):
    root, destination = tmp_path / "original", tmp_path / "materialized"
    for name in ["src/pkg/api.py", "src/pkg/tests/test_answer.py", "src/pkg/docs/example.py",
                 "src/pkg_neighbor/secret.py", "tests/test_answer.py", "src/pkg/CHANGELOG.md"]:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("result = 42\n")
    result = prepare_retrieval_corpus(root, destination, ["src/pkg"])
    assert set(result["files"]) == {"src/pkg/api.py"}
    assert (destination / ".git").is_dir()
    assert not (destination / "tests").exists()
    assert prepare_retrieval_corpus(root, destination, ["src/pkg"])["git_commit"] == result["git_commit"]
    assert "root" not in json.loads((tmp_path / "materialized.corpus.json").read_text())


def test_actual_v1_and_git_predicates_diverge_on_unchanged_caller(tmp_path):
    before, after = tmp_path / "before", tmp_path / "after"
    for root, rate in [(before, "0.05"), (after, "0.20")]:
        root.mkdir()
        (root / "checkout.py").write_text("from pricing import rate\n\ndef invoice_total(x):\n"
                                          "    return x * rate()\n")
        (root / "pricing.py").write_text(f"def rate():\n    return {rate}\n")
    bundle = make_bundle(build_index(before), "invoice_total", budget=4000, method="bm25")
    result = diagnose_saved_bundle(bundle, before, after)
    assert result["git_changed_file"]["status"] == "ok"
    assert result["git_changed_file"]["changed_files"] == ["pricing.py"]
    assert all(row["accept"] for row in result["git_changed_file"]["results"])
    assert all(row["accept"] for row in result["whole_file_hash"]["results"])
    assert result["v1_exact_source"]["valid"]
    assert not result["v1_one_hop"]["fresh"]
    assert result["v1_one_hop"]["summary"] == {"changed": 1}


def test_public_diagnostics_remove_host_identity():
    private = str(Path.home() / "Documents" / "trace.py")
    assert str(Path.home()) not in json.dumps(public_value({"trace": private}))
