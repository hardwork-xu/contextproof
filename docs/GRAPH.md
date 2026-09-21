# Versioned dependency evidence

The graph workflow follows supported Python references beyond one hop and puts
their current source into the model-facing payload. It can show which recorded
dependency changed behind an unchanged caller, preserve unaffected evidence, and
transport an exact update to the saved graph.

[Open the offline demonstration](assets/graph-demo.html). It is a **synthetic,
executed demonstration**, not a real-repository or model benchmark. Regenerate it
with `python scripts/demo_graph.py`; the script creates temporary local Git
revisions, runs the actual APIs and writes inspectable artifacts under
`work/graph-demo/artifacts/`. It never executes the fixture source.

## Capture an immutable revision, then refresh

```sh
contextproof graph-capture /path/to/repository "invoice_total" \
  --ref BEFORE_COMMIT --depth 4 --max-nodes 256 --budget 16000 \
  --output work/before-graph.json --payload work/before-context.json

contextproof graph-refresh /path/to/repository work/before-graph.json \
  --ref AFTER_COMMIT --view update --budget 16000 \
  --output work/after-graph.json --payload work/update-context.json \
  --delta work/change.json

contextproof graph-apply work/before-graph.json work/change.json \
  --output work/reconstructed-graph.json
```

Use actual commit IDs or refs in place of the example placeholders. Git source is
read from immutable objects without checkout or source execution. Omitting
`--ref` performs a fresh working-tree scan and byte hashing; that scan is not an
atomic filesystem snapshot. The source policy excludes unsafe paths, symlinks,
oversized files and files outside the indexer's supported corpus.

The capture query selects Python declaration anchors through the existing BM25
ranker. `--limit` controls the number of selected anchors. Expansion follows
supported references from their complete current declarations. This is not a
new retrieval algorithm; selecting the wrong anchor remains possible.

`--view full` emits current anchor and reachable source. `--view update` emits
current changed source and connecting paths against the named base graph. The
update carries `requires_base=true`: it is not standalone full context. A removed
node has a tombstone describing its absence from the current **evidence graph**;
this does not necessarily mean its file was deleted from the repository.

The commands save the full graph independently of the model payload. Exit status
`0` means the requested payload is complete under its declared scope, `1` means
it is incomplete, and `2` denotes an operation/input error. A CLI receipt is
diagnostic output; only the `--payload` file is the bounded model-facing text.

## Three different questions

| Result | Question it answers | Boundary |
| --- | --- | --- |
| `comparison.fresh` | Are captured source identities, bindings and supported references unchanged, with no unresolved/truncated frontier? | Static source identity, not unchanged behavior. |
| `payload.complete` | Did this full/update view deliver all its required source with no unresolved frontier? | Delivery under the declared view, not task sufficiency. |
| Verified delta reconstruction | Does applying the change to the exact named base reproduce the target graph? | Integrity and reconstruction, not authenticity or model correctness. |

A changed graph can have a complete current payload: the update delivered the new
source successfully. An unchanged caller can have an incomplete payload because
a runtime reference cannot be resolved. Unresolved references never become an
automatic freshness claim merely because their text stayed the same.

Supported resolution follows the [direct Python resolver](DEPENDENCIES.md), now
recursively, with node deduplication, import-binding witnesses and cycle handling.
Defaults are four expansion levels and 256 nodes. Dynamic dispatch, unknown
external/builtin bindings, ambiguous declarations and unsupported syntax remain
explicit frontiers. Reaching a depth or node limit also prevents completeness.
This is a bounded repository-local static closure, not a complete Python call
graph. Increasing limits does not make runtime uncertainty disappear.

The current graph policy is `resolver_version=2`. Version 1 could resolve a
nested or pattern-local name as a module global, miss module rebinding, or select
a package submodule despite an uncertain package attribute. Version 2 shares
conservative guards with the served direct-witness capture/check workflow and
marks these cases unresolved. Graph artifacts from version 1 require recapture;
the current validator rejects their obsolete policy instead of silently treating
them as current evidence.

The [eight-fixture scope audit](../benchmarks/graph/scope-audit.json) preserves
the original failing graphs alongside corrected graphs, exact model payloads,
legacy API checks, source fixtures and implementation hashes. All eight corrected
graphs are unresolved; their payloads retain the caller and omit the incorrectly
resolved dependency. Old legacy context artifacts also fail the current reuse
check. These were selected regression cases, not an estimate of Python resolver
accuracy. The frozen model-study inputs retain their original implementation.
Run the public fixtures with:

