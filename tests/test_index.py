"""Behavioral checks for cache correctness, source fidelity, and safe scanning."""

import hashlib
import json
import os
from pathlib import Path
import sqlite3

import pytest

from contextproof.index import (
    MAX_CHUNK_LINES, build_index, iter_source_files, read_source_bytes, source_lines,
)


def put(root: Path, name: str, source: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def test_ast_scopes_include_decorators_and_exact_source(tmp_path):
    source = (
        "import functools\n\n"
        "@functools.lru_cache()\n"
        "def answer(value):\n"
        "    return value + 1\n\n"
        "class Engine:\n"
        "    @staticmethod\n"
        "    def run():\n"
        "        return answer(41)\n"
    )
    put(tmp_path, "engine.py", source)
    snapshot = build_index(tmp_path)
    answer = next(c for c in snapshot.chunks if c.symbol == "answer")
    method = next(c for c in snapshot.chunks if c.symbol == "Engine.run")
    assert (answer.start_line, answer.end_line) == (3, 5)
    assert answer.text.startswith("@functools.lru_cache()\n")
    assert method.start_line == 8
    assert method.text.startswith("    @staticmethod\n")
    for chunk in snapshot.chunks:
        assert chunk.text == "".join(source.splitlines(keepends=True)[
            chunk.start_line - 1:chunk.end_line
        ])
        assert chunk.file_sha256 == hashlib.sha256(source.encode()).hexdigest()


def test_large_symbols_are_bounded_and_keep_all_nonblank_source(tmp_path):
    source = "def lengthy():\n" + "".join(f"    value_{i} = {i}\n" for i in range(205))
    put(tmp_path, "large.py", source)
    chunks = build_index(tmp_path).chunks
    assert len(chunks) == 3
    assert all(c.symbol == "lengthy" for c in chunks)
    assert all(c.end_line - c.start_line + 1 <= MAX_CHUNK_LINES for c in chunks)
    assert "".join(c.text for c in chunks) == source


def test_warm_cache_reuses_parsing_but_reads_and_hashes_content(tmp_path):
    path = put(tmp_path, "module.py", "def alpha():\n    return 1\n")
    cold = build_index(tmp_path)
    warm = build_index(tmp_path)
    assert warm.id == cold.id
    assert warm.chunks == cold.chunks
    assert warm.stats == {"files": 1, "parsed": 0, "reused": 1, "chunks": len(warm.chunks)}
    old_stat = path.stat()
    path.write_text("def alpha():\n    return 2\n")  # Same size, and restore mtime too.
    os.utime(path, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
    changed = build_index(tmp_path)
    assert changed.id != cold.id
    assert changed.stats["parsed"] == 1
    assert changed.stats["reused"] == 0
    assert "return 2" in changed.chunks[0].text


def test_add_delete_move_remove_stale_cache_rows_and_edges(tmp_path):
    put(tmp_path, "consumer.py", "from provider import result\nanswer = result()\n")
    provider = put(tmp_path, "provider.py", "def result():\n    return 42\n")
    initial = build_index(tmp_path)
    assert ("consumer.py", "provider.py") in initial.edges
    provider.rename(tmp_path / "replacement.py")
    moved = build_index(tmp_path)
    assert moved.id != initial.id
    assert "provider.py" not in moved.files
    assert all("provider.py" not in edge for edge in moved.edges)
    assert moved.stats["parsed"] == 1 and moved.stats["reused"] == 1
    (tmp_path / "replacement.py").unlink()
    deleted = build_index(tmp_path)
    assert deleted.edges == []
    assert all(c.path != "replacement.py" for c in deleted.chunks)
    with sqlite3.connect(tmp_path / ".contextproof/index.sqlite3") as connection:
        assert connection.execute("SELECT path FROM contextproof_files").fetchall() == [
            ("consumer.py",)
        ]
    put(tmp_path, "new.py", "x = 1\n")
    added = build_index(tmp_path)
    assert added.stats["parsed"] == 1 and added.stats["reused"] == 1


def test_dependency_graph_is_rebuilt_when_name_becomes_ambiguous(tmp_path):
    put(tmp_path, "caller.py", "answer = compute()\n")
    put(tmp_path, "first.py", "def compute():\n    return 1\n")
    first = build_index(tmp_path)
    assert first.edges == [("caller.py", "first.py")]
    put(tmp_path, "second.py", "def compute():\n    return 2\n")
    second = build_index(tmp_path)
    assert second.edges == []
    assert second.stats["reused"] == 2


def test_absolute_relative_and_src_layout_imports(tmp_path):
    put(tmp_path, "src/pkg/__init__.py", "from .worker import execute\n")
    put(tmp_path, "src/pkg/worker.py", "from . import constants\nanswer = constants.VALUE\n")
    put(tmp_path, "src/pkg/constants.py", "VALUE = 42\n")
    put(tmp_path, "entry.py", "import pkg.worker\n")
    edges = build_index(tmp_path).edges
    assert ("entry.py", "src/pkg/worker.py") in edges
    assert ("src/pkg/__init__.py", "src/pkg/worker.py") in edges
    assert ("src/pkg/worker.py", "src/pkg/constants.py") in edges


def test_fallback_and_crlf_source_are_exact(tmp_path):
    raw = b"def broken(:\r\n    ??\r\n"
    (tmp_path / "broken.py").write_bytes(raw)
    put(tmp_path, "notes.md", "# Notes\n\nA useful explanation.\n")
    snapshot = build_index(tmp_path)
    broken = next(c for c in snapshot.chunks if c.path == "broken.py")
    assert broken.kind == "text"
    assert broken.text.encode() == raw
    assert broken.end_line == 2
    assert next(c for c in snapshot.chunks if c.path == "notes.md").kind == "text"


def test_excludes_secrets_generated_vendor_binary_and_symlinks(tmp_path):
    root = tmp_path / "repository"
    root.mkdir()
    put(root, "main.py", "print('safe')\n")
    for name in (
        ".env", ".env.local", "credentials.json", "gcloud_credentials.json", "secrets.py",
        "private.key", ".git/config.py", "vendor/internal.py", "node_modules/pkg/index.js",
        ".contextproof/leak.txt", "build/output.py", "generated/output.py", "bundle.min.js",
        "work/downloaded.py", ".aws/config.json", "package-lock.json", "client_secret.json",
    ):
        put(root, name, "secret = 'excluded'\n")
    put(root, "hidden_key.txt", "-----BEGIN OPENSSH PRIVATE KEY-----\nsecret\n")
    put(root, "generated_header.py", "# Automatically generated; do not edit\nx = 1\n")
    (root / "binary.py").write_bytes(b"x\x00y")
    (root / "invalid.txt").write_bytes(b"\xff\xfe")
    outside = put(tmp_path, "outside.py", "SECRET = 'outside'\n")
    (root / "linked.py").symlink_to(outside)
    outside_dir = tmp_path / "external"
    put(outside_dir, "leak.py", "SECRET = 'outside'\n")
    (root / "linked_dir").symlink_to(outside_dir, target_is_directory=True)
    snapshot = build_index(root)
    assert list(snapshot.files) == ["main.py"]
    assert "linked.py" not in {p.name for p in iter_source_files(root)}
    assert read_source_bytes(root, Path("../outside.py")) is None
    assert read_source_bytes(root, outside) is None
    assert read_source_bytes(root, root / "linked.py") is None
    assert read_source_bytes(root, Path("linked_dir/leak.py")) is None
    assert read_source_bytes(root, Path("credentials.json")) is None
    assert read_source_bytes(root, Path("hidden_key.txt")) is None
    assert read_source_bytes(root, Path("main.py")) == b"print('safe')\n"


def test_snapshot_is_independent_of_creation_order_location_and_cache(tmp_path):
    left, right = tmp_path / "left", tmp_path / "right"
    put(left, "b.py", "def beta():\n    return 2\n")
    put(left, "a.py", "from b import beta\nvalue = beta()\n")
    put(right, "a.py", "from b import beta\nvalue = beta()\n")
    put(right, "b.py", "def beta():\n    return 2\n")
    first, second = build_index(left), build_index(right, right / "cache.sqlite3")
    assert first.id == second.id
    assert first.files == second.files
    assert first.chunks == second.chunks
    assert first.edges == second.edges


def test_rejects_symlink_cache_and_root(tmp_path):
    repository = tmp_path / "repo"
    repository.mkdir()
    destination = tmp_path / "outside"
    destination.mkdir()
    (repository / ".contextproof").symlink_to(destination, target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic links"):
        build_index(repository)
    root_link = tmp_path / "root_link"
    root_link.symlink_to(repository, target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic link"):
        build_index(root_link)
    assert not list(destination.iterdir())


def test_newly_excluded_file_is_removed_from_cache(tmp_path):
    path = put(tmp_path, "config.py", "VALUE = 1\n")
    assert "config.py" in build_index(tmp_path).files
    path.write_text("# do not edit: generated\nVALUE = 2\n")
    snapshot = build_index(tmp_path)
    assert snapshot.files == {} and snapshot.chunks == []
    with sqlite3.connect(tmp_path / ".contextproof/index.sqlite3") as connection:
        assert connection.execute("SELECT count(*) FROM contextproof_files").fetchone() == (0,)


def test_cache_version_change_reparses_and_changes_snapshot(tmp_path, monkeypatch):
    import contextproof.index as index

    put(tmp_path, "example.py", "answer = 42\n")
    original = build_index(tmp_path)
    monkeypatch.setattr(index, "SCHEMA_VERSION", index.SCHEMA_VERSION + 1)
    updated = build_index(tmp_path)
    assert updated.id != original.id
    assert updated.stats["parsed"] == 1 and updated.stats["reused"] == 0


def test_cache_cannot_substitute_text_not_in_hashed_source(tmp_path):
    put(tmp_path, "example.py", "answer = 42\n")
    original = build_index(tmp_path)
    with sqlite3.connect(tmp_path / ".contextproof/index.sqlite3") as connection:
        cached = json.loads(connection.execute("SELECT chunks FROM contextproof_files").fetchone()[0])
        cached[0]["text"] = "answer = 'forged cache content'\n"
        connection.execute("UPDATE contextproof_files SET chunks = ?", (json.dumps(cached),))
    recovered = build_index(tmp_path)
    assert recovered.id == original.id and recovered.chunks == original.chunks
    assert recovered.stats["parsed"] == 1


def test_file_changed_during_read_is_rejected(tmp_path, monkeypatch):
    import contextproof.index as index

    path = put(tmp_path, "changing.py", "answer = 42\n")
    original_read = os.read
    changed = False

    def mutate_once(fd, count):
        nonlocal changed
        block = original_read(fd, count)
        if not changed:
            changed = True
            path.write_text("answer = 43\n")
        return block

    monkeypatch.setattr(index.os, "read", mutate_once)
    assert read_source_bytes(tmp_path, path) is None


def test_symlink_sqlite_sidecar_is_rejected(tmp_path):
    cache = tmp_path / ".contextproof"
    cache.mkdir()
    outside = put(tmp_path, "other.txt", "leave intact\n")
    (cache / "index.sqlite3-journal").symlink_to(outside)
    with pytest.raises(ValueError, match="symbolic links"):
        build_index(tmp_path)
    assert outside.read_text() == "leave intact\n"


@pytest.mark.parametrize("separator", ["\u2028", "\u2029", "\x85", "\x0b", "\x0c"])
def test_unicode_and_control_separators_do_not_shift_ast_lines(tmp_path, separator):
    source = f'header = "one{separator}two"\ndef needle():\n    return 1\n'
    put(tmp_path, "example.py", source)
    cold = build_index(tmp_path)
    chunk = next(c for c in cold.chunks if c.symbol == "needle")
    assert (chunk.start_line, chunk.end_line) == (2, 3)
    assert chunk.text == "def needle():\n    return 1\n"
    module = next(c for c in cold.chunks if c.symbol == "<module>")
    assert module.text == f'header = "one{separator}two"\n'
    assert build_index(tmp_path).chunks == cold.chunks


@pytest.mark.parametrize("newline", ["\r", "\n", "\r\n"])
def test_source_lines_preserves_python_newline_conventions(newline):
    assert source_lines("") == []
    assert source_lines(f"one{newline}{newline}two") == [f"one{newline}", newline, "two"]
    assert source_lines(f"one{newline}") == [f"one{newline}"]


def test_deep_valid_expression_does_not_exhaust_ast_traversal(tmp_path):
    source = "value = " + "+".join("1" for _ in range(1500)) + "\n"
    put(tmp_path, "expression.py", source)
    snapshot = build_index(tmp_path)
    assert snapshot.stats["files"] == 1
    assert "".join(chunk.text for chunk in snapshot.chunks) == source
