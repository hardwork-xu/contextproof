# Local data and trust boundaries

ContextProof reads source files and stores their text in a local SQLite index.
Bundles contain source text. Treat both as having the same confidentiality as
the repository. No source is uploaded by ContextProof and no repository code runs.
The optional tokenizer may download its encoding table on first use.

The MCP server is stdio-only and fixes its root when launched. It has no shell
tool or model API. Retrieved comments and strings are untrusted data, even when
their hashes verify. A hash establishes byte identity, not trust or correctness.

The built-in file exclusions reduce accidental indexing of common secrets but
are not a secret scanner. Use this version on selected source repositories, not
your home directory. Symlinks and out-of-root evidence paths are rejected.

Verification checks a static snapshot. Concurrent writers can change the tree
after verification. For repeatable experiments, use immutable checkouts. Source
hashes are integrity checks, not cryptographic signatures: someone who controls
both an artifact and its hashes can replace both. The system does not authenticate
the author or prove semantic equivalence or complete dependency coverage.
