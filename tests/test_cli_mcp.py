import io
import json
import subprocess
import sys

from contextproof.evidence import render_bundle
from contextproof.mcp import Server, serve


def fixture_repo(tmp_path):
    (tmp_path / "pricing.py").write_text(
        "def discount(price, rate):\n    return price * (1 - rate)\n", encoding="utf-8")
    return tmp_path


def run_cli(*args):
    return subprocess.run([sys.executable, "-m", "contextproof", *map(str, args)],
                          capture_output=True, text=True, timeout=30)


def test_cli_bundle_verify_and_repair(tmp_path):
    root = fixture_repo(tmp_path)
    artifact = tmp_path / "saved.bundle"
    created = run_cli("bundle", root, "discount", "--budget", 10000, "-o", artifact)
    assert created.returncode == 0, created.stderr
    saved = json.loads(artifact.read_text())
    assert saved["entries"]
    assert str(root) not in artifact.read_text()
    assert run_cli("verify", root, artifact).returncode == 0
    (root / "pricing.py").write_text("def discount(price, rate):\n    return price\n")
    failed = run_cli("verify", root, artifact)
    assert failed.returncode == 1, failed.stderr
    repaired = run_cli("repair", root, artifact)
    assert repaired.returncode == 0, repaired.stderr
    assert json.loads(repaired.stdout)["invalidated"]


def test_cli_invalid_root_and_budget(tmp_path):
    result = run_cli("index", tmp_path / "missing")
    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    fixture_repo(tmp_path)
    result = run_cli("bundle", tmp_path, "discount", "--budget", "-1")
    assert result.returncode == 2


def rpc(method, request_id=1, **params):
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}


def test_mcp_lifecycle_and_bundle(tmp_path):
    server = Server(fixture_repo(tmp_path))
    assert "error" in server.handle(rpc("tools/list"))
    init = server.handle(rpc("initialize", protocolVersion="2025-11-25"))
    assert init["result"]["protocolVersion"] == "2025-11-25"
    assert len(server.handle(rpc("tools/list"))["result"]["tools"]) == 5
    result = server.handle(rpc("tools/call", name="contextproof_bundle",
                               arguments={"query": "discount", "budget": 10000}))
    assert not result["result"]["isError"]
    bundle = json.loads(result["result"]["content"][0]["text"])
    assert bundle["entries"]
    checked = server.handle(rpc("tools/call", name="contextproof_verify",
                                arguments={"bundle": bundle}))
    assert json.loads(checked["result"]["content"][0]["text"])["valid"]


def test_mcp_arguments_and_protocol_errors(tmp_path):
    server = Server(fixture_repo(tmp_path))
    server.handle(rpc("initialize", protocolVersion="unknown"))
    assert server.handle(rpc("missing"))["error"]["code"] == -32601
    for args in ({"query": "x", "root": "/"}, {"query": "x", "budget": True},
                 {"query": "x", "method": "invalid"}, {"query": ""}, [], {}):
        response = server.handle(rpc("tools/call", name="contextproof_bundle", arguments=args))
        assert response["result"]["isError"]
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert server.handle([])["error"]["code"] == -32600


def test_mcp_stdio_is_json_only(tmp_path):
    source = io.StringIO("bad json\n" + json.dumps(rpc("initialize")) + "\n" + json.dumps(
        {"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n" + json.dumps(
            rpc("ping", 2)) + "\n")
    sink = io.StringIO()
    serve(fixture_repo(tmp_path), stdin=source, stdout=sink)
    rows = [json.loads(line) for line in sink.getvalue().splitlines()]
    assert len(rows) == 3
    assert rows[0]["error"]["code"] == -32700
    assert rows[-1]["result"] == {}


def test_cli_render_matches_budget_exactly(tmp_path):
    root = fixture_repo(tmp_path)
    artifact = tmp_path / "saved.bundle"
    created = run_cli("bundle", root, "discount", "--budget", 10000, "-o", artifact)
    assert created.returncode == 0
    bundle = json.loads(artifact.read_text())
    rendered = run_cli("render", artifact)
    assert rendered.stdout == render_bundle(bundle)
    assert len(rendered.stdout.encode()) == bundle["consumed"]
    output = tmp_path / "rendered.output"
    assert run_cli("render", artifact, "-o", output).returncode == 0
    assert output.read_bytes() == rendered.stdout.encode()


def test_mcp_rejects_nonfinite_json_without_crashing(tmp_path):
    source = io.StringIO('{"jsonrpc":"2.0","id":NaN,"method":"ping"}\n'
                        + json.dumps(rpc("ping", 2)) + "\n")
    sink = io.StringIO()
    serve(fixture_repo(tmp_path), stdin=source, stdout=sink)
    rows = [json.loads(line) for line in sink.getvalue().splitlines()]
    assert rows[0]["error"]["code"] == -32700
    assert rows[1]["result"] == {}
    server = Server(tmp_path)
    for invalid_id in (True, None, 1.5, [], {}):
        assert server.handle(rpc("ping", invalid_id))["error"]["code"] == -32600


def test_corrupt_cache_returns_actionable_error(tmp_path):
    fixture_repo(tmp_path)
    (tmp_path / ".contextproof").mkdir()
    (tmp_path / ".contextproof" / "index.sqlite3").write_text("broken cache")
    result = run_cli("index", tmp_path)
    assert result.returncode == 2
    assert "cache error" in result.stderr
    assert "Traceback" not in result.stderr
    server = Server(tmp_path)
    server.handle(rpc("initialize"))
    response = server.handle(rpc("tools/call", name="contextproof_index"))
    assert response["result"]["isError"]
    assert "cache error" in response["result"]["content"][0]["text"]
    assert server.handle(rpc("ping"))["result"] == {}
