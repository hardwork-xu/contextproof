#!/usr/bin/env python3
"""Reproduce the preregistered v1 source-only drift study.

Frozen archive bytes are verified before safe regular-file staging. Upstream
code is never imported or executed. --check compares deterministic quality,
not timing observations. See docs/DRIFT_STUDY.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import statistics
import subprocess
import sys
import tarfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))
from benchmarks.v1.reference import (  # noqa: E402
    ACCEPTED, METHODS, annotate, at_lines, baselines, byte_matches, digest,
    line_offsets, paired_bootstrap, summarize,
)

DATA = ROOT / 'benchmarks/v1'
WORK = ROOT / 'work/v1-drift'
# Frozen corpus gate is intentionally independent of the engine implementation.
EXCLUDED_DIRS = frozenset('''.git .hg .svn .contextproof .venv venv env __pycache__
.pytest_cache .ruff_cache .mypy_cache node_modules vendor dist build target coverage
.next .nuxt .tox .nox .cache .idea .vscode .eggs site-packages htmlcov generated
_generated .ipynb_checkpoints work .ssh .aws .azure .gcloud .output .parcel-cache
.turbo .svelte-kit'''.split())


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def freeze_json(path: Path, value) -> None:
    """Freeze deterministic inputs; a changed input requires explicit investigation."""
    if path.exists():
        if json.loads(path.read_text()) != value:
            raise RuntimeError(f'Frozen input differs: {path}; investigate rather than overwriting')
    else:
        write_json(path, value)


def source_exclusion(path: str, raw: bytes, prefixes: list[str]) -> str | None:
    parts = PurePosixPath(path).parts
    name = parts[-1].lower()
    if not path.endswith('.py') or not any(path.startswith(prefix) for prefix in prefixes):
        return 'outside_library_python_prefixes'
    if any(p.lower() in EXCLUDED_DIRS or p.lower().endswith('.egg-info') for p in parts[:-1]):
        return 'excluded_directory'
    if any(marker in name for marker in ('credential', 'secret', 'private_key', 'private-key')) or name.startswith(('.env.', 'service-account', 'service_account')):
        return 'secret_like_filename'
    if name.endswith(('_pb2.py', '_pb2_grpc.py')):
        return 'generated_filename'
    if len(raw) > 2 * 1024 * 1024:
        return 'size_limit'
    if b'\0' in raw:
        return 'nul_bytes'
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        return 'non_utf8'
    if 'PRIVATE KEY-----' in text.upper():
        return 'private_key_header'
    offsets = line_offsets(raw)
    header = raw[:offsets[min(5, len(offsets) - 1)]].lower()
    if any(marker in header for marker in (b'@generated', b'automatically generated', b'do not edit')):
        return 'generated_header'
    return None


def prepare_sources(manifest: dict, download: bool) -> tuple[dict, dict]:
    roots, source_manifest = {}, {}
    archives = WORK / 'archives'
    archives.mkdir(parents=True, exist_ok=True)
    for repository in manifest['repositories']:
        name = repository['name']
        source_manifest[name] = {}
        for side, version in repository['versions'].items():
            archive = archives / f"{name}-{version['commit']}.tar.gz"
            if not archive.exists():
                if not download:
                    raise RuntimeError(f'Missing {archive.name}; rerun with --download')
                subprocess.run(['curl', '--fail', '--location', '--silent', '--show-error',
                                '--connect-timeout', '30', '--max-time', '180',
                                '--output', str(archive), version['archive_url']], check=True)
            if digest(archive.read_bytes()) != version['archive_sha256']:
                raise RuntimeError(f'Archive digest mismatch: {archive.name}')
            output = WORK / 'sources' / name / side
            if output.exists():
                shutil.rmtree(output)
            output.mkdir(parents=True)
            accepted, excluded = {}, []
            with tarfile.open(archive, 'r:gz') as tar:
                for member in tar:
                    path = PurePosixPath(member.name)
                    if path.is_absolute() or '..' in path.parts or not path.parts:
                        raise RuntimeError(f'Unsafe archive member: {member.name}')
                    if path.parts[0] != f"{name}-{version['commit']}":
                        raise RuntimeError(f'Unexpected archive prefix: {member.name}')
                    if not member.isfile():
                        continue
                    relative = '/'.join(path.parts[1:])
                    # Skip large non-Python assets without reading their contents.
                    if not relative.endswith('.py') or not any(relative.startswith(p) for p in repository['prefixes']):
                        continue
                    stream = tar.extractfile(member)
                    if stream is None:
                        raise RuntimeError(f'Unreadable archive member: {member.name}')
                    raw = stream.read()
                    reason = source_exclusion(relative, raw, repository['prefixes'])
                    if reason:
                        excluded.append({'path': relative, 'sha256': digest(raw), 'reason': reason})
                        continue
                    if relative in accepted:
                        raise RuntimeError(f'Duplicate archive member: {relative}')
                    target = output / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(raw)
                    accepted[relative] = digest(raw)
            if not accepted:
                raise RuntimeError(f'No source files for {name} {side}')
            source_manifest[name][side] = {
                'files': dict(sorted(accepted.items())), 'excluded_python_files': sorted(excluded, key=lambda r: r['path']),
                'accepted_files': len(accepted), 'accepted_bytes': sum((output / p).stat().st_size for p in accepted),
                'manifest_sha256': digest(json.dumps(accepted, sort_keys=True, separators=(',', ':')).encode()),
            }
            roots[name, side] = output
    frozen = {'schema_version': 1, 'manifest_sha256': digest((DATA / 'manifest.json').read_bytes()),
              'policy': 'Frozen library-only Python corpus, shared by reference and all evaluated methods.',
              'repositories': source_manifest}
    freeze_json(DATA / 'source_manifests.json', frozen)
    return roots, frozen


def load_corpus(root: Path, manifest: dict) -> dict[str, bytes]:
    corpus = {path: (root / path).read_bytes() for path in manifest['files']}
    if {path: digest(raw) for path, raw in corpus.items()} != manifest['files']:
        raise RuntimeError('Staged source files differ from frozen accepted source manifest')
    return corpus


def sample_before(repository: dict, snapshot, corpus: dict[str, bytes], protocol: dict) -> tuple[list, int]:
    sampling = protocol['sample']
    candidates = []
    for chunk in snapshot.chunks:
        raw = chunk.text.encode('utf-8')
        if len(line_offsets(raw)) - 1 < sampling['min_lines'] or len(raw) > sampling['max_bytes']:
            continue
        if at_lines(corpus[chunk.path], chunk.start_line, chunk.end_line) != raw:
            raise RuntimeError('Indexed chunk is not exact before-version source')
        if len(byte_matches(corpus, raw)) != 1:
            continue
        key = '\0'.join((sampling['seed'], repository['name'], chunk.path, str(chunk.start_line), digest(raw)))
        candidates.append((digest(key.encode()), chunk))
    candidates.sort(key=lambda pair: pair[0])
    size = sampling['per_repository']
    if len(candidates) < size:
        raise RuntimeError(f"{repository['name']} has only {len(candidates)} eligible snippets, expected {size}; record protocol amendment before proceeding")
    return candidates[:size], len(candidates)


def implementation_digest() -> str:
    paths = sorted([*ROOT.glob('src/contextproof/*.py'), *DATA.glob('*.py'),
                    ROOT / 'scripts/run_drift_benchmarks.py'])
    value = hashlib.sha256()
    for path in paths:
        value.update(path.relative_to(ROOT).as_posix().encode() + b'\0')
        value.update(path.read_bytes())
    return value.hexdigest()


def measure_cache(name: str, before: Path, after: Path, expected: dict, repeats: int) -> dict:
    from contextproof.index import build_index
    observations = []
    for repeat in range(repeats):
        cache = WORK / 'cache' / f'{name}-{repeat}.sqlite3'
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.unlink(missing_ok=True)
        row = {'repeat': repeat + 1}
        for phase, root, side in [('cold', before, 'before'), ('warm', before, 'before'), ('changed_version', after, 'after')]:
            start = time.perf_counter()
            snapshot = build_index(root, cache)
            seconds = time.perf_counter() - start
            if snapshot.files != expected[side]['files']:
                raise RuntimeError(f'Engine/source-policy corpus mismatch: {name} {side}')
            row[phase] = {'seconds': seconds, 'stats': snapshot.stats}
        observations.append(row)
    return {'repository': name, 'runs': observations,
            'median_seconds': {phase: statistics.median(row[phase]['seconds'] for row in observations)
                               for phase in ('cold', 'warm', 'changed_version')}}


def prepare_samples(manifest: dict, protocol: dict, roots: dict, source_manifests: dict) -> tuple[dict, dict, list]:
    from contextproof.index import build_index
    snapshots, entries, frozen = {}, {}, []
    for repository in manifest['repositories']:
        name = repository['name']
        before_manifest = source_manifests['repositories'][name]['before']
        before = load_corpus(roots[name, 'before'], before_manifest)
        snapshot = build_index(roots[name, 'before'], WORK / 'sampling-cache' / f'{name}.sqlite3')
        if snapshot.files != before_manifest['files']:
            raise RuntimeError(f'Engine/source-policy corpus mismatch: {name} before')
        selected, eligible = sample_before(repository, snapshot, before, protocol)
        snapshots[name] = snapshot
        entries[name] = selected
        for key, chunk in selected:
            frozen.append({'sample_id': key, 'repository': name, 'split': repository['split'],
                           'path': chunk.path, 'symbol': chunk.symbol, 'kind': chunk.kind,
                           'start_line': chunk.start_line, 'end_line': chunk.end_line,
                           'text_sha256': digest(chunk.text.encode()), 'file_sha256': chunk.file_sha256,
                           'before_commit': repository['versions']['before']['commit'],
                           'after_commit': repository['versions']['after']['commit'],
                           'eligible_before_chunks': eligible})
        print(f'Frozen before-only sample {name}: {len(selected)} / {eligible} eligible', flush=True)
    freeze_json(DATA / 'samples.json', {'schema_version': 1, 'preregistration_sha256': digest((DATA / 'preregistration.json').read_bytes()), 'samples': frozen})
    return snapshots, entries, frozen


def prepare_review(rows: list[dict], manifest: dict) -> None:
    selected = {}
    for name in sorted({r['repository'] for r in rows}):
        for row in sorted((r for r in rows if r['repository'] == name), key=lambda r: digest(('review\0' + r['sample_id']).encode()))[:2]:
            selected[row['sample_id']] = row
    for status in sorted({r['reference']['status'] for r in rows}):
        for row in sorted((r for r in rows if r['reference']['status'] == status), key=lambda r: digest(('review\0' + r['sample_id']).encode()))[:2]:
            selected[row['sample_id']] = row
    packet = []
    repo_lookup = {r['name']: r for r in manifest['repositories']}
    for row in sorted(selected.values(), key=lambda r: r['sample_id']):
        repository = repo_lookup[row['repository']]
        packet.append({key: row[key] for key in ('sample_id', 'repository', 'path', 'start_line', 'end_line', 'text_sha256', 'file_sha256')} | {
            'before_source_root': f"work/v1-drift/sources/{row['repository']}/before",
            'after_source_root': f"work/v1-drift/sources/{row['repository']}/after",
            'before_commit': repository['versions']['before']['commit'],
            'after_commit': repository['versions']['after']['commit'],
        })
    freeze_json(DATA / 'review_packet.json', {
        'disclosure': 'Blinded AI reviewer packet; neither automated labels nor engine predictions are included. Source bytes stay in ignored work/. No human ground truth claimed.',
        'instructions': 'Using only this packet and frozen source bytes, assign valid/relocated/ambiguous/modified/deleted under the contract in preregistration.json. Do not read reference.py, annotations.json, first_run_audit.json or results/. Return sample_id, status, occurrence coordinates, reasoning and reviewer disclosure.',
        'samples': packet,
    })


def markdown_report(result: dict) -> str:
    quality = result['quality']
    lines = ['# v1 measured drift study', '',
             'Generated by `python scripts/run_drift_benchmarks.py --download`. '
             'See [protocol](../../../docs/DRIFT_STUDY.md), [frozen selection](../preregistration.json), '
             '[all annotation rows](../annotations.json), and [full result](latest.json).', '',
             '**Scope limitation:** 23 of 29 primary `deleted` labels are dateutil test snippets that moved outside the frozen library prefixes and remain uniquely recoverable elsewhere in the newer archive. See [posthoc full-scope sensitivity](scope-sensitivity.md); these are corpus exits, not upstream deletions.', '',
             '**Automated reference annotation with blinded AI review; not human ground truth.** '
             'Exact-byte provenance only. The engine and reference implement the same stated contract with separate matching code. '
             'A [sealed blinded AI review](../ai_review.json) of 21 purposively selected items agrees with the frozen labels on 21/21 items; '
             'see the [comparison](../review_comparison.json). This is not a human-labeled error-rate estimate.', '',
             '| Repository | Split | N | Reference status counts | Engine agreement |',
             '| --- | --- | ---: | --- | ---: |']
    for row in quality['repositories']:
        counts = ', '.join(f'{k}={v}' for k, v in row['summary']['reference_status_counts'].items())
        lines.append(f"| {row['repository']} | {row['split']} | {row['summary']['n']} | {counts} | {row['summary']['status_agreement']:.3f} |")
    for split in ('all', 'development', 'holdout'):
        summary = quality['splits'][split]
        lines += ['', f'## {split.title()} acceptance', '',
                  '| Method | TP | FP | TN | FN | Accuracy | Precision | Recall | False acceptance rate |',
                  '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
        for method in METHODS:
            score = summary['methods'][method]
            cells = [str(score[key]) for key in ('true_positive', 'false_positive', 'true_negative', 'false_negative')]
            cells += ['undefined' if score[key] is None else f'{score[key]:.3f}' for key in ('accuracy', 'precision', 'recall', 'false_acceptance_rate')]
            lines.append(f"| {method} | {' | '.join(cells)} |")
    lines += ['', '## Paired repository-cluster bootstrap', '',
              'Macro repository accuracy difference (ContextProof minus baseline), 5000 seeded resamples. '
              'Only ten convenience-sampled repository clusters, with three in holdout: descriptive intervals, '
              'not evidence of performance on an unseen population.', '',
              '| Split | Clusters | Baseline | Difference | 95% percentile interval |',
              '| --- | ---: | --- | ---: | --- |']
    for split, bootstrap in quality['bootstrap'].items():
        for method, values in bootstrap['differences'].items():
            lower, upper = values['percentile_95_interval']
            lines.append(f"| {split} | {bootstrap['clusters']} | {method} | {values['mean_accuracy_difference']:.3f} | [{lower:.3f}, {upper:.3f}] |")
    lines += ['', '## Repeated local cache observations', '',
              'Three repetitions each: fresh cache, immediate same-version warm scan, changed-version scan sharing '
              'that cache. Medians below; raw times and parsed/reused counts are in JSON. Hashing and I/O still happen '
              'on warm scans. These local observations do not promise acceleration.', '',
              '| Repository | Cold seconds | Warm seconds | Changed-version seconds |',
              '| --- | ---: | ---: | ---: |']
    for row in result['observations']['cache']:
        times = row['median_seconds']
        lines.append(f"| {row['repository']} | {times['cold']:.6f} | {times['warm']:.6f} | {times['changed_version']:.6f} |")
    lines += ['', f"Engine/reference disagreements: {len(quality['mismatches'])}. "
              'First-run evidence is preserved in [first_run_audit.json](../first_run_audit.json).', '',
              'No upstream source was executed. No model task-completion, semantic preservation, general retrieval '
              'superiority, or security effectiveness is measured. Before-only uniqueness filtering and the library-only '
              'corpus reduce generality; all ten projects are Python libraries and three are HTTP-related. '
              'Natural drift may contain no ambiguity or deleted-file cases; controlled tests cover those cases separately.', '',
              f"Measured: {result['observations']['generated_at_utc']}; Python {result['observations']['python']}; {result['observations']['platform']}.", '']
    return '\n'.join(lines)


def run(download: bool, output: Path, check: Path | None = None, prepare_only: bool = False) -> dict:
    from contextproof.evidence import make_bundle, verify_bundle
    from contextproof.models import Snapshot
    protocol = json.loads((DATA / 'preregistration.json').read_text())
    manifest = json.loads((DATA / 'manifest.json').read_text())
    if manifest['preregistration_sha256'] != digest((DATA / 'preregistration.json').read_bytes()):
        raise RuntimeError('Preregistration changed after archive freeze')
    if len({r['github'].split('/')[0] for r in manifest['repositories']}) < 10:
        raise RuntimeError('Need at least ten different GitHub owners')
    roots, source_manifests = prepare_sources(manifest, download)
    snapshots, entries, frozen = prepare_samples(manifest, protocol, roots, source_manifests)
    by_id = {row['sample_id']: row for row in frozen}
    rows, per_repo, timings = [], [], []
    # Freeze every reference annotation before asking the engine for any predictions.
    annotation_rows = []
    for repository in manifest['repositories']:
        name = repository['name']
        after = load_corpus(roots[name, 'after'], source_manifests['repositories'][name]['after'])
        for key, chunk in entries[name]:
            entry = {'path': chunk.path, 'start_line': chunk.start_line, 'end_line': chunk.end_line,
                     'text': chunk.text, 'file_sha256': chunk.file_sha256}
            reference = annotate(entry, after)
            annotation_rows.append(by_id[key] | {'reference': reference,
                'after_original_file_sha256': digest(after[chunk.path]) if chunk.path in after else None,
                'after_corpus_manifest_sha256': source_manifests['repositories'][name]['after']['manifest_sha256']})
    freeze_json(DATA / 'annotations.json', {'disclosure': 'Automated byte-location reference annotation, not independent human ground truth.', 'samples': annotation_rows})
    prepare_review(annotation_rows, manifest)
    if prepare_only:
        print('Source manifests, before-only samples, annotations and blinded review packet frozen.', flush=True)
        return {'prepared': True}
    annotations = {row['sample_id']: row for row in annotation_rows}
    for repository in manifest['repositories']:
        name = repository['name']
        snapshot = snapshots[name]
        selected = [chunk for _, chunk in entries[name]]
        reduced = Snapshot(snapshot.id, snapshot.files, selected, [], {})
        query = ' '.join(sorted({chunk.path for chunk in selected}))
        bundle = make_bundle(reduced, query, budget=1000000, method='bm25', tokenizer='bytes')
        if {entry['id'] for entry in bundle['entries']} != {chunk.id for chunk in selected}:
            raise RuntimeError('Sampling bundle must retain every selected chunk exactly once')
        report = verify_bundle(bundle, roots[name, 'after'])
        results = {row['entry_id']: row for row in report['results']}
        after = load_corpus(roots[name, 'after'], source_manifests['repositories'][name]['after'])
        repo_rows = []
        for key, chunk in entries[name]:
            entry = {'path': chunk.path, 'start_line': chunk.start_line, 'end_line': chunk.end_line,
                     'text': chunk.text, 'file_sha256': chunk.file_sha256}
            status = results[chunk.id]['status']
            row = annotations[key] | {'engine_status': status,
                'predictions': baselines(entry, after) | {'contextproof': status in ACCEPTED}}
            rows.append(row)
            repo_rows.append(row)
        per_repo.append({'repository': name, 'split': repository['split'], 'summary': summarize(repo_rows)})
        timings.append(measure_cache(name, roots[name, 'before'], roots[name, 'after'], source_manifests['repositories'][name], protocol['cache']['repeats']))
        print(f"Evaluated {name}: {dict(Counter(r['reference']['status'] for r in repo_rows))}", flush=True)
    subsets = {'all': rows, 'development': [r for r in rows if r['split'] == 'development'],
               'holdout': [r for r in rows if r['split'] == 'holdout']}
    mismatches = [{'sample_id': row['sample_id'], 'repository': row['repository'],
                   'reference_status': row['reference']['status'], 'engine_status': row['engine_status']}
                  for row in rows if row['reference']['status'] != row['engine_status']]
    quality = {'repositories': per_repo, 'splits': {name: summarize(group) for name, group in subsets.items()},
               'bootstrap': {name: paired_bootstrap(group) for name, group in subsets.items()},
               'samples': rows, 'mismatches': mismatches}
    first_run = DATA / 'first_run_audit.json'
    if not first_run.exists():
        write_json(first_run, {'generated_at_utc': datetime.now(timezone.utc).isoformat(),
                              'implementation_sha256': implementation_digest(),
                              'annotations_sha256': digest((DATA / 'annotations.json').read_bytes()),
                              'disclosure': 'First engine predictions against frozen automated reference; preserved without overwriting.',
                              'mismatches': mismatches,
                              'predictions': [{'sample_id': r['sample_id'], 'engine_status': r['engine_status'],
                                               'reference_status': r['reference']['status']} for r in rows]})
    result = {'schema_version': 1,
              'provenance': {file.removesuffix('.json') + '_sha256': digest((DATA / file).read_bytes()) for file in ('preregistration.json', 'protocol_amendments.json', 'manifest.json', 'source_manifests.json', 'samples.json', 'annotations.json', 'review_packet.json')} | {'implementation_sha256': implementation_digest()},
              'quality': quality,
              'observations': {'generated_at_utc': datetime.now(timezone.utc).isoformat(),
                               'python': platform.python_version(), 'platform': platform.platform(),
                               'machine': platform.machine(), 'cache': timings}}
    if check:
        previous = json.loads(check.read_text())
        if previous['quality'] != quality:
            raise RuntimeError('Deterministic quality differs from comparison report')
        print('Deterministic quality matches comparison report.', flush=True)
    write_json(output / 'latest.json', result)
    (output / 'latest.md').write_text(markdown_report(result), encoding='utf-8')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--download', action='store_true')
    parser.add_argument('--output', type=Path, default=DATA / 'results')
    parser.add_argument('--check', type=Path)
    parser.add_argument('--prepare-only', action='store_true', help='Freeze inputs and annotation/review packet before engine predictions')
    args = parser.parse_args()
    run(args.download, args.output, args.check, args.prepare_only)


if __name__ == '__main__':
    main()
