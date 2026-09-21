# Posthoc source-scope sensitivity

Post-result corpus-scope sensitivity motivated by dateutil embedded-test corpus exits. Searches the same300 frozen before-only samples against all policy-eligible Python files in the same frozen archives. The primary preregistered corpus, samples, labels and results remain unchanged. Not a new holdout test or semantic evaluation.

**23/300 reference labels change when the source corpus expands.** Primary status counts: {'deleted': 29, 'modified': 80, 'relocated': 150, 'valid': 41}. Full-scope counts: {'deleted': 6, 'modified': 80, 'relocated': 173, 'valid': 41}.

Engine/reference status agreement in the expanded scope: 1.000; mismatches: 0.

All23 dateutil snippets labeled `deleted` in the primary scope are embedded tests that move outside the declared library prefixes. They are exact unique relocations under the broader scope. This is a source-boundary effect, not upstream source deletion. The primary report must be interpreted within its frozen corpus.

| Method | TP | FP | TN | FN | Accuracy |
| --- | ---: | ---: | ---: | ---: | ---: |
| path_exists_and_line_range | 155 | 79 | 7 | 59 | 0.540 |
| path_line_exact | 41 | 0 | 86 | 173 | 0.423 |
| file_hash | 24 | 0 | 86 | 190 | 0.367 |
| contextproof | 214 | 0 | 86 | 0 | 1.000 |

Reproduce with `python -m benchmarks.v1.scope_sensitivity` after running the primary study. Archives are rechecked and staged under ignored `work/v1-drift/sensitivity/`; primary source directories are untouched. Full manifests, annotations, coordinates and predictions are in sibling JSON artifacts. All-Python scope still excludes non-Python files and policy-excluded files. This remains automated contract agreement, not human or semantic ground truth.
