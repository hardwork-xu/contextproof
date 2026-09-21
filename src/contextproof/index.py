"""Deterministic, offline repository indexing with a disposable SQLite cache.

Python chunks follow the innermost class/function scope, include decorators, and
are split at 80 source lines. Other supported text files use fixed line windows.
The graph is an approximation: Python imports resolve against repository paths;
loaded Python names/attributes also link to a definition only when its name is
unique in the entire indexed corpus. Neither mechanism resolves runtime imports,
types, aliases, dynamic dispatch, or language-specific non-Python dependencies.
No repository code or Git command is ever executed.
"""

from __future__ import annotations

import ast
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
from typing import Iterator

from .models import Chunk, Snapshot

# Bump when the cache schema, chunking policy, or dependency extraction changes.
SCHEMA_VERSION = 2
MAX_CHUNK_LINES = 80
MAX_FILE_BYTES = 2 * 1024 * 1024
SUPPORTED_EXTENSIONS = frozenset(
    ".py .pyi .js .jsx .mjs .cjs .ts .tsx .go .rs .java .c .cc .cpp .h .hpp "
    ".cs .rb .php .swift .kt .kts .scala .sh .bash .zsh .md .mdx .rst .txt "
    ".toml .yaml .yml .json .sql .html .css .scss .vue .svelte .xml .ini .cfg".split()
)
SUPPORTED_NAMES = frozenset({"dockerfile", "makefile", "readme", "license"})
EXCLUDED_DIRS = frozenset(
    ".git .hg .svn .contextproof .venv venv env __pycache__ .pytest_cache "
    ".ruff_cache .mypy_cache node_modules vendor dist build target coverage "
    ".next .nuxt .tox .nox .cache .idea .vscode .eggs site-packages "
    "htmlcov generated _generated .ipynb_checkpoints work .ssh .aws .azure "
    ".gcloud .output .parcel-cache .turbo .svelte-kit".split()
)
_SECRET_SUFFIXES = frozenset({".pem", ".key", ".p12", ".pfx", ".keystore"})
_SECRET_NAMES = frozenset(
    {".env", ".npmrc", ".pypirc", ".netrc", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519"}
)


def _root_path(root: Path) -> Path:
    root = Path(root).expanduser().absolute()
    if root.is_symlink():
        raise ValueError("Repository root must not be a symbolic link")
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Repository root must be a directory")
    return root


def _allowed_name(path: Path) -> bool:
    name = path.name.lower()
    if (
        name in _SECRET_NAMES
        or name.startswith(".env.")
        or any(marker in name for marker in ("credential", "secret", "private_key", "private-key"))
        or name.startswith(("secret.", "secrets.", "service-account", "service_account"))
        or name in {"token.json", "tokens.json", "accesstokens.json", "serviceaccount.json",
                    "package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml"}
        or path.suffix.lower() in _SECRET_SUFFIXES
        or name.endswith((".min.js", ".min.css", "_pb2.py", "_pb2_grpc.py", ".lock"))
    ):
        return False
    return path.suffix.lower() in SUPPORTED_EXTENSIONS or name in SUPPORTED_NAMES


def iter_source_files(root: Path) -> Iterator[Path]:
    """Yield sorted eligible absolute paths without following file/dir symlinks.

    This is the filename allowlist. Content checks (UTF-8, NUL bytes, private-key
    headers, generated markers, and size) happen when build_index reads a file.
    The rules are intentionally explicit; .gitignore is not interpreted.
    """
    root = _root_path(root)
    found: list[Path] = []
    for directory, dirs, files in os.walk(root, topdown=True, followlinks=False):
        parent = Path(directory)
        dirs[:] = sorted(
            name for name in dirs
            if name.lower() not in EXCLUDED_DIRS
            and not name.lower().endswith(".egg-info")
            and not (parent / name).is_symlink()
        )
        for name in sorted(files):
            path = parent / name
            if not _allowed_name(path) or path.is_symlink():
                continue
            try:
                info = path.stat(follow_symlinks=False)
            except OSError:
                continue
            if stat.S_ISREG(info.st_mode) and info.st_size <= MAX_FILE_BYTES:
                found.append(path)
    yield from sorted(found, key=lambda path: path.relative_to(root).as_posix())


def _read_bytes(root: Path, path: Path) -> bytes | None:
    """Read beneath an open root, refusing symlinks in every relative component."""
    relative = path.relative_to(root)
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        return None
    descriptors: list[int] = []
    try:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        descriptors.append(os.open(root, flags))
        for component in relative.parts[:-1]:
            descriptors.append(os.open(component, flags, dir_fd=descriptors[-1]))
        fd = os.open(
            relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=descriptors[-1],
        )
        descriptors.append(fd)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE_BYTES:
            return None
        parts: list[bytes] = []
        total = 0
        while total <= MAX_FILE_BYTES:
            block = os.read(fd, min(65536, MAX_FILE_BYTES + 1 - total))
            if not block:
                break
            parts.append(block)
            total += len(block)
        after = os.fstat(fd)
        before_signature = (info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        after_signature = (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
        if before_signature != after_signature or total != after.st_size:
            return None
        return b"".join(parts) if total <= MAX_FILE_BYTES else None
    except OSError:
        return None
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


def _source_text(raw: bytes) -> str | None:
    if b"\x00" in raw:
        return None
    try:
        source = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    upper = source.upper()
    if "PRIVATE KEY-----" in upper:
        return None
    # Generated-file headers are checked only in the opening lines.
    header = "".join(source_lines(source)[:5]).lower()
    if any(marker in header for marker in ("@generated", "automatically generated", "do not edit")):
        return None
    return source


def source_lines(source: str) -> list[str]:
    """Keep exact CRLF/CR/LF source lines, matching Python/editor line numbers.

    str.splitlines also treats Unicode separators and form feeds as line breaks;
    these can legally occur inside Python string literals without advancing AST
    line numbers. Sharing this helper keeps indexing and verification aligned.
    """
    pieces = re.split(r"(\r\n|\r|\n)", source)
    lines = [pieces[index] + pieces[index + 1] for index in range(0, len(pieces) - 1, 2)]
    if pieces[-1]:
        lines.append(pieces[-1])
    return lines


def read_source_bytes(root: Path, path: Path) -> bytes | None:
    """Read an eligible UTF-8 source file safely, or return None if excluded.

    Paths may be absolute or repository-relative. The same filename and content
    policy used by build_index is applied; parent traversal is never accepted.
    """
    root = _root_path(root)
    path = Path(path)
    if not path.is_absolute():
        path = root / path
    try:
        relative = path.relative_to(root)
    except ValueError:
        return None
    if any(part in {".", ".."} for part in relative.parts):
        return None
    if any(part.lower() in EXCLUDED_DIRS or part.lower().endswith(".egg-info")
           for part in relative.parts[:-1]):
        return None
    if not _allowed_name(path):
        return None
    raw = _read_bytes(root, path)
    return raw if raw is not None and _source_text(raw) is not None else None


def _parse_file(path: str, source: str, digest: str) -> tuple[list[Chunk], dict]:
    lines = source_lines(source)
    # Each line belongs to the innermost declaration. Scope intervals include
    # decorators so retrieval never detaches a decorator from its definition.
    owners = [("<module>", "module")] * len(lines)
    metadata: dict = {"imports": [], "definitions": [], "references": []}
    tree = None
    if Path(path).suffix.lower() in {".py", ".pyi"}:
        try:
            tree = ast.parse(source, filename=path)
        except (SyntaxError, ValueError, RecursionError):
            pass
    if tree is None:
        owners = [("<text>", "text")] * len(lines)
    else:
        references: set[str] = set()

        pending: list[tuple[ast.AST, tuple[str, ...]]] = [(tree, ())]
        while pending:
            node, parents = pending.pop()
            scope = parents
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                scope = (*parents, node.name)
                kind = "class" if isinstance(node, ast.ClassDef) else "function"
                start = min([node.lineno, *(d.lineno for d in node.decorator_list)])
                end = node.end_lineno or node.lineno
                for index in range(start - 1, min(end, len(owners))):
                    owners[index] = (".".join(scope), kind)
                metadata["definitions"].append(node.name)
            if isinstance(node, ast.Import):
                metadata["imports"].extend(
                    {"module": alias.name, "level": 0, "names": []} for alias in node.names
                )
            elif isinstance(node, ast.ImportFrom):
                metadata["imports"].append({
                    "module": node.module or "", "level": node.level,
                    "names": [alias.name for alias in node.names],
                })
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                references.add(node.id)
            elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
                references.add(node.attr)
            pending.extend((child, scope) for child in reversed(list(ast.iter_child_nodes(node))))
        metadata["references"] = sorted(references)
    chunks: list[Chunk] = []
    start = 0
    while start < len(lines):
        owner = owners[start]
        end = start + 1
        while end < len(lines) and owners[end] == owner and end - start < MAX_CHUNK_LINES:
            end += 1
        text = "".join(lines[start:end])
        # Blank separators add no retrieval value; their source line numbers
        # remain represented correctly in the surrounding chunks.
        if text.strip():
            key = json.dumps([path, start + 1, end, owner, digest], separators=(",", ":"))
            chunks.append(Chunk(
                id=hashlib.sha256(key.encode()).hexdigest(), path=path,
                start_line=start + 1, end_line=end, text=text,
                symbol=owner[0], kind=owner[1], file_sha256=digest,
            ))
        start = end
    return chunks, metadata


def _dependency_edges(metadata: dict[str, dict]) -> list[tuple[str, str]]:
    modules: dict[str, list[str]] = {}
    definitions: dict[str, list[str]] = {}
    for path, data in metadata.items():
        if Path(path).suffix.lower() not in {".py", ".pyi"}:
            continue
        parts = list(Path(path).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        # src layouts and a repository root are both common Python import roots.
        names = {".".join(parts)}
        if len(parts) > 1 and parts[0] == "src":
            names.add(".".join(parts[1:]))
        for name in names:
            if name:
                modules.setdefault(name, []).append(path)
        for name in data["definitions"]:
            definitions.setdefault(name, []).append(path)
    edges: set[tuple[str, str]] = set()
    for path, data in metadata.items():
        package = list(Path(path).with_suffix("").parts[:-1])
        for item in data["imports"]:
            module = item["module"]
            if item["level"]:
                up = item["level"] - 1
                if up >= len(package):
                    continue
                base = package[:len(package) - up]
                module = ".".join([*base, *filter(None, module.split("."))])
            candidates = [module] if module else []
            candidates.extend(
                f"{module}.{name}" if module else name
                for name in item["names"] if name != "*"
            )
            for candidate in candidates:
                targets = modules.get(candidate, [])
                if len(targets) == 1 and targets[0] != path:
                    edges.add((path, targets[0]))
        for name in data["references"]:
            targets = definitions.get(name, [])
            if len(targets) == 1 and targets[0] != path:
                edges.add((path, targets[0]))
    return sorted(edges)


def _open_cache(root: Path, cache_path: Path | None) -> sqlite3.Connection:
    path = root / ".contextproof" / "index.sqlite3" if cache_path is None else Path(cache_path)
    if not path.is_absolute():
        path = root / path
    if ".." in path.parts:
        raise ValueError("Cache path must not contain parent traversal")
    # SQLite opens a path itself; reject symlink destinations and parents before
    # letting it create the disposable cache database.
    sidecars = [path.with_name(path.name + suffix) for suffix in ("-journal", "-wal", "-shm")]
    for component in [path, *path.parents, *sidecars]:
        if component.is_symlink():
            raise ValueError("Cache path must not contain symbolic links")
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=15)
    connection.execute("CREATE TABLE IF NOT EXISTS contextproof_meta (key TEXT PRIMARY KEY, value TEXT)")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS contextproof_files "
        "(path TEXT PRIMARY KEY, sha256 TEXT NOT NULL, chunks TEXT NOT NULL, metadata TEXT NOT NULL)"
    )
    version = connection.execute(
        "SELECT value FROM contextproof_meta WHERE key = 'schema_version'"
    ).fetchone()
    policy = json.dumps(_index_policy(), sort_keys=True)
    if version != (policy,):
        connection.execute("DELETE FROM contextproof_files")
        connection.execute(
            "INSERT OR REPLACE INTO contextproof_meta VALUES ('schema_version', ?)",
            (policy,),
        )
    return connection


def _index_policy() -> dict[str, int]:
    return {
        "schema": SCHEMA_VERSION,
        "max_chunk_lines": MAX_CHUNK_LINES,
        "max_file_bytes": MAX_FILE_BYTES,
    }


def snapshot_id(files: dict[str, str]) -> str:
    """Shared snapshot recipe: indexing version, sorted paths, and byte hashes."""
    manifest = json.dumps(
        {"policy": _index_policy(), "files": files}, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(manifest.encode()).hexdigest()


def _valid_cache(chunks: list[Chunk], metadata: dict, path: str, digest: str, source: str) -> bool:
    """A cache hit must still contain exact spans from the bytes just hashed."""
    if not isinstance(metadata, dict):
        return False
    for key in ("definitions", "references"):
        if not isinstance(metadata.get(key), list) or not all(
            isinstance(name, str) for name in metadata[key]
        ):
            return False
    if not isinstance(metadata.get("imports"), list):
        return False
    for item in metadata["imports"]:
        if (not isinstance(item, dict) or not isinstance(item.get("module"), str)
                or type(item.get("level")) is not int or item["level"] < 0
                or not isinstance(item.get("names"), list)
                or not all(isinstance(name, str) for name in item["names"])):
            return False
    lines = source_lines(source)
    for chunk in chunks:
        if (chunk.path != path or chunk.file_sha256 != digest
                or type(chunk.start_line) is not int or type(chunk.end_line) is not int
                or not 1 <= chunk.start_line <= chunk.end_line <= len(lines)
                or chunk.end_line - chunk.start_line + 1 > MAX_CHUNK_LINES
                or not isinstance(chunk.symbol, str) or not isinstance(chunk.kind, str)
                or chunk.text != "".join(lines[chunk.start_line - 1:chunk.end_line])):
            return False
        key = json.dumps(
            [path, chunk.start_line, chunk.end_line, (chunk.symbol, chunk.kind), digest],
            separators=(",", ":"),
        )
        if chunk.id != hashlib.sha256(key.encode()).hexdigest():
            return False
    return True


def build_index(root: Path, cache_path: Path | None = None) -> Snapshot:
    """Hash every eligible file and reuse unchanged parsed chunks from SQLite.

    Snapshot identity includes paths and raw file bytes, so edits, removals, and
    moves invalidate old evidence. Edges are directed (referencing, referenced)
    and rebuilt from the current manifest on every call, including warm scans.
    The default cache is root/.contextproof/index.sqlite3. `parsed` and `reused`
    count files; `reused` does not imply that file I/O or hashing was avoided.
    """
    root = _root_path(root)
    connection = _open_cache(root, cache_path)
    files: dict[str, str] = {}
    chunks: list[Chunk] = []
    metadata: dict[str, dict] = {}
    parsed = reused = 0
    try:
        with connection:
            for file in iter_source_files(root):
                raw = _read_bytes(root, file)
                if raw is None:
                    continue
                source = _source_text(raw)
                if source is None:
                    continue
                path = file.relative_to(root).as_posix()
                digest = hashlib.sha256(raw).hexdigest()
                files[path] = digest
                cached = connection.execute(
                    "SELECT chunks, metadata FROM contextproof_files WHERE path = ? AND sha256 = ?",
                    (path, digest),
                ).fetchone()
                loaded = False
                if cached:
                    try:
                        file_chunks = [Chunk(**item) for item in json.loads(cached[0])]
                        file_metadata = json.loads(cached[1])
                        if not _valid_cache(file_chunks, file_metadata, path, digest, source):
                            raise ValueError("Invalid cache entry")
                        loaded = True
                    except (TypeError, ValueError, KeyError):
                        pass
                if loaded:
                    reused += 1
                else:
                    file_chunks, file_metadata = _parse_file(path, source, digest)
                    parsed += 1
                    connection.execute(
                        "INSERT OR REPLACE INTO contextproof_files VALUES (?, ?, ?, ?)",
                        (path, digest, json.dumps([asdict(c) for c in file_chunks]),
                         json.dumps(file_metadata)),
                    )
                chunks.extend(file_chunks)
                metadata[path] = file_metadata
            cached_paths = connection.execute("SELECT path FROM contextproof_files").fetchall()
            connection.executemany(
                "DELETE FROM contextproof_files WHERE path = ?",
                ((path,) for (path,) in cached_paths if path not in files),
            )
    finally:
        connection.close()
    return Snapshot(
        id=snapshot_id(files), files=files, chunks=chunks,
        edges=_dependency_edges(metadata),
        stats={"files": len(files), "parsed": parsed, "reused": reused, "chunks": len(chunks)},
    )
