from copy import deepcopy
import json
import subprocess
import sys

import pytest

from contextproof.evidence import render_bundle
from contextproof.report import render_report
from contextproof.session import capture_context, check_context, refresh_context, validate_context


def repo(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "policy.py").write_text("def tax_rate():\n    return 0.10\n")
    (tmp_path / "checkout.py").write_text(
        "from policy import tax_rate\n\ndef invoice_total(amount):\n"
        "    return amount * (1 + tax_rate())\n")
    return tmp_path


def test_dependency_edit_triggers_refresh_while_source_is_valid(tmp_path):
    root = repo(tmp_path)
    context = capture_context(root, "invoice_total", budget=6000)
    assert check_context(context, root)["can_reuse"]
    (root / "policy.py").write_text("def tax_rate():\n    return 0.12\n")
    changed = check_context(context, root)
    assert changed["source"]["valid"]
    assert not changed["dependencies"]["fresh"]
    assert changed["recommendation"] == "retrieve"
    updated = refresh_context(context, root)
    assert updated["refresh_receipt"]["operation"] == "retrieved"
    assert check_context(updated, root)["can_reuse"]
    assert updated["dependencies"]["id"] != context["dependencies"]["id"]
    assert len(render_bundle(updated["bundle"]).encode()) <= 6000


def test_unchanged_and_relocated_context(tmp_path):
    root = repo(tmp_path)
    context = capture_context(root, "invoice_total", budget=6000)
    (root / "checkout.py").write_text("# insertion\n" + (root / "checkout.py").read_text())
    checked = check_context(context, root)
    assert not checked["can_reuse"]
    updated = refresh_context(context, root)
    assert check_context(updated, root)["can_reuse"]
    assert updated["id"] != context["id"]


def test_context_checksum_and_cross_binding(tmp_path):
    context = capture_context(repo(tmp_path), "invoice_total", budget=6000)
    bad = deepcopy(context)
    bad["dependencies"]["bundle_id"] = "wrong"
    with pytest.raises(ValueError, match="integrity"):
        validate_context(bad)
    with pytest.raises(ValueError):
        validate_context({"schema_version": 1, "kind": "another"})


def test_empty_context_never_reusable(tmp_path):
    context = capture_context(repo(tmp_path), "zzzznonexistent", budget=4000)
    assert not context["bundle"]["entries"]
    assert context["dependencies"] is None
    assert not check_context(context, tmp_path)["can_reuse"]


def test_unresolved_context_stays_explicit(tmp_path):
    (tmp_path / "app.py").write_text(
        "from mystery import normalize\n\ndef invoice_total(amount):\n"
        "    return normalize(amount)\n")
    context = capture_context(tmp_path, "invoice_total", budget=6000)
    report = check_context(context, tmp_path)
    assert not report["can_reuse"]
    assert report["recommendation"] == "review"
    assert not check_context(refresh_context(context, tmp_path), tmp_path)["can_reuse"]


def test_report_escapes_source_and_query(tmp_path):
    (tmp_path / "app.py").write_text(
        "def invoice_total():\n    return '<script>alert(1)</script>'\n")
    context = capture_context(tmp_path, "invoice_total <script>alert(2)</script>", budget=6000)
    output = render_report(context, check_context(context, tmp_path))
    assert "<script>alert(1)</script>" not in output
    assert "<script>alert(2)</script>" not in output
    assert "&lt;script&gt;" in output
    assert "Content-Security-Policy" in output
    with pytest.raises(ValueError):
        render_report(context, {"context_id": "wrong"})


def test_cli_complete_context_flow(tmp_path):
    root = repo(tmp_path / "repo")
    output = tmp_path / "context.json"

    def run(*args):
        return subprocess.run([sys.executable, "-m", "contextproof", *map(str, args)],
                              capture_output=True, text=True, timeout=30)

    assert run("capture", root, "invoice_total", "--budget", 6000, "-o", output).returncode == 0
    assert run("check", root, output).returncode == 0
    (root / "policy.py").write_text("def tax_rate():\n    return 0.12\n")
    assert run("check", root, output).returncode == 1
    report = tmp_path / "report.html"
    assert run("report", root, output, "-o", report).returncode == 0
    assert "changed" in report.read_text()
    updated = tmp_path / "updated.json"
    result = run("refresh", root, output, "-o", updated)
    assert result.returncode == 0, result.stderr
    assert run("check", root, updated).returncode == 0
    rendered = run("render", updated)
    assert len(rendered.stdout.encode()) == json.loads(updated.read_text())["bundle"]["consumed"]
