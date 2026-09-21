"""Command-line interface; JSON artifacts contain no absolute repository paths."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from . import __version__
from .evidence import make_bundle, render_bundle, repair_bundle, verify_bundle
from .index import build_index
from .models import as_json
from .retrieval import search


def parser():
    p = argparse.ArgumentParser(description="Verifiable code context across repository changes")
    p.add_argument("--version", action="version", version=__version__)
    commands = p.add_subparsers(dest="command", required=True)
    for name in ("index", "search", "bundle", "verify", "repair", "serve"):
        cmd = commands.add_parser(name)
        cmd.add_argument("root", type=Path, help="repository directory; source is never executed")
        if name in ("search", "bundle"):
            cmd.add_argument("query")
            cmd.add_argument("--method", choices=("bm25", "graph"), default="graph")
        if name == "search":
            cmd.add_argument("--limit", type=int, default=10)
        if name == "bundle":
            cmd.add_argument("--budget", type=int, default=4000)
            cmd.add_argument("--tokenizer", choices=("bytes", "cl100k_base", "o200k_base"),
                             default="bytes")
        if name in ("verify", "repair"):
            cmd.add_argument("bundle", type=Path)
        if name in ("bundle", "repair"):
            cmd.add_argument("--format", choices=("json", "markdown"), default="json")
        if name != "serve":
            cmd.add_argument("--output", "-o", type=Path)
    render = commands.add_parser("render")
    render.add_argument("bundle", type=Path)
    render.add_argument("--output", "-o", type=Path)
    return p


def read_bundle(path):
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("bundle exceeds the 16 MiB input limit")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("bundle must be a JSON object")
    return data


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "serve":
            from .mcp import serve
            serve(args.root)
            return 0
        if args.command == "render":
            result = render_bundle(read_bundle(args.bundle))
        elif args.command in ("verify", "repair"):
            operation = verify_bundle if args.command == "verify" else repair_bundle
            result = operation(read_bundle(args.bundle), args.root)
        else:
            snapshot = build_index(args.root)
            if args.command == "index":
                result = {"snapshot_id": snapshot.id, "stats": snapshot.stats,
                          "files": len(snapshot.files), "chunks": len(snapshot.chunks),
                          "edges": len(snapshot.edges)}
            elif args.command == "search":
                result = [as_json(hit) for hit in search(snapshot, args.query,
                          method=args.method, limit=args.limit)]
            else:
                result = make_bundle(snapshot, args.query, budget=args.budget,
                                     method=args.method, tokenizer=args.tokenizer)
        if getattr(args, "format", None) == "markdown":
            result = render_bundle(result)
        output = result if isinstance(result, str) else json.dumps(
            result, ensure_ascii=False, indent=2, allow_nan=False)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output, encoding="utf-8")
        else:
            sys.stdout.write(output)
            if not isinstance(result, str):
                sys.stdout.write("\n")
        if args.command == "verify" and not result.get("valid", False):
            return 1
        return 0
    except sqlite3.Error as exc:
        print(f"contextproof: index cache error: {exc}; if corrupt, remove "
              ".contextproof/index.sqlite3 and reindex", file=sys.stderr)
        return 2
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f"contextproof: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
