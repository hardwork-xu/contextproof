"""Regressions from independent product-integration adversarial review."""

from copy import deepcopy

import pytest

from contextproof.dependencies import _digest as witness_digest
from contextproof.report import render_report
from contextproof.session import _wrap, capture_context, check_context


def review_context(root):
    (root / "app.py").write_text(
        "def invoice_safe():\n    return 1\n\n"
        "def invoice_risky(callback):\n    return callback()\n"
    )
    return capture_context(root, "invoice", budget=6000)


@pytest.mark.parametrize("alteration", ["omitted_entry", "different_anchor"])
def test_sidecar_must_cover_the_exact_source_entries(tmp_path, alteration):
    context = review_context(tmp_path)
    assert len(context["bundle"]["entries"]) == 2
    assert not check_context(context, tmp_path)["can_reuse"]
    sidecar = deepcopy(context["dependencies"])
    safe = next(entry for entry in sidecar["entries"] if entry["anchor"]["symbol"] == "invoice_safe")
    risky = next(entry for entry in sidecar["entries"] if entry["anchor"]["symbol"] == "invoice_risky")
    if alteration == "omitted_entry":
        sidecar["entries"] = [safe]
    else:
        risky["anchor"] = deepcopy(safe["anchor"])
        risky["anchor"]["id"] = risky["entry_id"]
        risky["references"] = []
    sidecar["id"] = witness_digest(sidecar)
    malformed = _wrap(context["bundle"], sidecar)
    # A checksum is not a signature: validate source/sidecar structural binding
    # even if an artifact producer recomputed all wrapper checksums.
    try:
        assessment = check_context(malformed, tmp_path)
    except ValueError:
        return
    assert not assessment["can_reuse"]


@pytest.mark.parametrize("field", ["consumed", "budget"])
def test_report_never_executes_malformed_numeric_fields(tmp_path, field):
    context = review_context(tmp_path)
    payload = '<script>alert("untrusted-receipt")</script>'
    context["bundle"][field] = payload
    malformed = _wrap(context["bundle"], context["dependencies"])
    try:
        assessment = check_context(malformed, tmp_path)
        html = render_report(malformed, assessment)
    except ValueError:
        return  # Rejecting malformed artifacts before rendering is also safe.
    assert payload not in html


@pytest.mark.parametrize("relocated", [False, True])
def test_different_scan_snapshots_never_allow_reuse_or_repair(tmp_path, monkeypatch, relocated):
    import contextproof.session as session

    source = "def invoice_total(value):\n    return value + 1\n"
    (tmp_path / "app.py").write_text(source)
    context = capture_context(tmp_path, "invoice_total", budget=6000)
    if relocated:
        (tmp_path / "app.py").write_text("# inserted\n" + source)
    baseline = check_context(context, tmp_path)
    assert baseline["can_repair"]
    assert baseline["can_reuse"] == (not relocated)
    original_verify = session.verify_witnesses

    def change_between_scans(witnesses, root):
        # An unrelated edit preserves both source text and direct dependencies,
        # but the two independent scans no longer attest to the same snapshot.
        (root / "unrelated.py").write_text("VALUE = 2\n")
        return original_verify(witnesses, root)

    monkeypatch.setattr(session, "verify_witnesses", change_between_scans)
    assessment = check_context(context, tmp_path)
    assert assessment["dependencies"]["fresh"]
    assert assessment["source"]["valid"] == (not relocated)
    assert not assessment["snapshot_consistent"]
    assert not assessment["can_reuse"]
    assert not assessment["can_repair"]
    assert assessment["recommendation"] not in {"reuse", "repair"}
