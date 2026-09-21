#!/usr/bin/env python3
"""Plot exact public revision-study outcomes; requires matplotlib (tested: 3.10.8).

No model calls, invented uncertainty intervals, or private paths are emitted.
An optional resolver-v2 summary adds a separate condition without replacing v1.
"""

import argparse
import hashlib
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402
from matplotlib.colors import ListedColormap  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUMMARY = ROOT / "benchmarks/revision_tasks/model-results/holdout/summary.json"
ORDER = ["no_context", "stale_anchors", "fresh_anchors", "fresh_bm25", "graph_current", "archex"]
LABELS = {
    "no_context": ("No source context", "No\nsource", "#7a8490"),
    "stale_anchors": ("Stale supplied source", "Stale\nsource", "#c18465"),
    "fresh_anchors": ("Fresh supplied source", "Fresh\nsource", "#237383"),
    "fresh_bm25": ("Fresh BM25", "Fresh\nBM25", "#5689a8"),
    "graph_current": ("Graph · resolver v1", "Graph\nv1", "#756892"),
    "graph_corrected": ("Graph · resolver v2*", "Graph\nv2*", "#ab8bc1"),
    "archex": ("archex 0.31.2", "archex", "#6e8e7c"),
}


def read_summary(path):
    raw = path.read_bytes()
    summary = json.loads(raw)
    rows = summary["paired_tasks"]
    if summary["task_count"] != 25 or len(rows) != 25:
        raise ValueError("this frozen study requires exactly 25 paired tasks")
    if len({row["task_id"] for row in rows}) != 25:
        raise ValueError("duplicate task IDs")
    if len({row["repository"] for row in rows}) != 4:
        raise ValueError("this study requires four repositories")
    for condition in ORDER:
        values = [row["correct"][condition] for row in rows]
        metric = summary["conditions"][condition]
        if (any(type(value) is not bool for value in values)
                or metric["tasks"] != 25 or sum(values) != metric["correct"]):
            raise ValueError(f"aggregate and paired outcomes disagree: {condition}")
    return summary, hashlib.sha256(raw).hexdigest()


def portable_name(path):
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.name


def prepare(original, sensitivity=None):
    rows = {row["task_id"]: {**row, "correct": dict(row["correct"])}
            for row in original["paired_tasks"]}
    conditions = list(ORDER)
    metrics = dict(original["conditions"])
    if sensitivity is not None:
        if "sensitivity" not in sensitivity:
            raise ValueError("corrected summary must explicitly identify its post-freeze sensitivity")
        corrected = {row["task_id"]: row for row in sensitivity["paired_tasks"]}
        if corrected.keys() != rows.keys():
            raise ValueError("sensitivity uses different tasks")
        for key, row in rows.items():
            other = corrected[key]
            if any(row[field] != other[field] for field in ["repository", "family", "changed"]):
                raise ValueError("sensitivity changes paired task metadata")
            if any(row["correct"][name] != other["correct"][name]
                   for name in ORDER if name != "graph_current"):
                raise ValueError("sensitivity changes comparator outcomes; expected reused baselines")
            row["correct"]["graph_corrected"] = other["correct"]["graph_current"]
        conditions.insert(conditions.index("graph_current") + 1, "graph_corrected")
        metrics["graph_corrected"] = sensitivity["conditions"]["graph_current"]
    repositories = list(dict.fromkeys(row["repository"] for row in rows.values()))
    grouped = [row for repository in repositories for row in rows.values()
               if row["repository"] == repository]
    return grouped, conditions, metrics


def paired_message(rows, graph_key, label):
    pairs = [(row["correct"][graph_key], row["correct"]["fresh_anchors"]) for row in rows]
    graph_only = sum(a and not b for a, b in pairs)
    source_only = sum(b and not a for a, b in pairs)
    both = sum(a and b for a, b in pairs)
    neither = sum(not a and not b for a, b in pairs)
    return (f"{label} vs fresh supplied source\n"
            f"{graph_only} graph-only correct · {source_only} source-only correct\n"
            f"{both} both correct · {neither} both wrong")


