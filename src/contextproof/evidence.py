"""Budgeted source evidence and conservative verification across file changes.

Hashes attest to text identity, not semantic correctness. Repair retains only
exact source text and never calls a modified function semantically equivalent.
The byte counter measures UTF-8 bytes of the complete rendered payload; it is
not a measurement of model billing, API transport, or hidden prompt tokens.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path, PurePosixPath
from typing import Any

from .index import source_lines
from .models import Snapshot
from .retrieval import search

_TOKENIZERS = {"bytes", "cl100k_base", "o200k_base"}
_HASH = re.compile(r"^[0-9a-f]{64}$")
_CORE_KEYS = (
    "schema_version", "snapshot_id", "query", "method", "tokenizer", "budget",
    "budget_unit", "entries", "omitted_count", "provenance",
)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def count_tokens(text: str, tokenizer: str = "bytes") -> int:
    """Count UTF-8 bytes by default, or ordinary text tokens with tiktoken.

UTF-8 bytes upper-bound the ordinary byte-BPE text token count; they are
deliberately reported as bytes. Optional tiktoken encodings require the extra
and its encoding data cache (tiktoken may fetch those data on first use).
    """
    if tokenizer not in _TOKENIZERS:
        raise ValueError("tokenizer must be bytes, cl100k_base, or o200k_base")
    if tokenizer == "bytes":
        return len(text.encode("utf-8"))
    try:
        import tiktoken
    except ImportError as exc:
        raise ValueError("install contextproof[tokens] to use a tiktoken encoding") from exc
    return len(tiktoken.get_encoding(tokenizer).encode(text, disallowed_special=()))


def render_bundle(bundle: dict) -> str:
    """Render the entire model-facing bundle, including all citation metadata.

    The derived consumed count and the verification report returned by repair
    are out-of-band receipt fields, avoiding a self-referential count. All source
    metadata, provenance, and selected source entries are rendered and budgeted.
    Code fences are longer than any in the source text.
    """
    if not isinstance(bundle, dict) or bundle.get("schema_version") != 1:
        raise ValueError("unsupported or missing bundle schema")
    if not isinstance(bundle.get("entries"), list):
        raise ValueError("bundle entries must be a list")
    if not isinstance(bundle.get("query"), str) or bundle.get("method") not in {"bm25", "graph"}:
        raise ValueError("invalid bundle query or retrieval method")
    if bundle.get("tokenizer") not in _TOKENIZERS:
        raise ValueError("unsupported tokenizer")
    if not isinstance(bundle.get("id"), str) or not _HASH.fullmatch(bundle["id"]):
        raise ValueError("invalid bundle id")
    if not isinstance(bundle.get("snapshot_id"), str) or not bundle["snapshot_id"]:
        raise ValueError("missing snapshot identity")
    for key in ("budget", "omitted_count"):
        if not isinstance(bundle.get(key), int) or isinstance(bundle[key], bool) or bundle[key] < 0:
            raise ValueError(f"invalid {key}")
    if bundle["budget"] == 0:
        raise ValueError("budget must be positive")
    for entry in bundle["entries"]:
        error = _entry_error(entry)
        if error:
            raise ValueError(error)
    if bundle["id"] != _bundle_id(bundle):
        raise ValueError("bundle integrity checksum mismatch")
    metadata = {key: bundle[key] for key in (
        "schema_version", "id", "snapshot_id", "query", "method", "tokenizer",
        "budget", "budget_unit", "omitted_count", "provenance",
    ) if key in bundle}
    parts = ["# ContextProof source evidence\n", _json(metadata), "\n"]
    for entry in bundle.get("entries", []):
        text = entry["text"]
        runs = re.findall(r"`+", text)
        fence = "`" * max(3, 1 + max((len(run) for run in runs), default=0))
        citation = {key: value for key, value in entry.items() if key != "text"}
        parts.extend(["\n", _json(citation), "\n", fence, "\n", text])
        if not text.endswith("\n"):
            parts.append("\n")
        parts.extend([fence, "\n"])
    return "".join(parts)


def _bundle_id(bundle: dict) -> str:
    return sha256(_json({key: bundle[key] for key in _CORE_KEYS if key in bundle}))


def _seal(bundle: dict) -> dict:
    bundle["id"] = _bundle_id(bundle)
    bundle["consumed"] = count_tokens(render_bundle(bundle), bundle["tokenizer"])
    return bundle


def _pack(base: dict, candidates: list[dict]) -> dict:
    result = deepcopy(base)
    result["entries"] = []
    result["omitted_count"] = len(candidates)
    _seal(result)
    if result["consumed"] > result["budget"]:
        raise ValueError(
            f"budget {result['budget']} cannot fit bundle metadata "
            f"({result['consumed']} {result['budget_unit']})"
        )
    for candidate in candidates:
        trial = deepcopy(result)
        trial["entries"].append(candidate)
        trial["omitted_count"] = len(candidates) - len(trial["entries"])
        _seal(trial)
        if trial["consumed"] <= trial["budget"]:
            result = trial
    return result


def make_bundle(
    snapshot: Snapshot, query: str, budget: int = 4000, method: str = "graph",
    tokenizer: str = "bytes",
) -> dict:
    """Greedily pack ranked, untruncated chunks within a complete payload budget."""
    if not isinstance(budget, int) or isinstance(budget, bool) or budget <= 0:
        raise ValueError("budget must be a positive integer")
    count_tokens("", tokenizer)  # Validate optional dependency before retrieval.
    candidates = []
    for hit in search(snapshot, query, method, limit=len(snapshot.chunks)):
        chunk = hit.chunk
        candidates.append({
            "id": chunk.id, "path": chunk.path, "start_line": chunk.start_line,
            "end_line": chunk.end_line, "text": chunk.text, "symbol": chunk.symbol,
            "kind": chunk.kind, "file_sha256": chunk.file_sha256,
            "text_sha256": sha256(chunk.text), "score": round(hit.score, 8),
            "reasons": list(hit.reasons),
        })
    return _pack({
        "schema_version": 1, "snapshot_id": snapshot.id, "query": query,
        "method": method, "tokenizer": tokenizer, "budget": budget,
        "budget_unit": "utf8_bytes" if tokenizer == "bytes" else "tokens",
    }, candidates)


def _safe_parts(path: Any) -> tuple[str, ...]:
    if not isinstance(path, str) or not path or "\\" in path or "\x00" in path:
        raise ValueError("invalid relative source path")
    value = PurePosixPath(path)
    if value.is_absolute() or any(part in {"", ".", ".."} for part in path.split("/")):
        raise ValueError("source path must be normalized and root-relative")
    return value.parts


def _read_source(root: Path, relative: str) -> str:
    """Use the indexer's exact filename, content, and no-symlink policy."""
    from .index import read_source_bytes

    _safe_parts(relative)
    raw = read_source_bytes(root, Path(relative))
    if raw is None:
        raise ValueError("source is unreadable or excluded by source policy")
    return raw.decode("utf-8")


