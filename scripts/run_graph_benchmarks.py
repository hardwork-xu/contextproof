#!/usr/bin/env python3
"""Replay all frozen source anchors through transitive graphs and lossless updates."""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import platform
import statistics
import subprocess
import sys
import tarfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from contextproof.graph import build_graph, canonical_graph_bytes, compare_graphs  # noqa: E402
from contextproof.dependencies import _Corpus  # noqa: E402
from contextproof.graph_delta import apply_graph_delta, canonical, make_graph_delta  # noqa: E402
from contextproof.graph_payload import render_graph_context, render_graph_update  # noqa: E402
from contextproof.index import source_lines  # noqa: E402
from contextproof.parse_cache import ParseCache  # noqa: E402
from contextproof.revisions import SourceStore, read_worktree  # noqa: E402

DATA = ROOT / "benchmarks/graph"
WORK = ROOT / "work/graph-study"


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_json(path):
    return json.loads(path.read_text())


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


def prepare_history(download=False):
    """Pin first-parent SHAs before loading sources or running graph outcomes."""
    target = DATA / "history_manifest.json"
    manifest = read_json(ROOT / "benchmarks/v1/manifest.json")
    wanted = read_json(DATA / "protocol.json")["historical_extension"]["repositories"]
    repositories = {row["name"]: row for row in manifest["repositories"]}
    if not target.exists():
        if not download:
            raise RuntimeError("history manifest unavailable; use --prepare-history --download")

        def pin(name):
            repository = repositories[name]
            commit = repository["versions"]["before"]["commit"]
            versions = []
            for _ in range(6):
                response = subprocess.run(
                    ["gh", "api", f"repos/{repository['github']}/commits/{commit}"],
                    capture_output=True, check=True, timeout=25)
                data = json.loads(response.stdout)
                if data["sha"] != commit or not data["parents"]:
                    raise RuntimeError("unexpected upstream commit or absent first parent")
                versions.append({"commit": commit,
                                 "parents": [item["sha"] for item in data["parents"]],
                                 "commit_date": data["commit"]["committer"]["date"],
                                 "url": data["html_url"],
                                 "archive_url": f"https://codeload.github.com/{repository['github']}/tar.gz/{commit}"})
                commit = data["parents"][0]["sha"]
            return {"name": name, "github": repository["github"],
                    "prefixes": repository["prefixes"], "versions": list(reversed(versions))}
        with ThreadPoolExecutor(max_workers=3) as pool:
            pinned = list(pool.map(pin, wanted))
        write_json(target, {"schema_version": 1,
                            "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
                            "stage": "SHAs pinned before history source extraction or graph results",
                            "protocol_sha256": digest((DATA / "protocol.json").read_bytes()),
                            "repositories": pinned})
    pinned = read_json(target)
    # Import the already-published source policy, not any upstream code.
    from scripts.run_drift_benchmarks import source_exclusion

    def extract(repository):
        observations = []
        for version in repository["versions"]:
            commit = version["commit"]
            archive = WORK / "history/archives" / f"{repository['name']}-{commit}.tar.gz"
            archive.parent.mkdir(parents=True, exist_ok=True)
            if not archive.exists():
                existing = ROOT / "work/v1-drift/archives" / archive.name
                if existing.exists():
                    archive.write_bytes(existing.read_bytes())
                elif download:
                    pending = archive.with_suffix(".partial")
                    try:
                        subprocess.run(["curl", "--fail", "--location", "--silent", "--show-error",
                                        "--connect-timeout", "10", "--max-time", "40", "--output",
                                        str(pending), version["archive_url"]], check=True, timeout=45)
                        pending.replace(archive)
                    finally:
                        pending.unlink(missing_ok=True)
                else:
                    raise RuntimeError("missing pinned archive: " + archive.name)
            output = WORK / "history/sources" / repository["name"] / commit
            accepted = {}
            with tarfile.open(archive, "r:gz") as tar:
                for member in tar:
                    path = PurePosixPath(member.name)
                    if path.is_absolute() or ".." in path.parts or not path.parts:
                        raise RuntimeError("unsafe upstream archive member")
                    if path.parts[0] != repository["name"] + "-" + commit:
                        raise RuntimeError("unexpected upstream archive prefix")
                    if not member.isfile() or member.size > 2 * 1024 * 1024:
                        continue
                    relative = "/".join(path.parts[1:])
                    if not relative.endswith(".py") or not any(
                            relative.startswith(prefix) for prefix in repository["prefixes"]):
                        continue
                    raw = tar.extractfile(member).read()
                    if source_exclusion(relative, raw, repository["prefixes"]):
                        continue
                    if relative in accepted:
                        raise RuntimeError("duplicate upstream source path")
                    accepted[relative] = digest(raw)
                    destination = output / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(raw)
            if not accepted:
                raise RuntimeError("empty pinned source corpus")
            observations.append({"commit": commit, "archive_sha256": digest(archive.read_bytes()),
                                 "archive_bytes": archive.stat().st_size, "files": accepted,
                                 "source_manifest_sha256": digest(canonical(accepted))})
        return {"name": repository["name"], "versions": observations}
    with ThreadPoolExecutor(max_workers=3) as pool:
        sources = list(pool.map(extract, pinned["repositories"]))
    source_path = DATA / "history_sources.json"
    frozen = {"schema_version": 1, "history_manifest_sha256": digest(target.read_bytes()),
              "repositories": sources}
    if source_path.exists() and read_json(source_path) != frozen:
        raise RuntimeError("pinned history source bytes changed")
    write_json(source_path, frozen)
    return pinned


