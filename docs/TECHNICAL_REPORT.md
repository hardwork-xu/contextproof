# ContextProof v1.0: verifiable code evidence across repository changes

**Author and maintainer:** hardwork-xu. AI-assisted design, implementation, experiments,
and writing. **Date:** 2026-09-21. This is a project technical report, not a
peer-reviewed publication.

## Findings

ContextProof implements a complete local workflow for capturing code evidence,
checking it after repository changes, repairing unique exact-text citation moves,
and diagnosing supported direct Python dependencies. Its engineering contribution
is an explicit, inspectable evidence contract and its execution through a Python
package, CLI, MCP interface, and offline report.

The main version-drift study evaluates 300 snippets from ten Python libraries.
ContextProof agrees with a separately implemented reference on all 300 scoped
source-text labels. This is implementation agreement under a shared contract,
not independently human-labeled accuracy. A separate blinded AI check agrees on
21 selected samples. Expanding the allowed source scope changes 23 dateutil labels
from deleted to relocated, exposing a material corpus-boundary limitation.

Dependency verification matches all 34 predeclared controlled cases. A real local
model experiment executes 20 adapted HumanEval tasks under three context policies:
**all three obtain 0/20 task success**. Post-run oracle controls establish that
all adaptations are solvable. These results support the implemented source and
static-dependency contracts; they do not establish improved coding-agent outcomes.

## 1. Problem and contracts

A coding agent reads a function at a path and line range, then the repository
changes before the agent uses that context again. Three distinct questions arise:

1. Does the saved source text still occupy that location or an unambiguous new one?
2. Do the supported direct definitions and import bindings it references still match?
3. Does the resulting context help the agent complete a coding task?

The system exposes separate evidence for these questions. Passing a source-text
check does not answer the dependency question; passing both does not answer the
execution question.

A source bundle stores its query, retrieval method, snapshot identity, budget and
unit, plus each selected chunk's path, line span, source text, file hash, snippet
hash, score, and ranking reasons. A canonical JSON digest binds the evidence fields.
A snapshot records the accepted path-to-file-hash map. These hashes detect internal
inconsistency and identify bytes; an adversary who replaces content and recomputes
hashes has not been authenticated. There are no signatures or trusted-author claims.

The source verifier applies this precedence within the allowed current corpus:

| Status | Contract |
| --- | --- |
| `valid` | The complete original text remains at its recorded path and lines |
| `relocated` | The original location no longer matches, and exactly one whole-line occurrence exists |
| `ambiguous` | More than one relocation candidate exists |
| `modified` | No occurrence exists, but the original file remains |
| `deleted` | Neither an occurrence nor the original file exists in the allowed corpus |
| `invalid` | Malformed or inconsistent evidence, or a disallowed/unreadable source path |

An unchanged original location remains valid even when identical copies exist
elsewhere. Unique matching proves textual recoverability, not that the matched
text has the same historical identity, runtime binding, or semantics. Repair keeps
valid entries, updates unique relocations, and drops other entries with a receipt.
It never substitutes newly modified code for the old snippet. Empty evidence fails
closed rather than serving as proof of sufficient context.

A dependency sidecar is separately sealed and bound to the bundle and snapshot.
It records the selected source anchor, statically resolved direct definitions and
constants, import-binding witnesses, and unresolved references. Its statuses are
`unchanged`, `changed`, `missing`, `unresolved`, and `invalid`; freshness requires
all nonempty entries to be unchanged. A source anchor moving across module paths
can invalidate a sidecar even when the text layer can relocate it. This is a
conservative identity rule, not evidence that a called function's body changed.

The combined context artifact binds both layers. `check` offers `reuse` only when
recorded source locations remain valid and dependency witnesses are fresh. It
recommends repair when source is recoverable and witnesses permit it, review for
otherwise valid source with unresolved references, and retrieval when refreshed
source is needed. `refresh` preserves the query and budget, repairs where allowed,
and otherwise captures current evidence. Unresolved runtime behavior can remain
unresolved after retrieval.

## 2. Implementation and tradeoffs

### Retrieval and incremental indexing

