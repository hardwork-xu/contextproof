from copy import deepcopy

import pytest

from benchmarks.dependency_cases import CASES
from contextproof.dependencies import _digest, capture_witnesses, verify_witnesses
from contextproof.evidence import _seal, make_bundle, sha256, verify_bundle
from contextproof.index import build_index


def make_subject(root, files, path="app.py", symbol="subject"):
    for relative, source in files.items():
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(source, encoding="utf-8")
    bundle = make_bundle(build_index(root), symbol, budget=1000000, method="bm25")
    bundle["entries"] = [entry for entry in bundle["entries"]
                         if entry["path"] == path and entry["symbol"] == symbol]
    assert bundle["entries"], (path, symbol)
    _seal(bundle)
    return bundle


def mutate(root, changes):
    for path, text in changes.items():
        destination = root / path
        if text is None:
            destination.unlink()
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(text, encoding="utf-8")


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_independently_specified_cases(tmp_path, case):
    bundle = make_subject(tmp_path, case.before, case.path, case.symbol)
    witnesses = capture_witnesses(bundle, tmp_path)
    mutate(tmp_path, case.after)
    report = verify_witnesses(witnesses, tmp_path)
    assert report["status"] == case.expected, report
    assert report["fresh"] == (case.expected == "unchanged")


def test_text_identity_and_dependency_freshness_are_independent(tmp_path):
    bundle = make_subject(tmp_path, {"app.py": "from helpers import helper\ndef subject():\n    return helper()\n",
                                     "helpers.py": "def helper():\n    return 1\n"})
    witnesses = capture_witnesses(bundle, tmp_path)
    mutate(tmp_path, {"helpers.py": "def helper():\n    return 2\n"})
    assert verify_bundle(bundle, tmp_path)["valid"]
    report = verify_witnesses(witnesses, tmp_path)
    assert not report["fresh"]
    assert report["results"][0]["references"][0]["status"] == "changed"


def test_binding_changes_even_if_target_text_is_identical(tmp_path):
    files = {"app.py": "from helpers import helper\ndef subject():\n    return helper()\n",
             "helpers.py": "def helper():\n    return 1\n",
             "alternate.py": "def helper():\n    return 1\n"}
    bundle = make_subject(tmp_path, files)
    witnesses = capture_witnesses(bundle, tmp_path)
    mutate(tmp_path, {"app.py": files["app.py"].replace("from helpers", "from alternate")})
    report = verify_witnesses(witnesses, tmp_path)
    assert report["status"] == "changed"
    assert verify_bundle(bundle, tmp_path)["valid"]


def test_snapshot_required_at_capture(tmp_path):
    bundle = make_subject(tmp_path, {"app.py": "def subject():\n    return 1\n"})
    mutate(tmp_path, {"other.py": "VALUE = 2\n"})
    with pytest.raises(ValueError, match="exact current source snapshot"):
        capture_witnesses(bundle, tmp_path)


def test_capture_and_verify_deterministic(tmp_path):
    bundle = make_subject(tmp_path, {"app.py": "LIMIT = 3\ndef subject():\n    return LIMIT\n"})
    first = capture_witnesses(bundle, tmp_path)
    assert first == capture_witnesses(bundle, tmp_path)
    assert verify_witnesses(first, tmp_path) == verify_witnesses(first, tmp_path)
    assert first["bundle_id"] == bundle["id"]
    assert first["snapshot_id"] == bundle["snapshot_id"]


@pytest.mark.parametrize("field,value", [("bundle_id", "0" * 64), ("scope", "runtime-complete"),
                                          ("entries", []), ("snapshot_id", "1" * 64)])
def test_tampered_sidecar_is_invalid(tmp_path, field, value):
    bundle = make_subject(tmp_path, {"app.py": "def subject():\n    return 1\n"})
    witnesses = capture_witnesses(bundle, tmp_path)
    witnesses[field] = value
    assert verify_witnesses(witnesses, tmp_path)["status"] == "invalid"


