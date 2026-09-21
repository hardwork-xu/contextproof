"""Transformation labels are independent of ContextProof's verification output."""

from __future__ import annotations

import copy
import hashlib
import re
from pathlib import Path

SOURCE = '''"""Controlled fixture; never imported by the benchmark."""


def stable_total(values):
    """Sum values in a deterministic order."""
    total = 0
    for value in values:
        total += value
    return total


def unrelated():
    return "anchor"
'''

EXPECTED = {
    "unchanged": "valid",
    "insert_lines": "relocated",
    "move_file": "relocated",
    "edit_target": "modified",
    "delete_file": "deleted",
    "duplicate_displaced": "ambiguous",
    "tamper_bundle": "invalid",
}
ACCEPTABLE = frozenset({"valid", "relocated"})


def transform(case: str, destination: Path, bundle: dict) -> dict:
    """Produce a fresh controlled root and tampered copy where requested."""
    if case not in EXPECTED:
        raise ValueError(f"Unknown case: {case}")
    destination.mkdir(parents=True, exist_ok=True)
    content = SOURCE
    paths = ["subject.py"]
    if case == "insert_lines":
        content = "# inserted header\n# second inserted line\n\n" + content
    elif case == "move_file":
        paths = ["moved/subject.py"]
    elif case == "edit_target":
        content = content.replace("total += value", "total += value * 2")
    elif case == "delete_file":
        paths = []
    elif case == "duplicate_displaced":
        paths = ["first/subject.py", "second/subject.py"]
    for relative in paths:
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    candidate = copy.deepcopy(bundle)
    if case == "tamper_bundle":
        candidate["entries"][0]["text"] += "# injected into stored evidence\n"
    return candidate


def path_line_accepts(entry: dict, root: Path) -> bool:
    """Strict exact text at the old path and line range; no relocation search."""
    path = root / entry["path"]
    if not path.is_file():
        return False
    content = path.read_bytes().decode("utf-8")
    # Independent editor-line oracle: Unicode separators remain inside a line.
    lines = re.split(r"(?<=\n)|(?<=\r)(?!\n)", content)
    if lines and lines[-1] == "":
        lines.pop()
    selected = "".join(lines[entry["start_line"] - 1:entry["end_line"]])
    return selected == entry["text"]


def file_hash_accepts(entry: dict, root: Path) -> bool:
    """File hash at old path; does not bind snippet content or recover moves."""
    path = root / entry["path"]
    return path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == entry["file_sha256"]


def binary_metrics(expected: list[bool], predicted: list[bool]) -> dict:
    if len(expected) != len(predicted):
        raise ValueError("Labels and predictions must have equal length")
    tp = sum(e and p for e, p in zip(expected, predicted))
    fp = sum(not e and p for e, p in zip(expected, predicted))
    tn = sum(not e and not p for e, p in zip(expected, predicted))
    fn = sum(e and not p for e, p in zip(expected, predicted))
    return {
        "n": len(expected), "true_positive": tp, "false_positive": fp,
        "true_negative": tn, "false_negative": fn,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "accuracy": (tp + tn) / len(expected) if expected else None,
    }


def retrieval_metrics(relevant_files: list[str], returned_files: list[str]) -> dict:
    """File-label recall and first relevant entry rank; no unlabeled precision."""
    relevant = set(relevant_files)
    matched = relevant.intersection(returned_files)
    rank = next((i for i, path in enumerate(returned_files, 1) if path in relevant), None)
    return {
        "file_recall": len(matched) / len(relevant) if relevant else None,
        "hit": bool(matched),
        "reciprocal_rank": 1 / rank if rank else 0.0,
        "first_relevant_entry_rank": rank,
    }
