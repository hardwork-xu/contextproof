# ContextProof

[![CI](https://github.com/hardwork-xu/contextproof/actions/workflows/ci.yml/badge.svg)](https://github.com/hardwork-xu/contextproof/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**Recheck the code evidence a coding agent saved before the repository changed.**

ContextProof captures source snippets and their direct Python dependency witnesses.
After edits, it checks exact text, repairs unique citation moves, identifies changed
or unresolved dependencies, and produces an inspectable refresh decision.

**v1.0:** local Python package, CLI, eight MCP tools, offline HTML reports, and
reproducible evaluations. Python 3.11+, macOS/Linux; the default installation has
no runtime dependencies and needs no model, GPU, or API key.

[简体中文](docs/README.zh-CN.md) · [Technical report](docs/TECHNICAL_REPORT.md) ·
[Design](docs/DESIGN.md) · [Evaluation protocol](docs/EVALUATION.md)

![Offline report: invoice_total has unchanged source but a changed dependency, so the recommendation is retrieve](docs/assets/context-report.png)

## See the complete workflow

Install from GitHub; the package is not published to PyPI.

```sh
git clone https://github.com/hardwork-xu/contextproof.git
cd contextproof
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python scripts/demo.py
```

Open `work/demo/02-changed.html` in a browser. The demo changes a tax-rate helper
while leaving `invoice_total()` untouched: the saved source remains valid, its
witness detects the dependency change, and refreshing captures current evidence.
The three offline reports show **reuse → retrieve → reuse**.

Use the same workflow with a repository:

```sh
contextproof capture work/demo/repository "invoice_total" \
  --budget 6000 --output work/context.json
contextproof check work/demo/repository work/context.json
contextproof report work/demo/repository work/context.json --output work/context.html

# After repository edits, create updated evidence and inspect its receipt.
contextproof refresh work/demo/repository work/context.json --output work/refreshed.json
contextproof render work/refreshed.json --output work/model-context.md
```

`capture` saves a bound source bundle and dependency sidecar. `check` recommends
`reuse`, `repair`, `review`, or `retrieve`. `refresh` repairs when both contracts
permit it; otherwise it retrieves current source with the original query and budget.
Unsupported dependencies can still require review after refreshing.

The source-only `index`, `search`, `bundle`, `verify`, `repair`, and `render` commands
remain available. Exit codes: `0` success, `1` for a non-valid `verify` or non-reusable
`check`, and `2` for input/operation errors. Run `contextproof --help` for syntax.

## What the guarantees mean

| Layer | Checks | Boundary |
| --- | --- | --- |
| Source evidence | Exact recorded text; unique whole-line relocation; hashes and paths | Text identity, not unchanged behavior or historical authorship |
| Dependency witnesses | Supported direct Python definitions, constants, and import bindings | One hop; dynamic, external, ambiguous, and unsupported references stay unresolved |
| Context workflow | Source and witness receipts bound to the same bundle/snapshot | Conservative reuse advice; fresh retrieval cannot resolve unsupported runtime behavior |

Source outcomes are `valid`, `relocated`, `modified`, `deleted`, `ambiguous`, and
`invalid`. An exact original location takes precedence; repair drops changed,
missing, ambiguous, or unsafe evidence instead of substituting new source.
Dependency outcomes are `unchanged`, `changed`, `missing`, `unresolved`, and `invalid`.
An unresolved reference is never reported as fresh. See [source contracts](docs/DESIGN.md)
and [dependency resolution](docs/DEPENDENCIES.md).

Python uses AST chunks, BM25 or a small graph expansion heuristic, and a SQLite
parse cache. Warm scans still read and hash files. Repository source is inspected
without importing or executing it. Verification is not an atomic filesystem snapshot,
and integrity hashes are not signatures.

## Context budgets and MCP

The default `--budget` is **UTF-8 bytes**, not model tokens. It bounds the complete
rendered source payload, including citations, metadata, source, and delimiters.
Whole chunks that do not fit are omitted. **Dependency sidecars, HTML reports,
JSON receipts, MCP wrappers, and other messages are outside that budget.** Count
those separately if sending them to a model.

Optional `pip install -e '.[tokens]'` enables `--tokenizer cl100k_base` and
`--tokenizer o200k_base`; first use may fetch encoding data. These text-encoding
counts do not measure model conversation framing or billed tokens.

Configure an MCP client using [examples/mcp.json](examples/mcp.json), replacing
its root with an absolute source path. `contextproof serve ROOT` exposes eight
stdio tools: `contextproof_index`, `contextproof_search`, `contextproof_bundle`,
`contextproof_verify`, `contextproof_repair`, `contextproof_capture`,
`contextproof_check`, and `contextproof_refresh`. The server uses one fixed root.

## Measured results

| Study | Observed result | Interpretation |
| --- | --- | --- |
| [Natural version drift](benchmarks/v1/results/latest.md) | 300 samples, 10 repositories; 300/300 agreement with a separate reference | Scoped exact-text contract agreement, not human-labeled accuracy |
| [Scope sensitivity](benchmarks/v1/results/scope-sensitivity.md) | 23 dateutil labels change from deleted to relocated in broader scope | These were corpus exits, not upstream deletions |
| [Blinded AI check](benchmarks/v1/review_comparison.json) | 21/21 agreement on selected items | AI review; no independent human ground truth |
| [Dependency controls](benchmarks/results/dependencies.md) | 34/34 declared statuses; 12 stale and 12 unresolved cases never fresh | Designed contract checks with measured overhead |
| [Downstream coding](docs/DOWNSTREAM.md) | 20 adapted tasks × 3 policies; **0/20 success in every policy** | No demonstrated downstream improvement |

The downstream study uses one pinned local Qwen2.5-Coder-1.5B model, fixed prompts,
budgets, and one attempt per cell. All 60 responses and executed outcomes are public.
Post-run controls pass 20/20 with the correct API and 5/20 with obsolete APIs,
confirming all adaptations are solvable. The small model's instruction/API failures
remain in the results. [The technical report](docs/TECHNICAL_REPORT.md) explains
baselines, holdout selection, uncertainty, overhead, and failure analysis.

## Reproduce and develop

```sh
python -m pip install -e '.[dev]'
ruff check .
pytest -q
python -m build
python scripts/run_drift_benchmarks.py --download
python scripts/run_drift_benchmarks.py \
  --check benchmarks/v1/results/latest.json --output work/drift-replay
python scripts/run_dependency_benchmarks.py --repeats 7 --output work/dependencies.json
```

Complete protocols: [drift and scope sensitivity](docs/DRIFT_STUDY.md),
[dependency controls](docs/DEPENDENCIES.md), [natural dependency diagnostics](benchmarks/v1/results/dependency-drift.md),
[model run and safe replay](docs/DOWNSTREAM.md), and [earlier exploratory retrieval](docs/EVALUATION.md).
The CI badge links current results for the Linux/macOS Python matrix, package builds,
and optional-tokenizer checks. Model generation is a separately reproduced experiment.

[Completion matrix](docs/ROADMAP.md) · [Development log](docs/DEVELOPMENT_LOG.md) ·
[Research context](docs/RESEARCH.md) · [MIT license](LICENSE)

Maintained by **hardwork-xu** as a single-maintainer, AI-assisted project. Design,
implementation, experiments, and writing used AI assistance. The repository records
actual work and results; it does not claim a published paper or a new retrieval algorithm.