def test_resealed_malformed_record_is_invalid(tmp_path):
    bundle = make_subject(tmp_path, {"app.py": "LIMIT = 3\ndef subject():\n    return LIMIT\n"})
    witnesses = capture_witnesses(bundle, tmp_path)
    for key, value in [("path", "../outside.py"), ("end_line", 999),
                       ("text", "faked source"), ("start_line", True)]:
        altered = deepcopy(witnesses)
        altered["entries"][0]["references"][0]["target"][key] = value
        altered["id"] = _digest(altered)
        assert verify_witnesses(altered, tmp_path)["status"] == "invalid"


def test_dependency_symlink_rejected(tmp_path):
    bundle = make_subject(tmp_path, {"app.py": "from helpers import helper\ndef subject():\n    return helper()\n",
                                     "helpers.py": "def helper():\n    return 1\n"})
    witnesses = capture_witnesses(bundle, tmp_path)
    original = tmp_path / "helpers.py"
    original.rename(tmp_path / "safe_copy.py")
    original.symlink_to(tmp_path / "safe_copy.py")
    assert verify_witnesses(witnesses, tmp_path)["status"] == "invalid"


def test_content_policy_rejected(tmp_path):
    bundle = make_subject(tmp_path, {"app.py": "from helpers import helper\ndef subject():\n    return helper()\n",
                                     "helpers.py": "def helper():\n    return 1\n"})
    witnesses = capture_witnesses(bundle, tmp_path)
    mutate(tmp_path, {"helpers.py": "# do not edit\ndef helper():\n    return 1\n"})
    assert verify_witnesses(witnesses, tmp_path)["status"] == "invalid"


def test_source_spans_preserve_crlf_and_unicode_line_separator(tmp_path):
    source = 'LABEL = "a\u2028b"\r\ndef subject():\r\n    return LABEL\r\n'
    (tmp_path / "app.py").write_bytes(source.encode())
    bundle = make_bundle(build_index(tmp_path), "subject", budget=1000000)
    bundle["entries"] = [entry for entry in bundle["entries"] if entry["symbol"] == "subject"]
    _seal(bundle)
    witnesses = capture_witnesses(bundle, tmp_path)
    target = witnesses["entries"][0]["references"][0]["target"]
    assert target["text"] == 'LABEL = "a\u2028b"\r\n'
    assert target["end_line"] == 1
    assert target["text_sha256"] == sha256(target["text"])
    assert verify_witnesses(witnesses, tmp_path)["fresh"]


def test_unresolved_capture_remains_unresolved_after_resolvable_edit(tmp_path):
    bundle = make_subject(tmp_path, {"app.py": "from helpers import helper\ndef subject():\n    return helper()\n"})
    witnesses = capture_witnesses(bundle, tmp_path)
    mutate(tmp_path, {"helpers.py": "def helper():\n    return 1\n"})
    assert verify_witnesses(witnesses, tmp_path)["status"] == "unresolved"


def test_one_source_scan_per_operation(tmp_path, monkeypatch):
    import contextproof.dependencies as dependencies

    bundle = make_subject(tmp_path, {"app.py": "LIMIT = 3\ndef subject():\n    return LIMIT\n"})
    original = dependencies.iter_source_files
    calls = []

    def counted(root):
        calls.append(root)
        yield from original(root)

    monkeypatch.setattr(dependencies, "iter_source_files", counted)
    witnesses = capture_witnesses(bundle, tmp_path)
    assert len(calls) == 1
    verify_witnesses(witnesses, tmp_path)
    assert len(calls) == 2


def test_unsupported_language_is_unresolved(tmp_path):
    bundle = make_subject(tmp_path, {"app.js": "function subject() { return helper(); }\n"},
                          "app.js", "<text>")
    witnesses = capture_witnesses(bundle, tmp_path)
    assert verify_witnesses(witnesses, tmp_path)["status"] == "unresolved"


def test_default_argument_resolves_outside_parameter_scope(tmp_path):
    bundle = make_subject(tmp_path, {"app.py": "LIMIT = 3\ndef subject(LIMIT=LIMIT):\n    return LIMIT\n"})
    witnesses = capture_witnesses(bundle, tmp_path)
    assert witnesses["entries"][0]["references"][0]["target"]["symbol"] == "LIMIT"
    mutate(tmp_path, {"app.py": "LIMIT = 4\ndef subject(LIMIT=LIMIT):\n    return LIMIT\n"})
    assert verify_witnesses(witnesses, tmp_path)["status"] == "changed"


