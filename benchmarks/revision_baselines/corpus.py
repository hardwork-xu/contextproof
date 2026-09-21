"""One production-source allowlist shared by all retrieval conditions."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

from contextproof.index import iter_source_files, read_source_bytes

from .privacy import archive_raw


EXCLUDED_PARTS = {"test", "tests", "testing", "doc", "docs", "__pycache__"}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def prepare_retrieval_corpus(root, destination, allowed_prefixes, *, git_executable=None):
    """Materialize byte-identical allowed Python files; never include task oracles.

    Prefixes come from the pre-existing v1 source manifest. Tests, documentation,
    changelogs and non-Python files never enter retrieval. The same destination
    is passed to every method. A local Git commit satisfies archex's documented
    local-repository requirement; it has no remote and executes no source code.
    Reuse verifies the complete file manifest and refuses altered destinations.
    """
    root = Path(root).resolve(strict=True)
    destination = Path(destination).absolute()
    prefixes = tuple(item.rstrip("/") + "/" for item in allowed_prefixes)
    if not prefixes or any(not item or item.startswith("/") or ".." in Path(item).parts
                           for item in prefixes):
        raise ValueError("explicit safe production source prefixes are required")
    files = {}
    for path in iter_source_files(root):
        relative = path.relative_to(root).as_posix()
        if (not relative.startswith(prefixes) or path.suffix not in {".py", ".pyi"}
                or EXCLUDED_PARTS.intersection(part.lower() for part in Path(relative).parts[:-1])
                or path.name.startswith("test_") or path.name.endswith("_test.py")):
            continue
        raw = read_source_bytes(root, path)
        if raw is not None:
            files[relative] = raw
    if not files:
        raise ValueError("production allowlist selected no source files")
    manifest = {path: hashlib.sha256(raw).hexdigest() for path, raw in sorted(files.items())}
    identity = _digest(manifest)
    metadata_path = destination.parent / (destination.name + ".corpus.json")
    if destination.exists():
        if not metadata_path.is_file():
            raise ValueError("refusing to reuse an unmarked retrieval destination")
        metadata = json.loads(metadata_path.read_text())
        if "root" in metadata:
            archive_raw(metadata, "corpus-metadata")
            metadata.pop("root")
            metadata_path.write_text(json.dumps(metadata, sort_keys=True, indent=2) + "\n")
        observed = {path.relative_to(destination).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in iter_source_files(destination)}
        if metadata["source_manifest_sha256"] != identity or observed != manifest:
            raise ValueError("materialized retrieval corpus differs from its frozen source manifest")
        return {**metadata, "root": str(destination)}
    git = git_executable or os.environ.get("CONTEXTPROOF_GIT") or shutil.which("git")
    if not git:
        raise ValueError("Git is required to initialize the shared external-tool corpus")
    destination.mkdir(parents=True)
    for relative, raw in files.items():
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    base = [git, "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false",
            "-c", "core.autocrlf=false", "-c", "core.attributesFile=/dev/null",
            "-c", "user.name=ContextProof Benchmark", "-c", "user.email=benchmark@example.invalid",
            "-C", str(destination)]
    env = dict(os.environ, GIT_AUTHOR_DATE="2026-09-21T00:00:00+0000",
               GIT_COMMITTER_DATE="2026-09-21T00:00:00+0000")
    for arguments in (["init", "--quiet"], ["add", "--all"],
                      ["commit", "--quiet", "--no-verify", "-m", "Frozen production Python corpus"]):
        subprocess.run([*base, *arguments], check=True, capture_output=True, env=env, timeout=120)
    commit = subprocess.run([*base, "rev-parse", "HEAD"], check=True, capture_output=True,
                            text=True, timeout=30).stdout.strip()
    metadata = {"source_manifest_sha256": identity, "files": manifest,
                "allowed_prefixes": list(prefixes), "extensions": [".py", ".pyi"],
                "excluded_directories": sorted(EXCLUDED_PARTS), "git_commit": commit,
                "scope": "production Python only; no tests, docs, changelogs or oracle artifacts"}
    metadata_path.write_text(json.dumps(metadata, sort_keys=True, indent=2) + "\n")
    return {**metadata, "root": str(destination)}
