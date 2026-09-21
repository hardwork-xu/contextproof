"""Adversarial checks for the v1 reference, baseline arithmetic and frozen inputs."""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from benchmarks.v1.reference import (
    annotate, at_lines, baselines, binary_metrics, byte_matches, digest,
    line_offsets, paired_bootstrap,
)
from scripts.run_drift_benchmarks import source_exclusion

ROOT = Path(__file__).resolve().parents[1]


def entry(raw=b'def task():\n    return 1\n', **changes):
    result = {'path': 'a.py', 'start_line': 1, 'end_line': 2,
              'text': raw.decode(), 'file_sha256': digest(raw)}
    return result | changes


@pytest.mark.parametrize('newline', [b'\n', b'\r', b'\r\n'])
def test_raw_reference_editor_boundaries_are_not_unicode_splitlines(newline):
    raw = b'prefix\x0b\x0c\xc2\x85\xe2\x80\xa8\xe2\x80\xa9' + newline + b'wanted' + newline
    offsets = line_offsets(raw)
    assert len(offsets) == 3
    assert at_lines(raw, 2, 2) == b'wanted' + newline
    assert byte_matches({'a.py': raw}, b'wanted' + newline) == [{'path': 'a.py', 'start_line': 2, 'end_line': 2}]
    assert byte_matches({'a.py': raw}, b'wanted') == []


def test_raw_reference_rejects_partial_lines_and_handles_eof():
    assert line_offsets(b'') == [0]
    assert line_offsets(b'a\n') == [0, 2]
    assert byte_matches({'a.py': b'ab\n'}, b'b\n') == []
    assert byte_matches({'a.py': b'ab\n'}, b'ab') == []
    assert byte_matches({'a.py': b'x\nab'}, b'ab') == [{'path': 'a.py', 'start_line': 2, 'end_line': 2}]
    assert at_lines(b'a\n', 1, 2) is None
    with pytest.raises(ValueError):
        byte_matches({'a.py': b'a'}, b'')


@pytest.mark.parametrize(('corpus', 'expected'), [
    ({'a.py': b'def task():\n    return 1\n'}, 'valid'),
    ({'a.py': b'prefix\ndef task():\n    return 1\n'}, 'relocated'),
    ({'b.py': b'def task():\n    return 1\n'}, 'relocated'),
    ({'b.py': b'def task():\n    return 1\n', 'c.py': b'def task():\n    return 1\n'}, 'ambiguous'),
    ({'a.py': b'def task():\n    return 2\n'}, 'modified'),
    ({'b.py': b'def task():\n    return 2\n'}, 'deleted'),
    ({'a.py': b'def task():\n    return 1\n', 'b.py': b'def task():\n    return 1\n'}, 'valid'),
])
def test_reference_contract_cases(corpus, expected):
    assert annotate(entry(), corpus)['status'] == expected


def test_naive_baseline_failure_modes_are_explicit():
    changed = {'a.py': b'def task():\n    return 2\n'}
    assert baselines(entry(), changed) == {'path_exists_and_line_range': True, 'path_line_exact': False, 'file_hash': False}
    edited_elsewhere = {'a.py': b'def task():\n    return 1\n# extra line\n'}
    assert baselines(entry(), edited_elsewhere) == {'path_exists_and_line_range': True, 'path_line_exact': True, 'file_hash': False}
    moved = {'b.py': b'def task():\n    return 1\n'}
    assert not any(baselines(entry(), moved).values())
    assert annotate(entry(), moved)['accept']


def test_reference_does_not_import_engine_or_shared_line_matcher():
    source = (ROOT / 'benchmarks/v1/reference.py').read_text()
    tree = ast.parse(source)
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imports.append(node.module or '')
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
    assert not any(name.startswith(('contextproof', 'benchmarks.oracles')) for name in imports)


