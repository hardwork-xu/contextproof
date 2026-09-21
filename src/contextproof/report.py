"""Self-contained, escaped HTML evidence report; no external assets or requests."""

from html import escape
import json

from .session import validate_context


def render_report(context, assessment):
    validate_context(context)
    bundle = context["bundle"]
    if assessment.get("context_id") != context["id"]:
        raise ValueError("assessment belongs to a different context")
    source = {row["entry_id"]: row for row in assessment["source"]["results"]}
    dependency = {row["entry_id"]: row for row in assessment["dependencies"]["results"]}
    cards = []
    for entry in bundle["entries"]:
        status = source.get(entry["id"], {}).get("status", "unresolved")
        dep_status = dependency.get(entry["id"], {}).get("status", "unresolved")
        location = f"{entry['path']}:{entry['start_line']}–{entry['end_line']}"
        details = {"source": source.get(entry["id"]),
                   "dependency": dependency.get(entry["id"])}
        cards.append(f'''<article data-status="{escape(status)} {escape(dep_status)}">
<div class="card-top"><strong>{escape(location)}</strong>
<span>source: <b class="{escape(status)}">{escape(status)}</b> · dependencies:
<b class="{escape(dep_status)}">{escape(dep_status)}</b></span></div>
<h2>{escape(entry['symbol'])}</h2><pre><code>{escape(entry['text'])}</code></pre>
<details><summary>Verification evidence</summary><pre>{escape(json.dumps(details, indent=2, ensure_ascii=False))}</pre></details>
</article>''')
    body = "\n".join(cards) or "<article>No source evidence was retrieved.</article>"
    source_summary = escape(json.dumps(assessment["source"]["summary"], ensure_ascii=False))
    dep_summary = escape(json.dumps(assessment["dependencies"]["summary"], ensure_ascii=False))
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>ContextProof · Evidence report</title><style>
:root{{color-scheme:dark;--bg:#10151d;--panel:#19212d;--muted:#b0bdce;--accent:#8dd8c0;--border:#354254}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:#eef4fc;font:16px/1.6 system-ui,sans-serif}}
main{{max-width:1100px;margin:auto;padding:48px 24px 70px}}header{{border-bottom:1px solid var(--border);padding-bottom:30px}}
.eyebrow{{text-transform:uppercase;letter-spacing:.18em;color:var(--accent);font-size:13px}}h1{{font-size:clamp(32px,5vw,52px);line-height:1.15;margin:12px 0}}
h2{{font-size:20px;margin:16px 0}}p{{color:var(--muted)}}.metrics{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin:28px 0}}
.metric,article{{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:22px}}.metric b{{display:block;font-size:24px;overflow-wrap:anywhere}}.metric span{{color:var(--muted);font-size:13px}}
.toolbar{{display:flex;gap:12px;margin:30px 0 18px}}input,select{{background:var(--panel);color:inherit;border:1px solid var(--border);border-radius:8px;padding:12px;font:inherit}}input{{flex:1;min-width:0}}
article{{margin-bottom:18px}}.card-top{{display:flex;gap:10px;justify-content:space-between;flex-wrap:wrap;font-size:13px}}
.card-top strong{{overflow-wrap:anywhere}}pre{{overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;background:#111823;border-radius:8px;padding:16px;font:13px/1.6 ui-monospace,monospace}}
summary{{cursor:pointer;color:var(--muted)}}.valid,.unchanged{{color:#8dd8c0}}.modified,.changed,.deleted,.missing,.invalid{{color:#ffae9f}}.relocated,.unresolved,.ambiguous{{color:#ead28c}}
footer{{font-size:12px;color:var(--muted);overflow-wrap:anywhere;border-top:1px solid var(--border);margin-top:32px;padding-top:18px}}[hidden]{{display:none}}
@media(max-width:650px){{.metrics{{grid-template-columns:1fr}}.toolbar{{flex-direction:column}}}}
</style></head><body><main><header><div class="eyebrow">ContextProof / local evidence</div>
<h1>What changed since the agent read this code?</h1>
<p>{escape(bundle['query'])}</p></header>
<section class="metrics"><div class="metric"><span>Recommended next action</span><b>{escape(assessment['recommendation'])}</b></div>
<div class="metric"><span>Source entries</span><b>{len(bundle['entries'])}</b></div>
<div class="metric"><span>Rendered context / {escape(bundle['budget_unit'])}</span><b>{escape(str(bundle['consumed']))} / {escape(str(bundle['budget']))}</b></div></section>
<p>Source: {source_summary}<br>Dependencies: {dep_summary}</p>
<p>Measured against a source snapshot when this report was generated. Unchanged text and direct static witnesses do not prove unchanged behavior or complete dependency coverage.</p>
<div class="toolbar"><input id="query" aria-label="Filter evidence" placeholder="Filter paths, symbols, or code…">
<select id="status" aria-label="Filter by status"><option value="">All evidence</option><option value="changed">Changed dependencies</option><option value="relocated">Relocated</option><option value="unresolved">Unresolved</option><option value="valid">Valid source</option><option value="modified">Modified source</option><option value="invalid">Invalid</option><option value="missing">Missing dependency</option><option value="ambiguous">Ambiguous</option></select></div>
<section id="evidence">{body}</section><footer>Context {escape(context['id'])}<br>Snapshot {escape(bundle['snapshot_id'])}<br>
The budget covers rendered source context. Dependency sidecars, this HTML report, and transport wrappers are outside that budget. No external assets or network requests.</footer></main>
<script>const q=document.getElementById('query'),s=document.getElementById('status');function filter(){{for(const card of document.querySelectorAll('article')){{card.hidden=!(card.textContent.toLowerCase().includes(q.value.toLowerCase())&&(!s.value||(card.dataset.status||'').split(' ').includes(s.value)));}}}}q.addEventListener('input',filter);s.addEventListener('change',filter);</script></body></html>'''
