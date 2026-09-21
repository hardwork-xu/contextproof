# Research framing and related work

## Question

After a coding agent has read repository evidence and the repository changes,
which citations remain exact, which can be relocated without guessing, and which
must be invalidated? When the caller text remains identical, do captured direct
static definitions and import bindings remain identical too? ContextProof v1.0
studies these bounded contracts through explicit evidence objects, a conservative
cross-version verifier, and an executable capture/check/refresh workflow.

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
| [ContextBench](https://arxiv.org/abs/2602.05892) | Context-retrieval evaluation for coding agents | A possible external benchmark; no ContextBench results are claimed |

Sources reviewed on 2026-09-21. The literature review identifies project focus,
not proof that no prior system implements similar verification.

## Falsifiable hypotheses

1. Exact-span verification can retain unaffected snippets after unrelated edits
   while whole-file hashes invalidate them. Test with controlled edits and report
   both invalidation rates and incorrect acceptance rates.
2. Unique exact-text relocation recovers shifted or moved citations without
   accepting modified text. Test ambiguous duplicates separately.
3. Dependency changes can make unchanged snippets insufficient. v1 implements
   direct static witnesses and tests 34 predeclared cases. This covers direct
   source and binding identity; transitive or runtime equivalence is not proved.
4. Replacing stale context may improve downstream agent outcomes. The completed
   fixed-model comparison produced 0/20 in each of three conditions. These results
   do not establish a downstream benefit; most generations invented an import.
   Positive canonical controls passed 20/20 tasks. Retrieval or relocation scores
   alone cannot establish model effectiveness.

## Completed evidence and remaining research limits

The [drift study](DRIFT_STUDY.md) includes 300 frozen before-only samples from ten
owners, a repository-level holdout, independently implemented reference matching,
baseline comparisons, uncertainty intervals, and measured cache timings. Agreement
is agreement with the declared exact-text protocol, not human semantic truth.
The purposive 21-item blind AI check is disclosed separately. Expanding source
scope reclassifies 23 original corpus exits as relocations; the unchanged primary
sample and both reports are public.

The [dependency study](DEPENDENCIES.md) reports controlled cases and overhead.
Natural-drift observations separate anchor movement from changed direct references
and have no independent dependency correctness labels. The [downstream study](DOWNSTREAM.md)
publishes 20 adapted HumanEval tasks, all 60 actual generations, fixed model and
budget settings, isolated execution and positive controls. It is an artificial
API-adaptation study, not a HumanEval score or real-world issue benchmark.

A publication-strength extension would need independent human review, broader
languages and change types, comparisons with mature external systems, and a
preregistered capable-model experiment. Those are research extensions beyond the
completed [v1 delivery contract](COMPLETION.md), not claims made by this release.
