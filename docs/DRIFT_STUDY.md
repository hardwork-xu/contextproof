# Frozen v1 drift study

This study measures whether old code evidence remains exact and unambiguously
recoverable after a real library release changes. It evaluates **byte provenance**,
not function behavior, retrieval relevance, an agent's task success, or security.
The labels are **automated reference annotations, with separate blinded AI review**;
they are not independently collected human ground truth.

**Corpus-boundary limitation:** 23 of the primary study's 29 `deleted` labels
are dateutil tests that moved outside the frozen library prefixes. All 23 still
have exact unique matches elsewhere in the newer archive. These are corpus exits,
not actual upstream deletions. The [posthoc full-Python-scope sensitivity](../benchmarks/v1/results/scope-sensitivity.md)
rechecks the same 300 samples with a broader corpus while preserving every primary
input and result. This limitation was discovered by inspecting the first results.

The [measured report](../benchmarks/v1/results/latest.md) contains results;
[full JSON](../benchmarks/v1/results/latest.json) includes every prediction,
confusion matrix, bootstrap interval and repeated cache observation. The earlier
three-Pallets-library experiment remains available as a separate exploratory study.

## Selection and freezing

The [preregistration](../benchmarks/v1/preregistration.json) was written before
archive acquisition, sampling, annotation or engine predictions. It freezes the
question, named repositories and tags, repository split, eligibility and sampling,
reference contract, baselines, metrics, bootstrap procedure and cache sequence.
This is a local timestamped protocol with content hashes, not a third-party
preregistration service or a prospectively randomized study.

The [archive manifest](../benchmarks/v1/manifest.json) resolves both versions of
every repository to immutable commit SHAs and SHA-256 archive digests. It also
records public URLs, archive sizes, release tags, commit dates, SPDX license
identifiers and license-related file hashes. The `license_files` candidates were
selected by notice-like filename prefixes and can also include licensing
documentation or tools; repository license identifiers were checked against the
root notices. This metadata is not an exhaustive attribution map for every
upstream file. Source archives are stored only in ignored
`work/v1-drift/archives/`. No upstream project is installed, imported, built or
executed; the benchmark statically parses Python source with the local interpreter.
No upstream source snippets are redistributed in the tracked study files.

