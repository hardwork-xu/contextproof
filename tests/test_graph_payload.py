import ast
from copy import deepcopy
import hashlib
import json

import pytest

from contextproof.graph import build_graph, compare_graphs
from contextproof.graph_payload import render_graph_context, render_graph_update


def anchor(texts, path="checkout.py", symbol="invoice_total"):
    source = texts[path]
    node = next(item for item in ast.parse(source).body
                if isinstance(item, ast.FunctionDef) and item.name == symbol)
    text = "".join(source.splitlines(keepends=True)[node.lineno - 1:node.end_lineno])
    return {"id": hashlib.sha256(f"{path}:{symbol}".encode()).hexdigest(),
            "path": path, "symbol": symbol, "kind": "function", "start_line": node.lineno,
            "end_line": node.end_lineno, "text": text,
            "text_sha256": hashlib.sha256(text.encode()).hexdigest()}


def graph(texts, anchors=None, **kwargs):
    identity = hashlib.sha256(json.dumps(texts, sort_keys=True).encode()).hexdigest()
    return build_graph(texts, identity, anchors or [anchor(texts)], **kwargs)


def repository():
    return {"checkout.py": "from pricing import tax_rate\n\ndef invoice_total(amount):\n"
            "    return amount * (1 + tax_rate())\n",
            "pricing.py": "def tax_rate():\n    return 0.05\n"}


def test_full_payload_delivers_anchor_helper_and_import_source():
    current = graph(repository())
    result = render_graph_context(current)
    assert result["complete"]
    payload = json.loads(result["rendered"])
    assert {node["kind"] for node in payload["nodes"]} == {"function", "import"}
    source = "\n".join(node["text"] for node in payload["nodes"])
    assert "def invoice_total" in source
    assert "return 0.05" in source
    assert "from pricing import tax_rate" in source
    assert payload["references"]
    assert result["consumed"] == len(result["rendered"].encode("utf-8")) <= result["budget"]
    assert payload["graph_id"] == current["id"]


def test_changed_helper_actually_reaches_model_payload():
    texts = repository()
    saved = [anchor(texts)]
    before = graph(texts, saved)
    texts["pricing.py"] = "def tax_rate():\n    return 0.20\n"
    after = graph(texts, saved)
    result = render_graph_update(before, after)
    assert result["complete"]
    assert "return 0.20" in result["rendered"]
    assert "return 0.05" not in result["rendered"]
    assert "def invoice_total" in result["rendered"]
    assert "from pricing import tax_rate" in result["rendered"]
    assert result["requires_base"] and result["base_graph_id"] == before["id"]
    assert result["coverage"] == "required-update-nodes"
    assert result["consumed"] <= 16000
    full = json.loads(render_graph_context(after)["rendered"])
    current_nodes = {node["id"]: node for node in full["nodes"]}
    for node in json.loads(result["rendered"])["nodes"]:
        assert node == current_nodes[node["id"]]


def test_changed_grandchild_includes_current_causal_path():
    texts = repository()
    texts["pricing.py"] = "from policy import rate\n\ndef tax_rate():\n    return rate()\n"
    texts["policy.py"] = "def rate():\n    return 0.05\n"
    saved = [anchor(texts)]
    before = graph(texts, saved)
    texts["policy.py"] = "def rate():\n    return 0.20\n"
    after = graph(texts, saved)
    result = render_graph_update(before, after)
    assert result["complete"]
    nodes = json.loads(result["rendered"])["nodes"]
    assert {node["symbol"] for node in nodes if node["kind"] == "function"} == {
        "invoice_total", "tax_rate", "rate"}
    assert "return 0.20" in result["rendered"]
    assert "from policy import rate" in result["rendered"]


def test_retargeted_import_emits_current_binding_and_target_only():
    texts = repository()
    texts["replacement.py"] = "def tax_rate():\n    return 0.20\n"
    saved = [anchor(texts)]
    before = graph(texts, saved)
    texts["checkout.py"] = texts["checkout.py"].replace("from pricing", "from replacement")
    after = graph(texts, saved)
    result = render_graph_update(before, after)
    assert result["complete"]
    assert "from replacement import tax_rate" in result["rendered"]
    assert "return 0.20" in result["rendered"]
    assert "return 0.05" not in result["rendered"]
    assert any(item["path"] == "pricing.py" for item in result["deleted"])


def test_deleted_dependency_has_tombstone_without_obsolete_source():
    texts = repository()
    saved = [anchor(texts)]
    before = graph(texts, saved)
    del texts["pricing.py"]
    after = graph(texts, saved)
    result = render_graph_update(before, after)
    assert not result["complete"]
    assert result["frontier"]
    assert "return 0.05" not in result["rendered"]
    assert any(item["path"] == "pricing.py" for item in result["deleted"])
    assert json.loads(result["rendered"])["deleted"] == result["deleted"]