def test_closure_does_not_fall_back_to_same_named_global(tmp_path):
    source = "VALUE = 1\ndef outer(VALUE):\n    def subject():\n        return VALUE\n    return subject\n"
    bundle = make_subject(tmp_path, {"app.py": source}, symbol="outer.subject")
    witnesses = capture_witnesses(bundle, tmp_path)
    assert verify_witnesses(witnesses, tmp_path)["status"] == "unresolved"


def test_comprehension_binding_is_not_mistaken_for_an_ordinary_local(tmp_path):
    source = "VALUE = 1\ndef subject():\n    return VALUE, [VALUE for VALUE in (1, 2)]\n"
    bundle = make_subject(tmp_path, {"app.py": source})
    assert verify_witnesses(capture_witnesses(bundle, tmp_path), tmp_path)["status"] == "unresolved"


def test_nested_assignment_does_not_hide_outer_global_reference(tmp_path):
    source = "VALUE = 1\ndef subject():\n    def inner():\n        VALUE = 9\n        return VALUE\n    return VALUE\n"
    bundle = make_subject(tmp_path, {"app.py": source})
    witnesses = capture_witnesses(bundle, tmp_path)
    mutate(tmp_path, {"app.py": source.replace("VALUE = 1", "VALUE = 2")})
    assert verify_witnesses(witnesses, tmp_path)["status"] == "changed"


def test_deep_valid_ast_never_uses_recursive_traversal(tmp_path):
    source = "LIMIT = 1\ndef subject():\n    return " + " + ".join(["LIMIT"] * 1500) + "\n"
    bundle = make_subject(tmp_path, {"app.py": source})
    witnesses = capture_witnesses(bundle, tmp_path)
    assert verify_witnesses(witnesses, tmp_path)["fresh"]
    mutate(tmp_path, {"app.py": source.replace("LIMIT = 1", "LIMIT = 2")})
    assert verify_witnesses(witnesses, tmp_path)["status"] == "changed"


def test_deep_dynamic_expression_fails_closed(tmp_path):
    source = "def subject():\n    return (" + " + ".join(["1"] * 1500) + ")()\n"
    bundle = make_subject(tmp_path, {"app.py": source})
    witnesses = capture_witnesses(bundle, tmp_path)
    assert verify_witnesses(witnesses, tmp_path)["status"] == "unresolved"


def test_dependency_import_chain_has_a_resolution_limit(tmp_path):
    files = {"app.py": "from m0 import helper\ndef subject():\n    return helper()\n"}
    files.update({f"m{i}.py": f"from m{i + 1} import helper\n" for i in range(135)})
    files["m135.py"] = "def helper():\n    return 1\n"
    bundle = make_subject(tmp_path, files)
    witnesses = capture_witnesses(bundle, tmp_path)
    assert verify_witnesses(witnesses, tmp_path)["status"] == "unresolved"


def test_resealed_missing_resolution_reason_is_invalid(tmp_path):
    bundle = make_subject(tmp_path, {"app.py": "def subject(callback):\n    return callback()\n"})
    witnesses = capture_witnesses(bundle, tmp_path)
    del witnesses["entries"][0]["references"][0]["reason"]
    witnesses["id"] = _digest(witnesses)
    assert verify_witnesses(witnesses, tmp_path)["status"] == "invalid"


def test_import_binding_symlink_is_invalid_even_when_final_target_is_safe(tmp_path):
    files = {"app.py": "from exports import helper\ndef subject():\n    return helper()\n",
             "exports.py": "from helpers import helper\n",
             "helpers.py": "def helper():\n    return 1\n"}
    bundle = make_subject(tmp_path, files)
    witnesses = capture_witnesses(bundle, tmp_path)
    (tmp_path / "exports.py").rename(tmp_path / "exports_copy.py")
    (tmp_path / "exports.py").symlink_to(tmp_path / "exports_copy.py")
    assert verify_witnesses(witnesses, tmp_path)["status"] == "invalid"
