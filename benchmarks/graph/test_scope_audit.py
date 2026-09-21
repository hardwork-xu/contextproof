"""Execute the published regression fixtures through graph and direct APIs."""

import json
from pathlib import Path

import pytest

from contextproof.graph import build_graph, compare_graphs
from contextproof.graph_payload import render_graph_context
from contextproof.session import capture_context, check_context


AUDIT = json.loads(Path(__file__).with_name("scope-audit.json").read_text(encoding="utf-8"))


def write_sources(root, texts):
    for relative, source in texts.items():
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(source, encoding="utf-8")


@pytest.mark.parametrize("fixture", AUDIT["fixtures"], ids=lambda fixture: fixture["id"])
def test_scope_audit_graph_and_served_direct_interfaces(fixture, tmp_path):
    historical_graph = fixture["historical"]["before_graph"]
    selected = historical_graph["anchors"][0]
    anchor = {**historical_graph["nodes"][selected["node_id"]], "id": selected["entry_id"]}
    before = build_graph(fixture["before_sources"], "before", [anchor])
    after = build_graph(fixture["after_sources"], "after", [anchor])
    comparison = compare_graphs(before, after)
    assert comparison["status"] == "unresolved"
    assert comparison["fresh"] is False
    assert after["frontier"]

    payload = render_graph_context(after, budget=16000)
    assert payload["complete"] is False
    assert len(payload["rendered"].encode("utf-8")) == payload["consumed"] <= 16000
    expected = {(item["path"], item["symbol"])
                for item in fixture["expected_corrected"]["current_source_nodes"]}
    assert {(item["path"], item["symbol"]) for item in after["nodes"].values()} == expected
    assert {(item["path"], item["symbol"])
            for item in json.loads(payload["rendered"])["nodes"]} == expected

    write_sources(tmp_path, fixture["before_sources"])
    current_context = capture_context(tmp_path, "entry", budget=16000)
    assert {(entry["path"], entry["symbol"])
            for entry in current_context["bundle"]["entries"]} == expected
    write_sources(tmp_path, fixture["after_sources"])
    historical_context = fixture["historical"]["legacy_capture_check"]["context"]
    for context in [current_context, historical_context]:
        report = check_context(context, tmp_path)
        assert report["dependencies"]["status"] == "unresolved"
        assert report["dependencies"]["fresh"] is False
        assert report["can_reuse"] is False
