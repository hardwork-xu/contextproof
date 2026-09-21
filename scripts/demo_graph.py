#!/usr/bin/env python3
"""Generate an offline report from an executed synthetic Git revision workflow.

This demonstration executes ContextProof and Git only, never fixture source.
It is not a real-repository benchmark or a downstream model experiment.
"""

import argparse
from html import escape
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from contextproof.graph import canonical_graph_bytes  # noqa: E402
from contextproof.graph_delta import apply_graph_delta, canonical  # noqa: E402
from contextproof.graph_payload import render_graph_context  # noqa: E402
from contextproof.graph_session import GraphSession  # noqa: E402
from contextproof.session import capture_context, check_context  # noqa: E402


SOURCES = {
    "checkout.py": "from pricing import price_multiplier\n\ndef invoice_total(amount):\n"
                   "    return amount * price_multiplier()\n",
    "pricing.py": "from tax import tax_rate\n\ndef price_multiplier():\n    return 1 + tax_rate()\n",
    "tax.py": "from policy import base_rate\n\ndef tax_rate():\n    return base_rate()\n",
    "policy.py": "def base_rate():\n    return 0.05\n",
}


def execute_demo(work):
    git = os.environ.get("CONTEXTPROOF_GIT") or shutil.which("git")
    if not git:
        raise RuntimeError("Git is required for this immutable-revision demonstration")
    work.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="graph-demo-", dir=work) as temporary:
        directory = Path(temporary)
        root = directory / "repository"
        root.mkdir()
        for path, text in SOURCES.items():
            (root / path).write_text(text, encoding="utf-8")
        base = [git, "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false",
                "-c", "core.autocrlf=false", "-c", "user.name=ContextProof demo",
                "-c", "user.email=hardwork-xu@noreply", "-C", str(root)]
        environment = dict(os.environ, GIT_AUTHOR_DATE="2026-09-21T00:00:00+0000",
                           GIT_COMMITTER_DATE="2026-09-21T00:00:00+0000")

        def run_git(*args):
            return subprocess.run([*base, *args], capture_output=True, text=True,
                                  check=True, timeout=30, env=environment).stdout.strip()

        def commit(message):
            # Stage only known synthetic Python files; never cache databases.
            run_git("add", "--", *sorted(path.name for path in root.glob("*.py")))
            run_git("commit", "--quiet", "--no-verify", "-m", message)
            return run_git("rev-parse", "HEAD")

        run_git("init", "--quiet")
        before_ref = commit("Initial synthetic policy")
        legacy = capture_context(root, "invoice_total", budget=16000)
        with GraphSession(root, cache_path=directory / "evidence.sqlite", git_executable=git) as session:
            captured = session.capture("invoice_total", ref=before_ref, budget=16000,
                                       max_depth=4, max_nodes=32)
            before = captured["graph"]
            stored = session.store.load_graph(before["id"])
            assert canonical_graph_bytes(stored) == canonical_graph_bytes(before)
            (root / "policy.py").write_text("def base_rate():\n    return 0.20\n")
            after_ref = commit("Change synthetic leaf policy")
            legacy_check = check_context(legacy, root)
            refreshed = session.refresh(before["id"], ref=after_ref, budget=16000, view="update")
            after = refreshed["graph"]
            full = render_graph_context(after, budget=16000)
            reconstruction = apply_graph_delta(before, refreshed["delta"])
            exact = canonical_graph_bytes(reconstruction) == canonical_graph_bytes(after)
            assert exact
            assert refreshed["comparison"]["status"] == "changed"
            assert refreshed["payload"]["complete"] and full["complete"]
            assert "return 0.20" in refreshed["payload"]["rendered"]
            assert "return 0.05" not in refreshed["payload"]["rendered"]
            assert legacy_check["source"]["valid"] and legacy_check["dependencies"]["fresh"]
            small = render_graph_context(after, budget=300)
            assert not small["complete"] and small["consumed"] <= 300

            (root / "utility.py").write_text("def unrelated():\n    return 7\n")
            unrelated_ref = commit("Add unrelated synthetic utility")
            unrelated = session.refresh(after["id"], ref=unrelated_ref, budget=16000, view="update")
            assert unrelated["comparison"]["fresh"]
            assert not unrelated["payload"]["included_nodes"]

            (root / "policy.py").write_text("def base_rate():\n    return configured_rate()\n")
            dynamic_ref = commit("Introduce unresolved synthetic runtime input")
            dynamic = session.refresh(after["id"], ref=dynamic_ref, budget=16000, view="full")
            assert not dynamic["payload"]["complete"] and dynamic["payload"]["frontier"]
            assert "def invoice_total" in dynamic["payload"]["rendered"]

        causes = [cause for row in refreshed["comparison"]["results"] for cause in row["causes"]]
        path = max((cause["path"] for cause in causes), key=len)
        chain = [{key: after["nodes"][node_id][key] for key in ("path", "symbol")}
                 for node_id in path]
        payload = refreshed["payload"]
        data = {
            "kind": "synthetic-executable-demonstration", "source_execution": False,
            "before_revision": before_ref, "after_revision": after_ref,
            "before_handle": before["id"], "after_handle": after["id"],
            "stored_handle_roundtrip": True, "delta_reconstruction_exact": exact,
            "nodes": len(after["nodes"]), "edges": len(after["edges"]), "causal_path": chain,
            "source_only_valid": legacy_check["source"]["valid"],
            "one_hop_fresh": legacy_check["dependencies"]["fresh"],
            "transitive_status": refreshed["comparison"]["status"],
            "full_graph_bytes": len(canonical_graph_bytes(after)),
            "lossless_delta_bytes": len(canonical(refreshed["delta"])),
            "model_payload_bytes": payload["consumed"], "model_payload_budget": payload["budget"],
            "model_payload_complete": payload["complete"],
            "tiny_budget": {key: small[key] for key in ("budget", "consumed", "complete", "status")},
            "dynamic_frontier_count": len(dynamic["payload"]["frontier"]),
            "dynamic_payload_complete": dynamic["payload"]["complete"],
            "unrelated_payload_source_nodes": len(unrelated["payload"]["included_nodes"]),
            "unrelated_comparison_fresh": unrelated["comparison"]["fresh"],
        }
        records = {"before": before, "after": after, "delta": refreshed["delta"],
                   "comparison": refreshed["comparison"], "summary": data,
                   "model_payload": payload, "full_payload": full,
                   "dynamic_payload": dynamic["payload"], "tiny_payload": small}
        return records


