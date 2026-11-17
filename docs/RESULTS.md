# Reproduced benchmark results — 17 November 2026

## Full 20 × 6 real dbt matrix — 17 November 2026

**120/120 actual dbt/DuckDB scenario–strategy combinations executed successfully** across ten independent public hosted runner shards. [Primary evidence: GitHub Actions run #44039321822](https://github.com/mhatipog/dbt-chaos/actions/runs/44039321822), source commit `1eae541446896156496ca0cbb2574f7d31a266bc`. Machine-readable [aggregated results](results/full-matrix-2026-11-17.json) are transcribed and summed from each shard's public job log.

| Strategy | Correct checkpoints | Silent mismatches | Non-silent score | dbt invocations |
|---|---:|---:|---:|---:|
| Full refresh | 20/20 | 0 | 100% | 128 |
| Source-version CDC | 20/20 | 0 | 100% | 128 |
| Ingestion offset | 20/20 | 0 | 100% | 128 |
| Rolling lookback | 17/20 | 3 | 85% | 128 |
| Inclusive timestamp watermark | 15/20 | 5 | 75% | 128 |
| Strict timestamp watermark | 13/20 | 7 | 65% | 128 |

Across the 120 combinations there were 15 incorrect checkpoints, **all undetected by the four configured basic dbt tests**, and zero unexpected execution errors. The two deliberately invalid-data controls (negative and null amounts) triggered quality test alerts in each strategy. The source-version, offset and full-refresh approaches preserved correctness for all **tested** individual faults. Rolling lookback was better than strict global watermark under this specific input set but remained vulnerable to some backfills/future-time cases.

The aggregate contains 768 executed dbt commands. Cumulative wall time per strategy (around 459–466 seconds across 20 cases) includes repeated dbt process startups, tests and reference refreshes; **do not use it as a performance-cost ranking**.

All values are from a fixed synthetic workload, one snapshot per fault case, seed 20261117. These counts are *not* general incident frequencies, confidence intervals or proof that a given design handles all late arrivals, deletes, schema drift or production concurrency. Only 20 individual fault recipes are measured here; compound fault combinations require separate real-db testing.

Reproduce the individual two-scenario shards using the [full-matrix workflow](https://github.com/mhatipog/dbt-chaos/blob/main/.github/workflows/full-matrix.yml) or with `dbt-chaos bench-dbt --seed 20261117 --start 0 --count 2 --strategies strict,inclusive,lookback,offset,cdc,full --out shard.json`. The runnable HTML report can be generated with `dbt-chaos report docs/results/full-matrix-2026-11-17.json --out matrix.html`.

---

**Evidence:** [Public GitHub Actions real benchmark run #44038297377](https://github.com/mhatipog/dbt-chaos/actions/runs/44038297377), conclusion **success**. Execution on GitHub-hosted Ubuntu x64 with pinned dbt-core 1.10.15, dbt-duckdb 1.10.1 and DuckDB 1.4.4.

## Real dbt comparison (synthetic)

| Strategy | Cases | Wrong checkpoints | Silent wrong checkpoints | Non-silent score | dbt invocations | Wall time in cases |
|---|---:|---:|---:|---:|---:|---:|
| Full refresh | 3 | 0 | 0 | 100% | 18 | 48.343 s |
| Ingestion offset | 3 | 0 | 0 | 100% | 18 | 48.268 s |
| Strict timestamp watermark | 3 | 2 | 2 | 33.33% | 18 | 49.748 s |

Three scenarios: in-order arrival, late-arriving distinct key, timestamp collision at the global watermark. Every candidate was checked against independent source-version truth and a full-refresh dbt reference. Both injected silent failures were missed by the configured basic dbt data tests. All nine strategy/case executions completed without infrastructure errors.

**Interpretation:** This demonstrates a known weakness of an intentionally simplistic global timestamp-watermark SQL pattern. It is **not** a dbt framework defect or a universal comparison of warehouse techniques. The observed differences are synthetic, not real financial losses. The scores are specific to these three scenarios and cannot estimate reliability in production.

To reproduce with matching seed and versions:

```bash
python -m pip install -e '.[dbt]'
dbt-chaos bench-dbt --seed 20261117 --count 3 --strategies strict,offset,full --max-executions 9 --out verified.json
```

## Regression baseline

The imported legacy ten-case dbt experiment also passed on public runners: [successful baseline](https://github.com/mhatipog/dbt-chaos/actions/runs/44037284300). It includes four instances of silent model corruption, one negative-input detection control and repaired controls.

## Evidence levels

1. **Actual dbt** — confirmed by executed SQL, dbt tests, independent truth and structured run results.
2. **Python model screen** — a fast approximation for scenario discovery, not proof that any dbt adapter behaves identically.
3. **Planned** — named fault domains with no implementation or experimental evidence yet.

Do not combine these as though they were a single experimentally verified coverage percentage.