The index reads accepted source files, records raw-content hashes, and uses Python
AST spans for structural chunks. Other supported text formats use line windows.
BM25 ranks lexical overlap with modest symbol/path weighting. An optional one-hop
file-dependency expansion adds a small graph-derived score. This is a heuristic,
not a resolved call graph or a novel retrieval algorithm. New `capture` workflows
default to BM25; the earlier graph behavior remains available explicitly.

A SQLite cache reuses parsing results for unchanged content. Warm scans still read
and hash source, validate metadata, and assemble graph information. Reduced parsing
does not imply zero I/O, an atomic snapshot, or a guaranteed wall-time speedup.

### Explicit payload accounting

Packing considers complete chunks in ranked order and includes a chunk only when
the complete rendered source payload fits. The budget includes query, metadata,
provenance, citations, source, and delimiters; it does not count only code bodies.
The default unit is UTF-8 bytes. Optional `cl100k_base` and `o200k_base` encodings
count ordinary text tokens; neither should be substituted for a different model's
tokenizer or for complete API billing.

The consumed-count receipt sits outside rendering to avoid self-reference.
Dependency sidecars, JSON storage envelopes, HTML reports, MCP wrappers, other
messages, and conversation framing are outside the source payload budget. A
client sending these objects to a model must budget them separately. The downstream
experiment instead measures its complete evidence with the actual Qwen tokenizer.

### Direct static dependencies

Resolution supports unique module-level functions, classes, literal constants,
same-module names, module imports and aliases, `from` imports, relative imports,
and supported re-export chains. Both repository-root and `src/` import layouts
are considered; ambiguous resolution is not resolved by guessing a runtime path.
Target declaration text and import statements along the binding path are witnessed,
so alias retargeting can be detected even when the two target bodies are identical.

Dependencies are one hop. If `subject` calls `helper`, changing a function called
only by `helper` can leave this witness unchanged. Calls through parameters,
objects, closures, returned callables, dynamic expressions, external modules, and
unsupported or ambiguous bindings abstain. Builtin calls can also remain unresolved.
This sacrifices automatic reuse to avoid claiming coverage the resolver does not
have. It does not cover monkeypatching, runtime import hooks, module side effects,
environment variables, mutable state, or operator behavior.

### Interfaces and source handling

The package provides source-only operations and `capture/check/refresh/report`.
Eight fixed-root MCP stdio tools expose index, search, bundle, verify, repair,
capture, check, and refresh. Offline HTML reports show recommendations, separate
source/dependency statuses, evidence, and budget receipts without external assets.

Source processing parses text without importing, installing, or executing the
inspected repository. Filesystem reads enforce the shared source policy, including
path and symlink restrictions, file size, encoding, and content exclusions. These
checks bound which source may be evidence; they are not a claim of complete secret
detection or an evaluated security product. Concurrent file changes can still
prevent a coherent multi-file observation; no transactional snapshot is promised.

## 3. Natural version-drift protocol

The [frozen protocol](../benchmarks/v1/preregistration.json) predates archive
acquisition, sampling, annotation, and engine predictions. It names ten libraries
from ten GitHub owners, their version pairs, accepted library prefixes, sample
selection, baselines, metrics, cache sequence, and development/holdout split.
[The manifest](../benchmarks/v1/manifest.json) pins all twenty commits and archive
SHA-256 digests, with license identities and license-file hashes.

Development repositories are requests, httpx, urllib3, pydantic, attrs, packaging,
and pluggy. Babel, filelock, and dateutil form the repository-level holdout.
They are a convenience sample of Python libraries; three involve HTTP and ecosystem
relationships can cross owner boundaries. The split is prospective separation
within this sample, not a representative sample of unseen software projects.

Thirty before-version snippets are chosen per repository. Eligibility requires
at least three editor lines, at most 6,000 UTF-8 bytes, and exactly one whole-line
occurrence in the before corpus. A seeded SHA-256 rank selects the first thirty.
The sampler never reads after-version source. The uniqueness filter reduces
pre-existing ambiguity and therefore limits generality. The sampler also uses
the production AST chunker, so the evaluation does not independently validate
whether those chunk boundaries are the best evidence for a task.

