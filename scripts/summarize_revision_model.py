#!/usr/bin/env python3
"""Summarize every frozen held-out cell, including invalid completions."""

import argparse
from collections import defaultdict
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmarks.revision_model import canonical, sha, write_json  # noqa: E402


def metric(rows):
    valid = [row for row in rows if row["record"]["valid_completion"]]
    usage = [item for row in rows for item in row["record"]["usage"]]
    changed = [row for row in rows if row["behavior_changed"]]
    controls = [row for row in rows if not row["behavior_changed"]]
    by_family = defaultdict(list)
    by_repository = defaultdict(list)
    for row in rows:
        by_family[row["family"]].append(int(row["correct"]))
        by_repository[row["repository"]].append(int(row["correct"]))
    return {
        "tasks": len(rows), "correct": sum(row["correct"] for row in rows),
        "accuracy": statistics.mean(row["correct"] for row in rows),
        "valid_completions": len(valid), "invalid_completions": len(rows) - len(valid),
        "changed_correct": sum(row["correct"] for row in changed), "changed_tasks": len(changed),
        "control_correct": sum(row["correct"] for row in controls), "control_tasks": len(controls),
        "wrong_matches_old_on_changed": sum(row["matches_old"] and not row["correct"] for row in changed),
        "families": len(by_family),
        "equal_family_mean_accuracy": statistics.mean(statistics.mean(values) for values in by_family.values()),
        "equal_repository_mean_accuracy": statistics.mean(statistics.mean(values) for values in by_repository.values()),
        "input_tokens": sum(item.get("input_tokens", 0) for item in usage),
        "cached_input_tokens": sum(item.get("cached_input_tokens", 0) for item in usage),
        "output_tokens": sum(item.get("output_tokens", 0) for item in usage),
        "median_wall_seconds": statistics.median(row["record"]["wall_seconds"] for row in rows),
        "evidence_bytes_total": sum(row["record"]["evidence_bytes"] for row in rows),
        "evidence_bytes_mean": statistics.mean(row["record"]["evidence_bytes"] for row in rows),
        "evidence_bytes_max": max(row["record"]["evidence_bytes"] for row in rows),
        "by_repository": {name: {"correct": sum(values), "tasks": len(values)}
                          for name, values in sorted(by_repository.items())},
        "by_family": {name: {"correct": sum(values), "tasks": len(values)}
                      for name, values in sorted(by_family.items())},
    }


def summarize(rows, tasks, conditions):
    expected = {(task["id"], condition) for task in tasks for condition in conditions}
    keys = [(row["task_id"], row["condition"]) for row in rows]
    if set(keys) != expected or len(set(keys)) != len(keys):
        raise ValueError("results must contain exactly one attempt for every frozen task/condition")
    oracle = {row["id"]: row for row in json.loads(
        (ROOT / "benchmarks/revision_tasks/frozen/oracles.json").read_text())}
    for row in rows:
        actual = bool(row["record"]["valid_completion"] and canonical(row["record"]["answer"]) ==
                      canonical(oracle[row["task_id"]]["after"]))
        if actual != row["correct"]:
            raise ValueError("stored score disagrees with current exact oracle replay")
    grouped = {name: [row for row in rows if row["condition"] == name] for name in conditions}
    lookup = {(row["task_id"], row["condition"]): row for row in rows}
    paired = {}
    for baseline in [name for name in conditions if name != "graph_current"]:
        pairs = [(lookup[(task["id"], "graph_current")]["correct"],
                  lookup[(task["id"], baseline)]["correct"]) for task in tasks]
        paired[baseline] = {"graph_only_correct": sum(a and not b for a, b in pairs),
                            "baseline_only_correct": sum(b and not a for a, b in pairs),
                            "both_correct": sum(a and b for a, b in pairs),
                            "both_incorrect": sum(not a and not b for a, b in pairs)}
    return {"schema_version": 1, "attempts": len(rows), "task_count": len(tasks),
            "family_count": len({task["family"] for task in tasks}),
            "conditions": {name: metric(values) for name, values in grouped.items()},
            "graph_paired_against": paired,
            "limitations": ["Upstream-derived, source-conditioned output prediction with supplied localization hints.",
                            "Four repositories and correlated change families; task rows are not IID.",
                            "Single semantic sample; no immutable hosted-weight identifier or generation seed.",
                            "No claim about general patching, autonomous agents, monetary costs or novelty."],
            "paired_tasks": [{"task_id": task["id"], "repository": task["repository"],
                              "family": task["family"], "changed": oracle[task["id"]]["behavior_changed"],
                              "correct": {name: lookup[(task["id"], name)]["correct"] for name in conditions}}
                             for task in tasks]}


