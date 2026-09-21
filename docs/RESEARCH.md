# Research framing and related work

## Question

After a coding agent has read repository evidence and the repository changes,
which citations remain exact, which can be relocated without guessing, and which
must be invalidated? ContextProof v0.1 studies this narrower problem through an
explicit evidence object and a conservative cross-version verifier.

## Positioning

This is an engineering and empirical project, not a claim of a new retrieval
algorithm. Its core value is a testable evidence contract, auditable failure
states, reproducible drift experiments, and an interface agents can use.

| Prior work | What it already contributes | How this project relates |
|---|---|---|
| [Aider RepoMap](https://aider.chat/docs/repomap.html) | Dependency-based repository maps fitted to a context budget | Strong prior art; graph selection plus budgets are not novel here |
| [archex](https://github.com/Mathews-Tom/archex) and its [receipts](https://github.com/Mathews-Tom/archex/blob/main/docs/CONTEXT_RECEIPTS.md) | Local retrieval, graph expansion, budget bundles, receipts, incremental refresh | Closest engineering comparison; ContextProof focuses on verifying previously emitted evidence across versions |
| [jCodeMunch](https://github.com/jgravelle/jcodemunch-mcp) | Symbol extraction, content-hash indexing, MCP | Incremental hashing is established infrastructure |
| [RepoGraph](https://github.com/ozyyshr/RepoGraph) | Repository graphs for software engineering agents | Strong related graph method; our one-hop baseline is not a reproduction |
| [Agent Retrieval Bench](https://arxiv.org/abs/2607.24882) | Repository workflow retrieval and selective retrieval evaluation | Future external quality evaluation; our small diagnostic queries do not replace it |
| [ContextBench](https://arxiv.org/abs/2602.05892) | Context-retrieval evaluation for coding agents | A possible external benchmark; no ContextBench results are claimed in v0.1 |

Sources reviewed on 2026-09-21. The literature review identifies project focus,
not proof that no prior system implements similar verification.

## Falsifiable hypotheses

1. Exact-span verification can retain unaffected snippets after unrelated edits
   while whole-file hashes invalidate them. Test with controlled edits and report
   both invalidation rates and incorrect acceptance rates.
2. Unique exact-text relocation recovers shifted or moved citations without
   accepting modified text. Test ambiguous duplicates separately.
3. Dependency changes can make unchanged snippets insufficient. v0.1 deliberately
   does not solve this. Extend the evidence object with dependency witnesses and
   evaluate invalidation propagation as a separate experiment.
4. Spending less context on stale evidence may improve downstream agent outcomes.
   This remains untested until the same model, tasks, budget, and execution harness
   are compared. Retrieval or relocation scores alone cannot establish it.

## Next research gates

Before a publication claim, collect a larger repository-disjoint drift corpus,
annotate evidence status independently, freeze a holdout before tuning, run
paired comparisons with uncertainty intervals, and include an existing mature
retrieval system. Study aliases, same-text duplicates, generated code, dependency
changes, and concurrent updates. Compare cold/warm work with actual end-to-end
wall time rather than equating fewer parsed files with speedup.

For a downstream study, use an execution-based public benchmark in an isolated
environment and publish model settings, prompts, all attempts, total cost, and
failures. Do not treat changed files in a patch as complete context ground truth.
