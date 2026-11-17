# dbt-chaos

**Vecture open-source R&D: engineer adverse data conditions, prove whether transformations remain correct, and measure tradeoffs.**

Status: experimental v0.2. The framework is synthetic-only and makes no claim to exercise every possible real-world fault.

## What is actually implemented?

- A versioned, seed-independent JSON replay format with event IDs, source versions, logical timestamps, amounts in integer cents, and CDC tombstones.
- Twenty executable reproducible fault recipes across temporal, delivery, CDC, validation, scale and execution scheduling categories, with twelve additional categories clearly marked *planned*.
- Deterministic compound-fault generation (up to three operators), stable independent source-version business oracle, replay, and bounded failure minimization.
- Six comparison strategies: strict and inclusive timestamp watermarks, bounded lookback, ingestion-offset processing, source-version CDC, full refresh.
- Transparent model-screening metrics: silent corruption, detection, domain coverage, processed work units and a workload-specific score.
- Independent real dbt Core and DuckDB integration, real dbt test outcomes, reference full refresh, bounded benchmark runner, and separate real-evidence scoring.
- The original ten-case dbt benchmark retained under `benchmarks/legacy`.

## Quick start — no warehouse or API credentials

Python 3.10 or newer:

```bash
python -m pip install -e .
dbt-chaos faults
dbt-chaos generate --seed 20261117 --count 100 --out campaign
dbt-chaos bench --seed 20261117 --count 100 --out scores.json
dbt-chaos replay campaign/0001.json --strategy strict
dbt-chaos minimize campaign/0001.json --strategy strict --out minimized.json
```

**Important:** `bench` reports `python_model_screen`, not actual dbt execution.

To confirm with real dbt and a fresh, disposable DuckDB warehouse:

```bash
python -m pip install -e '.[dbt]'
dbt-chaos verify-dbt campaign/0001.json --strategy strict --out result.json
dbt-chaos bench-dbt --count 3 --strategies strict,offset,full --out verified.json
```

The real benchmark has a default maximum of 12 pipeline/case combinations and a 900-second scheduling budget; each dbt subprocess has a 100-second timeout. A GitHub Actions job also has a hard timeout.

## Interpreting results

The score is `100 × (1 - silent fault checkpoints / all evaluated fault checkpoints)`. An existing test alert and a model mismatch are recorded separately. An interrupted or invalid experiment is **not** a pass. The absolute score is workload-specific; it is not a probability of real failures. Equal case manifests are required for fair comparisons.

See [the experimental methodology](docs/METHODOLOGY.md). The original experiment can be inspected in [the legacy benchmark](benchmarks/legacy/README.md), and its CI is tracked in GitHub Actions.

## Safety and engineering constraints

All inputs are synthetic. Real dbt execution creates its own throwaway local DuckDB database and project, uses an allowlisted environment, and never accepts an external profile, customer SQL or production connection. No arbitrary server failures or system-level network faults are injected. Public CI uses fresh GitHub-hosted runners, **not** our private persistent Oracle VM. All job permissions are read-only.

## Research gaps

Multi-table relationship faults, transaction interruption and concurrency, true source-delivery deadline reconciliation, schema evolution, SQL-level mutation, cross-adapter Fabric/Databricks parity, financial-domain oracles, and cost measurement remain future research. These are not advertised as verified capabilities.

## Project

Copyright 2026 Vecture. Apache-2.0. Independent open-source research, not affiliated with dbt Labs or Netflix.
