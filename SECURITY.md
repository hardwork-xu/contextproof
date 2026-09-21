# Local data and trust boundaries

ContextProof's core reads source files and stores their text in a local SQLite
index. Source bundles, dependency sidecars, context artifacts and HTML reports
also contain source text. Treat all of them as having the same confidentiality
as the repository. The core uploads no source and executes no repository code.
The optional tokenizer may download its encoding table on first use.

The MCP server is stdio-only and fixes its root when launched. Its eight tools
cover index, search, bundle, verify, repair, capture, check and refresh; it has no
shell tool, remote transport or model API. Retrieved comments and strings are
untrusted data, even when their hashes verify. A hash establishes byte identity,
not trust or correctness. HTML reports escape source and metadata, including
malformed numeric fields; their local filtering script does not execute source.

The built-in file exclusions reduce accidental indexing of common secrets but
are not a secret scanner. Use this version on selected source repositories, not
your home directory. Symlinks and out-of-root evidence paths are rejected.

Context validation binds the sidecar to its source bundle and snapshot, requires
exactly one witness anchor per source entry, and checks every anchor source field.
Omitted, extra or substituted witness entries cannot authorize reuse. Dependency
verification explicitly retains unresolved external, dynamic and ambiguous
references. Its one-hop static source guarantee does not cover runtime effects,
all transitive dependencies, or semantic equivalence.

Source and dependency verification perform separate source scans. The combined
workflow permits reuse or repair only when their current snapshot IDs agree.
This comparison is not an atomic filesystem snapshot, and concurrent writers can
change the tree during or after verification. Use immutable checkouts or a
quiescent tree for repeatable checks. Source and wrapper hashes are integrity
checks, not cryptographic signatures: someone controlling an artifact and its
hashes can replace both. The system does not authenticate the author.

The optional [downstream research harness](scripts/run_downstream.py) is separate
from the installed core workflow. It uses a local model and deliberately
executes generated candidates, frozen repository adapters and tests. Evaluation
requires macOS Seatbelt, denies network access and process forks, limits filesystem
access and resources, and runs denial probes before model-code evaluation. Its
AST/import restrictions supplement the OS sandbox; they are not the security
boundary. It fails closed when the sandbox is unavailable and provides no
unsandboxed fallback. Do not treat the core's no-execution property as a claim
about this explicitly invoked research experiment.
