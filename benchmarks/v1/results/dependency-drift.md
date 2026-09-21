# Dependency diagnostics on natural version drift

All frozen v1 drift samples, no selection by dependency outcome. Batch diagnostic bundle budget=250000 UTF-8 bytes; this is not a retrieval budget experiment. Source-text acceptance vs direct-static witness invalidation; additional flags are observations, not independently labeled correctness or semantic staleness.

Evaluated 300 frozen samples. Exact text remained recoverable for 191; the sidecar additionally flagged 65 as changed/missing and marked 104 as unresolved for review.

Of the additional flags, 35 concern the anchor itself (including file movement that the source-text verifier can relocate). Only 30 have an unchanged anchor and a changed/missing direct reference. Anchor flags must not be counted as detections of changed dependencies behind unchanged callers.

| Repository | Samples | Recoverable text | Additional flags | Anchor flags | Direct-reference flags | Needs review |
|---|---:|---:|---:|---:|---:|---:|
| attrs | 30 | 16 | 2 | 0 | 2 | 12 |
| babel | 30 | 27 | 7 | 0 | 7 | 19 |
| dateutil | 30 | 7 | 7 | 7 | 0 | 0 |
| filelock | 30 | 19 | 3 | 0 | 3 | 14 |
| httpx | 30 | 19 | 4 | 0 | 4 | 7 |
| packaging | 30 | 11 | 4 | 0 | 4 | 4 |
| pluggy | 30 | 26 | 7 | 0 | 7 | 18 |
| pydantic | 30 | 19 | 1 | 0 | 1 | 14 |
| requests | 30 | 28 | 28 | 28 | 0 | 0 |
| urllib3 | 30 | 19 | 2 | 0 | 2 | 16 |

Reference annotation in the drift study labels exact text, not dependency behavior. Therefore this experiment does not estimate true-positive dependency detection or over-invalidation in natural code. Labeled controlled cases provide those contract checks.

Three repeated per-repository capture/verify measurements and sidecar sizes are in [the raw report](dependency-drift.json). Sidecars are outside the source-context budget.
