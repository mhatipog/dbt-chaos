# dbt-chaos — Vecture research

Open-source chaos engineering for data transformations. Reproducible fault campaigns, independent correctness checks, resilience measurement, and real dbt execution. Apache-2.0.

## Proven baseline

The `benchmarks/legacy` suite is a copied, previously verified dbt-core + dbt-duckdb experiment from Vecture's private lab. Ten deterministic synthetic scenarios exercise a deliberately fragile timestamp-watermark model, its repaired controls, ordinary dbt tests, and a full-refresh comparator. These cases demonstrate **model** errors, not defects in dbt Core.

Run:

    cd benchmarks/legacy
    python3 -m pip install -r requirements.txt
    python3 -m unittest -v
    python3 run.py --output results.json

No production connections or external data are used. This repository intentionally uses GitHub-hosted public runners, never the persistent Oracle VM. The new generalized framework is developed alongside the verified baseline; planned fault categories must not be misrepresented as implemented or confirmed.
