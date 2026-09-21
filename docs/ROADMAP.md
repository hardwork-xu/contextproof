# Research roadmap after v0.1

These are three proposed follow-up issues with measurable acceptance criteria.
They are not completed experiments or a promise of positive results. v0.1's
current evidence and limits remain in the [evaluation protocol](EVALUATION.md).

## 1. Freeze a broader, independently reviewed drift corpus

**Question:** How often do exact verification and unique relocation accept,
recover, or invalidate evidence correctly outside the initial Pallets sample?

Build a version-pair corpus from at least ten unrelated public repositories with
compatible source licenses. Freeze a minimum of 200 sampled snippets before
inspecting verifier output. Define labels from source comparisons and publish
annotation guidelines, selection rules, immutable source identities, and review
disagreements. Distinguish observed tool statuses from externally reviewed labels.

**Acceptance criteria:**

- At least ten repositories, 200 snippet pairs, frozen source identities, and a
  public annotation sheet covering original location, text identity, relocation
  ambiguity, and whether evidence is recoverable under the exact-text contract.
- Independent review of the labels with disagreement resolution recorded. If
  independent review is unavailable, label the study as single-annotator and keep
  the independent-validation gate open.
- Reserve at least 30% of repositories as a holdout before any method tuning;
  never split different versions of one repository between development and holdout.
- Compare path-and-line, whole-file hash, and ContextProof under the same labels.
  Report false acceptance, false invalidation, recoveries, per-repository results,
  and uncertainty intervals, including failures and unresolved cases.

**Result that would change the plan:** high ambiguous or incorrect acceptance
rates may favor stricter invalidation over broader relocation search.

## 2. Add dependency witnesses to otherwise unchanged evidence

**Question:** Can a small, explicit record of referenced definitions detect stale
context caused by dependency changes without invalidating too much unrelated code?

Prototype optional dependency witnesses alongside each snippet. Start with
statically identifiable Python references; record unresolved references explicitly.
Define evidence freshness separately from exact-text validity. Do not present a
static import graph as complete runtime dependency analysis.

**Acceptance criteria:**

- A documented, versioned witness schema and explicit statuses for changed,
  unchanged, unresolved, and missing referenced definitions.
- At least 20 controlled fixtures covering called-function edits, unrelated edits,
  aliases, cycles, ambiguous names, external imports, and deleted definitions.
  Expected labels must be written before checking implementation output.
- An ablation comparing exact text alone with one-hop witness invalidation on the
  frozen corpus from issue 1, reporting additional detections and over-invalidation.
- Reproducible runtime and context-size overhead measurements with repeated runs;
  failure examples retained. Unsupported dynamic behavior must remain explicit.

**Result that would change the plan:** high over-invalidation or overhead may make
witnesses useful as advisory diagnostics rather than automatic rejection rules.

## 3. Test the verification loop on downstream coding tasks

**Question:** Does checking saved evidence improve task outcomes compared with
reusing it or retrieving fresh context under the same resource constraints?

Build a small execution-based harness using a public task benchmark and isolated
checkouts. Start with at least 20 frozen tasks from repositories excluded from
method development. Compare reuse of saved evidence, fresh retrieval, and
verify/repair with explicit invalidation handling. Fix the model version, prompts,
context allowance, tool policy, retry count, and maximum spend before running.

**Acceptance criteria:**

- A public task manifest, exact environments, harness, baseline definitions, and
  preregistered primary outcome based on executable task checks. Retrieval hit
  rate must not substitute for task success.
- Identical task/model settings across conditions, a documented repetition policy,
  and all attempts retained, including failures and aborted tasks.
- Report task success, stale-evidence use, total input/output tokens, tool calls,
  wall time, and actual cost; distinguish retrieval overhead from total workflow
  cost and include uncertainty on paired differences.
- Publish prompts, logs that can be legally redistributed, aggregate results, and
  representative failure analyses. Keep the study marked incomplete if resources
  do not permit the prespecified run; do not silently shrink it to favorable cases.

**Result that would change the plan:** if fresh retrieval performs as well with
lower total cost, keep provenance verification as an audit feature rather than
claiming it improves agent performance.
