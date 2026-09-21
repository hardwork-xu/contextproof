# Preserved initial renderer diagnostic

This initial renderer often exhausted the 16,000-byte budget on metadata. Its failures are retained; final compact-renderer results are reported separately. The original renderer source was reconstructed from the applied patch and is replay-checked against all initial payload metrics.

# Versioned graph replay

Observed exact source and binding identity only. No semantic accuracy, algorithm novelty, downstream task success, or billed-token savings claim.

The protocol was frozen after exploratory graph inspection. Original source-study splits are retained as metadata; this is not a new independent holdout.

Checked 300 saved anchors; 300 lossless delta reconstructions matched canonical full graphs.

Depth 4 added 5 changed/missing observations over depth 1; 5 are changed descendants behind unchanged enclosing roots.

Status counts at depth 1: `{'changed': 130, 'missing': 68, 'unchanged': 1, 'unresolved': 101}`. At depth 4: `{'changed': 135, 'missing': 68, 'unchanged': 1, 'unresolved': 96}`.

Independent per-anchor full artifacts total 24,271,141 bytes; sealed field deltas total 9,642,246 bytes. Deltas require the matching base. These are serialized UTF-8 bytes, not model tokens or conversation savings.

| Payload at 16,000 UTF-8 bytes | Complete / incomplete / budget too small | Emitted bytes | Omitted node occurrences |
|---|---|---:|---:|
| full | {'budget_too_small': 27, 'complete': 1, 'incomplete': 272} | 1,849,861 | 3,005 |
| update | {'budget_too_small': 114, 'complete': 1, 'incomplete': 185} | 1,212,579 | 3,178 |

Incomplete or empty budget-failure payloads are not evidence of equivalent delivery or a successful context refresh. Frontier uncertainty remains visible.

| Repository | Cold after median s | Incremental after median s | Cold parse misses | Incremental parse misses |
|---|---:|---:|---:|---:|
| attrs | 1.4467 | 1.1083 | 570 | 12 |
| babel | 3.5901 | 2.3871 | 810 | 24 |
| dateutil | 1.7519 | 1.0157 | 510 | 17 |
| filelock | 0.2593 | 0.1839 | 240 | 5 |
| httpx | 2.9175 | 1.9854 | 690 | 23 |
| packaging | 1.6801 | 1.1153 | 480 | 15 |
| pluggy | 0.4916 | 0.3588 | 210 | 7 |
| pydantic | 13.0614 | 6.9611 | 3090 | 76 |
| requests | 1.0108 | 0.5805 | 540 | 18 |
| urllib3 | 2.9501 | 1.8190 | 1050 | 27 |

Timings exclude source loading/hashing and compare graph construction. AST caches are trusted local optimizations; module catalogs and resolutions are rebuilt. Raw repetitions, before/warm measurements, duplicated source counts, and every sample outcome are in JSON.

Additional observed descendant paths (all selected by the stated condition, not semantic labels):

- babel `to_python`: `to_python → PluralRule → _Parser → tokenize_rule`.
- babel `DateTimeFormat.format_month`: `DateTimeFormat.format_month → get_month_names → Locale → parse_locale`.
- httpx `LocalProtocolError`: `LocalProtocolError → ProtocolError → TransportError → RequestError`.
- httpx `ProxyError`: `ProxyError → TransportError → RequestError`.
- pydantic `schema`: `schema → model_process_schema → ModelField → find_validators`.
