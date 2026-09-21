"""Independent byte-location reference annotation, deliberately no engine imports.

This is automated contract checking, not independent human or semantic ground
truth. Matching operates on byte offsets and editor line boundaries, rather than
ContextProof's text-line window implementation.
"""
from __future__ import annotations

import hashlib
import random
from collections import Counter

ACCEPTED = frozenset({'valid', 'relocated'})
METHODS = ('path_exists_and_line_range', 'path_line_exact', 'file_hash', 'contextproof')
STATUSES = ('valid', 'relocated', 'ambiguous', 'modified', 'deleted', 'invalid')


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def line_offsets(raw: bytes) -> list[int]:
    """Offsets [start-of-line, ..., EOF], treating CRLF as one terminator."""
    offsets = [0]
    cursor = 0
    while cursor < len(raw):
        value = raw[cursor]
        cursor += 1
        if value == 13 and cursor < len(raw) and raw[cursor] == 10:
            cursor += 1
        if value in (10, 13):
            offsets.append(cursor)
    if offsets[-1] != len(raw):
        offsets.append(len(raw))
    return offsets


def at_lines(raw: bytes, start: int, end: int) -> bytes | None:
    offsets = line_offsets(raw)
    if not 1 <= start <= end < len(offsets):
        return None
    return raw[offsets[start - 1]:offsets[end]]


def byte_matches(corpus: dict[str, bytes], snippet: bytes) -> list[dict]:
    """Find substring occurrences, then require whole editor-line boundaries."""
    if not snippet:
        raise ValueError('Reference snippets must be nonempty')
    found = []
    for path, raw in sorted(corpus.items()):
        offset = raw.find(snippet)
        if offset == -1:
            continue
        boundaries = {value: index for index, value in enumerate(line_offsets(raw))}
        while offset != -1:
            finish = offset + len(snippet)
            if offset in boundaries and finish in boundaries:
                found.append({'path': path, 'start_line': boundaries[offset] + 1,
                              'end_line': boundaries[finish]})
            offset = raw.find(snippet, offset + 1)
    return found


def annotate(entry: dict, corpus: dict[str, bytes]) -> dict:
    snippet = entry['text'].encode('utf-8')
    original = corpus.get(entry['path'])
    matches = byte_matches(corpus, snippet)
    if original is not None and at_lines(original, entry['start_line'], entry['end_line']) == snippet:
        status = 'valid'
    elif len(matches) == 1:
        status = 'relocated'
    elif len(matches) > 1:
        status = 'ambiguous'
    else:
        status = 'modified' if original is not None else 'deleted'
    return {'status': status, 'accept': status in ACCEPTED,
            'whole_line_occurrences': len(matches), 'matches': matches}


def baselines(entry: dict, corpus: dict[str, bytes]) -> dict[str, bool]:
    raw = corpus.get(entry['path'])
    selected = None if raw is None else at_lines(raw, entry['start_line'], entry['end_line'])
    return {
        'path_exists_and_line_range': selected is not None,
        'path_line_exact': selected == entry['text'].encode('utf-8'),
        'file_hash': raw is not None and digest(raw) == entry['file_sha256'],
    }


def binary_metrics(truth: list[bool], predictions: list[bool]) -> dict:
    if len(truth) != len(predictions):
        raise ValueError('Truth and predictions have different lengths')
    counts = Counter((a, b) for a, b in zip(truth, predictions))
    tp, fp = counts[True, True], counts[False, True]
    tn, fn = counts[False, False], counts[True, False]
    n = len(truth)
    return {'n': n, 'true_positive': tp, 'false_positive': fp,
            'true_negative': tn, 'false_negative': fn,
            'accuracy': (tp + tn) / n if n else None,
            'precision': tp / (tp + fp) if tp + fp else None,
            'recall': tp / (tp + fn) if tp + fn else None,
            'false_acceptance_rate': fp / (fp + tn) if fp + tn else None}


def summarize(rows: list[dict]) -> dict:
    truth = [row['reference']['accept'] for row in rows]
    matrix = {label: {other: 0 for other in STATUSES} for label in STATUSES}
    for row in rows:
        matrix[row['reference']['status']][row['engine_status']] += 1
    return {
        'n': len(rows),
        'reference_status_counts': dict(sorted(Counter(r['reference']['status'] for r in rows).items())),
        'engine_status_counts': dict(sorted(Counter(r['engine_status'] for r in rows).items())),
        'status_confusion_matrix': matrix,
        'status_agreement': sum(r['reference']['status'] == r['engine_status'] for r in rows) / len(rows) if rows else None,
        'methods': {method: binary_metrics(truth, [r['predictions'][method] for r in rows]) for method in METHODS},
    }


def paired_bootstrap(rows: list[dict], repeats: int = 5000, seed: int = 20260921) -> dict:
    """Paired accuracy difference, sampling whole repository clusters equally."""
    names = sorted({row['repository'] for row in rows})
    if not names:
        raise ValueError('Bootstrap needs repository clusters')
    grouped = {name: [row for row in rows if row['repository'] == name] for name in names}
    differences = {}
    for method in METHODS[:-1]:
        per_repo = {}
        for name, selected in grouped.items():
            per_repo[name] = sum(
                int(row['predictions']['contextproof'] == row['reference']['accept'])
                - int(row['predictions'][method] == row['reference']['accept'])
                for row in selected
            ) / len(selected)
        rng = random.Random(seed)
        draws = sorted(sum(per_repo[rng.choice(names)] for _ in names) / len(names) for _ in range(repeats))
        differences[method] = {
            'mean_accuracy_difference': sum(per_repo.values()) / len(names),
            'percentile_95_interval': [draws[int(0.025 * (repeats - 1))], draws[int(0.975 * (repeats - 1))]],
        }
    return {'unit': 'repository', 'clusters': len(names), 'repeats': repeats,
            'seed': seed, 'estimand': 'macro repository acceptance-accuracy difference, ContextProof minus baseline',
            'differences': differences}
