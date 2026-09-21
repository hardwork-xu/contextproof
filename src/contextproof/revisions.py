"""Safe working-tree and immutable Git source snapshots with content storage.

Git revisions are read through object IDs without checkout, hooks, import, or
execution of repository code. Working-tree reads still hash all eligible files;
mtime is never accepted as evidence that source bytes are unchanged.
"""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import subprocess

from .index import (EXCLUDED_DIRS, MAX_FILE_BYTES, _allowed_name, _root_path,
                    _source_text, iter_source_files, read_source_bytes, snapshot_id)


@dataclass
class Revision:
    texts: dict[str, str]
    snapshot_id: str
    revision: str
    kind: str
    stats: dict


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def verify_blob_oid(oid, raw):
    """Verify Git's content identity even when no disposable store is in use."""
    if (not isinstance(oid, str) or len(oid) not in {40, 64}
            or any(character not in "0123456789abcdef" for character in oid)):
        raise ValueError("invalid Git blob identity")
    algorithm = hashlib.sha1 if len(oid) == 40 else hashlib.sha256
    actual = algorithm(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if actual != oid:
        raise ValueError("Git blob identity mismatch")


def _eligible(path):
    parts = PurePosixPath(path).parts
    return (bool(parts) and not PurePosixPath(path).is_absolute()
            and all(part not in {".", ".."} for part in parts)
            and not any(p.lower() in EXCLUDED_DIRS or p.lower().endswith(".egg-info")
                        for p in parts[:-1]) and _allowed_name(Path(path)))


class SourceStore:
    """A disposable SQLite store. Stored source is verified before every reuse."""

    def __init__(self, path: Path):
        self.path = Path(path).absolute()
        for candidate in [self.path, *self.path.parents]:
            if candidate.is_symlink():
                raise ValueError("source store path must not contain symlinks")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=30)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS source_blobs "
                        "(oid TEXT PRIMARY KEY, content BLOB NOT NULL, sha256 TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS graph_artifacts "
                        "(id TEXT PRIMARY KEY, content TEXT NOT NULL)")
        self.db.commit()

    def get_blob(self, oid):
        row = self.db.execute("SELECT content,sha256 FROM source_blobs WHERE oid=?", (oid,)).fetchone()
        if not row:
            return None
        raw = bytes(row[0])
        if _hash(raw) != row[1]:
            return None  # Repair cache corruption from the immutable object database.
        try:
            verify_blob_oid(oid, raw)
        except ValueError:
            return None
        return raw

    def put_blob(self, oid, raw):
        verify_blob_oid(oid, raw)
        self.db.execute("INSERT OR REPLACE INTO source_blobs VALUES (?,?,?)", (oid, raw, _hash(raw)))

    def save_graph(self, graph):
        from .graph import validate_graph
        validate_graph(graph)
        self.db.execute("INSERT OR REPLACE INTO graph_artifacts VALUES (?,?)",
                        (graph["id"], json.dumps(graph, ensure_ascii=False, sort_keys=True)))
        self.db.commit()

    def load_graph(self, handle):
        from .graph import validate_graph
        if not isinstance(handle, str) or len(handle) != 64 or any(
                c not in "0123456789abcdef" for c in handle):
            raise ValueError("invalid evidence graph handle")
        row = self.db.execute("SELECT content FROM graph_artifacts WHERE id=?", (handle,)).fetchone()
        if not row:
            raise ValueError("evidence graph handle is unavailable; capture it on this server first")
        result = json.loads(row[0])
        validate_graph(result)
        if result["id"] != handle:
            raise ValueError("stored graph does not match its handle")
        return result

    def close(self):
        self.db.commit()
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def read_worktree(root: Path) -> Revision:
    root = _root_path(root)
    texts, total = {}, 0
    for path in iter_source_files(root):
        raw = read_source_bytes(root, path)
        if raw is not None:
            texts[path.relative_to(root).as_posix()] = raw.decode("utf-8")
            total += len(raw)
    identity = snapshot_id({path: _hash(text.encode()) for path, text in texts.items()})
    return Revision(texts, identity, identity, "working-tree",
                    {"files": len(texts), "source_bytes_read": total,
                     "blob_cache_hits": 0, "blob_reads": len(texts)})


