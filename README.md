# ContextProof

[![CI](https://github.com/hardwork-xu/contextproof/actions/workflows/ci.yml/badge.svg)](https://github.com/hardwork-xu/contextproof/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**Code evidence you can recheck after a repository changes.**

ContextProof retrieves source snippets for coding agents, packages them within a
measured context budget, and checks the saved evidence against a later source
tree. When lines shift or files move, it can repair uniquely matching citations.
When text changes, disappears, or becomes ambiguous, it reports that explicitly.

A local Python tool with a CLI and MCP stdio interface. Python 3.11+, macOS/Linux,
no runtime dependencies in the default installation, no model or API key required.
**v0.1 is an experimental engineering and evaluation release.**

[简体中文](docs/README.zh-CN.md) · [Measured results](benchmarks/results/latest.md) ·
[Design](docs/DESIGN.md) · [Research framing](docs/RESEARCH.md) ·
[Evaluation protocol](docs/EVALUATION.md)

## What problem does it solve?

An agent reads `pricing.py:4–8`. Another edit inserts a header or moves the file.
The saved citation now points at the wrong location, even if the original code
still exists. A whole-file hash notices a change but cannot tell whether that
particular snippet survived.

ContextProof stores the source text, location, hashes, retrieval reasons, and
snapshot identity together. It verifies the old evidence against current source,
then retains exact evidence and repairs only unique exact-text relocations.
This supports an inspectable **retrieve → verify → repair → verify** loop.

- **Retrieve:** Python AST chunks, BM25 or a small dependency-graph heuristic,
  plus an incremental SQLite parse cache.
- **Package:** complete source chunks with provenance, bounded by the full
  rendered payload's UTF-8 bytes or an optional tiktoken encoding.
- **Recheck:** six explicit outcomes, conservative repair, and a receipt recording
  invalidated evidence. Source files are read as text and never executed.

Exact text is the contract. An unchanged snippet can still depend on a changed
function or configuration; ContextProof does not establish unchanged behavior.

## Three-minute quickstart

Install from this repository; v0.1 is not published to PyPI. The example below
uses a POSIX shell and keeps generated bundles outside the indexed source tree.

```sh
git clone https://github.com/hardwork-xu/contextproof.git
cd contextproof
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .

contextproof index examples/tinyshop
contextproof bundle examples/tinyshop "discount price rate" \
  --method bm25 --budget 4000 --output work/demo.json
contextproof verify examples/tinyshop work/demo.json
contextproof render work/demo.json --output work/demo.md
```

`work/demo.json` is the saved evidence artifact. `work/demo.md` is the bounded
payload to pass to an agent. Verification should initially report `valid`.
Now make a changed copy of the example and insert a header:

```sh
python - <<'PY'
from pathlib import Path
from shutil import copytree

source = Path("examples/tinyshop")
changed = Path("work/tinyshop")
copytree(source, changed, dirs_exist_ok=True)
(changed / "pricing.py").write_bytes(
    b"# Header added after retrieval.\n" + (source / "pricing.py").read_bytes()
)
PY

# Expected: relocated evidence and exit code 1.
contextproof verify work/tinyshop work/demo.json

contextproof repair work/tinyshop work/demo.json --output work/repaired.json
contextproof verify work/tinyshop work/repaired.json
contextproof render work/repaired.json --output work/repaired.md
```

The repaired citation has updated line numbers and verifies as `valid`. Changing
an expression inside a stored snippet instead would invalidate that evidence;
repair never silently substitutes newly changed code. Retrieve again to obtain it.

CLI exit codes are `0` for success, `1` when verification is not entirely valid,
and `2` for an input or operation error. Run `contextproof --help` for all commands.

## Verification outcomes

| Status | Meaning | Repair action |
| --- | --- | --- |
| `valid` | Exact text remains at the original path and lines | Retain |
| `relocated` | Old location changed; one exact whole-line match exists | Update citation |
| `modified` | Original file exists, but recorded text is absent | Drop and report |
| `deleted` | Original path and recorded text are absent | Drop and report |
| `ambiguous` | Multiple relocation candidates match exactly | Drop and report |
| `invalid` | Malformed evidence, integrity failure, or unsafe/unreadable source | Reject or invalidate |

An unchanged original location takes precedence over identical copies elsewhere.
Relocation is a text-match result, not proof of historical identity. An empty
bundle does not verify as sufficient evidence. See the [contract and edge
cases](docs/DESIGN.md#evidence-contract).

## What v0.1 actually measured

The [committed report](benchmarks/results/latest.md) and [raw
JSON](benchmarks/results/latest.json) were generated from the executable
[protocol](docs/EVALUATION.md), with frozen source origins and hashes.

| Experiment | Observed result | Scope |
| --- | --- | --- |
| Controlled changes | All 7 expected statuses and repair contracts matched | A small deterministic behavior test |
| Natural version drift | 118 snippets across Click, ItsDangerous, and MarkupSafe | Status observations; no independent accuracy labels |
| Budgeted retrieval | 84 runs; zero rendered-budget violations | 14 author-written queries × 2 methods × 3 budgets |
| Warm index cache | Zero files reparsed on each immediate warm run | One local cold/warm pair per repository |

The graph heuristic was **worse** than BM25 on this small query set at 2,000 bytes:
8/14 queries hit a labeled file versus 9/14. They tied at 4,000 bytes; at 8,000
bytes, graph hit 14/14 versus 13/14. These narrow, often exact-symbol queries do
not demonstrate general retrieval superiority. All three repositories belong to
Pallets, and no downstream LLM task was run.

Reproduce without executing upstream code:

```sh
python scripts/run_benchmarks.py --download
python scripts/run_benchmarks.py \
  --check benchmarks/results/latest.json --output work/repeated-results
```

The second command compares all deterministic quality fields. Timings and machine
metadata are recorded separately. Source archives remain under ignored `work/`.

## Budget units and agent integration

The default `--budget 4000` means **4,000 UTF-8 bytes**, not 4,000 model tokens.
The bound covers `render_bundle(bundle)`: query, metadata, provenance, citations,
source, and delimiters. JSON storage receipts, MCP transport wrappers, other
messages, and API overhead are outside this budget. The `consumed` receipt is the
exact count of the rendered payload and is itself excluded from rendering.

For a supported text-token encoding:

```sh
python -m pip install -e '.[tokens]'
contextproof bundle examples/tinyshop "discount price rate" \
  --budget 1000 --tokenizer o200k_base --output work/token-demo.json
contextproof render work/token-demo.json --output work/token-demo.md
```

`cl100k_base` is also supported. First use may download tiktoken's encoding table.
Encoding counts do not include a model's conversation framing or billing overhead.

For an MCP client, adapt [examples/mcp.json](examples/mcp.json) to an absolute
repository path. `contextproof serve ROOT` exposes index, search, bundle, verify,
and repair tools over stdio. The server has one fixed source root; the current
implementation does not provide an HTTP service or run repository code.

## Development and next work

```sh
python -m pip install -e '.[dev]'
ruff check .
pytest -q
python -m build
```

The [CI workflow](.github/workflows/ci.yml) covers Linux and macOS, a Python-version
matrix, package builds, and a separate optional-tokenizer job. Its current status
is shown by the badge above.

Python has structural parsing and dependency hints; other supported text formats
use line windows. The graph is a heuristic rather than a resolved call graph.
Warm indexing still reads and hashes source files. Hashes detect inconsistent
content but provide no signature or trusted authorship. Verification is not an
atomic filesystem transaction. Read the full [design limits](docs/DESIGN.md).

Next experiments address independent drift labels, dependency freshness, and
controlled downstream coding tasks. They are specified with acceptance criteria
in the [roadmap](docs/ROADMAP.md). See [related work](docs/RESEARCH.md), the
[development log](docs/DEVELOPMENT_LOG.md), and the [Chinese project overview](docs/README.zh-CN.md) for technical discussion and reproducibility details.

Maintained by **hardwork-xu** as a single-maintainer, AI-assisted project. Design,
implementation, and documentation used AI assistance; the repository records
actual code, tests, and measured experiments. It does not claim a published paper,
a new retrieval algorithm, or improved model task success.

[MIT license](LICENSE). Frozen benchmark source origins and upstream licenses are
listed in [benchmarks/manifest.json](benchmarks/manifest.json).