def selected_anchors(samples, revision):
    return [{**sample, "id": sample["sample_id"],
             "text": "".join(source_lines(revision.texts[sample["path"]])[
                 sample["start_line"] - 1:sample["end_line"]])} for sample in samples]


def build_batch(revision, anchors, cache=None, depth=4):
    graphs = []
    hits_before = cache.stats if cache is not None else None
    started = time.perf_counter()
    misses = 0
    for selected in anchors:
        current_cache = cache if cache is not None else ParseCache()
        graphs.append(build_graph(revision.texts, revision.snapshot_id, [selected],
                                  max_depth=depth, max_nodes=256, parsed_cache=current_cache))
        if cache is None:
            misses += current_cache.misses
    duration = time.perf_counter() - started
    stats = ({key: value - hits_before[key] for key, value in cache.stats.items()}
             if cache is not None else {"parse_cache_hits": 0, "parse_cache_misses": misses,
                                        "parse_cache_corrupt": 0})
    return graphs, {"seconds": duration, **stats}


def assert_equal(left, right, label):
    if len(left) != len(right) or any(canonical_graph_bytes(a) != canonical_graph_bytes(b)
                                    for a, b in zip(left, right)):
        raise RuntimeError("canonical full/cache graph mismatch: " + label)


def cache_replay(name, before, after, anchors, repeats):
    observations = []
    before_graphs = after_graphs = None
    for repetition in range(repeats):
        # Fresh per-run DB names are materialized in ignored work, never a user's cache.
        cache_path = WORK / "cache" / f"{name}-{time.time_ns()}.sqlite"
        with SourceStore(cache_path) as store:
            before_graphs, cold_before = build_batch(before, anchors)
            seeded, seed_before = build_batch(before, anchors, ParseCache(store))
            store.db.commit()
            warm_cache = ParseCache(store)  # Exercise persisted JSON decoding after restart.
            warmed, warm_before = build_batch(before, anchors, warm_cache)
            incremental, incremental_after = build_batch(after, anchors, warm_cache)
            after_graphs, cold_after = build_batch(after, anchors)
            assert_equal(before_graphs, seeded, name + " seed")
            assert_equal(before_graphs, warmed, name + " warm")
            assert_equal(after_graphs, incremental, name + " changed version")
            observations.append({"repetition": repetition + 1, "cold_before": cold_before,
                                 "seed_before": seed_before, "warm_before": warm_before,
                                 "incremental_after": incremental_after, "cold_after": cold_after})
        print(f"{name}: cache repetition {repetition + 1}/{repeats} agrees", flush=True)
    return before_graphs, after_graphs, observations



def fair_cache_replay(name, before, after, anchors, expected, repeats=3):
    """Give full rebuild and persistent replay identical same-version reuse."""
    records = []
    for repetition in range(repeats):
        cache_path = WORK / "cache" / f"fair-{name}-{time.time_ns()}.sqlite"
        with SourceStore(cache_path) as store:
            persistent = ParseCache(store)
            _Corpus.from_texts(before.texts, parsed_cache=persistent)
            store.db.commit()
            full, full_stats = build_batch(after, anchors, ParseCache())
            incremental, incremental_stats = build_batch(after, anchors, persistent)
            warm, warm_stats = build_batch(after, anchors, persistent)
            assert_equal(full, incremental, name + " fair incremental")
            assert_equal(full, warm, name + " fair warm")
            if [graph["id"] for graph in full] != expected:
                raise RuntimeError("fair benchmark changed original graph identities: " + name)
            records.append({"repetition": repetition + 1, "full_after_shared": full_stats,
                            "incremental_after": incremental_stats, "warm_stable_after": warm_stats})
        print(f"{name}: fair shared-cache repetition {repetition + 1}/{repeats} agrees", flush=True)
    return records