def draw(rows, conditions, metrics, original, sources, sensitivity):
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "svg.fonttype": "none", "svg.hashsalt": "contextproof-revision-results-v1",
                         "axes.unicode_minus": False, "figure.facecolor": "#ffffff",
                         "savefig.facecolor": "#ffffff"})
    figure = plt.figure(figsize=(15.5, 10.5))
    ink, muted = "#172c3a", "#52636e"
    figure.text(.055, .956, "EXPLORATORY PROTOTYPE STUDY", fontsize=10, weight="bold", color=muted)
    figure.text(.055, .913, "Revision-output prediction", fontsize=26, weight="bold", color=ink)
    version = ("Original graph: resolver v1 · corrected resolver v2 shown separately*" if sensitivity
               else "Original frozen graph: resolver v1")
    figure.text(.055, .875, version, fontsize=13, weight="bold", color="#67547f")
    figure.text(.055, .842, "25 paired tasks · 4 repositories · shared source-localization hints",
                fontsize=12, color=muted)

    bars = figure.add_axes([.195, .467, .305, .313])
    counts = [metrics[name]["correct"] for name in conditions]
    bars.barh(range(len(conditions)), counts,
              color=[LABELS[name][2] for name in conditions], height=.64)
    bars.set_yticks(range(len(conditions)), [LABELS[name][0] for name in conditions], fontsize=11)
    bars.invert_yaxis()
    bars.set_xlim(0, 28)
    bars.set_xticks([0, 5, 10, 15, 20, 25])
    bars.set_xlabel("Exact matches out of 25 tasks", labelpad=10, color=muted)
    bars.set_axisbelow(True)
    bars.xaxis.grid(True, color="#e3e9ed", linewidth=.7)
    bars.tick_params(axis="both", length=0, pad=8, colors=muted)
    for spine in bars.spines.values():
        spine.set_visible(False)
    for index, count in enumerate(counts):
        bars.text(count + .4, index, f"{count}/25", va="center", fontsize=11, weight="bold", color=ink)

    primary = paired_message(rows, "graph_current", "Resolver v1")
    figure.text(.065, .355, "PRIMARY COMPARATOR: SAME SUPPLIED ANCHORS", fontsize=10,
                weight="bold", color=muted)
    figure.text(.065, .277, primary, fontsize=11, linespacing=1.55, color=ink)
    if sensitivity:
        figure.text(.065, .179, paired_message(rows, "graph_corrected", "Resolver v2*"),
                    fontsize=11, linespacing=1.55, color=ink)
    else:
        figure.text(.065, .191,
                    "Exact paired outcomes are shown at right.\n"
                    "Counts describe this selected task set;\n"
                    "they do not establish a general graph benefit.",
                    fontsize=10, linespacing=1.55, color=muted)

    heat = figure.add_axes([.754, .198, .219, .584])
    matrix = [[int(row["correct"][condition]) for condition in conditions] for row in rows]
    correct_color, wrong_color = "#387d91", "#f0d5c4"
    heat.imshow(matrix, aspect="auto", interpolation="nearest",
                cmap=ListedColormap([wrong_color, correct_color]), vmin=0, vmax=1)
    heat.set_xticks(range(len(conditions)), [LABELS[name][1] for name in conditions], fontsize=8)
    labels = [row["task_id"] + (" [C]" if not row["changed"] else "") for row in rows]
    heat.set_yticks(range(len(rows)), labels, fontsize=8)
    heat.tick_params(axis="both", length=0, pad=5, colors=muted)
    for index, row in enumerate(matrix):
        for column, value in enumerate(row):
            if not value:
                heat.text(column, index, "×", ha="center", va="center", color="#874929", fontsize=12)
    heat.set_xticks([value - .5 for value in range(len(conditions) + 1)], minor=True)
    heat.set_yticks([value - .5 for value in range(len(rows) + 1)], minor=True)
    heat.grid(which="minor", color="white", linewidth=.6)
    heat.tick_params(which="minor", length=0)
    for index in range(1, len(rows)):
        if rows[index]["repository"] != rows[index - 1]["repository"]:
            heat.axhline(index - .5, color="white", linewidth=3)
    for spine in heat.spines.values():
        spine.set_visible(False)
    heat.set_title("The same 25 tasks in every condition", fontsize=11, color=ink, pad=15)
    heat.legend(handles=[Patch(facecolor=correct_color, label="Exact"),
                         Patch(facecolor=wrong_color, label="Wrong")],
                loc="upper center", bbox_to_anchor=(.5, -.075), ncol=2,
                frameon=False, fontsize=9)

    changed = sum(row["changed"] for row in rows)
    footer = (f"{changed} changed-behavior probes + {len(rows) - changed} controls [C]. "
              "Tasks within four repositories are correlated; no IID confidence intervals are shown.\n"
              "Single completion per task/condition. This measures exact output prediction, not code-patch success.")
    if sensitivity:
        footer += "\n*Post-freeze resolver-v2 sensitivity: only 25 graph cells rerun; all 125 comparator cells reused."
    else:
        footer += f"\nOriginal frozen run: all {original['attempts']} completions included. Resolver-v1 graph outcomes are historical."
    figure.text(.055, .073, footer, fontsize=9, color=muted, linespacing=1.5)
    source_note = " · ".join(f"{label} summary SHA256 {digest[:12]}" for label, _, digest in sources)
    figure.text(.055, .018, source_note, fontsize=8, color=muted)
    return figure


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--sensitivity", type=Path,
                        help="post-freeze resolver-v2 summary; append its graph result as a seventh condition")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/assets/revision-results",
                        help="output basename, without extension")
    args = parser.parse_args()
    original, digest = read_summary(args.summary)
    sources = [("Original", portable_name(args.summary), digest)]
    sensitivity = None
    if args.sensitivity:
        sensitivity, second_digest = read_summary(args.sensitivity)
        sources.append(("Sensitivity", portable_name(args.sensitivity), second_digest))
    rows, conditions, metrics = prepare(original, sensitivity)
    figure = draw(rows, conditions, metrics, original, sources, sensitivity)
    description = ("Exact output prediction on 25 paired source-conditioned tasks from four correlated repositories. "
                   "Original graph resolver v1; no IID confidence intervals. "
                   + "; ".join(f"{label}: {path} SHA256 {checksum}" for label, path, checksum in sources))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(args.output.with_suffix(".svg"), metadata={"Date": None, "Creator": "ContextProof",
                   "Title": "Revision-output prediction: prototype study", "Description": description})
    svg = args.output.with_suffix(".svg")
    svg.write_text("\n".join(line.rstrip() for line in svg.read_text().splitlines()) + "\n")
    figure.savefig(args.output.with_suffix(".png"), dpi=180, metadata={"Software": "ContextProof",
                   "Title": "Revision-output prediction: prototype study", "Description": description})
    plt.close(figure)
    print(json.dumps({"conditions": {name: {"correct": metrics[name]["correct"], "tasks": 25}
                                     for name in conditions},
                      "outputs": [portable_name(args.output.with_suffix(ext)) for ext in [".svg", ".png"]],
                      "matplotlib_version": matplotlib.__version__}, indent=2))


if __name__ == "__main__":
    main()
