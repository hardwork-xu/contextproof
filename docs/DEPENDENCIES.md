# Direct Python dependency witnesses

An unchanged snippet can have a changed dependency. If a retrieved `subject()`
still says `return helper()`, ordinary exact-text verification accepts it after
the implementation of `helper()` changes. ContextProof can capture a separate
dependency sidecar and flag that change.

```python
from pathlib import Path
from contextproof.dependencies import capture_witnesses, verify_witnesses
from contextproof.evidence import make_bundle, verify_bundle
from contextproof.index import build_index

root = Path("my-repository")
bundle = make_bundle(build_index(root), "subject", budget=8000)
witnesses = capture_witnesses(bundle, root)
# Save bundle and witnesses as JSON. After repository edits:
text_report = verify_bundle(bundle, root)
dependency_report = verify_witnesses(witnesses, root)
assert dependency_report["bundle_id"] == bundle["id"]
print(text_report["valid"], dependency_report["fresh"])
```

The two reports answer separate questions. `verify_bundle` checks exact source
text and location. `verify_witnesses` checks the captured scope plus the identity
of supported direct dependency definitions and import bindings. Neither report
establishes runtime correctness or semantic equivalence.

For a reuse decision, prefer `capture_context` and `check_context` from
`contextproof.session` (or the CLI `capture`/`check` commands). That integration
also enforces exact one-to-one entry/anchor coverage and agreement between the
two current scan identities. Checking only the bundle ID in a custom integration
does not establish these additional conditions. Scan agreement is still not an
atomic filesystem transaction.

## Scope and resolution rules

The resolver parses eligible repository Python files with `ast`; it never
imports or executes repository code. It supports unique module-level functions,
classes and literal constants, direct same-module names, `import module`, module
aliases, `from module import name`, imported aliases, relative imports and
re-export chains. Import roots are the repository root and `src/`. Ambiguity
between these roots is retained, rather than decided through an assumed Python
search path. Namespace-package paths can be followed for imported submodules.

Each selected snippet is analyzed in its enclosing source scope. Only references
whose expression begins within the selected lines are included. Parameters and
ordinary local-value reads are not global dependencies. Calls through parameters,
local aliases, closures, objects, returned callables or dynamically constructed
expressions are explicitly unresolved. Function-local imports are unresolved.
External modules and builtin calls are unresolved. Wildcard imports, duplicated
definitions, rebound names, conditional bindings, invalid Python, unsupported
languages and cyclic re-exports also prevent a freshness claim. A recursive
function can witness its own text; a call cycle does not require traversal.

Resolved targets include their complete raw declaration text, decorators,
relative path, symbol, source line range and SHA-256. Import statements along the
resolution chain are separately witnessed. A change to an import alias is
detected even if the newly selected target has identical text. Literal assignment
statements directly referenced by the snippet receive constant witnesses;
computed assignments such as `CONFIG = load_settings()` are unresolved.

The graph is **one hop**: a captured call to `helper()` records `helper`'s source,
but does not recursively witness functions that `helper` calls. A change to a
grandchild dependency can therefore leave this report unchanged. Monkeypatching,
module side effects, environment variables, runtime import hooks, descriptors,
overloaded operators, object state, mutable constants and execution order are
outside the guarantee. The `one_hop_boundary` fixture deliberately demonstrates
this limit. These witnesses should not be described as a complete semantic
dependency graph or as proof that a coding agent's answer is correct.

## Capture and verification contracts

`capture_witnesses(bundle: dict, root: Path) -> dict` first validates the bundle
and requires the current safe-source snapshot to equal `bundle["snapshot_id"]`.
Capture raises `ValueError` when it cannot establish that starting point. Use a
freshly built bundle after changing a repository. Unsupported references remain
in the sidecar with `status: "unresolved"`; they are never silently discarded.

The sidecar uses `schema_version: 1`, `kind:
"contextproof.dependency-witnesses"` and `scope: "python-direct-static"`. It binds
`bundle_id`, `snapshot_id`, source anchors and references with a canonical JSON
SHA-256 in `id`. This is an integrity checksum, not a signature or proof of who
created the file. The caller must pair the sidecar's bundle ID with the intended
bundle; a witness for a different bundle must not be accepted as its receipt.

`verify_witnesses(witnesses: dict, root: Path) -> dict` checks the sidecar's
integrity and structure, then rescans source once. It returns `bundle_id`, the
capture and current snapshot IDs, `results`, `summary`, overall `status`, and
`fresh`. Each result contains `entry_id`, source path, symbol, `anchor_status`
and reference-level results.

| Status | Meaning |
| --- | --- |
| `unchanged` | The selected source is still present and all captured, supported direct definitions and bindings retain identical text. Line movement alone is allowed. |
| `changed` | Selected source, a direct definition, or an import binding changed, or a new reference appeared. |
| `missing` | A selected source scope, dependency file, or dependency definition disappeared. |
| `unresolved` | The capture was unresolved, or current static resolution is ambiguous, unsupported or unparsable. |
| `invalid` | Sidecar integrity/structure failed or a source path violated the safe-source policy. |

When the selected source scope is available, aggregation precedence is
`invalid > missing > changed > unresolved > unchanged`. If the source scope
itself is unavailable or changed, its status is reported directly: the resolver
cannot infer which current expressions correspond to the old snippet. `fresh`
is true only when every nonempty captured entry is `unchanged`. An unresolved
capture remains unresolved even if later edits make the name resolvable; new
evidence must be captured at that point.

Definitions are resolved at their module path and symbol identity. The resolver
allows line movement; it does not search the entire repository for a same-text
replacement of a disappeared dependency. This intentionally differs from the
exact-text receipt's relocation operation, which can retain an unchanged snippet
that moves to another file.

## Source safety and payload cost

Capture and verification use the indexer's filename/content allowlists, size
limits and file reads that reject symlinks in each path component. They scan
eligible source once and parse each eligible Python file at most once per
operation. A file being rejected by the source policy cannot be used as a fresh
dependency witness. Repositories are not executed and dependencies are not
installed.

The sidecar is an out-of-band artifact. Its source text and metadata are **not**
included in the original bundle's context budget. A client that sends a sidecar
to a model must count that additional payload separately. The dependency
benchmark reports both rendered bundle bytes and serialized sidecar bytes,
including the duplicated anchor source; it makes no billing-token claim.

## Reproducible evaluation

```bash
python scripts/run_dependency_benchmarks.py --repeats 7
pytest -q tests/test_dependencies.py
```

The human-specified source transformations and expected statuses are in
[`dependency_cases.py`](../benchmarks/dependency_cases.py). The runner records
case outcomes, exact-text baseline outcomes, repeated capture/verification
timings, serialized payload overhead, source-scan scaling, environment metadata
and implementation/fixture hashes. Results are saved to
[`dependencies.json`](../benchmarks/results/dependencies.json) and
[`dependencies.md`](../benchmarks/results/dependencies.md).

These are controlled unit-scale source-change experiments. They test the stated
resolver contract and compare it with exact-text checks; they do not estimate
performance on an unbiased repository population, developer productivity,
coding-agent task success, or suitability for publication. Latency is measured
locally and is expected to vary across hosts and runs.