def memory_cache_replay(name, before, after, anchors, expected, repeats=3):
    """Pair the default process-local replay with the same shared-memory baseline."""
    records = []
    for repetition in range(repeats):
        previous = ParseCache()
        _Corpus.from_texts(before.texts, parsed_cache=previous)
        full, full_stats = build_batch(after, anchors, ParseCache())
        incremental, incremental_stats = build_batch(after, anchors, previous)
        warm, warm_stats = build_batch(after, anchors, previous)
        assert_equal(full, incremental, name + " memory incremental")
        assert_equal(full, warm, name + " memory warm")
        if [graph["id"] for graph in full] != expected:
            raise RuntimeError("memory condition changed original graph identities: " + name)
        records.append({"repetition": repetition + 1, "full_after_shared": full_stats,
                        "incremental_memory_after": incremental_stats, "warm_stable_after": warm_stats})
        print(f"{name}: default memory-cache repetition {repetition + 1}/{repeats} agrees", flush=True)
    return records

def frontier_counts(graph):
    return dict(sorted(Counter(item["kind"] for item in graph["frontier"]).items()))


def cause_record(cause, before, after):
    nodes = []
    for node_id in cause["path"]:
        node = after["nodes"].get(node_id) or before["nodes"].get(node_id)
        if node:
            nodes.append({"id": node_id, "path": node["path"], "symbol": node["symbol"],
                          "kind": node["kind"]})
    return {"kind": cause["kind"], "reason": cause["reason"], "nodes": nodes}


def transport_bytes(after, delta):
    """Compare independently compressed messages with identical gzip settings."""
    full_raw, delta_raw = canonical_graph_bytes(after), canonical(delta)
    full_gzip = gzip.compress(full_raw, compresslevel=9, mtime=0)
    delta_gzip = gzip.compress(delta_raw, compresslevel=9, mtime=0)
    return {"full_graph_bytes": len(full_raw), "field_delta_bytes": len(delta_raw),
            "gzip_full_graph_bytes": len(full_gzip), "gzip_field_delta_bytes": len(delta_gzip),
            "gzip_delta_smaller": len(delta_gzip) < len(full_gzip)}


def transport_summary(rows):
    return {key: sum(row[key] for row in rows) for key in (
        "full_graph_bytes", "field_delta_bytes", "gzip_full_graph_bytes",
        "gzip_field_delta_bytes", "gzip_delta_smaller")}


def analyze_pair(sample, before, after, direct_before, direct_after, budget=16000):
    comparison = compare_graphs(before, after)
    direct = compare_graphs(direct_before, direct_after)
    delta = make_graph_delta(before, after)
    rebuilt = apply_graph_delta(before, delta)
    if canonical_graph_bytes(rebuilt) != canonical_graph_bytes(after):
        raise RuntimeError("delta reconstruction mismatch: " + sample["sample_id"])
    root_before = before["nodes"].get(before["anchors"][0]["node_id"])
    root_after = after["nodes"].get(after["anchors"][0]["node_id"])
    root_unchanged = bool(root_before and root_after
                          and root_before["fingerprint"] == root_after["fingerprint"])
    causes = comparison["results"][0]["causes"]
    descendants = [cause for cause in causes if cause["kind"] == "changed" and len(cause["path"]) >= 2]
    added = direct["status"] not in {"changed", "missing"} and comparison["status"] in {"changed", "missing"}
    full = render_graph_context(after, budget)
    update = render_graph_update(before, after, comparison, budget)
    return {"sample_id": sample["sample_id"], "repository": sample["repository"],
            "split": sample["split"], "path": sample["path"], "symbol": sample["symbol"],
            "depth1_status": direct["status"], "depth4_status": comparison["status"],
            "root_unchanged": root_unchanged, "root_changed": bool(root_before and root_after and not root_unchanged),
            "source_anchor_status": after["anchors"][0]["source_status"],
            "added_flag_vs_depth1": added, "added_descendant_flag": added and root_unchanged and bool(descendants),
            "changed_descendant_behind_unchanged_root": root_unchanged and bool(descendants),
            "before_frontier": frontier_counts(before), "after_frontier": frontier_counts(after),
            "before_nodes": len(before["nodes"]), "after_nodes": len(after["nodes"]),
            "before_graph_sha256": before["id"], "after_graph_sha256": after["id"],
            "delta_sha256": delta["id"], "delta_reconstruction_equal": True,
            **transport_bytes(after, delta),
            "payloads": {name: {key: value[key] for key in (
                "status", "complete", "consumed", "budget", "minimum_budget", "omitted_nodes")}
                for name, value in (("full", full), ("update", update))},
            "changed_cause_paths": [cause_record(cause, before, after) for cause in causes
                                    if cause["kind"] == "changed"],
            "unresolved_cause_count": sum(cause["kind"] == "unresolved" for cause in causes)}