```sh
python -m pytest -q benchmarks/graph/test_scope_audit.py
```

## What the 16,000-byte budget counts

The renderer counts every UTF-8 byte of its returned `rendered` JSON string:
source, citations, graph/base handles, metadata, references and diagnostics.
It preserves whole declarations and never trims code to fit. Required source
that does not fit appears in omission diagnostics and makes the payload
incomplete. A declaration can itself exceed the allowance.

The exact graph remains in storage. The model payload includes compact frontier
reason counts, bounded omission examples and an explicit `full_graph_handle`.
Truncation flags identify summarized diagnostics; full frontier/omission details
remain in the graph and API receipt. Reference-ID prefixes are lengthened until
they are unambiguous within the graph. Source nodes retain their full IDs and
repository-relative path, symbol and line citations.

When even the compact manifest cannot fit, `rendered` is empty,
`complete=false`, and `status=budget_too_small`. Clients must handle that outcome;
an empty rendering is not valid complete evidence. API diagnostics outside
`rendered`, CLI receipts, graphs and deltas are separate storage/transport bytes.
Count them separately if a custom client also sends them to the model.

The MCP tools `contextproof_graph_capture` and `contextproof_graph_refresh` keep
the full graph in the server's local store and return the already-budgeted model
payload. Refresh uses a captured graph handle, avoiding repeated transmission of
the full witness artifact. A handle is local to that store; losing or clearing
the store requires a new capture. Model conversation framing and tool schemas
are outside this text payload budget.

## Python API and exact deltas

```python
from pathlib import Path
from contextproof.graph import canonical_graph_bytes
from contextproof.graph_delta import apply_graph_delta
from contextproof.graph_session import GraphSession

with GraphSession(Path("repository")) as session:
    before = session.capture("invoice_total", ref="BEFORE_COMMIT", budget=16000)
    after = session.refresh(before["graph"]["id"], ref="AFTER_COMMIT", budget=16000)
    restored = apply_graph_delta(before["graph"], after["delta"])
    assert canonical_graph_bytes(restored) == canonical_graph_bytes(after["graph"])
    model_text = after["payload"]["rendered"]
    assert len(model_text.encode("utf-8")) <= 16000
```

Stable node identity uses path, qualified symbol and declaration kind. A separate
source fingerprint excludes line positions, so line movement can update
citations without retransmitting unchanged source text. Field deltas bind both
base and target IDs, reject a wrong base or malformed edits, reconstruct the
target and validate its seal. They are storage/transport deltas, not a promise to
remove old tokens from an existing LLM conversation. A client must manage which
context it retains and supplies.

Git blobs and sealed graphs use a verified, disposable local store. Parsed ASTs
are reused in memory within a `GraphSession` by default. The MCP server retains
one session across requests and closes it on EOF; separate CLI processes do not
share that in-memory AST cache. Python callers can opt into JSON AST storage with
`GraphSession(..., persistent_ast_cache=True)`. Serialization has a cost, so disk
reuse does not imply a speedup.

Module catalogs and reference resolution are rebuilt for a current observation,
so new files and newly ambiguous imports are not hidden behind an old successful
lookup. This is not a fully incremental resolver. Report blob reads, parse work,
graph work, payload bytes and full latency separately.

## Evaluation boundaries

The synthetic demonstration checks the three-hop edit, actual changed-source
delivery, exact graph reconstruction, an unrelated change, runtime uncertainty
and insufficient budget. It makes no performance claim. The external revision
studies and raw results have separate protocols; results under an exact-source
contract are not semantic ground truth or evidence of improved coding success.

Graph ranking, receipts, dependency tracking and incremental computation already
have substantial prior art, including [archex receipts](https://github.com/Mathews-Tom/archex/blob/v0.31.2/docs/CONTEXT_RECEIPTS.md),
[Aider repository maps](https://aider.chat/docs/repomap.html), and
[rustc's incremental query system](https://rustc-dev-guide.rust-lang.org/queries/incremental-compilation-in-detail.html).
The relevant comparison is whether this implementation correctly repairs saved
evidence and delivers useful current source at an acceptable measured cost.
