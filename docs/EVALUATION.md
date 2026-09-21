# Evaluation protocol

This repository separates an exact-text provenance experiment from a small
retrieval smoke test. Neither establishes semantic equivalence, downstream coding
success, research novelty, or state-of-the-art performance. All published numbers
come from `scripts/run_benchmarks.py`; nothing is filled in with expected gains.
The machine-readable output is [latest.json](../benchmarks/results/latest.json),
and the compact report is [latest.md](../benchmarks/results/latest.md).

## Reproduce

Use Python 3.11 or newer and `curl`. No API key, model, paid service, upstream
installation, or GitHub authentication is required. From the repository root:

```sh
python scripts/run_benchmarks.py --download
python scripts/run_benchmarks.py --check benchmarks/results/latest.json --output work/repeated-results
```

The first command fetches any missing archives and verifies their SHA-256 digests
against [manifest.json](../benchmarks/manifest.json). The second reruns the
experiments and requires every deterministic `quality` field to equal the checked
report. Measured timings and environment metadata are intentionally excluded from
that comparison. Omit `--download` for an offline run after the archives are cached.
Run `pytest tests/test_benchmarks.py` with the development dependencies installed
to check transformation oracles and metric calculations.

The script extracts only regular archive files after validating their paths. It
reads upstream Python as source text; it never installs, imports, builds, or runs
upstream projects, their test suites, or their dependencies. Source archives,
extracted trees, controlled fixtures, and index caches stay under ignored `work/`.
Each run extracts a fresh tree from the digest-checked archive. Only manifest,
query labels, methodology, and measured result data are committed. Reports contain
source paths, symbol names, locations, and snippet hashes, but no upstream source
snippets. Frozen upstream license filenames are recorded in the manifest.

## Frozen corpus and source origins