def summarize(rows):
    result = {"samples": len(rows),
            "depth1_statuses": dict(sorted(Counter(row["depth1_status"] for row in rows).items())),
            "depth4_statuses": dict(sorted(Counter(row["depth4_status"] for row in rows).items())),
            "root_changed": sum(row["root_changed"] for row in rows),
            "added_flags_vs_depth1": sum(row["added_flag_vs_depth1"] for row in rows),
            "added_descendant_flags": sum(row["added_descendant_flag"] for row in rows),
            "delta_reconstructions_equal": sum(row["delta_reconstruction_equal"] for row in rows),
            **transport_summary(rows),
            "payloads": {kind: {"statuses": dict(sorted(Counter(row["payloads"][kind]["status"]
                for row in rows).items())), "consumed_utf8_bytes": sum(row["payloads"][kind]["consumed"] for row in rows),
                "omitted_node_occurrences": sum(len(row["payloads"][kind]["omitted_nodes"]) for row in rows)}
                for kind in ("full", "update")}}
    if rows and all("anchor_file_hash_changed" in row for row in rows):
        result["baseline_observations"] = {
            "revision_changed_invalidates_all": sum(row["git_revision_changed"] for row in rows),
            "anchor_file_hash_changed": sum(row["anchor_file_hash_changed"] for row in rows),
            "existing_v1_exact_source_statuses": dict(sorted(Counter(
                row["existing_v1_source_status"] for row in rows).items())),
            "existing_v1_direct_dependency_statuses": dict(sorted(Counter(
                row["existing_v1_dependency_status"] for row in rows).items()))}
    return result


def provenance():
    paths = [DATA / "protocol.json", ROOT / "benchmarks/v1/samples.json",
             ROOT / "benchmarks/v1/source_manifests.json", Path(__file__),
             DATA / "scope-correction-amendment.json"]
    return {"files": {path.relative_to(ROOT).as_posix(): digest(path.read_bytes()) for path in paths},
            "implementation_sha256": digest(b"".join(path.name.encode() + path.read_bytes()
                for path in sorted((ROOT / "src/contextproof").glob("*.py"))))}


