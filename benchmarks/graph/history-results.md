# Versioned graph replay

Actual first-parent upstream commits via hash-pinned archives. Graph construction and AST cache only; Git object transport performance is not measured.

The protocol was frozen after exploratory graph inspection. Original source-study splits are retained as metadata; this is not a new independent holdout.

Checked 450 saved anchors; 450 lossless delta reconstructions matched canonical full graphs.

15 adjacent transitions; status counts `{'changed': 32, 'unresolved': 418}`.

| Repository / transition | Changed library Python files | Full shared-cache median s | Incremental median s | Incremental parse misses |
|---|---:|---:|---:|---:|
| requests / 0 | 0 | 0.7678 | 0.7426 | 0 |
| requests / 1 | 0 | 0.7548 | 0.7237 | 0 |
| requests / 2 | 0 | 0.7591 | 0.7590 | 0 |
| requests / 3 | 1 | 0.7726 | 0.7564 | 1 |
| requests / 4 | 1 | 0.8382 | 0.8190 | 1 |
| httpx / 0 | 2 | 2.3852 | 2.3619 | 2 |
| httpx / 1 | 1 | 2.7599 | 2.6958 | 1 |
| httpx / 2 | 1 | 2.3583 | 2.3722 | 1 |
| httpx / 3 | 1 | 2.3473 | 2.4259 | 1 |
| httpx / 4 | 1 | 2.6020 | 2.5531 | 1 |
| packaging / 0 | 0 | 1.1637 | 1.1085 | 0 |
| packaging / 1 | 1 | 1.1672 | 1.1144 | 1 |
| packaging / 2 | 1 | 0.9913 | 0.9903 | 1 |
| packaging / 3 | 0 | 0.9995 | 0.9968 | 0 |
| packaging / 4 | 1 | 1.0102 | 0.9908 | 1 |

Conventional gzip comparison (level 9, mtime 0, each message compressed independently): full graphs 8,127,596 bytes; field deltas 844,340 bytes. Compressed deltas are smaller in 445/450 cases. Matching-base availability is required only for deltas; no cross-message compression dictionary or base-transfer cost is included.

For the default memory condition, summed batch medians are 21.6770s full shared-cache and 21.4105s before→after replay (1.2% faster). Three repetitions are descriptive; small timing differences are not a demonstrated general speedup. The negative persistent-AST phase remains separately published.
