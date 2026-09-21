"""Prompt schema and frozen-task readers independent of inference backends."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path


SYSTEM = (
    "You are reviewing Python repository behavior. Predict the result of the provided "
    "code using the supplied repository source as the project evidence. "
    "Return only one JSON object. If the code completes, use {\"value\": RESULT}, "
    "with RESULT converted to JSON. If the code raises before assigning RESULT, "
    "use {\"error\": \"ExceptionClassName\"}. Ignore uncaught warnings; "
    "warnings explicitly captured by the code are part of its result. "
    "Do not execute code, use tools, provide explanation, or include Markdown fences."
)


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def user_prompt(task: dict, context: str) -> str:
    # IDs, versions, dates, split, change family, test origins and oracle labels are
    # intentionally excluded. The code itself is the real engineering question.
    return (
        "Predict the exact JSON response for this code in the repository checkout.\n"
        "The code is run in Python 3.12 with deprecation warnings ignored, except "
        "when it explicitly captures warnings. No network operation is performed.\n\n"
        "Code:\n```python\n" + task["code"] + "```\n\n"
        "Repository source evidence:\n" + (context or "(No source evidence supplied.)")
    )


def source_records(root: Path, path: str) -> list[dict]:
    """Independent AST span extraction; does not consult ContextProof's resolver."""
    absolute = root / path
    if not absolute.is_file():
        return []
    source = absolute.read_text()
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    records = []

    def visit(nodes, prefix=""):
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = prefix + node.name
                first = min([node.lineno, *(d.lineno for d in node.decorator_list)])
                text = "".join(lines[first - 1:node.end_lineno])
                records.append({"path": path, "symbol": name, "start_line": first,
                                "end_line": node.end_lineno, "text": text,
                                "text_sha256": digest(text.encode())})
                visit(node.body, name + ".")
    visit(tree.body)
    return records


def load_frozen(directory: Path) -> tuple[dict, list[dict]]:
    protocol = json.loads((directory / "protocol.json").read_text())
    raw = (directory / "tasks.json").read_bytes()
    if digest(raw) != protocol["tasks_sha256"]:
        raise ValueError("frozen task bytes changed")
    return protocol, json.loads(raw)
