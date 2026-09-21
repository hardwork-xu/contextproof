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
    for name in ("index", "search", "bundle", "verify", "repair", "serve",
                 "capture", "check", "refresh", "report"):
        cmd = commands.add_parser(name)
        cmd.add_argument("root", type=Path, help="repository directory; source is never executed")
        if name in ("search", "bundle", "capture"):
            cmd.add_argument("query")
            cmd.add_argument("--method", choices=("bm25", "graph"),
                             default="bm25" if name == "capture" else "graph")
        if name == "search":
            cmd.add_argument("--limit", type=int, default=10)
        if name in ("bundle", "capture"):
            cmd.add_argument("--budget", type=int, default=4000)
            cmd.add_argument("--tokenizer", choices=("bytes", "cl100k_base", "o200k_base"),
                             default="bytes")
        if name in ("verify", "repair", "check", "refresh", "report"):
            cmd.add_argument("bundle", type=Path)
        if name in ("bundle", "repair"):
            cmd.add_argument("--format", choices=("json", "markdown"), default="json")
        if name != "serve":
            cmd.add_argument("--output", "-o", type=Path)
    render = commands.add_parser("render")
    render.add_argument("bundle", type=Path)
    render.add_argument("--output", "-o", type=Path)
    for name in ("graph-capture", "graph-refresh"):
        cmd = commands.add_parser(name)
        cmd.add_argument("root", type=Path)
        cmd.add_argument("query" if name == "graph-capture" else "artifact")
        cmd.add_argument("--ref", help="immutable Git commit/ref; default hashes the working tree")
        cmd.add_argument("--budget", type=int, default=16000)
        cmd.add_argument("--output", "-o", type=Path, required=True,
                         help="save full current graph separately from model-facing output")
        cmd.add_argument("--payload", type=Path, help="save exactly budgeted model-facing text")
        if name == "graph-capture":
            cmd.add_argument("--limit", type=int, default=1)
            cmd.add_argument("--depth", type=int, default=4)
            cmd.add_argument("--max-nodes", type=int, default=256)
        else:
            cmd.add_argument("--view", choices=("full", "update"), default="update")
            cmd.add_argument("--delta", type=Path, help="save lossless reconstruction delta")
    delta = commands.add_parser("graph-apply")
    delta.add_argument("base", type=Path)
    delta.add_argument("delta", type=Path)
    delta.add_argument("--output", "-o", type=Path, required=True)
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
        if args.command in {"graph-capture", "graph-refresh", "graph-apply"}:
            return _graph_command(args)
        if args.command == "serve":
            from .mcp import serve
            serve(args.root)
            return 0
        if args.command in ("capture", "check", "refresh", "report"):
            from .session import capture_context, check_context, refresh_context
            if args.command == "capture":
                result = capture_context(args.root, args.query, args.budget,
                                         args.method, args.tokenizer)
            else:
                context = read_bundle(args.bundle)
                if args.command == "refresh":
                    result = refresh_context(context, args.root)
                else:
                    result = check_context(context, args.root)
                    if args.command == "report":
                        from .report import render_report
                        result = render_report(context, result)
        elif args.command == "render":
            artifact = read_bundle(args.bundle)
            if artifact.get("kind") == "contextproof.context":
                from .session import validate_context
                validate_context(artifact)
                artifact = artifact["bundle"]
            result = render_bundle(artifact)
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
        if args.command == "check" and not result.get("can_reuse", False):
            return 1
        return 0
    except sqlite3.Error as exc:
        print(f"contextproof: index cache error: {exc}; if corrupt, remove "
              ".contextproof/index.sqlite3 and reindex", file=sys.stderr)
        return 2
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f"contextproof: {exc}", file=sys.stderr)
        return 2


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8")


def _graph_command(args):
    from .graph_delta import apply_graph_delta
    from .graph_session import GraphSession
    if args.command == "graph-apply":
        result = apply_graph_delta(read_bundle(args.base), read_bundle(args.delta))
        _write_json(args.output, result)
        print(json.dumps({"graph_id": result["id"], "reconstructed": True}))
        return 0
    with GraphSession(args.root) as session:
        if args.command == "graph-capture":
            result = session.capture(args.query, ref=args.ref, budget=args.budget,
                                     limit=args.limit, max_depth=args.depth, max_nodes=args.max_nodes)
        else:
            artifact = Path(args.artifact)
            before = read_bundle(artifact) if artifact.is_file() else args.artifact
            result = session.refresh(before, ref=args.ref, budget=args.budget, view=args.view)
    _write_json(args.output, result["graph"])
    if args.payload:
        args.payload.parent.mkdir(parents=True, exist_ok=True)
        args.payload.write_text(result["payload"]["rendered"], encoding="utf-8")
    if getattr(args, "delta", None):
        _write_json(args.delta, result["delta"])
    receipt = {"graph_id": result["graph"]["id"], "revision": result["revision"],
               "stats": result["stats"], "delivery": {
                   key: value for key, value in result["payload"].items() if key != "rendered"}}
    if "comparison" in result:
        receipt["comparison"] = result["comparison"]
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0 if result["payload"]["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