def _entry_error(entry: Any) -> str | None:
    if not isinstance(entry, dict):
        return "entry is not an object"
    try:
        _safe_parts(entry.get("path"))
    except ValueError as exc:
        return str(exc)
    text = entry.get("text")
    if not isinstance(text, str) or not text.strip():
        return "empty or non-text evidence"
    for key in ("text_sha256", "file_sha256"):
        if not isinstance(entry.get(key), str) or not _HASH.fullmatch(entry[key]):
            return f"invalid {key}"
    if sha256(text) != entry["text_sha256"]:
        return "evidence text does not match text_sha256"
    start, end = entry.get("start_line"), entry.get("end_line")
    if any(not isinstance(value, int) or isinstance(value, bool) for value in (start, end)):
        return "line range must contain integers"
    if start <= 0 or end < start or end - start + 1 != len(source_lines(text)):
        return "invalid evidence line range"
    if not isinstance(entry.get("id"), str) or not entry["id"]:
        return "missing entry id"
    return None


def _bundle_error(bundle: Any) -> str | None:
    if not isinstance(bundle, dict) or bundle.get("schema_version") != 1:
        return "unsupported or missing bundle schema"
    if not isinstance(bundle.get("entries"), list) or not bundle["entries"]:
        return "bundle contains no source evidence"
    try:
        if bundle.get("id") != _bundle_id(bundle):
            return "bundle integrity checksum mismatch"
        if bundle.get("tokenizer") not in _TOKENIZERS:
            return "unsupported tokenizer"
        if not isinstance(bundle.get("snapshot_id"), str) or not bundle["snapshot_id"]:
            return "missing snapshot identity"
        for key in ("budget", "consumed", "omitted_count"):
            if not isinstance(bundle.get(key), int) or isinstance(bundle[key], bool):
                return f"invalid {key}"
        if bundle["consumed"] < 0 or bundle["budget"] <= 0 or bundle["omitted_count"] < 0:
            return "invalid context budget"
        if bundle["consumed"] > bundle["budget"]:
            return "rendered context exceeds declared budget"
        expected_unit = "utf8_bytes" if bundle["tokenizer"] == "bytes" else "tokens"
        if bundle.get("budget_unit") != expected_unit:
            return "tokenizer and budget unit disagree"
        for entry in bundle["entries"]:
            error = _entry_error(entry)
            if error:
                return error
        if count_tokens(render_bundle(bundle), bundle["tokenizer"]) != bundle["consumed"]:
            return "rendered context cost does not match declared consumed count"
    except (TypeError, ValueError, KeyError, UnicodeError) as exc:
        return f"malformed bundle: {exc}"
    return None


def _all_matches(text: str, snippet: str) -> list[tuple[int, int]]:
    """Find exact snippets aligned to complete source lines, including EOF."""
    lines = source_lines(text)
    snippet_lines = source_lines(snippet)
    width = len(snippet_lines)
    return [(offset + 1, offset + width)
            for offset in range(len(lines) - width + 1)
            if lines[offset:offset + width] == snippet_lines]


