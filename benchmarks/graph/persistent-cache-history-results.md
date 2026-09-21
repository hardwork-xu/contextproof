# Versioned graph replay

Actual first-parent upstream commits via hash-pinned archives. Graph construction and AST cache only; Git object transport performance is not measured.

The protocol was frozen after exploratory graph inspection. Original source-study splits are retained as metadata; this is not a new independent holdout.

Checked 450 saved anchors; 450 lossless delta reconstructions matched canonical full graphs.

15 adjacent transitions; status counts `{'changed': 32, 'unresolved': 418}`.

| Repository / transition | Changed library Python files | Full shared-cache median s | Incremental median s | Incremental parse misses |
|---|---:|---:|---:|---:|
| requests / 0 | 0 | 0.6259 | 0.6050 | 0 |
| requests / 1 | 0 | 0.6321 | 0.6060 | 0 |
| requests / 2 | 0 | 0.6199 | 0.6141 | 0 |
| requests / 3 | 1 | 0.6327 | 0.6285 | 1 |
| requests / 4 | 1 | 0.6702 | 0.6476 | 1 |
| httpx / 0 | 2 | 1.8686 | 1.8750 | 2 |
| httpx / 1 | 1 | 1.8320 | 1.8150 | 1 |
| httpx / 2 | 1 | 1.8533 | 1.8354 | 1 |
| httpx / 3 | 1 | 1.8519 | 1.8361 | 1 |
| httpx / 4 | 1 | 1.8755 | 1.8252 | 1 |
| packaging / 0 | 0 | 0.8035 | 0.7898 | 0 |
| packaging / 1 | 1 | 0.8097 | 0.7998 | 1 |
| packaging / 2 | 1 | 0.8091 | 0.8072 | 1 |
| packaging / 3 | 0 | 0.8022 | 0.7925 | 0 |
| packaging / 4 | 1 | 0.8101 | 0.7901 | 1 |
