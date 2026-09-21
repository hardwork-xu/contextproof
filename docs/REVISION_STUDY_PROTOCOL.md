# Real revision behavior: protocol fixed before held-out model completions

This experiment asks whether different source contexts help a capable model
predict concrete Python API behavior at a recorded repository revision. It is
an upstream-regression-derived diagnostic, not autonomous issue resolution,
repository localization, a new benchmark leaderboard, or an independence claim.

## Inputs and leakage boundary

The [frozen suite](../benchmarks/revision_tasks/frozen/) contains 30 probes from
packaging, HTTPX, Pluggy and attrs: 5 development probes and 25 held-out probes.
Splits separate upstream change families. Several probes are correlated through
the same repository or change family; report both task and family aggregates.
Upstream test and issue links explain selection. Each oracle was executed twice
per version in a verified macOS Seatbelt sandbox. All 120 executions agreed.
The held-out set includes 19 changed outputs and 6 unchanged controls. A candidate
that turned out unchanged was retained, rather than filtered to favor detection.

Every retrieval method receives the same probe and upstream-derived path/symbol
hints. This is privileged localization information, deliberately shared across
conditions. Retrieval corpora contain only production Python package files.
Tests, documentation and changelogs are excluded. Task prompts omit task IDs,
split, dates, version labels, selection family and expected outputs. Source itself
is preserved verbatim, including comments. An opaque empty working directory
prevents the CLI's environment context from leaking condition names.

## Six conditions, one source allowance

Each condition has a **16,000 UTF-8 byte maximum for its entire evidence string**,
including its own metadata and citations. Shared task/instruction/schema overhead
is outside this allowance and is reflected in actual reported model input tokens.
Unused allowance is not padded. Declarations are never character-truncated.

| Condition | Evidence |
|---|---|
| `no_context` | No repository source; measures the model's unaided prior. |
| `stale_anchors` | Supplied declarations from the previous revision. |
| `fresh_anchors` | The same supplied symbols from the current revision, without dependency expansion. Getter/setter duplicates are all shown, without guessing their runtime binding. |
| `fresh_bm25` | Current ContextProof BM25 retrieval with the same query and package corpus. |
| `graph_current` | Current supplied anchors expanded through the bounded static graph (depth 4, at most 256 nodes), with current dependencies and explicit incomplete coverage. |
| `archex` | Pinned Archex 0.31.2 public query API, native XML output, local BM25 enabled; embeddings, SPLADE and reranking disabled. A declared token-budget backoff enforces the same actual byte cap. |

Archex is a relevant existing open-source system, currently marked Alpha by its
publisher. It is not represented as a mature production standard. Its full native
receipt is retained separately. None of the graph or Archex contexts claims full
runtime dependency coverage. Source-only completeness has a narrower meaning and
is not compared as the same metric.

The primary comparison is `graph_current` versus `fresh_anchors`, which controls
for the supplied anchor information. BM25 and Archex test alternative retrieval
strategies. Comparing fresh versus stale anchors tests the stale-context problem
and cannot by itself establish a benefit unique to ContextProof.

## Model, attempts and capability gate

Use `gpt-6-astra`, medium reasoning, through the authenticated Codex CLI
0.155.0-alpha.9.2, not an uninstrumented claim about the raw API. A fixed replacement
instruction file and JSON response schema are recorded. Shell, browser, apps,
plugins, skill discovery and multi-agent execution are disabled. Any tool event
invalidates a completion. No model receives oracle answers or executes code.
The service does not expose an immutable model-weight identifier or a sampling
seed, so exact regenerated text is not guaranteed.

The capability gate was fixed at at least 4/5 exact fresh-anchor development
answers. The initial run scored 5/5. Its source-only adapter mistakenly omitted
an ambiguous property pair; this was corrected before held-out inference, and
that original attempt was retained. A transport-only development check and a
second complete development run using the final adapter/configuration also
remain public. The final complete development run scored 5/5.

The initial CLI transport retried WebSockets before HTTPS, consuming roughly two
minutes per call. The final harness uses the documented custom-provider option
`supports_websockets=false`, existing OpenAI authentication and its unchanged
default endpoint. It neither extracts credentials nor redirects them elsewhere.
See [official provider source](https://github.com/openai/codex/blob/main/codex-rs/model-provider-info/src/lib.rs)
and [configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference).

Held-out inference: one semantic attempt per task/condition (150 attempts), a
240-second wall limit per attempt, four concurrent independent requests, and
fixed shuffled job order seed 230921. CLI transport retries remain in the record.
No semantic retry, answer repair, outcome-based exclusion or prompt tuning after
held-out answers. Setup failures before a request are distinct from a model
failure. A failed/invalid completion scores incorrect in the primary denominator.

## Scoring and disclosure

Parse the response's `answer_json` string into exactly `{"value": ...}` or
`{"error": "ExceptionClassName"}`. Reject nonfinite numbers, duplicate keys,
extra fields and malformed output. Compare canonical JSON with the executed
current-version oracle, preserving booleans versus numbers and list order.
Also report whether changed-task errors match the previous-version oracle.

Publish every answer and failure, per-task paired results, condition accuracy,
changed/control and repository/family breakdowns, actual token usage, wall time,
source bytes and retrieval preparation cost. Paired differences on 25 correlated
tasks are descriptive; do not extrapolate to general agent success or claim
statistical superiority from individual probes treated as independent evidence.
No monetary charge is inferred from subscription token counts.

Exact graph reconstruction and source-artifact delta size are evaluated separately
in the [graph study](../benchmarks/graph/README.md). Smaller artifacts are not
claimed to reduce model tokens: this experiment supplies full current context.

Raw runtime records are held outside Git. Public exports replace local paths and
session identifiers, retain original/exported hashes, and assert unchanged answers,
correctness and usage. See [publication policy](PUBLISHING.md).

## Reproduction

Prepare verified oracle inputs with `scripts/run_revision_tasks.py`, then freeze
the six conditions with `scripts/prepare_revision_contexts.py`. The
[input manifest](../benchmarks/revision_tasks/model-inputs/protocol.json) records
exact source corpora, adapter implementation hashes and the context-record digest.
Run `scripts/run_revision_model.py --help` for the completion runner and store its
output outside the repository. Export only through `scripts/publish_revision_model.py`.
No hosted-model calls are made by CI or the unit tests.
