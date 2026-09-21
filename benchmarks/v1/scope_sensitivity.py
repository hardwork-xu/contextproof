"""Post-result corpus-scope sensitivity on the same frozen 300 sampled snippets.

Motivated by dateutil moving embedded tests outside the original library prefixes.
Stages all policy-eligible Python files in separate work/ directories. Does not
change primary samples, labels, predictions, source directories, or metrics.
"""
from __future__ import annotations

import argparse
import json
import shutil
import tarfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from benchmarks.v1.reference import ACCEPTED, annotate, at_lines, baselines, digest, summarize
from scripts.run_drift_benchmarks import (
    DATA, WORK, freeze_json, implementation_digest, source_exclusion, write_json,
)


def run(check: Path | None = None) -> dict:
    from contextproof.evidence import make_bundle, verify_bundle
    from contextproof.index import build_index
    from contextproof.models import Snapshot
    manifest = json.loads((DATA / 'manifest.json').read_text())
    primary = json.loads((DATA / 'results/latest.json').read_text())
    samples = json.loads((DATA / 'samples.json').read_text())['samples']
    old_rows = {row['sample_id']: row for row in primary['quality']['samples']}
    manifests, roots = {}, {}
    for repository in manifest['repositories']:
        name = repository['name']
        manifests[name] = {}
        for side, version in repository['versions'].items():
            archive = WORK / 'archives' / f"{name}-{version['commit']}.tar.gz"
            if digest(archive.read_bytes()) != version['archive_sha256']:
                raise RuntimeError('Archive digest mismatch in sensitivity study')
            root = WORK / 'sensitivity' / name / side
            if root.exists():
                shutil.rmtree(root)
            root.mkdir(parents=True)
            files, excluded = {}, []
            with tarfile.open(archive, 'r:gz') as tar:
                for member in tar:
                    path = PurePosixPath(member.name)
                    if path.is_absolute() or '..' in path.parts or path.parts[0] != f"{name}-{version['commit']}":
                        raise RuntimeError('Unsafe archive path in sensitivity study')
                    if not member.isfile():
                        continue
                    relative = '/'.join(path.parts[1:])
                    if not relative.endswith('.py'):
                        continue
                    stream = tar.extractfile(member)
                    if stream is None:
                        raise RuntimeError('Unreadable archive member')
                    raw = stream.read()
                    reason = source_exclusion(relative, raw, [''])
                    if reason:
                        excluded.append({'path': relative, 'sha256': digest(raw), 'reason': reason})
                        continue
                    if relative in files:
                        raise RuntimeError('Duplicate archive member')
                    target = root / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(raw)
                    files[relative] = digest(raw)
            roots[name, side] = root
            manifests[name][side] = {'files': dict(sorted(files.items())),
                'excluded_python_files': sorted(excluded, key=lambda row: row['path']),
                'accepted_files': len(files), 'accepted_bytes': sum((root / path).stat().st_size for path in files)}
    freeze_json(DATA / 'sensitivity_source_manifests.json', {
        'disclosure': 'Post-result all-Python-file source scope; separate from preregistered library-prefix corpus. Same original archive hashes and same source safety/content gates.',
        'repositories': manifests,
    })
    reference_rows, pending = [], {}
    for repository in manifest['repositories']:
        name = repository['name']
        before, after = roots[name, 'before'], roots[name, 'after']
        after_corpus = {path: (after / path).read_bytes() for path in manifests[name]['after']['files']}
        selected = [sample for sample in samples if sample['repository'] == name]
        snapshot = build_index(before, WORK / 'sensitivity-cache' / f'{name}-before.sqlite3')
        after_snapshot = build_index(after, WORK / 'sensitivity-cache' / f'{name}-after.sqlite3')
        if snapshot.files != manifests[name]['before']['files'] or after_snapshot.files != manifests[name]['after']['files']:
            raise RuntimeError(f'Engine/reference scope mismatch in {name} sensitivity')
        by_span = {(chunk.path, chunk.start_line, chunk.end_line): chunk for chunk in snapshot.chunks}
        chunks = []
        for sample in selected:
            chunk = by_span[sample['path'], sample['start_line'], sample['end_line']]
            if digest(chunk.text.encode()) != sample['text_sha256']:
                raise RuntimeError('Sensitivity sample no longer matches frozen before bytes')
            raw = (before / sample['path']).read_bytes()
            if at_lines(raw, sample['start_line'], sample['end_line']) != chunk.text.encode():
                raise RuntimeError('Wrong sensitivity sample source')
            entry = {'path': sample['path'], 'start_line': sample['start_line'], 'end_line': sample['end_line'],
                     'text': chunk.text, 'file_sha256': sample['file_sha256']}
            reference_rows.append(sample | {'reference': annotate(entry, after_corpus),
                'predictions': baselines(entry, after_corpus)})
            chunks.append(chunk)
        pending[name] = (snapshot, chunks, selected)
    freeze_json(DATA / 'sensitivity_annotations.json', {'disclosure': 'Automated byte-location reference frozen before full-scope engine predictions; same300 primary samples. Posthoc sensitivity, not new holdout evidence.', 'samples': reference_rows})
    lookup = {row['sample_id']: row for row in reference_rows}
    rows, changes, repositories = [], [], []
    for repository in manifest['repositories']:
        name = repository['name']
        snapshot, chunks, selected = pending[name]
        reduced = Snapshot(snapshot.id, snapshot.files, chunks, [], {})
        bundle = make_bundle(reduced, ' '.join(sorted({chunk.path for chunk in chunks})), budget=1000000, method='bm25', tokenizer='bytes')
        if len(bundle['entries']) != len(chunks):
            raise RuntimeError('Sensitivity evidence packing dropped samples')
        report = verify_bundle(bundle, roots[name, 'after'])
        statuses = {row['entry_id']: row['status'] for row in report['results']}
        repo_rows = []
        for sample, chunk in zip(selected, chunks):
            status = statuses[chunk.id]
            row = lookup[sample['sample_id']] | {'engine_status': status}
            row['predictions'] = row['predictions'] | {'contextproof': status in ACCEPTED}
            old = old_rows[sample['sample_id']]
            row['primary_reference_status'] = old['reference']['status']
            if old['reference']['status'] != row['reference']['status']:
                changes.append({'sample_id': sample['sample_id'], 'repository': name,
                    'before_path': sample['path'], 'primary_status': old['reference']['status'],
                    'full_scope_status': row['reference']['status'], 'full_scope_matches': row['reference']['matches']})
            rows.append(row)
            repo_rows.append(row)
        repositories.append({'repository': name, 'split': repository['split'], 'summary': summarize(repo_rows)})
        print(f'Scope sensitivity {name}: {summarize(repo_rows)["reference_status_counts"]}', flush=True)
    result = {
        'disclosure': 'Post-result corpus-scope sensitivity motivated by dateutil embedded-test corpus exits. Searches the same300 frozen before-only samples against all policy-eligible Python files in the same frozen archives. The primary preregistered corpus, samples, labels and results remain unchanged. Not a new holdout test or semantic evaluation.',
        'provenance': {'samples_sha256': digest((DATA / 'samples.json').read_bytes()),
                       'source_manifests_sha256': digest((DATA / 'sensitivity_source_manifests.json').read_bytes()),
                       'annotations_sha256': digest((DATA / 'sensitivity_annotations.json').read_bytes()),
                       'implementation_sha256': implementation_digest()},
        'quality': {'samples': rows, 'repositories': repositories, 'summary': summarize(rows),
                    'changed_labels': changes,
                    'mismatches': [row['sample_id'] for row in rows if row['reference']['status'] != row['engine_status']]},
        'generated_at_utc': datetime.now(timezone.utc).isoformat(),
    }
    if check:
        previous = json.loads(check.read_text())
        if previous['quality'] != result['quality']:
            raise RuntimeError('Scope-sensitivity deterministic quality differs from comparison report')
        print('Scope-sensitivity deterministic quality matches comparison report.', flush=True)
    write_json(DATA / 'results/scope-sensitivity.json', result)
    summary = result['quality']['summary']
    lines = ['# Posthoc source-scope sensitivity', '', result['disclosure'], '',
        f"**{len(changes)}/300 reference labels change when the source corpus expands.** Primary status counts: {primary['quality']['splits']['all']['reference_status_counts']}. Full-scope counts: {summary['reference_status_counts']}.", '',
        f"Engine/reference status agreement in the expanded scope: {summary['status_agreement']:.3f}; mismatches: {len(result['quality']['mismatches'])}.", '',
        'All23 dateutil snippets labeled `deleted` in the primary scope are embedded tests that move outside the declared library prefixes. They are exact unique relocations under the broader scope. This is a source-boundary effect, not upstream source deletion. The primary report must be interpreted within its frozen corpus.', '',
        '| Method | TP | FP | TN | FN | Accuracy |', '| --- | ---: | ---: | ---: | ---: | ---: |']
    for method, values in summary['methods'].items():
        lines.append(f"| {method} | {values['true_positive']} | {values['false_positive']} | {values['true_negative']} | {values['false_negative']} | {values['accuracy']:.3f} |")
    lines += ['', 'Reproduce with `python -m benchmarks.v1.scope_sensitivity` after running the primary study. '
              'Archives are rechecked and staged under ignored `work/v1-drift/sensitivity/`; primary source directories are untouched. '
              'Full manifests, annotations, coordinates and predictions are in sibling JSON artifacts. '
              'All-Python scope still excludes non-Python files and policy-excluded files. This remains automated contract agreement, not human or semantic ground truth.', '']
    (DATA / 'results/scope-sensitivity.md').write_text('\n'.join(lines))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', type=Path, help='Require deterministic quality equality with a previous result')
    run(parser.parse_args().check)
