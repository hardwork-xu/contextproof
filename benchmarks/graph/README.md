# Versioned source-evidence graph replay

This engineering study reuses every one of the 300 frozen v1 source anchors and adds 15 actual adjacent upstream transitions (450 anchor-transition observations). It measures static source observations, canonical rebuild/cache equality, lossless field-delta reconstruction, required-source delivery, and parser work. It does not label semantic staleness, establish downstream task success, claim a new graph algorithm, or measure billed model tokens.

- [Protocol](protocol.json): fixed sample and graph scope. Frozen after exploratory inspection, not a new independent holdout.
- [Timing and delivery amendment](cache-baseline-amendment.json): retain the initial failures, give both main timing conditions same-version AST reuse, and replay compact delivery on identical graphs.
- [Default memory-cache decision](memory-cache-decision.json): remove the observed persistent-AST overhead from the default live-session path; add a separately paired memory measurement.
- Preserved persistent-AST phase: [release pairs](persistent-cache-results.md), [raw release metrics](persistent-cache-results.json), [adjacent history](persistent-cache-history-results.md), [raw history metrics](persistent-cache-history-results.json).
- [Final release-pair results](results.md), [all rows and repetitions](results.json).
- [Adjacent-history results](history-results.md), [all rows and repetitions](history-results.json).
- [Pinned first-parent commits](history_manifest.json), [archive and accepted-source hashes](history_sources.json).
- [Preserved initial renderer failures](initial-renderer-results.md), [raw initial metrics](initial-renderer-results.json), [recovered initial renderer source](initial_graph_payload.py).

Full and incremental main timing conditions each process the same 30 current-version queries with a shared AST cache. Full starts its cache empty. The final default-memory condition starts with previous-version process-local ASTs; stable-warm reuses the current version. The separate persistent-AST diagnostic includes JSON persistence writes. It was slower across the far-apart release pairs and is preserved, not silently relabeled as memory performance. Previous-cache priming, source loading/hashing, and Git-object transport are outside these measurements. The earlier fresh-per-anchor parsing baseline remains a diagnostic in JSON; it is not the main speed comparison.

One anchor per graph gives every anchor the same 256-node limit. Graph closure observes complete enclosing declarations, which can be larger than the originally selected snippets. Root changes are separated from descendant changes behind unchanged roots. Unknown runtime resolution and depth/node limits remain explicit. Per-anchor artifact sums duplicate shared nodes; JSON includes unique source/node totals to expose that overhead.

The 16,000-byte limit covers each complete rendered model string. `complete` is scoped to delivery of the recorded static closure/update, not behavior. Updates require their identified base. Incomplete output, omitted nodes, and an empty budget-failure result must not be presented as equivalent full delivery. Field-delta byte reductions concern serialized graph transport/storage only.

## Reproduce

From an installed development checkout (Python 3.11+):

```sh
python scripts/run_drift_benchmarks.py --download --prepare-only
python scripts/run_graph_benchmarks.py --repeats 3 \
  --check benchmarks/graph/results.json --output work/graph-replay/results
python scripts/run_graph_benchmarks.py --prepare-history --download
python scripts/run_graph_benchmarks.py --history --repeats 3 \
  --check benchmarks/graph/history-results.json --output work/graph-replay/history
```

The committed history manifest already contains actual SHAs and parent links. Its archive replay uses `curl`; `gh` is needed only to construct a missing manifest. Upstream archives are safely read as regular source files; upstream code is never imported or executed. Python parser versions can affect static extraction; the public reports record the version used.

To validate the preserved initial renderer against every initial payload metric and rerun compact delivery without repeating the old per-anchor-cold diagnostics:

```sh
python scripts/run_graph_benchmarks.py \
  --rerender benchmarks/graph/initial-renderer-results.json \
  --output work/graph-replay/compact
```

This asserts identical graph IDs and every non-payload metric, replays both renderers, and reruns the fair persistent-AST measurements. The final memory-only condition can be appended independently with `--memory-replay benchmarks/graph/persistent-cache-results.json` and `--memory-replay benchmarks/graph/persistent-cache-history-results.json` (use `--output` for a scratch report). Raw local files stay under ignored `work/`; published reports contain repository-relative upstream paths and hashes, not local personal paths.