| Repository | Domain | Versions | Split |
| --- | --- | --- | --- |
| [psf/requests](https://github.com/psf/requests) | HTTP client | v2.31.0 → v2.32.3 | Development |
| [encode/httpx](https://github.com/encode/httpx) | Async HTTP client | 0.26.0 → 0.28.1 | Development |
| [urllib3/urllib3](https://github.com/urllib3/urllib3) | HTTP transport | 2.0.7 → 2.2.3 | Development |
| [pydantic/pydantic](https://github.com/pydantic/pydantic) | Validation | v2.7.4 → v2.10.6 | Development |
| [python-attrs/attrs](https://github.com/python-attrs/attrs) | Object modeling | 23.2.0 → 24.3.0 | Development |
| [pypa/packaging](https://github.com/pypa/packaging) | Package metadata | 23.2 → 24.2 | Development |
| [pytest-dev/pluggy](https://github.com/pytest-dev/pluggy) | Plugin dispatch | 1.3.0 → 1.5.0 | Development |
| [python-babel/babel](https://github.com/python-babel/babel) | Localization | v2.13.1 → v2.16.0 | Holdout |
| [tox-dev/filelock](https://github.com/tox-dev/filelock) | File locking | 3.13.1 → 3.16.1 | Holdout |
| [dateutil/dateutil](https://github.com/dateutil/dateutil) | Date parsing | 2.8.2 → 2.9.0.post0 | Holdout |

These ten owners broaden the earlier sample, but they remain a convenience sample
of Python libraries. Three projects concern HTTP, and maintainer identities and
communities can overlap across organizations. "Holdout" denotes repository-level
separation declared before results; it does not make this sample representative.

## Identical source policy for every method

Archives are checked against their pinned digests. Only regular files under the
frozen Python library prefixes are staged. Absolute paths, parent traversal,
unexpected archive roots and duplicate accepted files fail closed; symlinks and
other nonregular members are never extracted. The stage excludes generated code,
secret-like filenames, known excluded directories, files over 2 MiB, non-UTF-8,
NUL-containing files, private-key headers and generated headers.

The complete accepted path-to-raw-hash maps and Python exclusions are frozen in
[source_manifests.json](../benchmarks/v1/source_manifests.json) **before annotation**.
The engine's indexed file map is required to equal this manifest in sampling and
in every cold, warm and changed-version measurement. The independent reference
reads exactly the same accepted staged bytes. Neither method searches the rest
of the upstream archive: relocation outside the frozen library corpus is outside
this study's scope. This avoids silently allowing the reference to recover from
files that the engine is forbidden to read.

## Before-only sampling

Thirty snippets are selected per repository, 300 total. Indexing the before
version supplies source spans. Eligible spans have at least three editor lines,
at most 6000 UTF-8 bytes and exactly one complete-line occurrence in the before
corpus. That uniqueness test is performed by the separate byte-offset reference.
Library prefixes can contain embedded tests: dateutil contributes 23 such selected
spans. Prefix inclusion was applied as registered; tests were not separately
excluded or replaced after seeing results. The seed, repository, path, start line
and text digest determine a SHA-256 rank;
the first thirty eligible spans are selected. The sampler does not read the
after version. All eligible counts and selected identifiers are frozen in
[samples.json](../benchmarks/v1/samples.json) before annotations or predictions.
No sample was dropped because the engine failed or because a baseline succeeded.

The eligibility restriction reduces ambiguity already present before drift; it
must not be read as a general workload distribution. Chunk selection still uses
the engine's Python AST chunker, so this tests evidence generated by this tool,
not arbitrary user-authored snippets.

## Reference annotation and baselines

The [reference module](../benchmarks/v1/reference.py) imports no ContextProof
verification, source-line splitting or matching code. It finds byte substring
offsets, then requires complete CR/LF/CRLF editor-line boundaries. Unicode
separators inside strings do not count as editor newlines. In contrast, the
engine compares windows of decoded editor lines. Independent implementation
reduces shared-code errors; a shared contract remains and agreement is not a
substitute for independent human or semantic assessment.

| Reference annotation | Meaning |
| --- | --- |
| `valid` | Identical bytes at the recorded path and line span; this takes precedence even if another copy exists elsewhere. |
| `relocated` | Recorded location differs, but exactly one complete-line byte occurrence remains in the corpus. |
| `ambiguous` | Recorded location differs and multiple occurrences remain. |
| `modified` | No exact occurrence remains; the old path is still in the accepted corpus. |
| `deleted` | Neither the old path nor any exact occurrence remains in the accepted corpus. |

`modified` and `deleted` are provenance categories, not semantic-diff judgments.
An old function moved and substantially edited can be labeled `deleted` if its old
file disappeared. Acceptance means `valid` or `relocated` only.

The reference annotations, matching coordinates, old/new file digests and corpus
hashes are frozen in [annotations.json](../benchmarks/v1/annotations.json) before
engine predictions. Three deliberately simple baselines operate on the same
current bytes: old path exists with an in-bounds line range; exact bytes at the
old path and lines; and unchanged full-file hash at the old path. The path/range
baseline can accept changed text; file hashes can reject unchanged snippets when
unrelated parts of their file change. The study quantifies those expected
tradeoffs. It does not compare against a state-of-the-art retrieval or patch tool.

A single large evidence bundle per repository carries all thirty selected spans;
this prevents repeated corpus I/O across snippets. Its generous fixed byte cap
is an evaluation transport choice, not a retrieval-budget result. A strict check
ensures all thirty entries were retained before verification.

## Blinded AI review and disagreement handling

The [review packet](../benchmarks/v1/review_packet.json) contains source coordinates,
commits and hashes, but no reference labels or engine predictions. Selection uses
a seeded hash: two items per repository, plus up to two per reference status,
with duplicates collapsed. A separate AI reviewer inspects frozen source bytes
under the stated contract while avoiding the annotation, reference implementation,
engine prediction and report files. This is **AI review**, not a human annotation
study or a second independently recruited research team.

The [protocol amendment](../benchmarks/v1/protocol_amendments.json) records why
review coverage was increased from one to two items per repository. This happened
after the first annotations were frozen but before any engine predictions or
review; sampling, labels, metrics and split were unchanged. The original smaller
packet remains in [review_packet_initial.json](../benchmarks/v1/review_packet_initial.json).
The [sealed AI review](../benchmarks/v1/ai_review.json) covers 21 purposively
selected items and was completed without access to reference labels or engine
predictions. The subsequent [comparison](../benchmarks/v1/review_comparison.json)
records 21/21 agreement with the frozen automated labels. It identifies both the
canonical review-payload checksum (excluding the checksum field itself) and the
raw published-file SHA-256, with explicit recipes. The original sealed review
bytes and predictions are preserved. This checks only the
selected items and the declared scoped-byte contract; it does not establish a
human-labeled error rate or resolve corpus-boundary limitations.

[first_run_audit.json](../benchmarks/v1/first_run_audit.json) records every first-run
engine status and any engine/reference disagreement. It is created once and never
overwritten by the runner. Frozen input or reference files are checked against
regenerated contents and cause a hard failure on drift. A future correction must
preserve the earlier evidence and explicitly document its cause; changing labels
to match predictions is not an accepted resolution.

## Metrics and uncertainty

Reports include per-repository and combined acceptance confusion matrices,
precision, recall, accuracy and false acceptance rate (`FP / (FP + TN)`). An
undefined denominator produces JSON `null`, not a zero score. Engine/reference
status confusion matrices include an `invalid` column for unexpected verification
failures. Development (210 snippets) and holdout (90) results are separate.

The paired bootstrap resamples entire repositories with replacement 5000 times,
using seed 20260921. Each repository contributes its mean paired acceptance
accuracy difference between ContextProof and a baseline; sampled repository
means are averaged. Percentile endpoints are fixed at 2.5% and 97.5%. This avoids
treating thirty related snippets as thirty independent repository observations.
There are only ten clusters overall and three in holdout: intervals are descriptive
and unstable for population inference. All repositories contribute the same number
of snippets here, so macro repository and pooled snippet accuracy coincide.

## Post-result scope sensitivity

After the first report, manual inspection found that dateutil's `dateutil/test/`
subtree moved outside `src/dateutil/`. All 23 selected snippets from that subtree
are `deleted` in the declared corpus but remain uniquely recoverable under
`tests/` in the full newer archive. This materially changes the interpretation of
the primary status distribution.

The [sensitivity runner](../benchmarks/v1/scope_sensitivity.py) stages all
policy-eligible Python files from the same 20 archives under separate ignored
`work/v1-drift/sensitivity/` directories. It keeps exactly the same 300 original
samples, hashes and line spans, freezes expanded manifests and automated reference
annotations, then runs the engine against this expanded scope. It reports every
changed label, per-repository results and full acceptance confusion matrices.
The primary corpus, labels and results remain unchanged. This is explicitly
**posthoc sensitivity**, motivated by an observed corpus-layout confound; it is
not a new preregistered test, holdout retuning or a claim about semantic deletion.
Broader scope can also introduce duplicate matches and change relocation to
ambiguity. All-Python scope still excludes non-Python and policy-excluded files.

Reproduce after the primary experiment with:

```bash
python -m benchmarks.v1.scope_sensitivity
python -m benchmarks.v1.scope_sensitivity \
  --check benchmarks/v1/results/scope-sensitivity.json
```

## Cache measurements and reproduction

Each repository has three independent cache repetitions. A repetition starts with
a fresh SQLite file, indexes the older version, scans the same version immediately
with that cache, then scans the newer version sharing that cache. The report saves
individual wall times, medians and parsed/reused file counts for all three phases.
Warm scans still perform file reads, hashing, manifest validation and graph work;
a warm run may be slower on this machine. No minimum speedup is promised. Platform
and interpreter versions accompany timings; thermal load and concurrent work
are uncontrolled. These measurements are local observations, not a throughput
benchmark.

```bash
python -m pip install -e '.[dev]'
python scripts/run_drift_benchmarks.py --download
python scripts/run_drift_benchmarks.py \
  --check benchmarks/v1/results/latest.json \
  --output work/v1-drift/reproduction
pytest tests/test_drift_benchmarks.py
```

`--download` only fetches missing pinned archives. Every run verifies archive
hashes and recreates accepted staged sources. `--prepare-only` freezes the source
manifests, samples, annotations and blinded packet before predictions. `--check`
requires exact equality of deterministic quality fields, including all rows,
metrics and seeded intervals; machine timing observations are intentionally not
compared. Implementation and all frozen input hashes accompany the report.

No benchmark result establishes semantic preservation, downstream model quality,
retrieval superiority or production security. Natural samples may omit rare
categories such as ambiguous relocations or deleted paths; controlled adversarial
tests exercise those contracts separately and must not be blended into the natural
sample's observed frequencies.
