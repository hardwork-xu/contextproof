from copy import deepcopy
import hashlib

import pytest

from contextproof.graph import build_graph, canonical_graph_bytes
from contextproof.graph_delta import _digest, apply_graph_delta, canonical, make_graph_delta
from contextproof.graph_session import GraphSession


def example(value=1, prefix=""):
    text = "def caller():\n    return helper()\n"
    source = prefix + text + f"\ndef helper():\n    return {value}\n"
    anchor = {"id": "saved-caller", "path": "app.py", "symbol": "caller", "kind": "function",
              "start_line": 1, "end_line": 2, "text": text,
              "text_sha256": hashlib.sha256(text.encode()).hexdigest()}
    return build_graph({"app.py": source}, hashlib.sha256(source.encode()).hexdigest(), [anchor])


def test_delta_reconstructs_exact_graph_and_does_not_mutate_base():
    before, after = example(), example(2)
    original = canonical_graph_bytes(before)
    delta = make_graph_delta(before, after)
    assert canonical_graph_bytes(apply_graph_delta(before, delta)) == canonical_graph_bytes(after)
    assert canonical_graph_bytes(before) == original


def test_coordinate_only_patch_does_not_retransmit_source():
    before, after = example(), example(prefix="# new header\n")
    delta = make_graph_delta(before, after)
    assert not delta["nodes"]["add"]
    assert all("text" not in change["set"] for change in delta["nodes"]["patch"].values())
    assert len(canonical(delta)) < len(canonical_graph_bytes(after))
    assert apply_graph_delta(before, delta) == after


def test_delta_binds_both_base_and_target():
    delta = make_graph_delta(example(), example(2))
    with pytest.raises(ValueError, match="base"):
        apply_graph_delta(example(3), delta)
    broken = deepcopy(delta)
    broken["target_id"] = "0" * 64
    broken["id"] = _digest(broken)
    with pytest.raises(ValueError, match="integrity"):
        apply_graph_delta(example(), broken)


def test_forged_patch_cannot_create_dangling_graph():
    delta = make_graph_delta(example(), example(2))
    broken = deepcopy(delta)
    broken["nodes"]["remove"] = [*example()["nodes"]]
    broken["id"] = _digest(broken)
    with pytest.raises(ValueError):
        apply_graph_delta(example(), broken)


def test_full_and_incremental_parsing_agree_under_changes(tmp_path):
    from contextproof.graph_session import graph_anchors
    from contextproof.revisions import read_worktree
    (tmp_path / "app.py").write_text("def invoice_total(x):\n    return helper(x)\n\ndef helper(x):\n    return x\n")
    (tmp_path / "other.py").write_text("UNCHANGED = 1\n")
    with GraphSession(tmp_path) as session:
        saved = session.capture("invoice_total")["graph"]
        assert session.parsed.misses == 2
        for step in range(12):
            path = tmp_path / ("other.py" if step % 3 else "app.py")
            path.write_text(path.read_text() + "\n# edit " + str(step) + "\n")
            revision = read_worktree(tmp_path)
            full = build_graph(revision.texts, revision.snapshot_id, graph_anchors(saved))
            incremental = session.refresh(saved)["graph"]
            assert canonical_graph_bytes(full) == canonical_graph_bytes(incremental)
            saved = incremental
        assert session.parsed.hits >= 12


def test_session_refresh_delivers_dependency_source_not_just_caller(tmp_path):
    (tmp_path / "checkout.py").write_text("from pricing import tax_rate\n\ndef invoice_total(x):\n    return x * tax_rate()\n")
    (tmp_path / "pricing.py").write_text("def tax_rate():\n    return 0.05\n")
    with GraphSession(tmp_path) as session:
        captured = session.capture("invoice_total")
        assert "0.05" in captured["payload"]["rendered"]
        (tmp_path / "pricing.py").write_text("def tax_rate():\n    return 0.20\n")
        refreshed = session.refresh(captured["graph"]["id"])
        assert "0.20" in refreshed["payload"]["rendered"]
        assert "0.05" not in refreshed["payload"]["rendered"]
        assert not refreshed["comparison"]["fresh"]
        assert apply_graph_delta(captured["graph"], refreshed["delta"]) == refreshed["graph"]
