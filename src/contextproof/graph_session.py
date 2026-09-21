"""Versioned evidence sessions with stored handles and budgeted delivery."""

from dataclasses import asdict
import hashlib
from pathlib import Path

from .graph import build_graph, compare_graphs, validate_graph
from .graph_delta import make_graph_delta
from .graph_payload import render_graph_context, render_graph_update
from .index import _parse_file
from .models import Snapshot
from .parse_cache import ParseCache
from .retrieval import search
from .revisions import SourceStore, read_revision


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def select_anchors(revision, query, limit=1):
    """BM25 selects Python declarations; the graph expands their actual source."""
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("anchor limit must be between 1 and 100")
    chunks = []
    files = {}
    for path, source in sorted(revision.texts.items()):
        if Path(path).suffix.lower() not in {".py", ".pyi"}:
            continue
        files[path] = _sha(source)
        parsed, _ = _parse_file(path, source, files[path])
        chunks.extend(parsed)
    snapshot = Snapshot(revision.snapshot_id, files, chunks, [], {})
    anchors, seen = [], set()
    for hit in search(snapshot, query, method="bm25", limit=len(chunks) or 1):
        chunk = hit.chunk
        key = (chunk.path, chunk.symbol, chunk.kind)
        if key in seen:
            continue
        seen.add(key)
        anchors.append({**asdict(chunk), "text_sha256": _sha(chunk.text)})
        if len(anchors) == limit:
            break
    if not anchors:
        raise ValueError("no Python source anchors found for this query")
    return anchors


def graph_anchors(graph):
    """Rebase a saved identity onto its last observed complete declaration."""
    validate_graph(graph)
    anchors = []
    for row in graph["anchors"]:
        node = graph["nodes"].get(row["node_id"])
        if node is None:
            node = {"path": row["path"], "symbol": row["symbol"], "kind": row["kind"],
                    "start_line": 1, "end_line": 1, "text": "# unavailable source\n",
                    "text_sha256": _sha("# unavailable source\n")}
        anchors.append({**node, "id": row["entry_id"], "file_sha256": _sha(node["text"])})
    return anchors


class GraphSession:
    """One local source store; immutable Git or freshly hashed working-tree reads.

    Stored handles keep full evidence out of MCP responses. Successful model
    responses consist only of the already-budgeted renderer string. AST reuse
    reduces parsing; module catalogs and resolutions are rebuilt each update.
    """

    def __init__(self, root, *, cache_path=None, git_executable=None, cache=True,
                 persistent_ast_cache=False):
        self.root = Path(root)
        self.store = SourceStore(cache_path or self.root / ".contextproof/revisions.sqlite")
        # Disk AST encoding was slower than a shared fresh parse cache in the
        # measured release-pair study. Keep it explicit and use memory by default.
        self.parsed = ParseCache(self.store if cache and persistent_ast_cache else None)
        self.git_executable = git_executable

    def _read(self, ref):
        return read_revision(self.root, ref, self.store, self.git_executable)

    def capture(self, query, *, ref=None, budget=16000, limit=1, max_depth=4, max_nodes=256,
                anchors=None):
        revision = self._read(ref)
        selected = anchors if anchors is not None else select_anchors(revision, query, limit)
        graph = build_graph(revision.texts, revision.snapshot_id, selected,
                            max_depth=max_depth, max_nodes=max_nodes, parsed_cache=self.parsed)
        self.store.save_graph(graph)
        return {"graph": graph, "payload": render_graph_context(graph, budget),
                "revision": {"kind": revision.kind, "identity": revision.revision},
                "stats": {**revision.stats, **self.parsed.stats}}

    def refresh(self, before, *, ref=None, budget=16000, view="update"):
        if view not in {"update", "full"}:
            raise ValueError("graph view must be update or full")
        old = self.store.load_graph(before) if isinstance(before, str) else before
        validate_graph(old)
        revision = self._read(ref)
        current = build_graph(revision.texts, revision.snapshot_id, graph_anchors(old),
                              max_depth=old["policy"]["max_depth"],
                              max_nodes=old["policy"]["max_nodes"], parsed_cache=self.parsed)
        comparison = compare_graphs(old, current)
        self.store.save_graph(current)
        payload = (render_graph_context(current, budget) if view == "full" else
                   render_graph_update(old, current, comparison, budget))
        return {"graph": current, "comparison": comparison, "payload": payload,
                "delta": make_graph_delta(old, current),
                "revision": {"kind": revision.kind, "identity": revision.revision},
                "stats": {**revision.stats, **self.parsed.stats}}

    def close(self):
        self.store.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
