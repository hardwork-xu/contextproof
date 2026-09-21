# Versioned source evidence: implementation and measured limits

ContextProof now connects change detection to actual source delivery. The earlier
workflow could detect a changed helper yet refresh the same unchanged caller,
leaving the helper in a sidecar outside the declared source budget. The graph
workflow includes supported current dependencies in the actual model-visible
allowance and retains the full evidence graph separately.

This is a source-evidence system and empirical study. It is not a new retrieval
algorithm, complete Python semantic analysis, or proof that graph context improves
general coding-agent success. [Archex](https://github.com/Mathews-Tom/archex) already
provides graph-aware retrieval, freshness receipts, budget information and
incremental refresh. Dependency-aware reuse is established in systems such as
[Salsa](https://salsa-rs.github.io/salsa/). The stale-context problem is also studied
by [When Retrieval Hurts Code Completion](https://arxiv.org/abs/2605.14478).
Our contribution is an inspectable implementation, exact source/update contracts,
reproducible measurements and documented counterexamples.

## Delivered behavior

Immutable Git reads bind a source mapping to a commit and independently verify
blob identities. They deny lazy fetch and repository-configured remote execution;
a missing local object is an error. Working-tree reads hash current bytes but do
not promise an atomic multi-file snapshot. Source filtering and symlink rules
remain shared with the original indexer.

The graph stores stable path/symbol/kind identities, text fingerprints, import
bindings, supported reference paths, cycles and explicit unresolved/truncated
frontiers. Defaults are depth 4 and 256 nodes. Class/function declarations are
preserved whole. Source selection remains BM25 or explicitly supplied anchors.

A field delta names the required base and target graphs. Application validates
the base, edit structure and reconstructed target seal. Line-position changes
need not retransmit source text. This establishes exact reconstruction, not
authenticity, program equivalence or removal of tokens from a past conversation.

MCP stores full graphs behind local handles. Its new graph tools return exactly
the already-counted UTF-8 payload string. Source, citations, handles, compact
reference records and summarized diagnostics all count. Truncation and omitted
source remain explicit; `complete` is scoped delivery, not task sufficiency.
The [API guide](GRAPH.md) and [generated demonstration](assets/graph-demo.html)
show the executable workflow.

## Real revision model comparison

The [pre-model protocol](REVISION_STUDY_PROTOCOL.md) and all inputs were public in
commit `0c6d0be9713971c36430c2f9f80cf24240e4e8da` before held-out completions.
Five development probes qualified the model at 5/5. The frozen study then ran
25 held-out probes × six conditions, with one semantic attempt per cell. All
150 completions were valid; failures and transport messages remain in the
[sanitized records](../benchmarks/revision_tasks/model-results/holdout/).

Each question predicts the exact JSON output or exception class of a small real
API probe. Oracles execute pinned packaging, HTTPX, Pluggy and attrs versions in
a verified sandbox. Retrieval excludes upstream tests and changelogs. All methods
receive the same upstream-derived source hints and a 16,000-byte evidence cap.
This controls source information but gives privileged localization; it does not
measure finding an unknown bug or completing a repository issue.

| Frozen resolver-v1 condition | Exact current-version answers | Wrong answers matching old behavior | Mean evidence bytes | Total input tokens |
|---|---:|---:|---:|---:|
| No context | 21/25 | 3 | 0 | 155,974 |
| Stale supplied source | 8/25 | 16 | 4,190 | 181,795 |
| Fresh supplied source | 24/25 | 1 | 4,189 | 181,712 |
| Fresh BM25 | 24/25 | 1 | 15,894 | 268,685 |
| Current graph, resolver v1 | 24/25 | 1 | 12,183 | 241,809 |
| Archex 0.31.2 native query | 21/25 | 2 | 14,402 | 252,611 |

Old-behavior errors count only the 19 tasks whose executed output changed. Six
unchanged controls remain in all denominators. There are 25 declared task families
but only four repositories, shared revision pairs and overlapping implementation
areas. These are descriptive paired observations, not 25 IID samples supporting
a population-level superiority claim.

The primary result is a tie: graph context and supplied fresh declarations answer
exactly the same 24 tasks correctly. Graph input uses 33.1% more reported input
tokens than that simpler comparator. Fresh BM25 also scores 24/25, with one
different success and one different failure relative to the graph. Archex's
three fewer successes are observations on this small, hinted task set and this
explicit non-embedding configuration, not a general ranking of the tools.

The stale-source condition is worse than no source: 16 errors reproduce old
behavior. Current source corrects those 16 errors. This supports handling stale
evidence, but does not establish a benefit unique to a dependency graph. The
result changes the project's positioning: emphasize auditable version transitions
and exact source transport; do not market graph expansion as a superior retriever.
When exact current symbols are already known, source-only delivery is the lower
overhead choice in this study.

The model is hosted `gpt-6-astra` at medium reasoning through an instrumented Codex
CLI. Instructions and schema are fixed; all execution, discovery and browsing
tools are disabled. Input tokens include the common harness overhead. Weight
versions and a generation seed are unavailable; no subscription token count is
converted into a monetary cost.

## Correctness review and versioned sensitivity

Independent AI-assisted code review, separate from model outcome tuning, found
concrete false-fresh counterexamples after the original freeze. The eight
preserved fixtures cover structural-pattern captures, hidden module rebinding,
conditional wildcard imports and unsafe package-submodule fallback.
Their exact fixtures, old/current receipts and implementation hashes are in the
[public scope audit](../benchmarks/graph/scope-audit.json).

Resolver v2 adds conservative scope/binding guards to both the graph and currently
served direct-witness APIs. All eight graph cases stay unresolved and omit the
incorrect dependency; all eight new direct captures and all eight historical
direct artifacts refuse reuse under the corrected checker. These are selected
regressions with independently specified counterexamples, not a semantic accuracy
estimate for arbitrary Python. Old graph resolver versions require recapture.

The original 150 records were not changed. Corrected contexts were frozen
separately for all 25 tasks; four changed their delivered source, while the others
changed only graph/diagnostic metadata. A separate single-attempt sensitivity
run used the same model and budgets, reusing all 125 original comparator records.
Its independently frozen protocol was public before its completions. It remains
exploratory because the correction and run occurred after partial original
outcomes were visible.

The [corrected results](../benchmarks/revision_tasks/model-results/scope-sensitivity/summary.json)
score **24/25**, comprising 18/19 changed-behavior probes and 6/6 controls, with no
invalid completions. All 25 parsed answers are identical to the original graph's
answers: there are zero gains and zero regressions. The sole failure remains
`httpx-userinfo-encoding`, whose answer matches the old behavior. Fresh supplied
source also has the same 24 successes and one failure, so neither graph run
demonstrates improved output prediction over that primary comparator.

| Source condition | Exact answers | Mean evidence bytes | Total input tokens |
|---|---:|---:|---:|
| Fresh supplied source, original run | 24/25 | 4,189.00 | 181,712 |
| Graph resolver v1, original run | 24/25 | 12,183.44 | 241,809 |
| Graph resolver v2, exploratory sensitivity | 24/25 | 12,176.40 | 241,255 |

The four changed source payloads belong to `packaging-iterable-specifiers`,
`packaging-missing-metadata`, `httpx-empty-params`, and `httpx-query-control`.
All four remain correct. This rerun does not isolate a causal model effect of the
scope correction: only four source payloads changed, all 25 calls were sampled
again, and no fixed generation seed or immutable hosted weights are available.
The correctness repair is established by the explicit regression fixtures; this
small, hinted model study records no answer changes.

![Exact counts and paired outcomes, preserving original resolver-v1 and exploratory resolver-v2 results separately](assets/revision-results.svg)

## Engineering replay and failed approaches

The [graph study](../benchmarks/graph/README.md) replays 300 original saved anchors
and 450 observations across 15 actual adjacent commit transitions in three
repositories. It checks canonical full/cache equivalence and exact delta
reconstruction, distinguishes root changes from deeper source observations, and
reports unresolved/truncated coverage rather than inventing semantic labels.
Historical phases remain separately named with integrity manifests.

The first renderer could spend its allowance on diagnostics, leaving no source.
The initial 300-case phase had 27 full and 114 update payloads whose metadata alone
exceeded 16,000 bytes. Summarized frontiers, bounded examples and stored full
handles address that failure without silently declaring missing evidence complete.

A first cache comparison unfairly rebuilt parsing independently for every query.
It was retained as a diagnostic and replaced by a shared-cache full baseline.
Against the fair baseline, JSON AST persistence was about 8% slower in the initial
release-pair replay. The product default therefore uses memory reuse across MCP
requests; disk AST persistence is explicit opt-in. Catalogs and resolutions are
still rebuilt. This is not an incremental semantic dependency engine, and small
timing differences are not promoted as reliable speedups.

The corrected resolver-v2 release-pair replay reconstructs all **300/300** target
graphs exactly, with canonical cache/full agreement across three repetitions.
Depth 4 observes five changed descendants behind unchanged enclosing roots that
depth 1 misses, including HTTPX's `LocalProtocolError → ProtocolError →
TransportError → RequestError`. These are inspectable source changes, not
independent labels of behavior or proof of task relevance.

| Corrected release-pair measurement | Full graph | Field delta |
|---|---:|---:|
| Serialized artifact bytes, 300 observations | 24,453,398 | 9,725,769 |
| Independently gzip-compressed bytes | 4,665,737 | 2,293,057 |

Compressed deltas total 50.9% fewer bytes and are smaller individually in 218/300
cases. The other 82 cases remain in the denominator. Deltas require a matching
base already held by the client; its acquisition cost is excluded. Each message
uses gzip level 9 with `mtime=0`, without a shared compression dictionary.
Per-anchor graphs duplicate shared nodes, and the raw report exposes unique-node
and source totals. These are transport/storage measurements, not model tokens.

At 16,000 bytes only **1/300** full payloads has complete scoped coverage; the
other 299 expose unresolved frontiers or omissions. Updates have one complete,
297 incomplete and two metadata-budget failures. The selected real Python code
frequently exceeds this resolver's support or delivery limits. Nonempty useful
source can still be delivered, but this does not justify claiming a complete
refresh on those cases or a sound general Python dependency analysis.

The corrected memory-cache comparison is **2.2% slower** in summed batch medians
(19.9711 s versus 19.5395 s for a fair shared-cache rebuild). Persisted ASTs are
6.8% slower in the separately paired comparison. Three repetitions and one host
are descriptive; the current evidence supports no general speedup. Prior-version
cache priming, source loading/hashing and Git transport are outside these timings.

Across the 15 adjacent transitions, all **450/450** target graphs also reconstruct
exactly and match full/cache construction. There are 32 changed observations and
418 unresolved ones. Full artifacts total 43,041,317 bytes versus 5,453,109 delta
bytes; gzip totals are 8,127,596 versus 844,340 bytes, with deltas smaller in
445/450 cases. The histories contain few changed accepted files (zero to two per
transition), so they describe a different change regime from release pairs.

Memory-cache batch medians total 21.4105 s versus 21.6770 s for shared-cache full
rebuild, a small 1.23% difference in the opposite direction to release pairs.
Persistent-cache timings are similarly close (20.9461 s versus 21.1858 s).
This mixed timing evidence reinforces the absence of a demonstrated general
speedup. The exact reconstruction and model-byte budget contracts are separate
from performance. Artifact compression does not establish billed-token savings:
the model experiment supplies full current context, and update views require a
retained identified base.

## Boundaries and reproduction

The evidence supports the implemented contracts and the stated diagnostic
questions. It does not establish runtime soundness, low false-invalidation rates,
independent human labels, unseen-repository generalization, long-running agent
success or a novel algorithm. Source inference remains conservative and Python
specific. Complete source units can exceed the allowance; updates can require
more metadata than a small cap can hold.

Run the linked graph and model protocols for exact commands and artifact hashes.
Ordinary tests and CI do not call hosted models. The
[historical v1 study](TECHNICAL_REPORT.md), including all 60 unsuccessful small-model
generations, remains intact. Public exports preserve answers, scores, costs in
tokens and failures while replacing personal paths and local session identifiers.
Raw originals and privacy backups stay outside Git.