Every method receives exactly the same frozen accepted files. The independent
reference module imports no ContextProof code: it matches raw byte offsets with
CR/LF/CRLF editor-line boundaries. It nevertheless implements the same source
contract, so common specification errors and shared scope choices remain possible.
First-run predictions and disagreements are preserved; labels are not rewritten
to make predictions agree.

For acceptance metrics, `valid` and `relocated` mean **recoverable exact text**.
This is different from directly reusable context: a moved citation still needs
repair, and dependency freshness is a separate requirement. Comparators are:

- Path existence plus a line range that fits, without checking text.
- Exact source at the original path and lines.
- An unchanged original whole-file hash.
- ContextProof's exact-location-or-unique-relocation rule.

The evaluation bundle allowance is 250,000 bytes so all thirty selected entries
fit. This is an evaluation transport choice, not a retrieval-quality or production
context-budget experiment.

## 4. Natural drift results and scope correction

The [primary results](../benchmarks/v1/results/latest.md) contain 41 valid,
150 relocated, 80 modified, and 29 deleted labels: 191 recoverable and 109
unrecoverable within the frozen library corpus. Engine/reference status agreement
is 300/300, with no first-run disagreement.

| Recoverability decision | TP | FP | TN | FN | Agreement with reference |
| --- | ---: | ---: | ---: | ---: | ---: |
| Path exists and range fits | 155 | 79 | 30 | 36 | 61.7% |
| Exact original path and lines | 41 | 0 | 109 | 150 | 50.0% |
| Whole-file hash | 24 | 0 | 109 | 167 | 44.3% |
| ContextProof | 191 | 0 | 109 | 0 | 100.0% |

These are decisions under a byte-location reference contract, not semantic
correctness or human-labeled accuracy. The strict baselines avoid false acceptance
on this sample but discard recoverable text after unrelated edits and movement.
The weak path/range baseline accepts 79 unrecoverable snippets. Before-only sampling
and published failures prevent selecting only examples that favor relocation,
but they do not make the workload representative.

Development has 210 samples and 138 recoverable entries; holdout has 90 samples
and 53 recoverable entries. Paired bootstrap intervals resample entire repository
clusters 5,000 times with a fixed seed. For all ten clusters, the mean agreement
difference versus exact original coordinates is 0.500, with a 95% percentile
interval of [0.373, 0.647]. There are only three holdout clusters; all intervals
are descriptive and should not be interpreted as established population effects.
The full report retains every comparator, split, confusion matrix, and interval.

A separate AI reviewer received source coordinates and hashes without engine
predictions or reference labels. Its sealed judgments agree on 21/21 purposively
selected items. A disclosed amendment increased per-repository review coverage
before predictions and review. This is a blinded AI cross-check, not independent
human annotation or a representative estimate of labeling errors.

### The dateutil corpus-boundary finding

Inspection after the first run found that 23 selected dateutil tests moved outside
the registered library prefixes. They were `deleted` **from the selected corpus**,
but exact unique copies remained under the newer archive's tests directory.
Calling them upstream deletions would be wrong.

The [posthoc sensitivity analysis](../benchmarks/v1/results/scope-sensitivity.md)
keeps the same 300 before samples and frozen archives, then expands to all
policy-eligible Python files. It preserves the primary inputs/results and records
every changed label. Exactly 23/300 change: the broader counts are 41 valid,
173 relocated, 80 modified, and 6 deleted, giving 214 recoverable entries.
Engine/reference agreement remains 300/300 under this broader contract.

This is an outcome-motivated scope sensitivity, not a new preregistered test or
holdout retuning. The result demonstrates that source scope changes the meaning of
recoverability. All-Python scope still excludes non-Python and policy-rejected
files, and expanding scope can in principle introduce ambiguous duplicates.

## 5. Dependency evaluation and overhead

The [controlled dependency study](../benchmarks/results/dependencies.md) declares
34 source transformations and expected statuses before checking the engine. It
covers changed helpers and constants, unrelated edits, aliases, relative imports,
cycles, missing definitions, duplicate bindings, dynamic calls, external imports,
and the deliberate one-hop boundary.

