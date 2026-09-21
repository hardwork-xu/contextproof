"""Git source reads must not execute transport configuration or widen root scope."""

import os
import shlex
import shutil
import subprocess
import zlib

import pytest

from contextproof.revisions import read_git_revision


@pytest.fixture
def isolated_git(tmp_path):
    binary = os.environ.get("CONTEXTPROOF_GIT") or shutil.which("git")
    if not binary:
        pytest.skip("Git unavailable")
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)

    def git(root, *args):
        completed = subprocess.run([binary, "-C", str(root), *args], text=True,
                                   capture_output=True, timeout=15, env=env)
        if completed.returncode:
            raise RuntimeError(completed.stderr)
        return completed.stdout.strip()

    def repository(name):
        root = tmp_path / name
        root.mkdir()
        git(root, "init", "-q")
        git(root, "config", "user.name", "ContextProof regression test")
        git(root, "config", "user.email", "test@example.invalid")
        (root / "module.py").write_text(f"VALUE = {name!r}\n")
        git(root, "add", ".")
        git(root, "commit", "-qm", "source snapshot")
        return root

    return binary, git, repository


def test_promisor_missing_blob_does_not_execute_repository_ssh_command(isolated_git):
    binary, git, repository = isolated_git
    root = repository("partial")
    blob = git(root, "rev-parse", "HEAD:module.py")
    (root / ".git/objects" / blob[:2] / blob[2:]).unlink()
    marker = root / "transport-executed"
    script = root / "transport-probe.sh"
    # This is a controlled local sentinel, not a real SSH or network operation.
    script.write_text(f"#!/bin/sh\n: > {shlex.quote(str(marker))}\nexit 1\n")
    script.chmod(0o755)
    git(root, "config", "core.repositoryformatversion", "1")
    git(root, "config", "extensions.partialClone", "origin")
    git(root, "config", "remote.origin.promisor", "true")
    git(root, "config", "remote.origin.url", "ssh://example.invalid/source")
    git(root, "config", "core.sshCommand", shlex.quote(str(script)))

    with pytest.raises(ValueError, match="unavailable locally|snapshot read failed"):
        read_git_revision(root, "HEAD", git_executable=binary)
    assert not marker.exists(), "read-only source access executed repository transport config"


def test_git_revision_rejects_nested_root_instead_of_reading_parent_sources(isolated_git):
    binary, git, repository = isolated_git
    root = repository("root")
    nested = root / "nested"
    nested.mkdir()
    (nested / "inside.py").write_text("INSIDE = 1\n")
    git(root, "add", ".")
    git(root, "commit", "-qm", "nested scope")

    with pytest.raises(ValueError, match="top-level"):
        read_git_revision(nested, "HEAD", git_executable=binary)


def test_ambient_git_directory_cannot_redirect_selected_repository(isolated_git, monkeypatch):
    binary, _, repository = isolated_git
    selected = repository("selected")
    other = repository("other")
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))
    monkeypatch.setenv("GIT_OBJECT_DIRECTORY", str(other / ".git/objects"))

    revision = read_git_revision(selected, "HEAD", git_executable=binary)
    assert revision.texts == {"module.py": "VALUE = 'selected'\n"}


def test_uncached_git_read_rejects_same_size_corrupt_loose_blob(isolated_git):
    binary, git, repository = isolated_git
    root = repository("corrupt")
    blob = git(root, "rev-parse", "HEAD:module.py")
    loose_object = root / ".git/objects" / blob[:2] / blob[2:]
    original = zlib.decompress(loose_object.read_bytes())
    corrupt = original.replace(b"VALUE", b"OTHER", 1)
    assert len(corrupt) == len(original) and corrupt != original
    loose_object.chmod(0o600)
    loose_object.write_bytes(zlib.compress(corrupt))

    # cat-file returns the altered payload without independently checking its
    # hash. A correct size/header must not make the source trustworthy.
    with pytest.raises(ValueError, match="Git blob identity mismatch"):
        read_git_revision(root, "HEAD", store=None, git_executable=binary)
