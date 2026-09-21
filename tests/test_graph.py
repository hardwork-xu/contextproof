from copy import deepcopy
import hashlib
import json

import pytest

from contextproof.graph import (
    build_graph, canonical_graph_bytes, compare_graphs, validate_graph,
)
from contextproof.dependencies import _Corpus
from contextproof.index import source_lines


def anchor(texts, path="app.py", symbol="entry", entry_id="selected-entry"):
    corpus = _Corpus.from_texts(texts)
    owner = corpus.definitions[path][symbol][0]
    record = corpus.record(path, symbol, "class" if owner.__class__.__name__ == "ClassDef"
                           else "function", owner)
    return {**record, "id": entry_id, "file_sha256": hashlib.sha256(texts[path].encode()).hexdigest()}


def graph(texts, selected, **kwargs):
    return build_graph(texts, hashlib.sha256(json.dumps(texts, sort_keys=True).encode()).hexdigest(),
                       [selected], **kwargs)


def reseal(value):
    value["id"] = hashlib.sha256(json.dumps(
        {key: item for key, item in value.items() if key != "id"}, sort_keys=True,
        ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return value


def test_transitive_change_has_causal_path_through_unchanged_caller_and_helper():
    old = {"app.py": "from helper import compute\ndef entry():\n    return compute()\n",
           "helper.py": "from policy import rate\ndef compute():\n    return rate()\n",
           "policy.py": "def rate():\n    return 5\n"}
    selected = anchor(old)
    before = graph(old, selected)
    after = graph(old | {"policy.py": "def rate():\n    return 20\n"}, selected)
    result = compare_graphs(before, after)
    assert result["status"] == "changed" and not result["fresh"]
    changed = [cause for cause in result["results"][0]["causes"] if cause["kind"] == "changed"]
    assert any([before["nodes"][key]["symbol"] for key in cause["path"]]
               == ["entry", "compute", "rate"] for cause in changed)
    assert before["anchors"][0]["status"] == "unchanged"
    assert after["anchors"][0]["source_status"] == "unchanged"
    assert len(before["nodes"]) == 5  # Three declarations plus two import bindings.


def test_stable_identity_survives_line_movement_and_changed_root_is_rebuilt():
    old = {"app.py": "def entry():\n    return 5\n"}
    selected = anchor(old)
    before = graph(old, selected)
    moved = graph({"app.py": "# moved\n\n" + old["app.py"]}, selected)
    assert set(before["nodes"]) == set(moved["nodes"])
    assert compare_graphs(before, moved)["fresh"]
    changed = graph({"app.py": "def entry():\n    return 20\n"}, selected)
    assert changed["anchors"][0]["source_status"] == "changed"
    assert next(iter(changed["nodes"].values()))["text"].endswith("return 20\n")
    assert compare_graphs(before, changed)["status"] == "changed"


def test_mutual_recursion_is_finite_and_not_itself_unresolved():
    texts = {"app.py": "def entry():\n    return other()\ndef other():\n    return entry()\n"}
    built = graph(texts, anchor(texts))
    validate_graph(built)
    assert len(built["nodes"]) == 2 and len(built["edges"]) == 2
    assert built["frontier"] == []
    assert compare_graphs(built, built)["fresh"]


@pytest.mark.parametrize("kwargs", [{"max_depth": 1}, {"max_nodes": 1}, {"max_depth": 0}])
def test_bounded_frontier_never_becomes_fresh(kwargs):
    texts = {"app.py": "def entry():\n    return helper()\ndef helper():\n    return 5\n"}
    built = graph(texts, anchor(texts), **kwargs)
    validate_graph(built)
    assert built["frontier"]
    assert built["anchors"][0]["status"] == "unresolved"
    assert not compare_graphs(built, built)["fresh"]


def test_dynamic_binding_and_capture_uncertainty_stay_visible():
    old = {"app.py": "def entry():\n    return callback()\ncallback = factory()\n"}
    selected = anchor(old)
    before = graph(old, selected)
    after = graph({"app.py": "def entry():\n    return callback()\ndef callback():\n    return 1\n"}, selected)
    assert before["anchors"][0]["status"] == "unresolved"
    assert compare_graphs(before, after)["status"] == "unresolved"
    assert not compare_graphs(before, after)["fresh"]


def test_adding_duplicate_module_invalidates_cached_resolution():
    old = {"app.py": "from helper import compute\ndef entry():\n    return compute()\n",
           "helper.py": "def compute():\n    return 5\n"}
    selected = anchor(old)
    cache = {}
    before = graph(old, selected, parsed_cache=cache)
    new = old | {"src/helper.py": "def compute():\n    return 99\n"}
    warm = graph(new, selected, parsed_cache=cache)
    cold = graph(new, selected)
    assert canonical_graph_bytes(warm) == canonical_graph_bytes(cold)
    assert compare_graphs(before, warm)["status"] == "unresolved"
    assert any("ambiguous" in item["reason"] for item in warm["frontier"])


def test_current_missing_ambiguous_and_parse_failure_are_explicit():
    old = {"app.py": "def entry():\n    return 5\n"}
    selected = anchor(old)
    before = graph(old, selected)
    missing = graph({}, selected)
    assert missing["anchors"][0]["status"] == "missing"
    assert compare_graphs(before, missing)["status"] == "missing"
    duplicate = graph({"app.py": old["app.py"] * 2}, selected)
    broken = graph({"app.py": "def entry(:\n"}, selected)
    for current in (duplicate, broken):
        validate_graph(current)
        assert current["anchors"][0]["status"] == "unresolved"
        assert not compare_graphs(before, current)["fresh"]


def test_import_retarget_is_changed_even_with_identical_definition_text():
    old = {"app.py": "from one import compute\ndef entry():\n    return compute()\n",
           "one.py": "def compute():\n    return 5\n",
           "two.py": "def compute():\n    return 5\n"}
    selected = anchor(old)
    before = graph(old, selected)
    after = graph(old | {"app.py": old["app.py"].replace("from one", "from two")}, selected)
    assert compare_graphs(before, after)["status"] in {"changed", "missing"}
    assert after["anchors"][0]["source_status"] == "unchanged"


def test_class_inheritance_is_transitive_and_preserves_source_guarantee():
    old = {"app.py": "class Base:\n    pass\nclass Parent(Base):\n    pass\nclass entry(Parent):\n    pass\n"}
    selected = anchor(old)
    before = graph(old, selected)
    after = graph({"app.py": old["app.py"].replace("class Base:\n    pass", "class Base:\n    code = 7")}, selected)
    assert compare_graphs(before, after)["status"] == "changed"
    assert "semantic" in before["guarantee"]


def test_shared_roots_are_bounded_per_anchor_and_input_order_is_deterministic():
    texts = {"app.py": "def entry():\n    return helper()\ndef helper():\n    return leaf()\ndef leaf():\n    return 1\n"}
    anchors = [anchor(texts), anchor(texts, symbol="helper", entry_id="other")]
    first = build_graph(texts, "snapshot", anchors, max_depth=2)
    second = build_graph(dict(reversed(list(texts.items()))), "snapshot", anchors[::-1], max_depth=2)
    assert canonical_graph_bytes(first) == canonical_graph_bytes(second)
    validate_graph(first)
    entries = {item["entry_id"]: item for item in first["anchors"]}
    assert entries["selected-entry"]["status"] == "unresolved"
    assert entries["other"]["status"] == "unchanged"


def test_tampered_seal_and_resealed_omitted_frontier_are_rejected():
    texts = {"app.py": "def entry():\n    return dynamic()\n"}
    built = graph(texts, anchor(texts))
    tampered = deepcopy(built)
    next(iter(tampered["nodes"].values()))["text"] += "# tamper\n"
    with pytest.raises(ValueError, match="integrity"):
        validate_graph(tampered)
    missing_frontier = deepcopy(built)
    missing_frontier["frontier"] = []
    missing_frontier["anchors"][0]["frontier"] = []
    missing_frontier["anchors"][0]["status"] = "unchanged"
    with pytest.raises(ValueError, match="frontier"):
        validate_graph(reseal(missing_frontier))


def test_parse_cache_reuses_only_unchanged_source_and_does_not_read_files(monkeypatch):
    texts = {"app.py": "def entry():\n    return 5\n"}
    selected = anchor(texts)
    cache = {}
    first = graph(texts, selected, parsed_cache=cache)
    assert len(cache) == 1
    def no_parse(*args, **kwargs):
        raise AssertionError("unchanged source was reparsed")
    monkeypatch.setattr("contextproof.dependencies.ast.parse", no_parse)
    assert graph(texts, selected, parsed_cache=cache) == first


def test_source_lines_stay_exact_for_crlf():
    texts = {"app.py": "def entry():\r\n    return 5\r\n"}
    selected = anchor(texts)
    built = graph(texts, selected)
    record = next(iter(built["nodes"].values()))
    assert source_lines(record["text"]) == ["def entry():\r\n", "    return 5\r\n"]
    validate_graph(built)


def test_changing_anchor_declaration_kind_reports_changed():
    old = {"app.py": "def entry():\n    return 1\n"}
    selected = anchor(old)
    before = graph(old, selected)
    after = graph({"app.py": "class entry:\n    pass\n"}, selected)
    assert compare_graphs(before, after)["status"] == "changed"


def test_resealed_unavailable_anchor_cannot_drop_its_uncertainty():
    texts = {"app.py": "def entry():\n    return 1\n"}
    built = graph({}, anchor(texts))
    built["anchors"][0]["status"] = "unresolved"
    built["anchors"][0]["frontier"] = []
    built["frontier"] = []
    with pytest.raises(ValueError, match="frontier"):
        validate_graph(reseal(built))