def run_frozen(repeats=3):
    captured_provenance = provenance()
    protocol = read_json(DATA / "protocol.json")
    samples_path = ROOT / "benchmarks/v1/samples.json"
    if digest(samples_path.read_bytes()) != protocol["frozen_samples"]["sha256"]:
        raise RuntimeError("frozen sample provenance changed")
    samples = read_json(samples_path)["samples"]
    manifests = read_json(ROOT / "benchmarks/v1/source_manifests.json")["repositories"]
    legacy = {row["sample_id"]: row for row in read_json(
        ROOT / "benchmarks/v1/results/dependency-drift.json")["quality"]["rows"]}
    rows, observations = [], []
    for name in sorted({sample["repository"] for sample in samples}):
        revisions = [read_worktree(ROOT / "work/v1-drift/sources" / name / side)
                     for side in ("before", "after")]
        before, after = revisions
        for side, revision in zip(("before", "after"), revisions):
            current = {path: digest(text.encode()) for path, text in revision.texts.items()}
            if current != manifests[name][side]["files"]:
                raise RuntimeError("source corpus differs from frozen manifest: " + name + side)
        selected = [sample for sample in samples if sample["repository"] == name]
        anchors = selected_anchors(selected, before)
        old_graphs, new_graphs, timings = cache_replay(name, before, after, anchors, repeats)
        direct_old, _ = build_batch(before, anchors, ParseCache(), depth=1)
        direct_new, _ = build_batch(after, anchors, ParseCache(), depth=1)
        unique_nodes = {}
        occurrences = source_bytes = 0
        for sample, old, new, old_direct, new_direct in zip(
                selected, old_graphs, new_graphs, direct_old, direct_new):
            row = analyze_pair(sample, old, new, old_direct, new_direct)
            row.update({"existing_v1_source_status": legacy[sample["sample_id"]]["source_status"],
                        "existing_v1_dependency_status": legacy[sample["sample_id"]]["dependency_status"],
                        "git_revision_changed": True,
                        "anchor_file_hash_changed": before.texts.get(sample["path"]) != after.texts.get(sample["path"])})
            rows.append(row)
            for node in new["nodes"].values():
                size = len(node["text"].encode())
                occurrences += 1
                source_bytes += size
                unique_nodes[node["id"], node["text_sha256"]] = size
        fair = fair_cache_replay(name, before, after, anchors, [graph["id"] for graph in new_graphs], repeats)
        memory = memory_cache_replay(name, before, after, anchors, [graph["id"] for graph in new_graphs], repeats)
        observations.append({"repository": name, "repetitions": timings, "fair_repetitions": fair,
                             "memory_repetitions": memory,
                             "after_node_occurrences": occurrences, "after_unique_nodes": len(unique_nodes),
                             "after_source_bytes_with_repetition": source_bytes,
                             "after_unique_source_bytes": sum(unique_nodes.values())})
        partial = {"quality": summarize(rows) | {"rows": rows}, "observations": observations}
        write_json(WORK / "partial-frozen.json", partial)
        print(f"{name}: {len(selected)} payload and delta checks complete", flush=True)
    return {"schema_version": 1, "study": "frozen-natural-version-graph-replay",
            "scope": protocol["scope"], "provenance": captured_provenance,
            "quality": summarize(rows) | {"rows": rows},
            "observations": {"python": platform.python_version(), "platform": platform.platform(),
                             "repeats": repeats, "repositories": observations}}


def run_history(repeats=3):
    captured_provenance = provenance()
    pinned = prepare_history(download=False)
    samples = read_json(ROOT / "benchmarks/v1/samples.json")["samples"]
    rows, observations = [], []
    for repository in pinned["repositories"]:
        name = repository["name"]
        selected = [sample for sample in samples if sample["repository"] == name]
        original = read_worktree(ROOT / "work/v1-drift/sources" / name / "before")
        anchors = selected_anchors(selected, original)
        versions = [read_worktree(WORK / "history/sources" / name / version["commit"])
                    for version in repository["versions"]]
        for offset, (before, after) in enumerate(zip(versions, versions[1:])):
            label = name + "-history-" + str(offset)
            old, new, timings = cache_replay(label, before, after, anchors, repeats)
            for sample, left, right in zip(selected, old, new):
                delta = make_graph_delta(left, right)
                if canonical_graph_bytes(apply_graph_delta(left, delta)) != canonical_graph_bytes(right):
                    raise RuntimeError("historical delta mismatch")
                comparison = compare_graphs(left, right)
                rows.append({"repository": name, "sample_id": sample["sample_id"],
                             "transition": offset, "status": comparison["status"],
                             "before_graph_sha256": left["id"], "after_graph_sha256": right["id"],
                             "delta_reconstruction_equal": True, **transport_bytes(right, delta)})
            changed = [path for path in before.texts.keys() | after.texts.keys()
                       if before.texts.get(path) != after.texts.get(path)]
            fair = fair_cache_replay(label, before, after, anchors, [graph["id"] for graph in new], repeats)
            memory = memory_cache_replay(label, before, after, anchors, [graph["id"] for graph in new], repeats)
            observations.append({"repository": name, "transition": offset, "fair_repetitions": fair,
                                 "memory_repetitions": memory,
                "before_commit": repository["versions"][offset]["commit"],
                "after_commit": repository["versions"][offset + 1]["commit"],
                "before_files": len(before.texts), "after_files": len(after.texts),
                "changed_source_files": sorted(changed), "repetitions": timings})
    return {"schema_version": 1, "study": "adjacent-upstream-source-history-parse-replay",
            "scope": "Actual first-parent upstream commits via hash-pinned archives. Graph construction and AST cache only; Git object transport performance is not measured.",
            "provenance": captured_provenance | {"history_manifest_sha256": digest((DATA / "history_manifest.json").read_bytes()),
                "history_sources_sha256": digest((DATA / "history_sources.json").read_bytes())},
            "quality": {"samples": len(rows), "transitions": len(observations),
                        "canonical_comparisons_equal": len(rows),
                        "delta_reconstructions_equal": len(rows),
                        "statuses": dict(sorted(Counter(row["status"] for row in rows).items())),
                        **transport_summary(rows), "rows": rows},
            "observations": {"repeats": repeats, "python": platform.python_version(),
                             "platform": platform.platform(), "transitions": observations}}



