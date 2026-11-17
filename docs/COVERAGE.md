# Fault taxonomy, realized coverage and remaining gaps

## Executable synthetic operators (20)

| Domain | Supported operators |
|---|---|
| Temporal | late, same_time, future_poison |
| Historical | historical_update |
| Delivery | duplicate, out_of_order, stale_replay, split_batch, empty_batch |
| CDC | tombstone, replay_after_delete, reinsert, reverse_version, version_collision |
| Validation | negative_amount, null_amount |
| Execution scheduling | skipped_run |
| Scale | hot_key |
| Positive controls | normal, fresh_update |

These operators run in the **Python semantic screen**. The real dbt runner accepts the same serialized scenario format, but the complete operator/strategy matrix has not been experimentally executed.

The seeded campaign generator first covers all 20 individual fault operators, then all 190 unordered fault pairs when 210 scenarios are requested with --max-faults 2. Subsequent runs can compose up to three operators. Unit tests verify the planned pair count. The score report also exposes *realized* pair coverage for shorter runs. This does not constitute path, temporal parameter, cross-engine or all-real-world fault coverage.

## Catalogue only, NOT executable yet (12)

| Area | Missing experiment |
|---|---|
| Schema | schema_rename, type_narrowing |
| Relationships | missing_dimension, join_fanout |
| History | scd2_overlap |
| Transport | missing_delivery_deadline |
| Execution | transaction_crash, concurrent_writes |
| Business semantics | currency_shift, precision_loss |
| Scale | large_scale |
| Engines | cross_platform_parity |

## Next independent experimental milestones

- Source-delivery deadline and complete-vs-admitted input truth, with separate transport and model correctness.
- Multi-table relations and SCD2, including facts without dimensions, fanout, backfill and temporal joins.
- Crash/restart and isolation hooks solely in child processes and disposable databases; verify transaction guarantees rather than assuming them.
- Schema contract-driven migrations and intentionally incorrect types or units.
- Real dbt testing against PostgreSQL and qualified additional adapters.
- Adaptive workload search, fault parameter shrinking and independent negative controls.
- Performance benchmarks with non-trivial datasets and actual cloud billing evidence where lawful and free to test.

These are explicitly missing. No framework can promise exhaustiveness over every possible failure, SQL dialect or source system.