def report(records):
    data = records["summary"]
    before = next(node for node in records["before"]["nodes"].values()
                  if node["path"] == "policy.py" and node["symbol"] == "base_rate")
    after = next(node for node in records["after"]["nodes"].values()
                 if node["path"] == "policy.py" and node["symbol"] == "base_rate")
    chain = data["causal_path"]
    shapes = []
    width = 240
    for index, node in enumerate(chain):
        x = index * width + 4
        color = "#f9c46b" if index == len(chain) - 1 else "#8ebaff"
        shapes.append(f'<rect x="{x}" y="12" width="206" height="68" rx="9" '
                      f'fill="#172335" stroke="{color}"/>')
        shapes.append(f'<text x="{x + 14}" y="38" fill="#f2f6ff">{escape(node["symbol"])}</text>')
        shapes.append(f'<text x="{x + 14}" y="61" fill="#a7b6cc" font-size="12">'
                      f'{escape(node["path"])}</text>')
        if index + 1 < len(chain):
            shapes.append(f'<path d="M{x + 209} 46 H{x + width - 7}" stroke="#8ebaff" '
                          'stroke-width="2" marker-end="url(#arrow)"/>')
    svg = (f'<svg viewBox="0 0 {width * len(chain)} 94" role="img" '
           'aria-label="Recorded dependency path from the unchanged caller to the changed leaf" '
           'xmlns="http://www.w3.org/2000/svg"><defs><marker id="arrow" markerWidth="6" '
           'markerHeight="6" refX="5" refY="3" orient="auto"><path d="M0 0L6 3L0 6" '
           'fill="#8ebaff"/></marker></defs>' + "".join(shapes) + '</svg>')
    def json_view(item):
        return escape(json.dumps(item, ensure_ascii=False, sort_keys=True, indent=2))

    dynamic_reasons = ", ".join(sorted({item["reason"] for item in records["dynamic_payload"]["frontier"]}))
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:">
<title>ContextProof · an actual dependency update</title>
<style>
:root{{color-scheme:dark;font-family:ui-sans-serif,system-ui,-apple-system,sans-serif;background:#0b1220;color:#e7effc}}
*{{box-sizing:border-box}}body{{margin:0}}main{{max-width:1080px;margin:0 auto;padding:48px 24px 64px}}
.eyebrow{{color:#8ebaff;letter-spacing:.12em;font-size:12px;font-weight:700;text-transform:uppercase}}
h1{{font-size:clamp(28px,5vw,43px);line-height:1.12;max-width:850px;margin:18px 0}}
h2{{font-size:21px;margin:0 0 14px}}p{{line-height:1.65;color:#b9c8dc;max-width:900px}}
.badge{{display:inline-block;border:1px solid #3b5270;padding:6px 10px;border-radius:20px;font-size:12px;color:#d5e5ff}}
.notice{{padding:14px 18px;background:#192638;border-left:3px solid #f9c46b;margin:24px 0}}
.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:28px 0}}
.card,section{{border:1px solid #26364e;border-radius:12px;background:#111b2b;padding:22px}}
section{{margin:18px 0}}.value{{font-size:30px;letter-spacing:-.03em;margin:7px 0;color:#f5f8ff}}
.label,small{{font-size:12px;color:#a9bad2}}.ok{{color:#90deb0}}.warn{{color:#f9c46b}}
.twocol{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}.codecard{{min-width:0}}
pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#091220;border:1px solid #23334b;border-radius:8px;
padding:16px;line-height:1.55;font-size:13px;max-height:450px;overflow:auto}}
code{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}}.old{{border-top:3px solid #dd8390}}.new{{border-top:3px solid #90deb0}}
svg{{width:100%;font-family:ui-monospace,SFMono-Regular,monospace;font-size:14px}}
table{{width:100%;border-collapse:collapse;font-size:14px}}td,th{{text-align:left;border-bottom:1px solid #29364b;padding:12px 8px}}
th{{color:#aac0df;font-weight:500}}summary{{cursor:pointer;color:#afd0ff;padding:7px 0}}footer{{font-size:12px;color:#8c9cb4;margin-top:26px;line-height:1.7}}
@media(max-width:720px){{main{{padding:26px 16px}}.grid,.twocol{{grid-template-columns:1fr}}section{{padding:17px}}}}
</style></head><body><main>
<div class="eyebrow">ContextProof / executable graph demonstration</div>
<h1>The caller is unchanged.<br>The policy three calls away changed.</h1>
<span class="badge">Synthetic fixture · real execution of ContextProof and Git</span>
<p>This page was generated from immutable Git revisions, actual graph comparisons and the exact model payload.
The fixture source was inspected, never executed. These are demonstration results, not evidence of production accuracy or model improvement.</p>
<div class="grid">
<div class="card"><div class="label">Transitive source comparison</div><div class="value warn">{escape(data['transitive_status'])}</div><small>{data['nodes']} source nodes · {data['edges']} references</small></div>
<div class="card"><div class="label">Current update sent to a model</div><div class="value">{data['model_payload_bytes']:,} B</div><small>of {data['model_payload_budget']:,} UTF-8 bytes · complete for this update</small></div>
<div class="card"><div class="label">Delta reconstruction</div><div class="value ok">byte-exact</div><small>{data['lossless_delta_bytes']:,} B delta / {data['full_graph_bytes']:,} B full graph</small></div>
</div>
<section><h2>One recorded cause, followed back to the caller</h2>{svg}
<p>The original caller and its direct helper retain identical source. The bounded transitive graph reaches the changed leaf and includes its current definition and connecting import statements in the update.</p>
<div class="twocol"><div class="codecard"><small>Previous policy.py</small><pre class="old"><code>{escape(before['text'])}</code></pre></div>
<div class="codecard"><small>Current policy.py</small><pre class="new"><code>{escape(after['text'])}</code></pre></div></div></section>
<section><h2>What each check actually observed</h2><table><thead><tr><th>Check</th><th>Recorded result</th><th>Meaning</th></tr></thead><tbody>
<tr><td>Exact caller text</td><td class="ok">valid</td><td>The saved caller text is unchanged.</td></tr>
<tr><td>v1 direct dependency</td><td class="ok">unchanged</td><td>The direct helper is unchanged; the third-hop edit is outside its scope.</td></tr>
<tr><td>Transitive graph</td><td class="warn">changed</td><td>The stored path reaches the modified base_rate declaration.</td></tr>
<tr><td>Verified graph delta</td><td class="ok">exact match</td><td>Applying the delta to its correct base reproduces the full current graph bytes.</td></tr>
<tr><td>Unrelated-file edit</td><td class="ok">fresh captured closure</td><td>The update contains {data['unrelated_payload_source_nodes']} source nodes; its graph and base handles remain explicit.</td></tr>
</tbody></table></section>
<section><h2>Current evidence actually delivered</h2><p>The source below is the real budgeted update. The full graph stays in the local store behind its handle. This update requires the identified base; it is not a standalone full-context claim.</p>
<details><summary>Inspect all {data['model_payload_bytes']:,} UTF-8 bytes</summary><pre><code>{escape(records['model_payload']['rendered'])}</code></pre></details></section>
<section><h2>Two deliberate limits</h2><div class="twocol"><div>
<h3 class="warn">A runtime name cannot be resolved</h3><p>The next revision calls <code>configured_rate()</code>, whose binding is unavailable.
The payload retains source, reports {data['dynamic_frontier_count']} unresolved frontier item(s), and sets <code>complete=false</code>.</p>
<pre><code>{escape(dynamic_reasons)}</code></pre></div><div><h3 class="warn">A 300-byte allowance cannot carry the evidence</h3>
<p>The small-budget check reports <code>{escape(data['tiny_budget']['status'])}</code>, consumes {data['tiny_budget']['consumed']} bytes and sets <code>complete=false</code>. It never truncates a declaration or labels omitted evidence complete.</p></div></div></section>
<section><h2>Reproduce and inspect</h2><pre><code>python scripts/demo_graph.py
# Open docs/assets/graph-demo.html
# Generated graphs, delta and payloads: work/graph-demo/artifacts/</code></pre>
<details><summary>Actual demonstration receipt</summary><pre><code>{json_view(data)}</code></pre></details></section>
<div class="notice">Source identity and payload delivery are separate from runtime behavior. A complete static closure does not prove that an answer is correct, that Python runtime dependencies are complete, or that a model forgot earlier context.</div>
<footer>Generated by scripts/demo_graph.py from the actual saved graphs and payloads. No network assets, tracking, scripts, personal names or host paths are embedded. All fixture revisions and rate values are synthetic.</footer>
</main></body></html>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, default=PROJECT / "work/graph-demo")
    parser.add_argument("--output", type=Path, default=PROJECT / "docs/assets/graph-demo.html")
    args = parser.parse_args()
    records = execute_demo(args.work)
    artifact_dir = args.work / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    for name, value in records.items():
        (artifact_dir / f"{name}.json").write_text(
            json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    output = report(records)
    if str(Path.home()) in output or str(PROJECT) in output:
        raise RuntimeError("private host path unexpectedly entered the public demo")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(output, encoding="utf-8")
    print(json.dumps(records["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