def rerender(initial_path):
    """Replay identical graph IDs with both preserved and compact renderers."""
    initial = read_json(initial_path)
    captured_provenance = provenance()
    legacy_path = DATA / "initial_graph_payload.py"
    specification = importlib.util.spec_from_file_location("contextproof.initial_graph_payload", legacy_path)
    legacy_renderer = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(legacy_renderer)
    if digest(legacy_path.read_bytes()) != initial["provenance"]["initial_renderer_sha256"]:
        raise RuntimeError("preserved initial renderer checksum mismatch")
    samples = read_json(ROOT / "benchmarks/v1/samples.json")["samples"]
    originals = {row["sample_id"]: row for row in initial["quality"]["rows"]}
    rows = []
    for name in sorted({sample["repository"] for sample in samples}):
        before, after = [read_worktree(ROOT / "work/v1-drift/sources" / name / side)
                         for side in ("before", "after")]
        selected = [sample for sample in samples if sample["repository"] == name]
        anchors = selected_anchors(selected, before)
        cache = ParseCache()
        old, _ = build_batch(before, anchors, cache)
        new, _ = build_batch(after, anchors, cache)
        direct_old, _ = build_batch(before, anchors, cache, depth=1)
        direct_new, _ = build_batch(after, anchors, cache, depth=1)
        for sample, left, right, left_direct, right_direct in zip(selected, old, new, direct_old, direct_new):
            previous = originals[sample["sample_id"]]
            current = analyze_pair(sample, left, right, left_direct, right_direct)
            if any(previous[key] != value for key, value in current.items() if key != "payloads"):
                raise RuntimeError("structural graph replay changed during renderer update: " + sample["sample_id"])
            comparison = compare_graphs(left, right)
            legacy_payloads = {"full": legacy_renderer.render_graph_context(right, 16000),
                               "update": legacy_renderer.render_graph_update(left, right, comparison, 16000)}
            for kind, value in legacy_payloads.items():
                keys = previous["payloads"][kind]
                if {key: value[key] for key in keys} != keys:
                    raise RuntimeError("preserved initial renderer does not reproduce recorded metrics: " + sample["sample_id"])
            rows.append({**previous, "payloads": current["payloads"]})
        fair = fair_cache_replay(name, before, after, anchors, [graph["id"] for graph in new], 3)
        observation = next(row for row in initial["observations"]["repositories"] if row["repository"] == name)
        observation["fair_repetitions"] = fair
        print(f"{name}: initial-renderer metrics reproduced and compact delivery rerun", flush=True)
    return {**initial, "quality": summarize(rows) | {"rows": rows},
            "provenance": captured_provenance | {
                "graph_cache_timing_source_sha256": digest(initial_path.read_bytes()),
                "initial_renderer_sha256": digest(legacy_path.read_bytes()),
                "initial_renderer_payload_rows_reproduced": len(rows),
                "rendering_update": "Graph IDs, every non-payload row metric, full/cache equality and deltas are unchanged. Three-repetition construction timings are retained from the preserved run; both old and compact renderers were separately replayed against the same graphs.",
                "source_recovery": "Initial renderer source reconstructed by reversing the compact-renderer patch, then all published initial payload metrics reproduced."}}


def fair_history(initial_path):
    result = read_json(initial_path)
    result["provenance"]["fair_baseline_amendment_sha256"] = digest((DATA / "cache-baseline-amendment.json").read_bytes())
    result["provenance"]["fair_baseline_implementation"] = provenance()
    samples = read_json(ROOT / "benchmarks/v1/samples.json")["samples"]
    for row in result["observations"]["transitions"]:
        name = row["repository"]
        selected = [sample for sample in samples if sample["repository"] == name]
        original = read_worktree(ROOT / "work/v1-drift/sources" / name / "before")
        anchors = selected_anchors(selected, original)
        before, after = [read_worktree(WORK / "history/sources" / name / row[key])
                         for key in ("before_commit", "after_commit")]
        expected = [quality["after_graph_sha256"] for quality in result["quality"]["rows"]
                    if quality["repository"] == name and quality["transition"] == row["transition"]]
        row["fair_repetitions"] = fair_cache_replay(
            name + "-history-" + str(row["transition"]), before, after, anchors, expected, 3)
    return result


