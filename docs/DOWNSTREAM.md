# Downstream controlled coding study

This experiment runs a real local language model and executes its generated Python.
It measures functional success on **20 artificial API-adaptation tasks**, each under
three context policies. It is not an official HumanEval score, a real GitHub issue
benchmark, or evidence of production coding-agent improvements.

**Observed result: 0/20 tasks passed in every condition.** The complete 60-cell
experiment produced no evidence of a downstream success improvement for this model
and prompt. All outcomes were retained; the model was not reprompted or upgraded
after observing failures.

| Policy | Executed success | Prompt tokens | Generated tokens | Generation time |
| --- | ---: | ---: | ---: | ---: |
| Reuse | 0/20 | 15,263 | 2,605 | 43.04 s |
| Fresh | 0/20 | 15,341 | 2,642 | 43.10 s |
| Verify, repair, refresh | 0/20 | 15,977 | 2,605 | 42.31 s |

The dominant failure was a hallucinated `from repository_helper import ...` in
**54/60** responses. That module does not exist; none of the prompts contains the
literal `repository_helper`. Every model input includes one complete helper source
entry with its actual path. The other six failures were three undefined decoder
names, two operations on a tuple instead of its unpacked argument, and one unchanged
multi-argument entry-point signature. No generation failed, no worker failed, no
completion hit the 384-token output limit, and model-reported prompt counts match
the separately computed Qwen counts for all 60 cells.

For example, HumanEval/0 with fresh context imports the invented module and retains
the original two-argument signature despite being asked for `has_close_elements(request)`.
HumanEval/1 with fresh context reaches execution but calls undefined `unpack_request`.
These instruction/API failures overwhelm the intervention. Fresh context itself
does not solve them, so this study cannot estimate benefits in a stronger working
coding-agent system.

After the model run, **20/20 known-good algorithm controls passed** the same sandbox,
current API, and original functional tests. With obsolete API calls, exactly the
five unchanged controls passed and all fifteen changed controls failed as expected.
These controls use the public upstream canonical algorithms in a separate, local
post-run validation step; they never enter retrieval or model prompts. They establish
that all task adaptations are solvable and the drift intervention is effective.
Re-executing the 60 unedited model completions reproduced every recorded pass/fail
outcome. This remains a null model result, not a positive result inferred from controls.

## Frozen design