def test_tiny_budget_cannot_silently_claim_complete_context():
    current = graph(repository())
    result = render_graph_context(current, budget=1)
    assert result["status"] == "budget_too_small"
    assert not result["complete"]
    assert result["rendered"] == ""
    assert result["consumed"] == 0
    assert result["omitted_nodes"]
    assert result["minimum_budget"] > result["budget"]


def test_changed_helper_update_with_small_budget_fails_explicitly():
    texts = repository()
    saved = [anchor(texts)]
    before = graph(texts, saved)
    texts["pricing.py"] = "def tax_rate():\n    return 0.20\n"
    after = graph(texts, saved)
    result = render_graph_update(before, after, budget=100)
    assert not result["complete"]
    assert result["status"] == "budget_too_small"
    assert result["consumed"] <= 100
    assert any(after["nodes"][node_id]["symbol"] == "tax_rate"
               for node_id in result["omitted_nodes"])


def test_recursive_graph_sources_are_deduplicated():
    texts = {"checkout.py": "def invoice_total(amount):\n    return helper(amount)\n\n"
             "def helper(amount):\n    return invoice_total(amount - 1) if amount else 0\n"}
    current = graph(texts)
    result = render_graph_context(current)
    assert result["complete"]
    payload = json.loads(result["rendered"])
    ids = [node["id"] for node in payload["nodes"]]
    assert len(ids) == len(set(ids)) == 2
    assert len(payload["references"]) == 2


def test_fitting_manifest_explicitly_lists_omitted_whole_nodes():
    current = graph(repository())
    large = render_graph_context(current, budget=100000)
    result = render_graph_context(current, budget=large["minimum_budget"] + 20)
    assert result["rendered"]
    assert result["consumed"] <= result["budget"]
    assert not result["complete"]
    assert result["omitted_nodes"]
    payload = json.loads(result["rendered"])
    assert payload["omitted_node_count"] == len(result["omitted_nodes"])
    width = payload["reference_id_prefix_length"]
    assert payload["omitted_nodes"] == [value[:width] for value in result["omitted_nodes"][:8]]
    for node in payload["nodes"]:
        assert node["text"] == current["nodes"][node["id"]]["text"]


def test_frontier_remains_explicit_even_when_all_nodes_fit():
    current = graph(repository(), max_depth=1)
    result = render_graph_context(current)
    assert not result["complete"]
    assert not result["omitted_nodes"]
    assert result["frontier"]
    payload = json.loads(result["rendered"])
    assert payload["frontier_count"] == len(result["frontier"])
    assert payload["frontier"] == result["frontier_summary"]
    assert payload["frontier_details_truncated"]
    assert payload["full_graph_handle"] == current["id"]


def test_many_frontiers_do_not_displace_all_source():
    names = [f"helper_{index:03}" for index in range(80)]
    source = "def invoice_total(amount):\n    return [" + ", ".join(
        name + "()" for name in names) + "]\n\n"
    source += "\n".join(f"def {name}():\n    return len([])\n" for name in names)
    current = graph({"checkout.py": source})
    result = render_graph_context(current, budget=16000)
    assert len(result["frontier"]) == 80
    assert not result["complete"]
    assert result["rendered"] and result["consumed"] <= 16000
    assert "def invoice_total" in result["rendered"]
    payload = json.loads(result["rendered"])
    assert len(payload["frontier"]) <= 4
    assert payload["frontier_count"] == 80
    assert payload["frontier_details_truncated"]
    assert payload["full_graph_handle"] == current["id"]


def test_unrelated_edit_needs_no_source_update_but_pins_both_graphs():
    texts = repository()
    saved = [anchor(texts)]
    before = graph(texts, saved)
    texts["unrelated.py"] = "def other():\n    return 42\n"
    after = graph(texts, saved)
    result = render_graph_update(before, after)
    assert result["complete"]
    assert result["included_nodes"] == []
    assert result["base_graph_id"] == before["id"]
    assert result["graph_id"] == after["id"]
    assert result["consumed"] < render_graph_context(after)["consumed"]


def test_utf8_byte_count_and_determinism():
    texts = repository()
    texts["pricing.py"] = 'def tax_rate():\n    return "税率"\n'
    current = graph(texts)
    result = render_graph_context(current)
    assert result["complete"]
    assert "税率" in result["rendered"]
    assert result["consumed"] > len(result["rendered"])
    assert result == render_graph_context(deepcopy(current))
    assert render_graph_context(current, result["consumed"])["complete"]


def test_comparison_is_bound_to_actual_graphs():
    texts = repository()
    saved = [anchor(texts)]
    before = graph(texts, saved)
    texts["pricing.py"] = "def tax_rate():\n    return 0.20\n"
    after = graph(texts, saved)
    comparison = compare_graphs(before, after)
    assert render_graph_update(before, after, comparison)["complete"]
    comparison["results"] = []
    with pytest.raises(ValueError, match="comparison"):
        render_graph_update(before, after, comparison)


@pytest.mark.parametrize("budget", [-1, True, 1.5, "16000"])
def test_invalid_budgets_rejected(budget):
    with pytest.raises(ValueError, match="budget"):
        render_graph_context(graph(repository()), budget)
