"""Deterministic lexical retrieval and conservative, one-hop file expansion.

Graph edges are static dependency hints, not a compiler-resolved call graph. Scores
are ranking heuristics, not probabilities or claims of semantic relevance.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict

from .models import Hit, Snapshot


def terms(text: str) -> list[str]:
    """Retain exact identifiers and expose their snake/camel-case components."""
    result = []
    for word in re.findall(r"[^\W_]+(?:_[^\W_]+)*", text, flags=re.UNICODE):
        whole = word.lower()
        result.append(whole)
        expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", word)
        expanded = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", expanded)
        components = expanded.replace("_", " ").lower().split()
        if components != [whole]:
            result.extend(components)
    return result


def search(
    snapshot: Snapshot, query: str, method: str = "bm25", limit: int = 50
) -> list[Hit]:
    """Rank chunks; graph mode expands from lexical seeds by exactly one hop.

Each neighbor gets at most 15% of its strongest seed file score. Edges are
traversed in either direction because a caller or an imported module can supply
context. This is an explicit heuristic rather than evidence that the dependency
is required. Isolated, zero-overlap chunks are never returned by BM25.
    """
    if method not in {"bm25", "graph"}:
        raise ValueError("method must be 'bm25' or 'graph'")
    if not isinstance(query, str):
        raise ValueError("query must be a string")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
        raise ValueError("limit must be a non-negative integer")
    query_terms = sorted(set(terms(query)))
    if not query_terms or not snapshot.chunks or limit == 0:
        return []

    # A small, explicit lexical prior on paths and symbols is part of this
    # baseline. Keep it fixed across experiments and disclose it in reports.
    documents = [
        Counter(terms(chunk.text) + 2 * terms(chunk.symbol) + terms(chunk.path))
        for chunk in snapshot.chunks
    ]
    lengths = [sum(document.values()) for document in documents]
    average_length = sum(lengths) / len(lengths) or 1.0
    frequencies: Counter[str] = Counter()
    for document in documents:
        frequencies.update(document.keys())
    scores: dict[str, float] = {}
    reasons: dict[str, list[str]] = {}
    file_scores: dict[str, float] = defaultdict(float)
    for chunk, document, length in zip(snapshot.chunks, documents, lengths):
        score = 0.0
        matched = []
        for term in query_terms:
            frequency = document[term]
            if not frequency:
                continue
            idf = math.log(1.0 + (len(documents) - frequencies[term] + 0.5)
                           / (frequencies[term] + 0.5))
            denominator = frequency + 1.2 * (0.25 + 0.75 * length / average_length)
            score += idf * (frequency * 2.2) / denominator
            matched.append(term)
        scores[chunk.id] = score
        reasons[chunk.id] = ["lexical overlap: " + ", ".join(matched)] if matched else []
        file_scores[chunk.path] = max(file_scores[chunk.path], score)

    if method == "graph":
        neighbors: dict[str, set[str]] = defaultdict(set)
        for source, target in snapshot.edges:
            if source != target:
                neighbors[source].add(target)
                neighbors[target].add(source)
        # Only lexical scores seed expansion: graph-derived scores cannot walk
        # additional hops or feed back into the seed file.
        for chunk in snapshot.chunks:
            candidates = [(file_scores[path], path) for path in neighbors[chunk.path]
                          if file_scores[path] > 0]
            if candidates:
                seed_score, seed_path = sorted(candidates, key=lambda row: (-row[0], row[1]))[0]
                scores[chunk.id] += 0.15 * seed_score
                reasons[chunk.id].append(f"one-hop static dependency hint from {seed_path}")

    hits = [Hit(chunk, scores[chunk.id], tuple(reasons[chunk.id]))
            for chunk in snapshot.chunks if scores[chunk.id] > 0]
    return sorted(hits, key=lambda hit: (
        -hit.score, hit.chunk.path, hit.chunk.start_line, hit.chunk.id
    ))[:limit]
