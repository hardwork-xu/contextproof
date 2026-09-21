from pathlib import Path

import pytest

from contextproof.index import build_index
from contextproof.models import Chunk, Snapshot
from contextproof.retrieval import search, terms


def test_identifier_components():
    values = terms("HTTPRequest cache_entry parseJSON")
    assert {"httprequest", "http", "request", "cache_entry", "cache", "entry",
            "parsejson", "parse", "json"} <= set(values)


def test_bm25_prefers_distinctive_symbol(tmp_path: Path):
    (tmp_path / "cache.py").write_text("def invalidate_cache():\n    return 1\n")
    (tmp_path / "other.py").write_text("def fetch_entry():\n    return 2\n")
    snapshot = build_index(tmp_path)
    hits = search(snapshot, "invalidate cache")
    assert hits[0].chunk.symbol == "invalidate_cache"
    assert "lexical overlap" in hits[0].reasons[0]
    assert search(snapshot, "totallyabsentword") == []
    assert search(snapshot, "   ") == []


def test_graph_uses_only_one_hop_and_discloses_hint():
    chunks = [Chunk(str(i), f"{name}.py", 1, 1, content, name, "text", "a" * 64)
              for i, (name, content) in enumerate([
                  ("a", "needle"), ("b", "middle"), ("c", "distant")])]
    snapshot = Snapshot("test", {}, chunks, [("a.py", "b.py"), ("b.py", "c.py")])
    lexical = search(snapshot, "needle", "bm25")
    graph = search(snapshot, "needle", "graph")
    assert [hit.chunk.path for hit in lexical] == ["a.py"]
    assert [hit.chunk.path for hit in graph] == ["a.py", "b.py"]
    assert graph[1].reasons == ("one-hop static dependency hint from a.py",)
    assert graph[1].score == pytest.approx(graph[0].score * 0.15)


def test_ties_are_stable_and_invalid_options_rejected():
    chunks = [Chunk(path, path, 1, 1, "needle", "s", "text", "a" * 64)
              for path in ["b.py", "a.py"]]
    snapshot = Snapshot("test", {}, chunks, [])
    assert [hit.chunk.path for hit in search(snapshot, "needle")] == ["a.py", "b.py"]
    assert len(search(snapshot, "needle", limit=1)) == 1
    assert search(snapshot, "needle", limit=0) == []
    with pytest.raises(ValueError):
        search(snapshot, "needle", method="made-up")
    with pytest.raises(ValueError):
        search(snapshot, "needle", limit=-1)
