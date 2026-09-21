# Direct dependency witness benchmark

Controlled static source transformations, with expected labels specified independently in `benchmarks/dependency_cases.py`. Repository fixture code is never executed.

- Correct declared statuses: **34/34**.
- Explicitly stale cases: **12**; accepted as fresh by dependency verification: **0**; still usable under exact-text-only verification: **11**.
- Unresolved cases: **12**; accepted as fresh: **0**.
- Repetitions per measured operation: **7**. Medians below include a complete safe source scan; indexing and fixture setup are excluded.
- Median serialized sidecar: **1292 bytes**, an additional **1.75×** the original rendered bundle. The sidecar is out of band and is not included in that bundle's model-context budget.

## Per-case results

| Case | Expected | Observed | Exact text usable | Capture ms | Dependency verify ms | Sidecar bytes |
| --- | --- | --- | --- | ---: | ---: | ---: |
| same_local_helper | unchanged | unchanged | true | 0.436 | 0.419 | 1292 |
| changed_local_helper | changed | changed | true | 0.403 | 0.393 | 1292 |
| unrelated_file | unchanged | unchanged | true | 0.615 | 0.581 | 1292 |
| unrelated_definition | unchanged | unchanged | true | 0.487 | 0.402 | 1292 |
| line_insertion | unchanged | unchanged | true | 0.457 | 0.414 | 1292 |
| imported_change | changed | changed | true | 0.641 | 0.643 | 1494 |
| from_alias | changed | changed | true | 0.688 | 0.626 | 1484 |
| module_alias | unchanged | unchanged | true | 0.589 | 0.611 | 1486 |
| module_attribute | changed | changed | true | 0.646 | 0.672 | 1499 |
| alias_retarget_identical_definition | changed | changed | true | 0.919 | 0.788 | 1494 |
| deleted_dependency_file | missing | missing | true | 0.690 | 0.392 | 1494 |
| deleted_definition | missing | missing | true | 0.590 | 0.583 | 1494 |
| duplicate_definition | unresolved | unresolved | true | 0.413 | 0.371 | 1062 |
| new_duplicate_definition | unresolved | unresolved | true | 0.400 | 0.382 | 1292 |
| external_import | unresolved | unresolved | true | 0.483 | 0.403 | 1074 |
| callable_parameter | unresolved | unresolved | true | 0.417 | 0.405 | 1111 |
| dynamic_method | unresolved | unresolved | true | 0.424 | 0.389 | 1104 |
| call_returned_callable | unresolved | unresolved | true | 0.488 | 0.426 | 1419 |
| changed_called_expression | changed | changed | false | 0.421 | 0.421 | 1292 |
| constant_change | changed | changed | true | 0.418 | 0.390 | 1269 |
| imported_constant | changed | changed | true | 0.767 | 0.634 | 1471 |
| recursive_call | unchanged | unchanged | true | 0.510 | 0.453 | 1340 |
| import_cycle | unchanged | unchanged | true | 0.604 | 0.644 | 1502 |
| reexport_cycle | unresolved | unresolved | true | 0.768 | 0.731 | 1061 |
| relative_import | changed | changed | true | 0.880 | 0.984 | 1507 |
| src_layout | unchanged | unchanged | true | 1.090 | 1.040 | 1506 |
| ambiguous_module | unresolved | unresolved | true | 1.366 | 1.125 | 1064 |
| wildcard_import | unresolved | unresolved | true | 0.828 | 0.566 | 1076 |
| local_shadow | unresolved | unresolved | true | 0.468 | 0.449 | 1105 |
| one_hop_boundary | unchanged | unchanged | true | 0.492 | 0.476 | 1297 |
| syntax_error_dependency | unresolved | unresolved | true | 0.617 | 0.667 | 1494 |
| no_dependencies | unchanged | unchanged | true | 0.433 | 0.382 | 967 |
| selected_external_import | unresolved | unresolved | true | 0.396 | 0.364 | 1058 |
| selected_from_import | changed | changed | true | 0.633 | 0.600 | 1484 |

## Source scan scaling

Each fixture selects one function with one direct imported helper; unrelated files increase. These small synthetic modules measure source scan/parse overhead, not real-world repository complexity.

| Python files | Source bytes | Capture ms | Dependency verify ms | Exact-text verify ms |
| ---: | ---: | ---: | ---: | ---: |
| 10 | 313 | 2.258 | 2.265 | 1.916 |
| 100 | 3009 | 20.147 | 22.174 | 19.090 |
| 500 | 15805 | 104.040 | 103.338 | 94.229 |

## Interpretation and reproducibility

`unchanged` is a bounded one-hop source/binding claim. The `one_hop_boundary` case intentionally leaves a grandchild edit undetected. Dynamic, external, ambiguous and unsupported resolution abstains. Perfect agreement on these designed cases is not an unbiased semantic-accuracy estimate and does not establish coding-agent task success.

Run `python scripts/run_dependency_benchmarks.py --repeats 7`. JSON includes all timing samples, fixture and implementation SHA-256 values, deterministic quality digest, payload bytes and environment. Wall-clock measurements vary by host and run; status/quality results should reproduce.

Generated: 2026-09-21T09:30:09.740229+00:00. Python 3.12.14; Darwin arm64.

Quality SHA-256: `f81343759c921f13be1d7482a5c44b1c3dc95d1602ec82676136e08f6dd11d68`.
