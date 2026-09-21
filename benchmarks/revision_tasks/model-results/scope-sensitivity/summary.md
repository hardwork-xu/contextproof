# Post-freeze resolver-v2 sensitivity

All attempts are included. These are exact API-output predictions with shared upstream-derived source hints, not issue-resolution scores. See [the pre-model protocol](../../../../docs/REVISION_STUDY_PROTOCOL.md).

25 held-out probes, 25 change/control families, 4 repositories, 150 completions.

| Context | Exact | Changed | Controls | Wrong old answer | Invalid | Mean source bytes | Input tokens |
|---|---:|---:|---:|---:|---:|---:|---:|
| archex | 21/25 | 16/19 | 5/6 | 2 | 0 | 14402 | 252,611 |
| fresh_anchors | 24/25 | 18/19 | 6/6 | 1 | 0 | 4189 | 181,712 |
| fresh_bm25 | 24/25 | 18/19 | 6/6 | 1 | 0 | 15894 | 268,685 |
| graph_current | 24/25 | 18/19 | 6/6 | 1 | 0 | 12176 | 241,255 |
| no_context | 21/25 | 15/19 | 6/6 | 3 | 0 | 0 | 155,974 |
| stale_anchors | 8/25 | 2/19 | 6/6 | 16 | 0 | 4190 | 181,795 |

Input-token totals include the shared harness overhead. Source bytes include each condition's actual metadata. Cached usage, output tokens, request times and family/repository breakdowns are in summary.json. No monetary price or statistical superiority is inferred.

| Paired against graph_current | Graph only correct | Comparator only correct | Both correct | Both wrong |
|---|---:|---:|---:|---:|
| archex | 3 | 0 | 21 | 1 |
| fresh_anchors | 0 | 0 | 24 | 1 |
| fresh_bm25 | 1 | 1 | 23 | 0 |
| no_context | 3 | 0 | 21 | 1 |
| stale_anchors | 16 | 0 | 8 | 1 |

The primary comparator is fresh_anchors: both methods receive the same symbol hints. Fresh-versus-stale differences diagnose stale evidence and do not establish a unique graph benefit.

Only the 25 corrected graph contexts were rerun. All 125 comparator cells are reused from the original run. This is exploratory after the scope audit and partial original outcomes, not an untouched confirmatory holdout.
