# Development log

This record describes actual work completed on 2026-09-21. ContextProof is maintained
by hardwork-xu with AI assistance for design, implementation, experiments, and writing.
It does not imply a longer development history, a separate engineering team, or an
independent human annotation study.

## 2026-09-21 — Initial prototype

**Problem and implementation.** Selected the problem of saved code evidence becoming
stale after repository changes. Implemented source scanning, Python AST chunks,
SQLite parsing cache, BM25, a small graph-expansion heuristic, complete-payload
budgeting, exact-text verification, conservative citation repair, CLI, and a
fixed-root MCP interface. The initial public milestone was v0.1.

**Contract decisions.** Used UTF-8 bytes as the default budget unit and counted
the complete rendered source payload. Whole chunks that did not fit were omitted.
Original exact locations took precedence over identical copies; displaced text
required a unique whole-line match for repair. Changed, missing, ambiguous, and
unsafe evidence was explicitly invalidated. Hashes were described as integrity
checks, never as signatures or semantic-equivalence proofs.

**Initial measurements.** Froze version pairs for Click, ItsDangerous, and MarkupSafe;
recorded 118 natural-drift observations, seven controlled transformations, and
84 retrieval runs from fourteen queries, two methods, and three budgets. Graph
expansion performed worse than BM25 at 2,000 bytes, tied at 4,000, and better at
8,000 on this small query set. The mixed result and limited Pallets-only sample
remain in the [earlier report](../benchmarks/results/latest.md).

## 2026-09-21 — Complete v1 project scope

**Scope correction.** A runnable prototype was an intermediate milestone. The
[completion contract](COMPLETION.md) expanded the deliverable to an end-to-end
capture/check/refresh workflow, direct dependency diagnostics, broader frozen
evaluation, executed downstream tasks, reporting, and reproducible documentation.
Positive experimental findings were not made a completion requirement.

**Product workflow.** Added bound context artifacts containing a source bundle and
separate dependency sidecar. Added `capture`, `check`, `refresh`, and offline `report`
commands, preserving the source-only API and expanding MCP to eight tools. A small
original demo changes a tax-rate helper while its caller remains text-identical;
its three reports show reuse, retrieval after the dependency edit, and reuse after
refresh. The report is self-contained and uses no external assets.

**Dependency contract.** Implemented supported direct Python definitions, literal
constants, and import-binding witnesses. Aliases and supported re-exports retain
binding identity; ambiguous, external, dynamic, or unsupported references abstain.
The resolver remains one hop. Sidecar bytes are measured as additional overhead,
not hidden inside the source bundle's stated budget. All 34 predeclared controlled
cases matched; none of the twelve stale or twelve unresolved cases was accepted
as fresh. Seven-repetition timing and source-scan scaling measurements were retained
in the [dependency report](../benchmarks/results/dependencies.md).

**Broader frozen study.** Recorded a protocol before source acquisition, sampling,
annotation, or predictions. Pinned two versions each of ten Python libraries from
ten GitHub owners. Selected thirty snippets per repository using before-version
information only, with seven development and three holdout repositories. Both
engine and a separately implemented byte-offset reference received the same frozen
source policy. The resulting 300/300 agreement is reported as scoped contract
agreement, not human-labeled accuracy. First-run predictions and all artifact
hashes are preserved.

**Blinded cross-check.** A separate AI reviewer inspected selected source evidence
without reference labels or engine predictions. A disclosed protocol amendment
increased coverage before predictions and review; the sealed 21-item check agreed
on every item. Its limited, purposive AI-review status is explicit in the
[comparison](../benchmarks/v1/review_comparison.json).

**Corpus-boundary correction.** Inspection of the first drift results found that
23 dateutil tests labeled deleted had moved outside the registered library prefixes,
while exact unique matches survived elsewhere in the newer archive. The primary
labels were retained as scoped outcomes and prominently identified as corpus exits.
A separate posthoc all-Python-scope sensitivity kept the same 300 samples and changed
exactly those 23 labels to relocated. Both primary and sensitivity results remain
available; the wider search was not presented as a new prospective holdout test.

