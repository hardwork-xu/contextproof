# v1 completion matrix and future research

The v1 implementation and declared experiments are delivered. This matrix replaces
the v0.1 list of unexecuted follow-ups with links to the actual code, protocols,
and results. The [completion contract](COMPLETION.md) defines the project boundary;
ongoing release verification is visible in [GitHub Actions](https://github.com/hardwork-xu/agent-code-evidence/actions)
and published packages in [Releases](https://github.com/hardwork-xu/agent-code-evidence/releases).

## Delivered v1 scope

| Deliverable | Completed work | Reviewable evidence |
| --- | --- | --- |
| Usable local workflow | Capture source and witnesses, check, conservatively repair or retrieve, render bounded context | [CLI and quickstart](../README.md), [session implementation](../src/contextproof/session.py) |
| Agent integration | Eight fixed-root MCP stdio tools; source-only operations preserved | [MCP implementation](../src/contextproof/mcp.py), [client example](../examples/mcp.json) |
| Demonstration and reporting | Reproducible dependency-change demo; offline searchable HTML report | [Demo](../scripts/demo.py), [report screenshot](assets/context-report.png) |
| Dependency diagnostics | Sealed direct-static sidecar; unresolved references explicit; 34 controlled cases and repeated overhead measurements | [Contract](DEPENDENCIES.md), [controlled results](../benchmarks/results/dependencies.md) |
| Broader natural drift study | 300 before-only samples from ten owners; immutable version pairs; seven development and three holdout repositories | [Protocol](DRIFT_STUDY.md), [primary results](../benchmarks/v1/results/latest.md) |
| Annotation cross-check | Separate reference implementation, preserved first-run predictions, sealed 21-item blinded AI check | [Reference](../benchmarks/v1/reference.py), [first-run audit](../benchmarks/v1/first_run_audit.json), [review comparison](../benchmarks/v1/review_comparison.json) |
| Corpus-scope sensitivity | Same 300 samples rechecked against broader Python scope; all 23 changed labels retained | [Sensitivity report](../benchmarks/v1/results/scope-sensitivity.md) |
| Natural dependency analysis | Witness diagnostics on the frozen drift samples, with cause and uncertainty limits | [Dependency-drift report](../benchmarks/v1/results/dependency-drift.md) |
| Executed downstream study | 20 public-benchmark-derived tasks × 3 policies, one fixed local model, all 60 attempts, real isolated execution | [Protocol and null result](DOWNSTREAM.md), [raw responses](../benchmarks/downstream/results/results.jsonl) |
| Harness validation | All 60 outcomes reproduced; current-API controls 20/20, obsolete-API controls 5/20 | [Replay](../benchmarks/downstream/results/replay.json), [oracle controls](../benchmarks/downstream/results/oracle_controls.json) |
| Reproducibility and packaging | Frozen manifests/hashes, runnable scripts, package build configuration, tests and CI workflow | [Build configuration](../pyproject.toml), [tests](../tests), [CI](../.github/workflows/ci.yml) |
| Candidate/reviewer documentation | Bilingual entry points, design, technical report, learning guide and dated development record | [Technical report](TECHNICAL_REPORT.md), [Chinese guide](README.zh-CN.md), [development log](DEVELOPMENT_LOG.md) |

Completion means the declared work was implemented, run, and made inspectable.
The downstream study's 0/20 result in every condition is a completed negative
experiment. It is not a postponed positive-result requirement. The blinded review
is AI review, not a claim that independent humans have supplied ground truth.

## Extensions beyond the completed project

These are possible research directions, not remaining work hidden behind a future
version number. They require new protocols and should retain the v1 evidence.

| Direction | Question worth testing | Evidence needed before making a stronger claim |
| --- | --- | --- |
| Independent human annotation | Do people agree with the source contract and its practical relevance? | Independent annotators, explicit guidance, disagreements, and a broader sample |
| Runtime and deeper dependencies | Which staleness lies beyond one-hop static witnesses? | Labeled multi-hop/runtime examples, supported-language boundaries, and measured false invalidation |
| Real issue-resolution tasks | Does evidence verification help a working coding agent? | Frozen repository-disjoint real tasks, reliable execution environments, fixed agent/model policies and all attempts |
| Stronger and interactive agents | Does a model that follows the API contract respond differently to stale and verified context? | A new prospective protocol, multiple seeds/models where feasible, task success and full workflow cost |
| Mature-system comparisons | Does the evidence workflow add value to existing retrieval or repository-map tools? | Comparable task context, budgets and integration effort; reproduction of each baseline's intended use |
| Concurrent editing and scale | Can a consistent source snapshot and lower scan cost improve practical use? | Snapshot identity under mutation, large-repository workloads, and repeated end-to-end measurements |
| External research validation | Are the claims independently reproducible and publication-ready? | Outside replication and review; any submission or acceptance reported only when it occurs |

No extension implies a current publication, semantic-equivalence guarantee,
state-of-the-art retrieval result, or demonstrated improvement in model task success.