All 34 observed statuses match their declarations. Of twelve explicitly stale
cases, eleven retain recoverable exact text; none is accepted as fresh by the
witness layer. All twelve unresolved cases remain non-fresh. The grandchild-change
fixture intentionally remains unchanged, demonstrating the one-hop limit.
These are designed contract checks, not an unbiased semantic detection rate.

Seven repetitions record capture and verification latency and sidecar size. The
median sidecar is 1,292 bytes, **additional overhead equal to 1.75 times** the
original rendered source bundle. It is outside the source context allowance.
Source-scan scaling with one direct imported helper and 10/100/500 tiny Python
files gives capture medians of 2.26/20.15/104.04 ms and verification medians
of 2.27/22.17/103.34 ms. These are local observations on small synthetic files,
not throughput promises for complex repositories.

[Natural dependency diagnostics](../benchmarks/v1/results/dependency-drift.md)
apply the witness layer to the same 300 frozen version-drift samples. Of 191
text-recoverable entries, the sidecar additionally flags 65 as changed or missing:
**35 concern the source anchor itself**, including module/file movement, and
**30 have an unchanged anchor with a changed or missing direct reference**.
Another 104 of those 191 entries are unresolved and need review. The first 35 must not be
counted as detections of changed dependencies behind unchanged callers; requests
and dateutil account for those anchor flags in this run.

Unresolved references are abstentions, not confirmed stale behavior. The source
reference labels only text recoverability, so neither the 65 total flags nor the
30 direct-reference flags establish true-positive semantic detection or measure
unnecessary invalidation in natural code. The report retains all causes and
per-repository counts rather than collapsing them into a dependency-accuracy score.

The primary study also records three cold/warm/changed-version cache repetitions
per repository. Reusing a warm cache reduced median time in these local pairs,
but file reads and hashing remain and concurrency/thermal conditions were not
controlled. Raw timings and parsed/reused counts accompany all observations.

## 6. Executed downstream model study

The [downstream protocol and traces](DOWNSTREAM.md) select HumanEval IDs 0–19 at
pinned commit `6d43fb980f9fee3c892a914eda09951f772ad10d`. The functional specification
and original tests are preserved, while each entry point receives an opaque
request and must use a repository helper to decode its original arguments.
Helpers contain decoding only; canonical algorithms never enter model context.
This deliberately artificial API adaptation is not an unmodified HumanEval score,
real issue-resolution benchmark, or training-contamination-free evaluation.

Task ID modulo four assigns five symbol renames, five signature changes, five
exact file moves, and five unchanged controls. Three policies use the same task,
model, prompt template, budget, and single-attempt rule: reuse before-context;
fresh current BM25 retrieval; and verify/repair, refreshing invalidated evidence.
This experiment isolates the source-evidence loop. It does not evaluate the full
combined dependency-witness workflow or an interactive multi-turn coding agent.

All 60 complete prompts and policy decisions were frozen before generation.
Qwen2.5-Coder-1.5B-Instruct in MLX 4-bit format is pinned to revision
`b3252a2f97102b1fb1571fec2c9b27219a8536be`. MLX-LM 0.31.3 runs locally with
zero-temperature decoding, seed zero, and a fresh prompt cache per completion.
The native Qwen context cap is 1,024 tokens, actual maximum 605, and output cap
384 tokens. Every model-reported prompt count equals its separately computed count.

| Policy | Tasks passed | Prompt tokens | Generated tokens | Generation seconds |
| --- | ---: | ---: | ---: | ---: |
| Reuse | 0/20 | 15,263 | 2,605 | 43.04 |
| Fresh | 0/20 | 15,341 | 2,642 | 43.10 |
| Verify, repair, refresh | 0/20 | 15,977 | 2,605 | 42.31 |

Every generated program was submitted to the same execution harness. The dominant
failure is an invented `repository_helper` import in 54/60 outputs; that literal
occurs in none of the prompts. The other six fail through three undefined decoder
names, two tuple/argument mistakes, and one unchanged multi-argument signature.
There are no generation/worker failures or output-limit hits. Replaying all sixty
unedited completions reproduces every recorded outcome.

