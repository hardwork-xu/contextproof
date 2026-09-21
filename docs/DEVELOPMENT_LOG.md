# Development log

This log records decisions and evidence from actual development. ContextProof is
maintained by hardwork-xu with AI assistance for design, implementation, and writing.
It does not reconstruct a longer history or imply an external engineering team.

## 2026-09-21 — Initial v0.1 implementation and evaluation

**Problem selected.** Focus on saved code evidence becoming stale after repository
changes. The implemented contract checks exact source text and conservatively
repairs citations. It does not claim a novel retrieval algorithm or infer semantic
equivalence. Related systems and untested research questions are recorded in
[RESEARCH.md](RESEARCH.md).

**Implementation completed.** Added source scanning, Python AST chunks, source
hashes, a SQLite parse cache, BM25, a small dependency-graph ranking heuristic,
budgeted evidence packing, six verification outcomes, conservative repair, a CLI,
and a fixed-root MCP stdio interface. The default implementation uses the Python
standard library. Optional tiktoken encodings have separate dependency and test
coverage. Source trees are inspected as text without executing repository code.

**Budget decision.** The default allowance is explicitly UTF-8 bytes. The counted
object is the full rendered agent payload, including source and provenance. JSON
storage receipts and transport wrappers are outside the allowance. The consumed
count lives outside the rendered payload to avoid a self-referential count.
Whole chunks that do not fit are skipped rather than truncated. These choices are
specified in [DESIGN.md](DESIGN.md).

**Verification decision.** Original exact locations take precedence; displaced
text is recoverable only when an exact whole-line match is unique. Modified,
deleted, and ambiguous evidence is invalidated. Malformed or tampered bundles can
be refused before repair. This detects internal inconsistency, not a malicious
party able to replace both content and checksums. Dependency freshness and
transactional consistency remain unresolved.

**Evaluation completed.** Froze two versions each of Click, ItsDangerous, and
MarkupSafe using commit SHAs and archive SHA-256 digests. Added independent
controlled-transformation labels, path-and-line and whole-file-hash baselines,
and a deterministic sample of 118 production snippets. Added 14 exploratory
file-relevance queries and evaluated both retrieval methods at three byte budgets.
The committed [report](../benchmarks/results/latest.md) includes all outcomes,
source provenance, and local cold/warm indexing observations.

**Results retained.** All seven controlled statuses and repair contracts matched
expectations. All 84 retrieval runs respected their rendered budgets. Graph
expansion reduced labeled-file hit rate at 2,000 bytes (8/14 versus BM25's 9/14),
tied at 4,000 bytes, and increased it at 8,000 bytes (14/14 versus 13/14). This mixed
result is retained without treating the small query set as general evidence of
superiority. Natural drift remains status observations without independent gold
labels. No downstream agent experiment was performed.

**Validation completed.** Ran the local test suite, lint checks, CLI integration,
optional-tokenizer checks, and benchmark-oracle tests. A second full benchmark run
matched all deterministic quality fields. The CI workflow defines a Linux/macOS
Python matrix, package-build checks, and a separate tokenizer job; its current
remote outcome is available in [GitHub Actions](https://github.com/hardwork-xu/contextproof/actions).
Test counts can change during review, so this log does not freeze a numeric count.

**Next decision gates.** The [roadmap](ROADMAP.md) defines independent drift
annotation, dependency witnesses, and downstream evaluation. Those are proposed
follow-up work, not completed features or demonstrated research findings.
