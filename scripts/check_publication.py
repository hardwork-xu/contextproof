#!/usr/bin/env python3
"""Reject accidental personal paths or secrets in tracked publication files.

Optional --private-rules points outside the repository to a JSON list of personal
strings. Findings report locations and categories, never the matched secrets.
This is a publication guard, not a general-purpose credential scanner.
"""

import argparse
import json
from pathlib import Path
import re
import subprocess

PATTERNS = {
    "absolute personal directory": re.compile(r"/(?:Users|home)/[^/<>{}\s\"']+/"),
    "Windows personal directory": re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+[^<>\\/\s]+[\\/]"),
    "private key block": re.compile(r"^\s*-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{60,})\b"),
}


def findings(text, private_terms=()):
    found = []
    for number, line in enumerate(text.splitlines(), 1):
        for name, pattern in PATTERNS.items():
            if pattern.search(line):
                found.append((number, name))
        if any(term and term.casefold() in line.casefold() for term in private_terms):
            found.append((number, "private publication rule"))
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-rules", type=Path)
    args = parser.parse_args()
    private_terms = json.loads(args.private_rules.read_text()) if args.private_rules else []
    if not isinstance(private_terms, list) or not all(isinstance(term, str) for term in private_terms):
        raise ValueError("private rules must be a JSON string list")
    root = Path(__file__).resolve().parents[1]
    paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode().split("\0")
    count = 0
    for name in filter(None, paths):
        path = root / name
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for line, category in findings(content, private_terms):
            print(f"{name}:{line}: {category}")
            count += 1
    print(f"Publication scan: {count} finding(s).")
    return 1 if count else 0


if __name__ == "__main__":
    raise SystemExit(main())
