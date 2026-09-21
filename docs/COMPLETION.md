# Project completion contract

The v0.1 release was a working prototype. The project goal is to finish and
publish v1.0 with the following deliverables, not merely defer them to a roadmap.
This contract was recorded before the v1 evaluation results were available.

| Deliverable | Acceptance evidence |
|---|---|
| End-to-end tool | Installable package; capture/check/refresh; backward-compatible source bundle tools; CLI and MCP; usable offline report |
| Dependency diagnostics | Versioned, sealed direct-static witness sidecar; changes, missing targets and unresolved calls explicit; at least 20 predeclared controlled cases and measured overhead |
| Diverse drift evaluation | At least 10 different GitHub owners, 200 before-only samples, frozen archives/hashes/licenses, repository-level development/holdout split |
| Evaluation validity | Independently implemented reference annotation, separated from engine predictions; discrepancies retained and reviewed; AI review explicitly distinguished from human annotation |
| Statistical reporting | Per-repository baseline comparison, paired uncertainty, fixed sampling and holdout before results; negative outcomes retained |
| Executable downstream evaluation | At least 20 frozen public-benchmark-derived tasks, three conditions, identical local model and budgets, all attempts, actual test results, source and model identities |
| Safe reproducibility | Source inspection does not execute upstream repositories; generated-code execution uses verified isolation; portable scripts and frozen protocol |
| Delivery | Passing tests/CI, clean installation, release artifacts, technical report, reproducible demonstration, bilingual guide and real GitHub history |

The initial downstream study may adapt a public function benchmark to controlled
repository API changes. If so, it must be described as an adapted controlled study,
not a score on the original benchmark or a real-world GitHub-issue result. No
model is selected or changed because of observed task success. A small local model
can produce negative or inconclusive results; those are valid completion outcomes.

The independent reference program is an implementation cross-check, not independent
human ground truth. AI-assisted blind checks are reported as such. These constraints
limit the claims; they do not authorize inventing an unavailable external review.

No publication, SOTA, hiring, or downstream improvement is an acceptance requirement.
Completion requires running the declared work and explaining what the results
support. Future extensions may remain, but the deliverables above may not be marked
complete by moving them into another list of future work.