def markdown(summary):
    lines = ["# Source-conditioned real revision behavior", "",
             "All attempts are included. These are exact API-output predictions with shared upstream-derived "
             "source hints, not issue-resolution scores. See [the pre-model protocol](../../../../docs/REVISION_STUDY_PROTOCOL.md).", "",
             f"{summary['task_count']} held-out probes, {summary['family_count']} change/control families, "
             f"4 repositories, {summary['attempts']} completions.", "",
             "| Context | Exact | Changed | Controls | Wrong old answer | Invalid | Mean source bytes | Input tokens |",
             "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for name, item in summary["conditions"].items():
        lines.append(f"| {name} | {item['correct']}/{item['tasks']} | "
                     f"{item['changed_correct']}/{item['changed_tasks']} | "
                     f"{item['control_correct']}/{item['control_tasks']} | "
                     f"{item['wrong_matches_old_on_changed']} | {item['invalid_completions']} | "
                     f"{item['evidence_bytes_mean']:.0f} | {item['input_tokens']:,} |")
    lines += ["", "Input-token totals include the shared harness overhead. Source bytes include "
              "each condition's actual metadata. Cached usage, output tokens, request times and family/repository "
              "breakdowns are in summary.json. No monetary price or statistical superiority is inferred.", "",
              "| Paired against graph_current | Graph only correct | Comparator only correct | Both correct | Both wrong |",
              "|---|---:|---:|---:|---:|"]
    for name, item in summary["graph_paired_against"].items():
        lines.append(f"| {name} | {item['graph_only_correct']} | {item['baseline_only_correct']} | "
                     f"{item['both_correct']} | {item['both_incorrect']} |")
    lines += ["", "The primary comparator is fresh_anchors: both methods receive the same symbol hints. "
              "Fresh-versus-stale differences diagnose stale evidence and do not establish a unique graph benefit.", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--replace-graph-results", type=Path,
                        help="explicit post-freeze sensitivity: retain baselines, replace all 25 graph cells")
    args = parser.parse_args()
    raw = args.results.read_bytes()
    rows = json.loads(raw)
    sensitivity = None
    if args.replace_graph_results:
        extra_raw = args.replace_graph_results.read_bytes()
        extra = json.loads(extra_raw)
        if len(extra) != 25 or any(row["condition"] != "graph_current" for row in extra):
            raise ValueError("sensitivity must supply exactly 25 graph cells")
        rows = [row for row in rows if row["condition"] != "graph_current"] + extra
        sensitivity = {"type": "post-freeze resolver-v2 sensitivity; baselines reused, not rerun",
                       "corrected_graph_results_sha256": sha(extra_raw),
                       "original_results_sha256": sha(raw)}
    tasks = [task for task in json.loads((ROOT / "benchmarks/revision_tasks/frozen/tasks.json").read_text())
             if task["split"] == "holdout"]
    conditions = json.loads((ROOT / "benchmarks/revision_tasks/model-inputs/protocol.json").read_text())["conditions"]
    summary = {**summarize(rows, tasks, conditions), "results_sha256": sha(raw)}
    if sensitivity:
        summary["sensitivity"] = sensitivity
    write_json(args.output / "summary.json", summary)
    rendered = markdown(summary)
    if sensitivity:
        rendered = rendered.replace("# Source-conditioned real revision behavior",
                                    "# Post-freeze resolver-v2 sensitivity", 1)
        rendered += ("\nOnly the 25 corrected graph contexts were rerun. All 125 comparator cells "
                     "are reused from the original run. This is exploratory after the scope audit "
                     "and partial original outcomes, not an untouched confirmatory holdout.\n")
    (args.output / "summary.md").write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
