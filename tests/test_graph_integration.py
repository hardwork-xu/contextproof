import json
import subprocess
import sys

from contextproof.mcp import Server


def source(root, rate):
    (root / "pricing.py").write_text(
        "from policy import tax_rate\n\ndef invoice_total(amount):\n"
        "    return amount * (1 + tax_rate())\n", encoding="utf-8")
    (root / "policy.py").write_text(f"def tax_rate():\n    return {rate}\n", encoding="utf-8")


def rpc(server, name, **arguments):
    return server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
        "name": name, "arguments": arguments}})["result"]


def initialized(root):
    server = Server(root)
    server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    return server


def test_mcp_persistent_handles_deliver_current_dependency_inside_budget(tmp_path):
    source(tmp_path, "0.10")
    captured = rpc(initialized(tmp_path), "contextproof_graph_capture",
                   query="invoice_total", budget=16000)
    before = json.loads(captured["content"][0]["text"])
    assert not captured["isError"]
    source(tmp_path, "0.25")
    # A new server process/session can resolve the persisted opaque handle.
    refreshed = rpc(initialized(tmp_path), "contextproof_graph_refresh",
                    handle=before["graph_id"], budget=16000)
    text = refreshed["content"][0]["text"]
    payload = json.loads(text)
    assert not refreshed["isError"]
    assert len(text.encode("utf-8")) <= 16000
    assert payload["base_graph_id"] == before["graph_id"]
    assert payload["requires_base"]
    assert "return 0.25" in text and "return 0.10" not in text
    assert payload["complete"]
    current = rpc(initialized(tmp_path), "contextproof_graph_refresh",
                  handle=payload["graph_id"], view="full", budget=16000)
    standalone = json.loads(current["content"][0]["text"])
    assert not standalone["requires_base"]
    assert "invoice_total" in current["content"][0]["text"]


def test_mcp_graph_tiny_budget_and_unknown_handle_are_errors(tmp_path):
    source(tmp_path, "0.10")
    server = initialized(tmp_path)
    assert rpc(server, "contextproof_graph_capture", query="invoice_total", budget=512)["isError"]
    assert rpc(server, "contextproof_graph_refresh", handle="0" * 64)["isError"]
    assert rpc(server, "contextproof_graph_refresh", handle="/" * 64)["isError"]
    server.close()


def test_mcp_reuses_memory_parses_but_keeps_graph_handles_persistent(tmp_path):
    source(tmp_path, "0.10")
    server = initialized(tmp_path)
    result = rpc(server, "contextproof_graph_capture", query="invoice_total", budget=16000)
    handle = json.loads(result["content"][0]["text"])["graph_id"]
    misses = server.graph_session.parsed.misses
    rpc(server, "contextproof_graph_refresh", handle=handle, view="full", budget=16000)
    assert server.graph_session.parsed.misses == misses
    assert server.graph_session.parsed.hits >= 2
    assert server.graph_session.parsed.store is None
    server.close()
    assert server.graph_session is None
    resumed = initialized(tmp_path)
    assert not rpc(resumed, "contextproof_graph_refresh", handle=handle, budget=16000)["isError"]
    resumed.close()


def test_cli_graph_refresh_and_lossless_delta(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    source(root, "0.10")

    def run(*arguments):
        return subprocess.run([sys.executable, "-m", "contextproof", *map(str, arguments)],
                              capture_output=True, text=True, timeout=30)

    base, after, delta, rebuilt = (tmp_path / name for name in ("base", "after", "delta", "rebuilt"))
    payload = tmp_path / "payload"
    result = run("graph-capture", root, "invoice_total", "--output", base, "--payload", payload)
    assert result.returncode == 0, result.stderr
    handle = json.loads(result.stdout)["graph_id"]
    source(root, "0.25")
    result = run("graph-refresh", root, handle, "--output", after, "--delta", delta,
                 "--payload", payload)
    assert result.returncode == 0, result.stderr
    assert "return 0.25" in payload.read_text() and "return 0.10" not in payload.read_text()
    assert payload.stat().st_size == json.loads(result.stdout)["delivery"]["consumed"]
    result = run("graph-apply", base, delta, "--output", rebuilt)
    assert result.returncode == 0, result.stderr
    assert json.loads(after.read_text()) == json.loads(rebuilt.read_text())