def verify_bundle(bundle: dict, root: Path) -> dict:
    """Verify a bundle against safe current source files without trusting an index.

An exact current location is valid even if an identical snippet also exists
elsewhere. Relocation is allowed only when the old location no longer matches
and exactly one current source location contains the complete original text.
    """
    from .index import iter_source_files, snapshot_id

    error = _bundle_error(bundle)
    entries = bundle.get("entries", []) if isinstance(bundle, dict) else []
    if not isinstance(entries, list):
        entries = []
    report = {
        "schema_version": 1, "bundle_id": bundle.get("id") if isinstance(bundle, dict) else None,
        "results": [], "summary": {}, "valid": False,
        "guarantee": "exact source text identity only; no semantic equivalence claim",
    }
    if error:
        report["error"] = error
        for entry in entries:
            report["results"].append({
                "entry_id": entry.get("id") if isinstance(entry, dict) else None,
                "status": "invalid", "reason": error,
            })
        report["summary"] = {"invalid": len(entries)}
        return report

    root = Path(root).absolute()
    if root.is_symlink():
        raise ValueError("repository root must not be a symbolic link")
    root = root.resolve(strict=True)
    corpus: dict[str, str] = {}
    unavailable: dict[str, str] = {}
    for path in iter_source_files(root):
        relative = path.relative_to(root).as_posix()
        try:
            corpus[relative] = _read_source(root, relative)
        except (OSError, ValueError, UnicodeError) as exc:
            unavailable[relative] = str(exc)
    report["current_snapshot_id"] = snapshot_id({
        path: sha256(text) for path, text in sorted(corpus.items())
    })
    report["unavailable_files"] = unavailable
    for entry in entries:
        path = entry["path"]
        item = {"entry_id": entry["id"], "path": path,
                "start_line": entry["start_line"], "end_line": entry["end_line"]}
        # A symlink at the old path is a trust-boundary change, not a relocation
        # hint. Reject it even if a matching safe copy happens to exist elsewhere.
        current = root
        unsafe = False
        for part in _safe_parts(path):
            current = current / part
            if current.is_symlink():
                unsafe = True
                break
        if unsafe or path in unavailable:
            item.update(status="invalid", reason="source path is unsafe or unreadable")
        else:
            source = corpus.get(path)
            at_location = (source is not None and "".join(source_lines(source)[
                entry["start_line"] - 1:entry["end_line"]
            ]) == entry["text"])
            if at_location:
                repaired = deepcopy(entry)
                repaired["file_sha256"] = sha256(source)
                item.update(status="valid", reason="exact text at the recorded lines", repaired=repaired)
            else:
                matches = [(candidate_path, start, end)
                           for candidate_path, candidate_text in sorted(corpus.items())
                           for start, end in _all_matches(candidate_text, entry["text"])]
                if len(matches) == 1:
                    new_path, start, end = matches[0]
                    repaired = deepcopy(entry)
                    repaired.update(path=new_path, start_line=start, end_line=end,
                                    file_sha256=sha256(corpus[new_path]))
                    item.update(status="relocated", reason="one unique exact source match",
                                repaired=repaired)
                elif len(matches) > 1:
                    item.update(status="ambiguous", reason="multiple exact source matches",
                                matches=[{"path": match[0], "start_line": match[1],
                                          "end_line": match[2]} for match in matches])
                elif source is not None:
                    item.update(status="modified", reason="recorded file exists; original text absent")
                elif current.exists():
                    item.update(status="invalid", reason="recorded path is outside the allowed source corpus")
                else:
                    item.update(status="deleted", reason="recorded path and original text absent")
        report["results"].append(item)
        report["summary"][item["status"]] = report["summary"].get(item["status"], 0) + 1
    report["valid"] = bool(report["results"]) and all(
        item["status"] == "valid" for item in report["results"]
    )
    return report


def repair_bundle(bundle: dict, root: Path) -> dict:
    """Return a new, budget-checked bundle containing only exact verified evidence.

Modified, deleted, ambiguous, and malformed evidence is invalidated. A repaired
bundle may be empty; verify will then fail closed. Additional metadata may make
previously fitting evidence exceed the budget, in which case it is omitted.
    """
    report = verify_bundle(bundle, root)
    if report.get("error"):
        raise ValueError(report["error"])
    candidates = [item["repaired"] for item in report["results"] if "repaired" in item]
    base = {key: deepcopy(bundle[key]) for key in (
        "schema_version", "query", "method", "tokenizer", "budget", "budget_unit",
    )}
    base["snapshot_id"] = report["current_snapshot_id"]
    base["provenance"] = {
        "previous_bundle_id": bundle["id"], "previous_snapshot_id": bundle["snapshot_id"],
        "operation": "exact-text verification and conservative relocation",
    }
    result = _pack(base, candidates)
    selected_ids = {entry["id"] for entry in result["entries"]}
    result["invalidated"] = [item for item in report["results"] if "repaired" not in item]
    result["budget_omitted"] = [entry["id"] for entry in candidates if entry["id"] not in selected_ids]
    result["verification_report"] = report
    return result