Post-run controls wrap the original upstream canonical algorithms with the correct
current API and pass 20/20. Obsolete-API controls pass only the five unchanged tasks;
all fifteen changed tasks fail. These controls are separate from model inputs and
run after all model attempts. They rule out an unsolvable adaptation or universally
broken harness as an explanation for the null result, without converting the
control successes into model successes.

The small model's instruction/API failures overwhelm the intervention. The run
provides **no evidence of improved downstream success** and does not determine
whether stronger models or interactive agents would benefit. No model was replaced,
no prompt was edited, and no favorable subset was selected after observing results.
A single seed, fixed condition ordering, possible HumanEval memorization, artificial
contracts, and a small model all constrain interpretation. No confidence interval
is presented as evidence of a generalized effect from these sixty cells.

### Execution and artifact integrity

Generated code runs under macOS Seatbelt, with preflight checks proving denied
network connections, process forks, and outside-scratch writes, plus protected user
and temporary-tree reads. CPU, wall-time, file-size, and descriptor bounds apply.
AST/import restrictions and reduced builtins are additional controls; subprocess
execution alone is not described as isolation. The harness has no unsandboxed
fallback and is intentionally limited to these pure-function tasks.

The model runs locally without an API charge or source upload. Full model-file
hashes, environment versions, prompts, responses, token IDs/counts, elapsed times,
errors, and started/finished attempt events are recorded. The pinned model was
obtained through a disclosed mirror when the primary domain was unavailable.

Public diagnostics replace local path prefixes with placeholders. Byte-identical
originals remain outside the repository; a publication audit records both raw and
public hashes. Model responses, token counts, timings, outcomes, and the frozen
input bytes are unchanged. Source hashes identify the preparation snapshot;
subsequent project edits are not silently represented as the original code.

## 7. Reproduction and interpretation

Start with the [README demo](../README.md#see-the-complete-workflow) to inspect the
full capture/change/check/refresh loop. Each experiment has its own protocol and
artifact identity; the main study should not be conflated with earlier exploration.

| Evidence | Protocol and executable record |
| --- | --- |
| Source drift and cache observations | [Protocol](DRIFT_STUDY.md), [raw results](../benchmarks/v1/results/latest.json), [first-run audit](../benchmarks/v1/first_run_audit.json) |
| Broader source scope | [Runner](../benchmarks/v1/scope_sensitivity.py), [raw results](../benchmarks/v1/results/scope-sensitivity.json) |
| Separate AI review | [Sealed review](../benchmarks/v1/ai_review.json), [comparison](../benchmarks/v1/review_comparison.json) |
| Controlled dependencies | [Contract](DEPENDENCIES.md), [fixtures](../benchmarks/dependency_cases.py), [raw results](../benchmarks/results/dependencies.json) |
| Natural dependency diagnostics | [Report](../benchmarks/v1/results/dependency-drift.md), [raw results](../benchmarks/v1/results/dependency-drift.json) |
| Downstream execution | [Protocol and replay instructions](DOWNSTREAM.md), [frozen inputs](../benchmarks/downstream/results/inputs.json), [all attempts](../benchmarks/downstream/results/attempts.jsonl) |
| Earlier exploratory retrieval | [Protocol](EVALUATION.md), [84 retrieval runs and 118 drift observations](../benchmarks/results/latest.md) |

The earlier graph/BM25 experiment has mixed results: at 2,000 bytes graph hits a
labeled file for 8/14 queries versus BM25's 9/14; they tie at 4,000, while graph
hits 14/14 versus 13/14 at 8,000. Those exact-symbol-heavy queries and three
Pallets libraries do not establish general retrieval superiority.

The delivered project supplies an inspectable provenance mechanism, bounded
static diagnostics, usable interfaces, and completed experiments with retained
negative results. Independent human labels, runtime/semantic dependency analysis,
real issue benchmarks, stronger multi-turn agent studies, and publication-level
external validation remain possible extensions, not claimed v1 results.