def memory_replay(initial_path):
    result = read_json(initial_path)
    result["provenance"]["memory_cache_decision_sha256"] = digest((DATA / "memory-cache-decision.json").read_bytes())
    result["provenance"]["memory_condition_implementation"] = provenance()
    result["provenance"]["preserved_persistent_report_sha256"] = digest(initial_path.read_bytes())
    samples = read_json(ROOT / "benchmarks/v1/samples.json")["samples"]
    historical = "transitions" in result["observations"]
    observed = result["observations"]["transitions" if historical else "repositories"]
    for row in observed:
        name = row["repository"]
        selected = [sample for sample in samples if sample["repository"] == name]
        original = read_worktree(ROOT / "work/v1-drift/sources" / name / "before")
        anchors = selected_anchors(selected, original)
        if historical:
            before, after = [read_worktree(WORK / "history/sources" / name / row[key])
                             for key in ("before_commit", "after_commit")]
        else:
            before, after = [read_worktree(ROOT / "work/v1-drift/sources" / name / side)
                             for side in ("before", "after")]
        expected = [quality["after_graph_sha256"] for quality in result["quality"]["rows"]
                    if quality["repository"] == name and (
                        not historical or quality["transition"] == row["transition"])]
        row["memory_repetitions"] = memory_cache_replay(
            name + ("-history-" + str(row["transition"]) if historical else ""),
            before, after, anchors, expected, 3)
    return result

