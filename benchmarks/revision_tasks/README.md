# Real-history behavioral audit

This suite asks a model to predict the exact JSON result of a short program using
real repository APIs. It measures source-grounded behavior prediction. It does
**not** measure generated patch correctness, issue resolution, or autonomous
repository development.

The frozen inputs are in `frozen/tasks.json`; executable answers are separately
stored in `frozen/oracles.json`. No model outputs were used to select tasks,
construct answers, or freeze this suite. Every answer was executed twice against
each original upstream snapshot under macOS Seatbelt: 120 isolated executions,
all deterministic. Network, process creation, outside reads, and all writes
(including scratch writes) were tested and denied before these runs.

## Task population and split

| Split | Packaging | HTTPX | Pluggy | attrs | Total | Changed behavior | Same behavior |
|---|---:|---:|---:|---:|---:|---:|---:|
| Development | 2 | 1 | 1 | 1 | 5 | 4 | 1 |
| Holdout | 6 | 7 | 5 | 7 | 25 | 19 | 6 |

The source snapshots are Packaging 23.2/24.2, HTTPX 0.26.0/0.28.1, Pluggy
1.3.0/1.5.0, and attrs 23.2.0/24.3.0. Exact commits, archive SHA-256 values,
licenses, source-file hashes, upstream test/changelog URLs, runtime dependencies,
and the sandbox preflight are recorded in `frozen/protocol.json` and the task
provenance. Sources are unmodified upstream archives.

Tasks cover release behaviors including version matching, metadata defaults,
request encoding, plugin warnings, generated equality, class initialization,
and frozen exceptions. Five holdout cases were intentionally selected as stable
controls. The Pluggy extra-hook ordering probe also produced the same result in
both snapshots; it remains in the denominator. It must not be described as a
detected regression.

Each task has a change-family key, and no key crosses the split. These keys are
grouping metadata, **not proof of statistical independence**: multiple behaviors
share release histories, code, and libraries. Report per-repository and
per-family results; do not treat 30 tasks as 30 independent software projects or
estimate the prevalence of stale-context failures from this hand-selected set.
In particular, HTTPX's query and URL escaping changes may share an upstream
change mechanism even though their probe identifiers differ.

The development gate is frozen at at least 4/5 correct with fresh targeted
source. A failed gate stops heldout model evaluation. It does not authorize
discarding hard development tasks or choosing a model after inspecting heldout
answers. Any later change to the task population or prompting requires a new,
explicitly labeled protocol; keep this frozen run intact.

## Prompt and oracle boundary

The model sees the program, neutral execution instructions, and the chosen
source evidence. It does not see task IDs, development/holdout labels, version
numbers, commit IDs, change-family names, expected outcomes, upstream tests, or
before/after labels. Source text itself can naturally contain version mentions;
the harness does not rewrite real repository code to conceal these.

The answer is exactly `{"value": RESULT}` or, if execution raises before assigning
`RESULT`, `{"error": "ExceptionClassName"}`. The inference transport may wrap that
JSON as a string field; scoring must parse it and compare the JSON value, not a
regular expression or an LLM judgment. A failed upstream import aborts oracle
preparation instead of becoming a scored task error. Warning tasks explicitly
capture warnings; all other warnings are ignored consistently.

Source anchors are manually supplied localization hints derived from the
upstream changes. A comparison that uses them must supply the same hints to
every applicable retrieval baseline and disclose this narrower setting. This
suite is not an evaluation of repository localization. Missing historical
declarations are explicit in `source_anchors`; no stale fallback is fabricated.
Two helper hints (`_Validator._process_keywords`, `_make_init_script`) are absent
in both snapshots and recorded with `present: false`; only other real source
matches for those tasks are usable evidence. They remain visible in the frozen
audit record rather than being silently rewritten after freezing.

Fresh retrieval is a quality reference, stale reuse and no-context are
diagnostic controls, and changed-file/Git invalidation is a necessary practical
baseline. ContextProof can only claim savings over full fresh retrieval when
quality is maintained and hashing, indexing, parsing, invalidation, rendering,
storage, and model token costs are all counted. A byte change or dependency flag
alone is not a behavioral success.

## Reproduce oracle preparation

Run from the ContextProof repository with Python 3.12 and the verified upstream
archives already available. The dependency source directory must contain
`anyio`, `certifi`, `httpcore`, `h11`, `idna`, and `typing_extensions`; the separate
Sniffio 1.3.1 wheel is hashed and extracted into the scratch dependency directory.

```sh
python scripts/run_revision_tasks.py prepare \
  --work /absolute/path/to/new-oracle-work \
  --output /absolute/path/to/new-frozen-output \
  --site-packages /absolute/path/to/dependency/site-packages \
  --sniffio-wheel /absolute/path/to/sniffio-1.3.1-py3-none-any.whl
```

The command refuses to replace an existing frozen protocol. There is no
unsandboxed execution fallback. It does not invoke a model. Execution times,
absolute scratch paths, and timestamps will differ across reruns; the task and
oracle answers should agree when source/dependency identities agree.

Frozen task SHA-256:
`e27051186f0fe5b56a615cd9ee9de5ba6b56232b227e1ea40b72379aeacd4c0b`.

`frozen/publication.json` records the separate original and public protocol
hashes. The original protocol is retained privately. Its public copy replaces
local absolute paths with source paths relative to the ContextProof repository
root and redacts sandbox sentinel paths; task bytes and oracle bytes are
unchanged. Resolve relative `source_roots` against the project root, not the
process working directory. New preparation runs use portable paths directly.
