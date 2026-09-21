"""Guard benchmark denominators and attribution, not timing thresholds."""

from scripts import run_graph_benchmarks as study
from contextproof.dependencies import _Corpus
from contextproof.graph import build_graph
from contextproof.revisions import read_worktree


def saved(texts):
    corpus = _Corpus.from_texts(texts)
    node = corpus.definitions['app.py']['entry'][0]
    return {**corpus.record('app.py', 'entry', 'function', node),
            'id': 'sample', 'sample_id': 'sample', 'repository': 'example', 'split': 'development'}


def pair(texts, changed):
    sample = saved(texts)
    graphs = [build_graph(source, label, [sample], max_depth=depth)
              for depth in (4, 1) for source, label in ((texts, 'before'), (changed, 'after'))]
    return study.analyze_pair(sample, *graphs)


def test_descendant_attribution_does_not_conflate_changed_root():
    before = {'app.py': 'def entry():\n    return helper()\ndef helper():\n    return leaf()\n'
              'def leaf():\n    return 1\n'}
    descendant = pair(before, {'app.py': before['app.py'].replace('return 1', 'return 2')})
    assert descendant['added_descendant_flag']
    assert descendant['root_unchanged'] and not descendant['root_changed']
    root = pair(before, {'app.py': before['app.py'].replace('return helper()', 'return 7')})
    assert root['root_changed'] and not root['added_descendant_flag']
    summary = study.summarize([descendant, root])
    assert summary['samples'] == summary['delta_reconstructions_equal'] == 2
    assert summary['added_descendant_flags'] == 1


def test_transport_baseline_compresses_both_messages_identically():
    import gzip
    from contextproof.graph import canonical_graph_bytes
    from contextproof.graph_delta import canonical, make_graph_delta

    before = {'app.py': 'def entry():\n    return helper()\ndef helper():\n    return 1\n'}
    after = {'app.py': before['app.py'].replace('return 1', 'return 2')}
    anchor = saved(before)
    left = build_graph(before, 'before', [anchor])
    right = build_graph(after, 'after', [anchor])
    delta = make_graph_delta(left, right)
    actual = study.transport_bytes(right, delta)
    assert actual['gzip_full_graph_bytes'] == len(gzip.compress(canonical_graph_bytes(right), compresslevel=9, mtime=0))
    assert actual['gzip_field_delta_bytes'] == len(gzip.compress(canonical(delta), compresslevel=9, mtime=0))
    assert study.transport_summary([actual, actual])['gzip_delta_smaller'] == 2 * actual['gzip_delta_smaller']


def test_persisted_cache_replay_keeps_all_anchors_and_counts_work(tmp_path, monkeypatch):
    monkeypatch.setattr(study, 'WORK', tmp_path / 'study')
    before_root, after_root = tmp_path / 'before', tmp_path / 'after'
    before_root.mkdir()
    after_root.mkdir()
    before = {'app.py': 'from policy import rate\ndef entry():\n    return rate()\n',
              'policy.py': 'def rate():\n    return 1\n'}
    for path, text in before.items():
        (before_root / path).write_text(text)
        (after_root / path).write_text(text.replace('return 1', 'return 2'))
    selected = saved(before)
    old, new, repetitions = study.cache_replay('example', read_worktree(before_root),
                                              read_worktree(after_root), [selected], repeats=2)
    assert len(old) == len(new) == 1 and len(repetitions) == 2
    for repetition in repetitions:
        assert repetition['warm_before']['parse_cache_misses'] == 0
        assert repetition['incremental_after']['parse_cache_misses'] == 1
        assert repetition['cold_after']['parse_cache_misses'] == 2


def test_fair_full_baseline_shares_same_version_parses(tmp_path, monkeypatch):
    monkeypatch.setattr(study, 'WORK', tmp_path / 'study')
    before_root, after_root = tmp_path / 'before', tmp_path / 'after'
    before_root.mkdir()
    after_root.mkdir()
    before = {'app.py': 'from policy import rate\ndef entry():\n    return rate()\n',
              'policy.py': 'def rate():\n    return 1\n'}
    for path, text in before.items():
        (before_root / path).write_text(text)
        (after_root / path).write_text(text.replace('return 1', 'return 2'))
    anchors = [saved(before) | {'id': f'sample-{index}'} for index in range(2)]
    old, current = read_worktree(before_root), read_worktree(after_root)
    expected, _ = study.build_batch(current, anchors)
    observations = study.fair_cache_replay('example', old, current, anchors,
                                           [graph['id'] for graph in expected], repeats=1)
    observed = observations[0]
    # The full baseline parses two files once across both queries, not four times.
    assert observed['full_after_shared']['parse_cache_misses'] == 2
    assert observed['incremental_after']['parse_cache_misses'] == 1
    assert observed['warm_stable_after']['parse_cache_misses'] == 0


def test_default_memory_condition_keeps_identical_graph_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(study, 'WORK', tmp_path / 'study')
    before_root, after_root = tmp_path / 'before', tmp_path / 'after'
    before_root.mkdir()
    after_root.mkdir()
    before = {'app.py': 'from policy import rate\ndef entry():\n    return rate()\n',
              'policy.py': 'def rate():\n    return 1\n'}
    for path, text in before.items():
        (before_root / path).write_text(text)
        (after_root / path).write_text(text.replace('return 1', 'return 2'))
    anchors = [saved(before) | {'id': f'sample-{index}'} for index in range(2)]
    old, current = read_worktree(before_root), read_worktree(after_root)
    expected, _ = study.build_batch(current, anchors)
    observations = study.memory_cache_replay('example', old, current, anchors,
                                             [graph['id'] for graph in expected], repeats=1)
    observed = observations[0]
    assert observed['full_after_shared']['parse_cache_misses'] == 2
    assert observed['incremental_memory_after']['parse_cache_misses'] == 1
    assert observed['warm_stable_after']['parse_cache_misses'] == 0