def test_metrics_zero_denominators_and_clusters():
    result = binary_metrics([True, True, False, False], [True, False, True, False])
    assert all(result[name] == 0.5 for name in ('accuracy', 'precision', 'recall', 'false_acceptance_rate'))
    assert binary_metrics([], [])['accuracy'] is None
    assert binary_metrics([True], [True])['false_acceptance_rate'] is None
    with pytest.raises(ValueError):
        binary_metrics([], [True])
    rows = []
    for name, baseline in [('a', False), ('b', True)]:
        for _ in range(3):
            rows.append({'repository': name, 'reference': {'accept': True}, 'predictions': {
                'contextproof': True, 'path_exists_and_line_range': baseline,
                'path_line_exact': baseline, 'file_hash': baseline}})
    result = paired_bootstrap(rows, repeats=200)
    assert result == paired_bootstrap(rows, repeats=200)
    assert result['clusters'] == 2
    assert result['differences']['file_hash']['mean_accuracy_difference'] == 0.5
    assert result['differences']['file_hash']['percentile_95_interval'] == [0.0, 1.0]


@pytest.mark.parametrize(('path', 'raw', 'reason'), [
    ('src/pkg/a.py', b'print(1)\n', None),
    ('tests/a.py', b'print(1)\n', 'outside_library_python_prefixes'),
    ('src/pkg/secrets.py', b'print(1)\n', 'secret_like_filename'),
    ('src/pkg/.env.py', b'print(1)\n', 'secret_like_filename'),
    ('src/pkg/vendor/a.py', b'print(1)\n', 'excluded_directory'),
    ('src/pkg/a_pb2.py', b'print(1)\n', 'generated_filename'),
    ('src/pkg/a.py', b'\0', 'nul_bytes'),
    ('src/pkg/a.py', b'\xff', 'non_utf8'),
    ('src/pkg/a.py', b'# Automatically generated\n', 'generated_header'),
    ('src/pkg/a.py', b'-----BEGIN PRIVATE KEY-----\n', 'private_key_header'),
])
def test_frozen_source_policy(path, raw, reason):
    assert source_exclusion(path, raw, ['src/pkg/']) == reason


def test_preregistration_archive_and_sample_integrity():
    folder = ROOT / 'benchmarks/v1'
    protocol = json.loads((folder / 'preregistration.json').read_text())
    manifest = json.loads((folder / 'manifest.json').read_text())
    assert manifest['preregistration_sha256'] == digest((folder / 'preregistration.json').read_bytes())
    repositories = manifest['repositories']
    assert len(repositories) == 10
    assert len({r['github'].split('/')[0] for r in repositories}) == 10
    assert sum(r['split'] == 'holdout' for r in repositories) == 3
    assert sum(r['split'] == 'development' for r in repositories) == 7
    assert protocol['sample']['per_repository'] == 30
    for repository in repositories:
        for version in repository['versions'].values():
            assert len(version['commit']) == 40
            assert len(version['archive_sha256']) == 64
            assert version['commit'] in version['archive_url']
            assert version['license_files']
            assert all(len(license['sha256']) == 64 for license in version['license_files'])
    samples = json.loads((folder / 'samples.json').read_text())['samples']
    assert len(samples) == 300
    assert len({r['sample_id'] for r in samples}) == 300
    assert all(sum(r['repository'] == repo['name'] for r in samples) == 30 for repo in repositories)


def test_scope_boundary_changes_are_not_source_deletion():
    sample = entry(path='pkg/test/test_task.py')
    narrow = {'src/pkg/core.py': b'core = 1\n'}
    broader = narrow | {'tests/test_task.py': sample['text'].encode()}
    assert annotate(sample, narrow)['status'] == 'deleted'
    assert annotate(sample, broader)['status'] == 'relocated'
    duplicated = broader | {'examples/copied_task.py': sample['text'].encode()}
    assert annotate(sample, duplicated)['status'] == 'ambiguous'


def test_frozen_review_is_blinded_and_primary_annotation_matches_report():
    folder = ROOT / 'benchmarks/v1'
    packet = json.loads((folder / 'review_packet.json').read_text())['samples']
    assert len(packet) >= 20
    for row in packet:
        assert not any(key in row for key in ('reference', 'status', 'engine_status', 'predictions', 'text'))
        assert not Path(row['before_source_root']).is_absolute()
        assert not Path(row['after_source_root']).is_absolute()
    annotations = json.loads((folder / 'annotations.json').read_text())['samples']
    report = json.loads((folder / 'results/latest.json').read_text())
    actual = {row['sample_id']: row['reference'] for row in report['quality']['samples']}
    assert {row['sample_id']: row['reference'] for row in annotations} == actual
    assert all('text' not in row for row in annotations)