| Public repository | Before | After | License |
| --- | --- | --- | --- |
| [pallets/click](https://github.com/pallets/click) | 8.1.7 | 8.1.8 | BSD-3-Clause |
| [pallets/itsdangerous](https://github.com/pallets/itsdangerous) | 2.1.2 | 2.2.0 | BSD-3-Clause |
| [pallets/markupsafe](https://github.com/pallets/markupsafe) | 2.1.5 | 3.0.2 | BSD-3-Clause |

Tag names are human-readable labels. The manifest pins full commit SHAs, archive
URLs, and archive SHA-256 digests; reproducibility depends on these immutable
identities, not on future tag resolution. The initial SHAs were resolved through
GitHub's commits API. All three repositories are maintained by Pallets. They are
small, Python-oriented, and correlated; they do not represent the diversity of
production repositories, languages, monorepos, or large generated codebases.

## Controlled transformations and explicit labels

A standalone Python text fixture contains one selected function and one unrelated
function. The benchmark constructs seven variants. Expected labels are defined in
[oracles.py](../benchmarks/oracles.py), independently of the verifier's output.

| Transformation | Expected status | Accept exact evidence? |
| --- | --- | --- |
| No change | `valid` | Yes |
| Insert lines before the function | `relocated` | Yes |
| Move the file to another directory | `relocated` | Yes |
| Change an expression inside the selected function | `modified` | No |
| Delete the file | `deleted` | No |
| Remove the original file and create two identical copies elsewhere | `ambiguous` | No |
| Alter stored bundle text without updating its checksums | `invalid` | No |

“Accept” here means that the untampered recorded exact text remains available at
an unambiguous recoverable location. The positive labels are `valid` and
`relocated`; all others are negative. After repair, accepted evidence must be
retained and verify as `valid`, while modified, deleted, or ambiguous entries
must be dropped. A tampered bundle may be rejected with an integrity error
instead of producing a repaired bundle. This is a
small behavior contract, not an estimate of real-world classification accuracy.
An unchanged old location takes precedence over duplicates elsewhere; the
ambiguous fixture therefore deliberately removes the original location.

Two simple baselines operate on the same stored entry:

- **Old path and line range, exact text:** accept only if the stored snippet is
  identical to the current bytes at the recorded location.
- **Old file hash:** accept only if the file at the recorded path still has its
  original SHA-256 digest. This cannot bind a tampered snippet to that file and
  cannot recover moved files.

The report includes all seven outcomes, true/false positives and negatives, and
precision, recall, and accuracy. Undefined divisions are JSON `null`, not zero.
The fixture includes known failure modes of these baselines by design, so an
advantage on these seven cases is not evidence of a general effect size.
Checksums establish internal consistency and exact content identity; a party that
can rewrite a bundle and recompute its checksums can create a different internally
consistent bundle. There is no signature, trusted timestamp, or origin attestation.

## Natural version drift

For each before revision, eligible indexed chunks must be in `src/`, have at least
three source lines, contain at most 6,000 UTF-8 bytes, and have exactly one textual
occurrence across the indexed production Python files of that revision. Chunks
are sorted by SHA-256 of `path + NUL + symbol + NUL + text`; the first 40 are
selected, or all eligible chunks when fewer than 40 exist. This makes the sampling
rule independent of the after revision and its eventual statuses. Actual eligible,
sampled, evaluated, and budget-excluded counts appear in the output.

Each selected chunk is placed in a singleton index and packaged with an 8,000-byte
budget, using its symbol (or path fallback) as the query. A bundle that cannot hold
the full chunk plus metadata is explicitly recorded as budget-excluded. Each
bundle is then verified against the frozen after revision. Per-sample hashes and
locations make the selection auditable without redistributing source snippets.

Only status distributions and raw baseline acceptance counts are reported.
There is **no independently annotated gold standard for natural changes**. A
`modified` label does not establish a semantic change; a `relocated` label does
not establish that the evidence is still useful for the user's question. Drift
counts must not be described as precision, recall, correctness, or successful
repair rates. No natural-drift status is used to tune the sampling rule.

## Retrieval smoke test and full byte accounting

[queries.json](../benchmarks/queries.json) contains 14 author-written queries with
explicit file-level relevance labels: five each for Click and ItsDangerous, four
for MarkupSafe. Queries target public API concepts and frequently include exact
symbols. MarkupSafe has few production Python files, so several labels overlap.
These queries are exploratory smoke checks, not an independent or held-out IR
benchmark. They do not label every relevant file and should not be used for
precision estimates. Upstream tests and documentation are indexed when supported
by the engine; relevance labels only refer to the stated production files.

Both `bm25` and `graph` are run on the before snapshot under 2,000-, 4,000-, and
8,000-byte limits. Byte accounting measures UTF-8 bytes of the **entire rendered
bundle**, including query, evidence text, metadata, and provenance. It is compared
to the bundle's reported consumed cost. Bytes are deterministic; they are not
model tokens and these experiments make no tokenizer savings claim.

For each query, the report records whether any labeled file occurs, the fraction
of unique labeled files retrieved, and the reciprocal rank of the first relevant
entry. A file can appear through multiple chunks; duplicate chunks do not increase
file recall. Summary figures average across queries, giving queries equal weight.
Raw rows include returned file order and rendered bytes. A method returning no
entries has hit=false, recall=0, and reciprocal rank=0 for nonempty relevance labels.

Graph expansion is a heuristic. Equal or worse observed scores must be retained.
The small labeled set and exact-symbol bias do not justify claims that graph
retrieval beats BM25, works on general natural-language questions, or improves
LLM task success.

## Cache observations and provenance

Each repository receives one cold index run with a fresh SQLite cache and one
immediate warm run with the same cache. The output records elapsed wall-clock
seconds and each snapshot's parsed/reused counts. “Cold” means an empty
application cache; operating-system disk caches are not cleared. A single pair
has no confidence interval and does not control machine load. Timings must be
reported as local observations, not generalized latency or throughput claims.

`observations` stores UTC measurement time, Python version, platform, architecture,
and timing data. `provenance` stores SHA-256 digests of the frozen manifest, query
labels, and the local implementation files used. The implementation digest covers
`src/contextproof/*.py`, `benchmarks/*.py`, the runner, manifest, and queries. It
excludes result files to avoid self-reference. `quality` contains only the
repeatable outcomes and accounting checks; `--check` compares this object exactly.

Useful next work would add independently authored relevance judgments, unrelated
repositories and languages, many change pairs, downstream coding tasks, realistic
adversarial edits, and repeated performance measurements. Those experiments have
not been performed by this release.