def read_git_revision(root: Path, ref: str, store: SourceStore | None = None,
                      git_executable: str | None = None) -> Revision:
    root = _root_path(root)
    executable = git_executable or os.environ.get("CONTEXTPROOF_GIT") or shutil.which("git")
    if not executable:
        raise ValueError("Git is required for immutable revisions; use working-tree mode otherwise")
    if not isinstance(ref, str) or not ref or "\0" in ref:
        raise ValueError("invalid Git revision")
    base = [executable, "--no-replace-objects", "-C", str(root)]
    # A promisor clone may lazy-fetch even during ls-tree/cat-file, invoking
    # repository-configured SSH or remote helpers. These reads are local only.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_NO_LAZY_FETCH="1", GIT_TERMINAL_PROMPT="0", GIT_ALLOW_PROTOCOL="",
               GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_OPTIONAL_LOCKS="0")

    def git(*args, data=None):
        try:
            proc = subprocess.run([*base, *args], input=data, capture_output=True,
                                  timeout=120, env=env)
        except subprocess.TimeoutExpired as exc:
            raise ValueError("Git snapshot read timed out") from exc
        if proc.returncode:
            raise ValueError("Git snapshot read failed: " + proc.stderr.decode(errors="replace")[:1200])
        return proc.stdout

    top = Path(os.fsdecode(git("rev-parse", "--show-toplevel").rstrip(b"\n"))).resolve()
    if top != root.resolve():
        raise ValueError("Git revision root must be the repository top-level directory")
    commit = git("rev-parse", "--verify", "--end-of-options", ref + "^{commit}").strip().decode()
    if len(commit) not in {40, 64} or any(c not in "0123456789abcdef" for c in commit):
        raise ValueError("Git returned an invalid commit identity")
    listing = git("ls-tree", "-r", "-l", "-z", "--full-tree", commit)
    files = {}
    for record in listing.split(b"\0"):
        if not record:
            continue
        header, raw_path = record.split(b"\t", 1)
        mode, kind, raw_oid, size = header.split()
        try:
            path = raw_path.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if mode not in {b"100644", b"100755"} or kind != b"blob" or not _eligible(path):
            continue
        if not size.isdigit():
            raise ValueError("Git source object is unavailable locally; snapshot reads never fetch")
        if int(size) > MAX_FILE_BYTES:
            continue
        files[path] = raw_oid.decode("ascii")
    blobs, missing, hits = {}, [], 0
    for oid in sorted(set(files.values())):
        cached = store.get_blob(oid) if store else None
        if cached is None:
            missing.append(oid)
        else:
            blobs[oid] = cached
            hits += 1
    if missing:
        stream = git("cat-file", "--batch", data="".join(oid + "\n" for oid in missing).encode())
        position = 0
        for oid in missing:
            end = stream.index(b"\n", position)
            response = stream[position:end].split()
            if len(response) != 3 or response[:2] != [oid.encode(), b"blob"]:
                raise ValueError("unexpected Git object response")
            size = int(response[2])
            if size < 0 or size > MAX_FILE_BYTES:
                raise ValueError("Git object exceeds source size limit")
            raw = stream[end + 1:end + 1 + size]
            if len(raw) != size or stream[end + 1 + size:end + 2 + size] != b"\n":
                raise ValueError("truncated Git object response")
            position = end + 2 + size
            verify_blob_oid(oid, raw)
            blobs[oid] = raw
            if store:
                store.put_blob(oid, raw)
        if position != len(stream):
            raise ValueError("unexpected trailing Git object response")
    texts = {}
    for path, oid in sorted(files.items()):
        source = _source_text(blobs[oid])
        if source is not None:
            texts[path] = source
    if store:
        store.db.commit()
    identity = snapshot_id({path: _hash(text.encode()) for path, text in texts.items()})
    return Revision(texts, identity, commit, "git-commit",
                    {"files": len(texts), "tree_entries": len(files),
                     "blob_cache_hits": hits, "blob_reads": len(missing),
                     "source_bytes_read": sum(len(blobs[oid]) for oid in missing)})


def read_revision(root, ref=None, store=None, git_executable=None):
    return (read_worktree(root) if ref is None or ref == "WORKTREE"
            else read_git_revision(root, ref, store, git_executable))