def markdown(result):
    quality = result["quality"]
    lines = ["# Versioned graph replay", "", result["scope"], "",
             "The protocol was frozen after exploratory graph inspection. Original source-study splits are retained as metadata; this is not a new independent holdout.", "",
             f"Checked {quality['samples']} saved anchors; {quality['delta_reconstructions_equal']} lossless delta reconstructions matched canonical full graphs.", ""]
    if "added_descendant_flags" in quality:
        lines += [f"Depth 4 added {quality['added_flags_vs_depth1']} changed/missing observations over depth 1; {quality['added_descendant_flags']} are changed descendants behind unchanged enclosing roots.", "",
                  f"Status counts at depth 1: `{quality['depth1_statuses']}`. At depth 4: `{quality['depth4_statuses']}`.", "",
                  f"Independent per-anchor full artifacts total {quality['full_graph_bytes']:,} bytes; sealed field deltas total {quality['field_delta_bytes']:,} bytes. Deltas require the matching base. These are serialized UTF-8 bytes, not model tokens or conversation savings.", "",
                  "| Payload at 16,000 UTF-8 bytes | Complete / incomplete / budget too small | Emitted bytes | Omitted node occurrences |",
                  "|---|---|---:|---:|"]
        for kind, values in quality["payloads"].items():
            lines.append(f"| {kind} | {values['statuses']} | {values['consumed_utf8_bytes']:,} | {values['omitted_node_occurrences']:,} |")
        if "baseline_observations" in quality:
            baseline = quality["baseline_observations"]
            lines += ["", f"Baseline observations: revision-change invalidation rejects {baseline['revision_changed_invalidates_all']}/{quality['samples']} anchors; anchor file hashes change for {baseline['anchor_file_hash_changed']}/{quality['samples']}. Original exact-source statuses: `{baseline['existing_v1_exact_source_statuses']}`. Original direct-witness statuses: `{baseline['existing_v1_direct_dependency_statuses']}`. These contracts differ; these counts are not semantic accuracy or false-positive labels."]
        lines += ["", "Incomplete or empty budget-failure payloads are not evidence of equivalent delivery or a successful context refresh. Frontier uncertainty remains visible.", "",
                  "| Repository | Full shared-cache median s | Incremental median s | Full parse misses | Incremental parse misses |",
                  "|---|---:|---:|---:|---:|"]
        for row in result["observations"]["repositories"]:
            reps = row.get("memory_repetitions", row.get("fair_repetitions", row["repetitions"]))
            full_key = "full_after_shared" if "fair_repetitions" in row else "cold_after"
            update_key = "incremental_memory_after" if "memory_repetitions" in row else "incremental_after"
            lines.append(f"| {row['repository']} | {statistics.median(r[full_key]['seconds'] for r in reps):.4f} | {statistics.median(r[update_key]['seconds'] for r in reps):.4f} | {reps[0][full_key]['parse_cache_misses']} | {reps[0][update_key]['parse_cache_misses']} |")
        lines += ["", "Both main timing conditions share one AST cache across the same 30 current-version queries. The full baseline starts that cache empty. The final default-memory condition begins with previous-version process-local ASTs; the separate persistent-AST diagnostic includes JSON persistence writes and remains in JSON and the preserved diagnostic report. Source loading/hashing and previous-cache priming are excluded. AST caches are trusted local optimizations; catalogs and resolutions are rebuilt. Raw full, stable-warm, incremental repetitions and the earlier per-anchor-cold diagnostic are retained in JSON. Small or negative timing differences are reported unchanged."]
        examples = [row for row in quality["rows"] if row["added_descendant_flag"]]
        lines += ["", "Additional observed descendant paths (all selected by the stated condition, not semantic labels):", ""]
        for row in examples:
            paths = [cause for cause in row["changed_cause_paths"] if len(cause["nodes"]) >= 2]
            if paths:
                chain = " → ".join(node["symbol"] for node in paths[0]["nodes"])
                lines.append(f"- {row['repository']} `{row['symbol']}`: `{chain}`.")
    else:
        lines += [f"{quality['transitions']} adjacent transitions; status counts `{quality['statuses']}`.", "",
                  "| Repository / transition | Changed library Python files | Full shared-cache median s | Incremental median s | Incremental parse misses |",
                  "|---|---:|---:|---:|---:|"]
        for row in result["observations"]["transitions"]:
            reps = row.get("memory_repetitions", row.get("fair_repetitions", row["repetitions"]))
            full_key = "full_after_shared" if "fair_repetitions" in row else "cold_after"
            update_key = "incremental_memory_after" if "memory_repetitions" in row else "incremental_after"
            lines.append(f"| {row['repository']} / {row['transition']} | {len(row['changed_source_files'])} | {statistics.median(r[full_key]['seconds'] for r in reps):.4f} | {statistics.median(r[update_key]['seconds'] for r in reps):.4f} | {reps[0][update_key]['parse_cache_misses']} |")
    observations = result["observations"].get("repositories", result["observations"].get("transitions", []))
    if "gzip_full_graph_bytes" in quality:
        lines += ["", f"Conventional gzip comparison (level 9, mtime 0, each message compressed independently): full graphs {quality['gzip_full_graph_bytes']:,} bytes; field deltas {quality['gzip_field_delta_bytes']:,} bytes. Compressed deltas are smaller in {quality['gzip_delta_smaller']}/{quality['samples']} cases. Matching-base availability is required only for deltas; no cross-message compression dictionary or base-transfer cost is included."]
    if observations and all("memory_repetitions" in row for row in observations):
        full = sum(statistics.median(rep["full_after_shared"]["seconds"] for rep in row["memory_repetitions"])
                   for row in observations)
        update = sum(statistics.median(rep["incremental_memory_after"]["seconds"] for rep in row["memory_repetitions"])
                     for row in observations)
        relation = "slower" if update >= full else "faster"
        lines += ["", f"For the default memory condition, summed batch medians are {full:.4f}s full shared-cache and {update:.4f}s before→after replay ({abs(update / full - 1):.1%} {relation}). Three repetitions are descriptive; small timing differences are not a demonstrated general speedup. The negative persistent-AST phase remains separately published."]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--prepare-history", action="store_true")
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--history", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", type=Path)
    parser.add_argument("--memory-replay", type=Path,
                        help="append paired default-memory measurements to preserved diagnostics")
    parser.add_argument("--fair-history", type=Path,
                        help="add fair shared-cache timing to an existing history report")
    parser.add_argument("--rerender", type=Path,
                        help="rebuild identical graphs and rerender a preserved initial report")
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("repeats must be positive")
    if args.prepare_history:
        prepare_history(args.download)
        print("Pinned adjacent-history archives and source manifests are ready.", flush=True)
        return
    result = (memory_replay(args.memory_replay) if args.memory_replay else
              fair_history(args.fair_history) if args.fair_history else
              rerender(args.rerender) if args.rerender else
              run_history(args.repeats) if args.history else run_frozen(args.repeats))
    if args.check and result["quality"] != read_json(args.check)["quality"]:
        raise RuntimeError("graph replay quality differs from recorded results")
    historical = args.history or args.fair_history or "transitions" in result["observations"]
    output = args.output or DATA / ("history-results" if historical else "results")
    write_json(output.with_suffix(".json"), result)
    output.with_suffix(".md").write_text(markdown(result))


if __name__ == "__main__":
    main()
