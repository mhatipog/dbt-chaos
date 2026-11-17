# Reproduced benchmark results — 17 November 2026

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