**Natural dependency diagnostics.** Applied witness checks to the same frozen drift
samples and recorded repeated measurements and sidecar sizes. Interpretation keeps
source-anchor changes and moves separate from changes to a direct target or import
binding. The source reference does not label dependency behavior, so additional
flags are diagnostics rather than measured semantic detection accuracy.

**Executed model study.** Froze HumanEval IDs 0–19 with controlled request-decoder
API adaptations, three context policies, complete prompts, a native Qwen context
cap, one attempt per condition, and one pinned local 1.5B model. Downloaded the
model through a disclosed mirror after direct access failed, recorded every file
hash, and ran without a paid API or uploading source to a model service. The model
ran all sixty cells; every condition scored 0/20. Fifty-four outputs invented a
nonexistent module, while the remaining six had decoder/name/argument errors.
There were no hidden retries, replacement models, or selected favorable examples.

**Harness controls and publication hygiene.** macOS Seatbelt preflight checks
confirmed the execution boundary; AST/import restrictions and resource limits
provided additional controls. All sixty outcomes reproduced on replay. Post-run
known-good algorithms passed 20/20 using current APIs, while obsolete APIs passed
only the five unchanged tasks. Canonical algorithms never entered model inputs.
Local diagnostic paths were redacted in a separate publication step; unredacted
originals, raw/public checksum pairs, and byte-identical frozen prompts were preserved.
The [downstream report](DOWNSTREAM.md) states the null conclusion and its limits.

**Final documentation and verification.** Replaced the proposed-work roadmap with
an evidence-linked completion matrix. Added the technical report, bilingual v1
entry points, explicit budget boundaries, and a demonstration screenshot. Local
checks cover contracts, malformed inputs, source-policy boundaries, CLI/MCP flows,
packaging, and artifact integrity. Release verification and remote CI remain
observable in [GitHub Actions](https://github.com/hardwork-xu/agent-code-evidence/actions)
and [Releases](https://github.com/hardwork-xu/agent-code-evidence/releases); this log does
not freeze a changing test count or assert a remote status before it is recorded.

## 2026-09-21 — Versioned graph evidence and real revision evaluation

**Value audit and corrected scope.** The prior small-model study could not answer
whether useful source improved a capable model. Reviewing current primary sources
also showed that graph retrieval and incremental dependency reuse are established.
The project now focuses on source identity, explicit uncertainty, auditable version
transitions and exact transport contracts. No novelty or general-agent success is
inferred from test counts.

**Delivered source.** Added immutable Git-object reads, bounded transitive Python
evidence, durable full-graph handles, exact field deltas, and complete model-payload
budgeting through CLI and the official MCP SDK. A changed supported helper now
appears in delivered source when the allowance permits it. Reads verify blob IDs,
reject unsafe paths and deny lazy fetching or repository-configured remote commands.
The generated three-hop demonstration checks source delivery and reconstruction.

**Counterexamples and failed approaches.** An independent AI-assisted review found
eight concrete scope/binding cases incorrectly treated as fresh. Resolver v2 fixes
them conservatively in both graph and direct-witness APIs; old graph versions must
be recaptured. All fixtures and original outcomes remain public. The initial
renderer overflowed its budget with diagnostics, and persisted JSON ASTs lost to a
fair shared-cache baseline. Compact bounded diagnostics and default in-memory reuse
replace those designs; original measurements remain separately versioned.

**Capable-model comparison.** Froze 30 real upstream-derived API probes, 5 for
development and 25 held out, with executed version-specific oracles. After a 5/5
development gate, published inputs preceded all 150 held-out completions across
six context conditions. Stale source scored 8/25; graph, current supplied source
and BM25 each scored 24/25; Archex scored 21/25. The graph tied the same-anchor
source comparator while using more input tokens. Its advantage over stale source
does not establish a unique retrieval benefit.

**Versioned sensitivity and publication.** Corrected graph contexts were separately
frozen and all 25 rerun; all answers matched the original graph run, still 24/25.
This post-freeze sensitivity is exploratory, with 125 original comparator results
reused. Public exports retain every answer, failure, timing and usage record. Raw
local logs and personal records stay outside Git. Release building now checks
archive ownership, public maintainer metadata, content hashes and personal paths.
See the [measured report](GRAPH_REPORT.md) for final engineering replay and paired
model results, methodological limits and reproduction records.
