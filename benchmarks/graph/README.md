# Versioned source-evidence graph replay

This engineering study reuses every one of the 300 frozen v1 source anchors and adds 15 actual adjacent upstream transitions (450 anchor-transition observations). It measures static source observations, canonical rebuild/cache equality, lossless field-delta reconstruction, required-source delivery, and parser work. It does not label semantic staleness, establish downstream task success, claim a new graph algorithm, or measure billed model tokens.

The corrected resolver-2 release replay reconstructs all 300 current graphs exactly and observes five additional changed descendant paths at depth 4 versus depth 1. Gzip-compressed full graphs total 4,665,737 bytes versus 2,293,057 for compressed deltas; deltas are smaller in 218 cases and full graphs in 82. Default memory replay was 2.2% slower than the fair full-rebuild baseline; persistent AST replay was 6.8% slower. These measurements do not demonstrate a speedup. Only one full payload and one update payload are complete for their declared scope within 16,000 bytes. Current graphs contain unresolved frontiers for 231 anchors, truncation for 41, and missing roots for 68 (categories overlap).

All 450 adjacent-history observations also match fresh construction and lossless reconstruction. Gzip-compressed full graphs total 8,127,596 bytes versus 844,340 for deltas, which are smaller in 445 cases. Incremental parsing misses equal the number of changed accepted source files in each of the 15 transitions. Default memory replay was 1.2% faster and persistent AST replay 1.1% faster on these sparse changes; these small, descriptive differences do not establish a general speedup. The observed statuses are 32 changed and 418 unresolved, not behavioral correctness labels.

- [Protocol](protocol.json): fixed sample and graph scope. Frozen after exploratory inspection, not a new independent holdout.
- [Timing and delivery amendment](cache-baseline-amendment.json): retain the initial failures, give both main timing conditions same-version AST reuse, and replay compact delivery on identical graphs.
- [Default memory-cache decision](memory-cache-decision.json): remove the observed persistent-AST overhead from the default live-session path; add a separately paired memory measurement.
- [Resolver correctness amendment](scope-correction-amendment.json): shared conservative lexical/module guards, a complete corrected replay, and conventional gzip transport baselines. The [eight-case audit](scope-audit.json) retains the historical false-fresh receipts and verifies current graph, direct, and previously captured direct evidence.
- Preserved resolver-1 final phase: [release pairs](pre-scope-fix-results.md), [raw release metrics](pre-scope-fix-results.json), [adjacent history](pre-scope-fix-history-results.md), [raw history metrics](pre-scope-fix-history-results.json). The [SHA-256 manifest](pre-scope-fix-manifest.json) covers every historical study phase. Known resolver-1 bugs make these historical development records, not current correctness evidence.
- Preserved persistent-AST phase: [release pairs](persistent-cache-results.md), [raw release metrics](persistent-cache-results.json), [adjacent history](persistent-cache-history-results.md), [raw history metrics](persistent-cache-history-results.json).
- [Final release-pair results](results.md), [all rows and repetitions](results.json).
- [Adjacent-history results](history-results.md), [all rows and repetitions](history-results.json).
- [Pinned first-parent commits](history_manifest.json), [archive and accepted-source hashes](history_sources.json).
- [Preserved initial renderer failures](initial-renderer-results.md), [raw initial metrics](initial-renderer-results.json), [recovered initial renderer source](initial_graph_payload.py).

Full and incremental main timing conditions each process the same 30 current-version queries with a shared AST cache. Full starts its cache empty. The final default-memory condition starts with previous-version process-local ASTs; stable-warm reuses the current version. The separate persistent-AST diagnostic includes JSON persistence writes. It was slower across the far-apart release pairs and is preserved, not silently relabeled as memory performance. Previous-cache priming, source loading/hashing, and Git-object transport are outside these measurements. The earlier fresh-per-anchor parsing baseline remains a diagnostic in JSON; it is not the main speed comparison.

One anchor per graph gives every anchor the same 256-node limit. Graph closure observes complete enclosing declarations, which can be larger than the originally selected snippets. Root changes are separated from descendant changes behind unchanged roots. Unknown runtime resolution and depth/node limits remain explicit. Per-anchor artifact sums duplicate shared nodes; JSON includes unique source/node totals to expose that overhead.

The 16,000-byte limit covers each complete rendered model string. `complete` is scoped to delivery of the recorded static closure/update, not behavior. Updates require their identified base. Incomplete output, omitted nodes, and an empty budget-failure result must not be presented as equivalent full delivery. Field-delta byte reductions concern serialized graph transport/storage only. The corrected replay additionally compresses each canonical full artifact and sealed delta independently with gzip level 9 and `mtime=0`; it publishes per-case sizes, totals, and the count of cases where the compressed delta is smaller. Deltas require an already-held matching base, whose delivery cost is excluded. No cross-message compression dictionary is used.

The corrected release-pair implementation digest was captured with package label
`1.0.0`; the adjacent-history digest uses label `1.1.0`. Their source difference is
only `__version__` in `src/contextproof/__init__.py`; resolver, renderer, delta and
cache code are identical. Both original digests remain recorded. The
[current official SDK check](mcp-interop.json) identifies server `1.1.0`; the
[earlier SDK record](mcp-interop-resolver1.json) is retained separately.

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

Historical renderer and cache-only replay modes require the matching historical resolver implementation recorded in those reports. Resolver 2 changes graph identities and rejects resolver-1 comparisons; old reports must not be passed to a current replay as if their graph policy were unchanged. The preserved initial renderer was recovered from patch history, then every recorded initial payload metric was reproduced before the scope correction. All raw historical reports and their integrity hashes remain available above.

Raw local files stay under ignored `work/`; published reports contain repository-relative upstream paths and hashes, not local personal paths.
