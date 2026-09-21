import ast
import os
import shutil
import subprocess

import pytest

from contextproof.parse_cache import ParseCache
from contextproof.revisions import SourceStore, read_git_revision, read_worktree


@pytest.fixture
def git_repo(tmp_path):
    binary = os.environ.get("CONTEXTPROOF_GIT") or shutil.which("git")
    if not binary:
        pytest.skip("Git unavailable")
    def git(*args):
        process = subprocess.run([binary, "-C", str(tmp_path), *args], capture_output=True)
        if process.returncode:
            raise RuntimeError(process.stderr.decode())
        return process.stdout.decode().strip()
    git("init", "-q")
    git("config", "user.name", "ContextProof test")
    git("config", "user.email", "test@example.invalid")
    (tmp_path / "a.py").write_text("def value():\n    return 1\n")
    (tmp_path / "keep.py").write_text("KEEP = 42\n")
    git("add", ".")
    git("commit", "-qm", "first")
    return tmp_path, git, binary


def test_git_source_is_immutable_and_blob_cache_reuses_unchanged_files(git_repo):
    root, git, binary = git_repo
    first = git("rev-parse", "HEAD")
    with SourceStore(root / ".contextproof/revisions.sqlite") as store:
        before = read_git_revision(root, first, store, binary)
        assert before.stats["blob_reads"] == 2
        (root / "a.py").write_text("def value():\n    return 2\n")
        assert read_git_revision(root, first, store, binary).texts == before.texts
        git("add", "a.py")
        git("commit", "-qm", "second")
        after = read_git_revision(root, "HEAD", store, binary)
        assert after.stats["blob_reads"] == 1
        assert after.stats["blob_cache_hits"] == 1
        assert after.texts["a.py"].endswith("return 2\n")
        assert after.snapshot_id != before.snapshot_id
        assert after.texts == read_worktree(root).texts
        assert read_git_revision(root, "HEAD", store, binary).stats["source_bytes_read"] == 0


def test_git_policy_excludes_symlinks_secrets_and_generated_source(git_repo):
    root, git, binary = git_repo
    (root / "link.py").symlink_to(root / "a.py")
    (root / "secrets.py").write_text("API_KEY = 'not-an-actual-key'\n")
    (root / "generated.py").write_text("# automatically generated\nX = 1\n")
    (root / "odd\tname.py").write_text("X = 2\n")
    git("add", ".")
    git("commit", "-qm", "policy")
    snapshot = read_git_revision(root, "HEAD", git_executable=binary)
    assert set(snapshot.texts) == {"a.py", "keep.py", "odd\tname.py"}
    assert snapshot.texts == read_worktree(root).texts
    with pytest.raises(ValueError):
        read_git_revision(root, "--help", git_executable=binary)


def test_corrupt_blob_cache_is_rebuilt_from_git(git_repo):
    root, _, binary = git_repo
    with SourceStore(root / ".contextproof/revisions.sqlite") as store:
        before = read_git_revision(root, "HEAD", store, binary)
        store.db.execute("UPDATE source_blobs SET content=?", (b"incorrect",))
        after = read_git_revision(root, "HEAD", store, binary)
        assert after.texts == before.texts
        assert after.stats["blob_reads"] == 2


def test_worktree_does_not_trust_preserved_mtime(tmp_path):
    source = tmp_path / "a.py"
    source.write_text("VALUE = 1\n")
    timestamp = source.stat()
    before = read_worktree(tmp_path)
    source.write_text("VALUE = 2\n")
    os.utime(source, ns=(timestamp.st_atime_ns, timestamp.st_mtime_ns))
    after = read_worktree(tmp_path)
    assert before.snapshot_id != after.snapshot_id


def test_json_ast_cache_roundtrip_and_corruption_recovery(tmp_path):
    source = "@decorator\ndef f(x: str = 'α'):\n    return b'abc', 3j, ..., [i for i in x]\n"
    tree = ast.parse(source)
    with SourceStore(tmp_path / "cache.sqlite") as store:
        cache = ParseCache(store)
        cache[("a.py", "source-hash")] = tree
        reopened = ParseCache(store)
        assert ast.dump(reopened[("a.py", "source-hash")], include_attributes=True) == ast.dump(
            tree, include_attributes=True)
        store.db.execute("UPDATE ast_modules SET content='{}'")
        corrupted = ParseCache(store)
        assert corrupted.get(("a.py", "source-hash")) is None
        assert corrupted.stats["parse_cache_corrupt"] == 1


def test_store_rejects_symlink_location(tmp_path):
    (tmp_path / "actual").mkdir()
    (tmp_path / "alias").symlink_to(tmp_path / "actual", target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        SourceStore(tmp_path / "alias/cache.sqlite")
