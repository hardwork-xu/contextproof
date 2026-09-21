# Versioned graph replay

Actual first-parent upstream commits via hash-pinned archives. Graph construction and AST cache only; Git object transport performance is not measured.

The protocol was frozen after exploratory graph inspection. Original source-study splits are retained as metadata; this is not a new independent holdout.

Checked 450 saved anchors; 450 lossless delta reconstructions matched canonical full graphs.

15 adjacent transitions; status counts `{'changed': 32, 'unresolved': 418}`.

| Repository / transition | Changed library Python files | Full shared-cache median s | Incremental median s | Incremental parse misses |
|---|---:|---:|---:|---:|
| requests / 0 | 0 | 0.6497 | 0.6258 | 0 |
| requests / 1 | 0 | 0.6950 | 0.6765 | 0 |
| requests / 2 | 0 | 0.6613 | 0.6283 | 0 |
| requests / 3 | 1 | 0.6341 | 0.6286 | 1 |
| requests / 4 | 1 | 0.6897 | 0.7112 | 1 |
| httpx / 0 | 2 | 2.0992 | 1.9134 | 2 |
| httpx / 1 | 1 | 1.8911 | 1.8782 | 1 |
| httpx / 2 | 1 | 1.9438 | 1.9330 | 1 |
| httpx / 3 | 1 | 1.8862 | 1.8328 | 1 |
| httpx / 4 | 1 | 1.8664 | 1.8401 | 1 |
| packaging / 0 | 0 | 0.8147 | 0.8024 | 0 |
| packaging / 1 | 1 | 0.8422 | 0.8090 | 1 |
| packaging / 2 | 1 | 0.8646 | 0.8084 | 1 |
| packaging / 3 | 0 | 0.8262 | 0.8128 | 0 |
| packaging / 4 | 1 | 0.8202 | 0.8275 | 1 |

For the default memory condition, summed batch medians are 17.1846s full shared-cache and 16.7281s before→after replay (2.7% faster). Three repetitions are descriptive; small timing differences are not a demonstrated general speedup. The negative persistent-AST phase remains separately published.