The source is [OpenAI HumanEval](https://github.com/openai/human-eval/tree/6d43fb980f9fee3c892a914eda09951f772ad10d),
revision `6d43fb980f9fee3c892a914eda09951f772ad10d`, under its MIT license. We select
IDs 0–19 numerically, without looking at model outcomes. The original prompts and
functional tests are retained in `benchmarks/downstream/upstream/tasks.json`;
canonical solutions are removed and never included in model context. HumanEval's
OpenAI origin is separate from the external repository retrieval corpus. This is
an evaluation holdout by repository origin, **not a model-training holdout**:
HumanEval contamination is possible and no claim of unseen algorithms is made.

Each task receives one fixed adaptation. Its public entry point now accepts an
opaque `Request`; a small repository helper decodes it into the original positional
arguments. The model must implement the original algorithm itself. The helper
contains argument decoding and documentation only, never the algorithm solution.
Tests call the generated entry point through an adapter and execute the original
HumanEval `check` function. Every tested invocation must decode its request.

The task ID modulo four assigns drift before any generation:

| Remainder | Drift | Current repository change |
| --- | --- | --- |
| 0 | Symbol rename | `unpack_request` becomes `decode_request`; decoder version changes |
| 1 | Signature change | `unpack_request` now requires keyword `version="v2"` |
| 2 | File move | Exact helper source moves from `request_api.py` to `current_api.py` |
| 3 | Unchanged | The helper and its path remain unchanged |

There are five tasks of each type. This intervention deliberately makes current
API context relevant; it is not a natural distribution of repository changes.

The three policies use the same task prompt template and model settings:

1. **Reuse:** use the complete source bundle retrieved before the change.
2. **Fresh:** index and retrieve from the current tiny repository using BM25.
3. **Verify, repair, refresh:** verify the saved bundle; retain valid evidence,
   repair unique exact moves, and retrieve fresh context when evidence is invalidated
   or omitted by the repair budget. No invalidated evidence is given to the model.

The query is mechanically derived from the entry-point name plus `decode arguments
request tuple`. All policy decisions and complete rendered prompts are generated
and frozen before any model completion. The context payload cap is **1,024 tokens
counted by the model's Qwen tokenizer**; the byte cap for the complete ContextProof
bundle is 4,000. Actual maximum context is 605 Qwen tokens. No source chunk is
truncated. The output limit is 384 tokens. Task instructions are outside the context
cap; their complete rendered prompt counts are recorded separately.

## Model and execution

The model is [Qwen2.5-Coder-1.5B-Instruct, MLX 4-bit conversion](https://huggingface.co/mlx-community/Qwen2.5-Coder-1.5B-Instruct-4bit/tree/b3252a2f97102b1fb1571fec2c9b27219a8536be),
pinned to `b3252a2f97102b1fb1571fec2c9b27219a8536be`. The upstream model is
[Apache-2.0 licensed](https://huggingface.co/Qwen/Qwen2.5-Coder-1.5B-Instruct/blob/main/LICENSE).
Weights are not committed. This run downloaded that revision through `hf-mirror.com`
because the primary domain was unavailable locally; every downloaded file's SHA-256
and byte size is recorded in `environment.json`. The conversion was originally
published using MLX-LM 0.18.1; this experiment runs MLX-LM 0.31.3 / MLX 0.32.2 on
macOS arm64. Full installed dependency versions are preserved.

[MLX-LM](https://github.com/ml-explore/mlx-lm) runs entirely on the local machine.
There is no paid API and no upload of source or prompts to a model service.
Temperature is zero, the MLX seed is zero, and there is one attempt per cell.
Tasks run in numeric order, with conditions ordered reuse/fresh/verify-repair-refresh.
Each completion gets a new prompt cache. Hardware/library changes may still alter
generation; deterministic decoding is not a promise of cross-platform bit identity.

Generated code is executed inside **macOS Seatbelt (`sandbox-exec`)**, with no
unsandboxed fallback. The OS profile denies network access, process fork, and all
file writes outside a disposable scratch directory. It denies reads in user and OS
temporary trees except the scratch directory and interpreter/runtime dependencies.
System runtime files remain readable; this is not a claim of hermetic filesystem
isolation. Before execution, an unrestricted probe must confirm denied TCP connection,
fork, outside-scratch read/write, and permitted scratch writes. The results are saved.

The worker additionally limits CPU time to 3 seconds, wall time to 10 seconds,
file output to 1 MiB, and open descriptors to 64. An AST/import gate rejects private
attribute access and unsupported syntax, and executes with restricted builtins and
an explicit standard-library/module allowlist. This is defense in depth, **not the
OS isolation mechanism**. The benchmark is deliberately limited to pure functions;
its execution gate is unsuitable as a general Python-agent sandbox.

The first Python code fence is extracted verbatim, or the complete response is
used if there is no fence. No generated code is repaired. Syntax failures, missing
imports, wrong signatures, failed assertions, budget truncations, sandbox rejection,
timeouts, and generation errors all count as failures. All attempts, including
start events and complete outputs, are preserved. No best-of selection or reprompting
is performed.

## Recorded artifacts

All paths below are under `benchmarks/downstream/results/`:

| Artifact | Contents |
| --- | --- |
| `protocol.json` | Pre-generation timestamp, selection, settings, input/source hashes, sandbox checks |
| `inputs.json` | All 60 task/condition inputs, before/after helper files, full bundles, policy decisions, prompts |
| `environment.json` | Exact model file hashes, dependency versions, machine information, execution checks |
| `attempts.jsonl` | Append-only started and finished events, including complete responses |
| `results.jsonl` | Every raw response, extracted code, token IDs/counts, latency, execution output/error |
| `summary.json` | Aggregated functional success and failure types, including all failures |
| `replay.json` | Model-free rerun of generated code against the same current task fixtures |
| `oracle_controls.json` | Post-run known-good/current and obsolete-API harness controls; no model calls |
| `publication.json` | Raw/private and public artifact hashes, with diagnostic path-redaction audit |

Public diagnostic paths use `<WORKSPACE>` and `<USER_HOME>` placeholders. A separate
deterministic publication step preserves byte-identical originals outside the Git
repository, then redacts local path prefixes in diagnostics. Model responses, code,
token IDs/counts, timings, pass/fail outcomes, and the complete `inputs.json` bytes
remain unchanged. `publication.json` records both original and public hashes.
`protocol.json` explicitly identifies itself as a publication copy. Its preparation
source hashes describe the files at freeze time; concurrent later project development
can change final source files. The frozen prompt/input hash is the authority for what
the recorded model actually received, not a claim that final files equal old hashes.

The primary outcome is binary: all original functional tests **and** the decoder
contract pass. Retrieval accuracy, repaired-citation counts, and choosing a relevant
helper are not substituted for executed task success. Context preparation latency
is in each input policy; generation latency and test execution latency are separate.
There are no repeated-seed uncertainty estimates or statistical generalization
claims from this small controlled sample.

## Reproduce

On an Apple Silicon Mac, use a dedicated Python 3.12 environment. Install the core
project and the separately pinned model runner. Model weights require about 1 GiB;
do not store them inside the Git repository.

```bash
python3.12 -m venv work/model-venv
work/model-venv/bin/python -m pip install -e . 'mlx-lm==0.31.3'
export HF_HOME="$PWD/work/huggingface"
work/model-venv/bin/python -c 'from huggingface_hub import snapshot_download; snapshot_download("mlx-community/Qwen2.5-Coder-1.5B-Instruct-4bit", revision="b3252a2f97102b1fb1571fec2c9b27219a8536be", local_dir="work/model")'
work/model-venv/bin/python scripts/run_downstream.py sandbox-check --work work/downstream-scratch
work/model-venv/bin/python scripts/run_downstream.py prepare --model work/model --work work/downstream-scratch --output work/downstream-rerun
work/model-venv/bin/python scripts/run_downstream.py run --model work/model --work work/downstream-scratch --output work/downstream-rerun
```

For the recorded environment, pin the transitive versions in `environment.json` as
well. Compare local model file SHA-256 values with that file before interpreting a
rerun. A new output directory is required: the runner refuses to overwrite frozen
protocols or existing attempt logs. Preparation uses current ContextProof code, so
new code versions may produce different input hashes; the shipped `inputs.json`
preserves exactly what the recorded model saw.

To re-execute the published completions without downloading or running a model:

```bash
mkdir -p work
cp -R benchmarks/downstream/results work/downstream-replay
python scripts/run_downstream.py replay --work work/downstream-scratch --output work/downstream-replay
python scripts/run_downstream.py summarize --work work/downstream-scratch --output work/downstream-replay
```

Use a disposable copy as shown because these commands write their replay/summary
artifacts; the committed publication checksums should remain untouched.

To reproduce the post-run harness controls, download the pinned original
`data/HumanEval.jsonl.gz` to an ignored local directory, then run:

```bash
python -m benchmarks.downstream.oracle_controls --source-gzip work/HumanEval.jsonl.gz --work work/downstream-scratch --output work/downstream-replay
```

The control runner checks the original archive SHA-256, requires all 60 model results
to exist, and verifies that model inputs/results are byte-identical before and after
the controls. The canonical solutions remain outside the public model-input files.

The protocol is locally frozen with timestamps and hashes, not independently
preregistered. Small artificial repositories, a small quantized model, possible
HumanEval memorization, fixed ordering, one seed, and an enforced decoder contract
all limit external validity. The study supports only its observed controlled result.
