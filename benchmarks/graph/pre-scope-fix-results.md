# Versioned graph replay

Observed exact source and binding identity only. No semantic accuracy, algorithm novelty, downstream task success, or billed-token savings claim.

The protocol was frozen after exploratory graph inspection. Original source-study splits are retained as metadata; this is not a new independent holdout.

Checked 300 saved anchors; 300 lossless delta reconstructions matched canonical full graphs.

Depth 4 added 5 changed/missing observations over depth 1; 5 are changed descendants behind unchanged enclosing roots.

Status counts at depth 1: `{'changed': 130, 'missing': 68, 'unchanged': 1, 'unresolved': 101}`. At depth 4: `{'changed': 135, 'missing': 68, 'unchanged': 1, 'unresolved': 96}`.

Independent per-anchor full artifacts total 24,271,141 bytes; sealed field deltas total 9,642,246 bytes. Deltas require the matching base. These are serialized UTF-8 bytes, not model tokens or conversation savings.

| Payload at 16,000 UTF-8 bytes | Complete / incomplete / budget too small | Emitted bytes | Omitted node occurrences |
|---|---|---:|---:|
| full | {'complete': 1, 'incomplete': 299} | 1,718,863 | 2,201 |
| update | {'budget_too_small': 1, 'complete': 1, 'incomplete': 298} | 1,967,366 | 2,234 |

Baseline observations: revision-change invalidation rejects 300/300 anchors; anchor file hashes change for 276/300. Original exact-source statuses: `{'deleted': 29, 'modified': 80, 'relocated': 150, 'valid': 41}`. Original direct-witness statuses: `{'changed': 105, 'missing': 68, 'unchanged': 22, 'unresolved': 105}`. These contracts differ; these counts are not semantic accuracy or false-positive labels.

Incomplete or empty budget-failure payloads are not evidence of equivalent delivery or a successful context refresh. Frontier uncertainty remains visible.

| Repository | Full shared-cache median s | Incremental median s | Full parse misses | Incremental parse misses |
|---|---:|---:|---:|---:|
| attrs | 1.0218 | 1.0537 | 19 | 12 |
| babel | 2.2156 | 2.2154 | 27 | 24 |
| dateutil | 0.8954 | 0.8517 | 17 | 17 |
| filelock | 0.1736 | 0.1842 | 8 | 5 |
| httpx | 2.0289 | 1.8958 | 23 | 23 |
| packaging | 1.2475 | 1.1405 | 16 | 15 |
| pluggy | 0.3449 | 0.3424 | 7 | 7 |
| pydantic | 6.1774 | 6.2044 | 103 | 76 |
| requests | 0.5364 | 0.5829 | 18 | 18 |
| urllib3 | 1.9751 | 1.7389 | 35 | 27 |

Both main timing conditions share one AST cache across the same 30 current-version queries. The full baseline starts that cache empty. The final default-memory condition begins with previous-version process-local ASTs; the separate persistent-AST diagnostic includes JSON persistence writes and remains in JSON and the preserved diagnostic report. Source loading/hashing and previous-cache priming are excluded. AST caches are trusted local optimizations; catalogs and resolutions are rebuilt. Raw full, stable-warm, incremental repetitions and the earlier per-anchor-cold diagnostic are retained in JSON. Small or negative timing differences are reported unchanged.

Additional observed descendant paths (all selected by the stated condition, not semantic labels):

- babel `to_python`: `to_python → PluralRule → _Parser → tokenize_rule`.
- babel `DateTimeFormat.format_month`: `DateTimeFormat.format_month → get_month_names → Locale → parse_locale`.
- httpx `LocalProtocolError`: `LocalProtocolError → ProtocolError → TransportError → RequestError`.
- httpx `ProxyError`: `ProxyError → TransportError → RequestError`.
- pydantic `schema`: `schema → model_process_schema → ModelField → find_validators`.

For the default memory condition, summed batch medians are 16.6166s full shared-cache and 16.2099s before→after replay (2.4% faster). Three repetitions are descriptive; small timing differences are not a demonstrated general speedup. The negative persistent-AST phase remains separately published.
