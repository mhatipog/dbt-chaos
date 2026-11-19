# Declarative process contracts: business-truth chaos without hardcoded commerce

This is **process-contract v1**, implemented on the research branch
`research/good-intentions-handoff-20261119`. It is a **constrained
declarative DSL**, not a schema-inference agent or arbitrary user SQL.

The goal is to let a data engineer ask:

> When our platform receives plausible, well-intentioned but incorrect
> source changes, does it silently publish false business metrics,
> detect a problem, withhold correct records unnecessarily, or recover
> from independently verifiable evidence?

The original business truth is defined by an immutable process-event log,
**not** by the same corrupted source that the platform consumes.

## What has been implemented

Each JSON contract defines three independently configurable roles:

| Role | Example: procurement | Example: grants | Semantics |
|---|---|---|---|
| Party | `suppliers` | `beneficiaries` | Versioned entity and changing reporting dimension |
| Document | `invoices` | `grant_awards` | Versioned linked document, status, currency, date and limit |
| Money movement | `settlements` | `disbursements` | Versioned money events, sign/type, amount and document link |

The same engine interprets those contracts to produce:
- an immutable, ordered business event log (`party_created`,
  `document_opened`, `document_state`, `movement_recorded`,
  legitimate corrections and idempotent delivery retries);
- full clean source CSVs with legitimate history;
- a second, independently corrupted source snapshot;
- a **private** event-ledger business oracle that never reads the
  corrupted source;
- a separate source-implied oracle for measuring transformation versus
  upstream errors;
- actual SQLite execution of the source transformation as a third check;
- optional, **public** reference SQL and source-quality checks;
- a scored, platform-neutral published-output interface.

All generated data are synthetic and use integer cents. The contract is
validated and bounded. It cannot inject arbitrary Python, SQL expressions,
files, URLs, external connections or model-provided shell commands.

## Fastest example: procurement

From the research branch:

```bash
python -m pip install -e .

dbt-chaos contract-generate \
  --contract procurement \
  --seed 20261119 --fault rewrite_credit \
  --public-dir /tmp/dbt-chaos-procurement-public \
  --private-dir /tmp/dbt-chaos-procurement-private

dbt-chaos contract-reference \
  --public-dir /tmp/dbt-chaos-procurement-public \
  --output-dir /tmp/dbt-chaos-procurement-sql-results

dbt-chaos contract-probe \
  --public-dir /tmp/dbt-chaos-procurement-public \
  --out /tmp/dbt-chaos-probes.json

dbt-chaos contract-score \
  --public-dir /tmp/dbt-chaos-procurement-public \
  --answer-key /tmp/dbt-chaos-procurement-private/answer_key.json \
  --published-dir /tmp/dbt-chaos-procurement-sql-results \
  --out /tmp/dbt-chaos-assessment.json
```

All steps are free, offline and reproducible; SQLite is part of the Python
standard library. No dbt adapter, LLM model download, cloud warehouse or
production credentials are required. **`procurement` and `grants` are
bundled contract names** in the installed Python wheel; `--contract
path/to/your-contract.json` also works for a validated custom definition.
The public SQL files are generated automatically; `contract-probe` executes
their observable checks without the private ledger.

The clean reference result must match the ledger truth. In the
`rewrite_credit` scenario, the platform's SQL correctly computes
*the delivered but false input* and silently differs from the original
events by €20. This is an expected **negative control** for source-only
protections, not a benchmark result claiming SQLite is defective.

The optional `--fail-on-silent` flag of `contract-score` causes a
nonzero exit if any incorrect business groups remain exposed. Use it
for enforcing an agreed resilience policy in CI; omit it when deliberately
exploring a platform's current baseline weaknesses.

## Run the other domain

```bash
dbt-chaos contract-generate \
  --contract grants \
  --seed 20261119 --fault reclassify_party \
  --public-dir grants-public --private-dir grants-secret

dbt-chaos contract-reference \
  --public-dir grants-public --output-dir grants-reference

dbt-chaos contract-score \
  --public-dir grants-public \
  --answer-key grants-secret/answer_key.json \
  --published-dir grants-reference --out grants-score.json
```

A party-dimension reclassification can leave overall money totals
unchanged while shifting significant values between regions or cost
centres. This is why the evaluator uses **absolute per-group error**,
not merely net aggregate error.

## Bring your own data platform

Only deliver the **public** directory to an isolated environment. It
contains:

```text
public/
  contract.json                 # declared business relationships and invariants
  manifest.json                 # challenge identifier and SHA-256 checksums
  README.md
  inputs/clean/{three-contract-tables}.csv
  inputs/chaos/{three-contract-tables}.csv
  sql/reference_query.sql       # optional, source-only reference transformation
  sql/quality_checks.sql        # optional observable integrity probes
```

The two SQL files are provided as readable reference material. They are
not automatically installed as native dbt tests or security barriers.
SQL dialect adjustments may be needed for a particular warehouse. The
current reference adapter is **SQLite**.

The operator runs identical transformation logic on each input
snapshot, then exports whatever was actually published as two files:

```text
platform-output/
  clean.csv
  chaos.csv
```

Each CSV must have the exact columns:

```csv
period,group,amount_cents
2026-01-02,IT,12345
```

The generated reference SQL uses `group_label` as its SQL alias, because
`GROUP` is reserved in SQL; rename that field to `group` in the
publication CSV. Never count a deliberately withheld group as a
published zero.

Optionally, provide `held/clean.csv` and `held/chaos.csv` containing
`period,group` when groups are intentionally not published, and
`alerts.json` with arrays of actual alert strings for `clean` and
`chaos`. These are distinct pieces of evidence:

- A **warning** alone is not containment.
- Withholding everything prevents wrong publication but destroys useful
  availability.
- A valid published number is not proof of an evidence-backed repair.
- The hidden ledger can reveal a missing or modified authentic event
  that no source-only check can always infer.

The evaluator compares published outputs against the independent process
truth and also against the source-implied oracle, reporting both error
sources without improperly adding absolute errors. It requires the
private answer key locally and verifies source and SQL reference-file
hashes before scoring. Keep the private answer key and event ledger
outside the platform's input directory.

## Faults and observable controls

| Scenario `--fault` | Plausible operator task | Expected source-only structural tests | Business oracle |
|---|---|---|---|
| `none` | No change | Normal version history/retries | Correct |
| `rewrite_credit` | Reconcile a suspicious partial credit | Often passes: the edited value is plausible | Detects wrong amount |
| `reclassify_party` | Align a party to a different dimension | Usually passes: dimension remains valid | Detects money shifted across groups |
| `drop_document` | Deduplicate a supposed repeat | Finds movements with no parent document | Detects missing business record |
| `duplicate_delivery` | Retry a potentially lost delivery | Notes an idempotent repeated movement | Correct |

The generated `quality_checks.sql` tests observable orphan documents,
missing parties, invalid kinds, negative amounts, over-credits, same-version
conflicts, and duplicates. It treats a byte-identical retry as
**informational** rather than necessarily bad. These are **candidate
quality probes, not production-enforced quarantine rules**.

## What has been independently validated?

[GitHub Actions workflow](https://github.com/mhatipog/dbt-chaos/actions/workflows/process-contract.yml)
runs both contracts across all five fault types. The independent
business-event oracle, delivered-source oracle and actual SQL execution
agree on the clean inputs. For three harmful faults, source-only SQL
correctly transforms the corrupted inputs but publishes wrong values;
the harmless retry retains correct business output.

Additional tests prevent contract-to-SQL injection through identifiers,
private/oracle leakage, falsified file hashes, duplicate output groups,
incorrectly rewarded all-group withholding, and regressions in the earlier
commerce benchmark.

## Scope and scientific honesty

This is an implemented **three-role transactional process-contract
family** with customizable tables, column names, semantics and data
distributions. It is **not yet a universal process-mining DSL** or a
workflow inferred automatically from any schema. The new faults are
scripted human-like calibration—not new model decisions. The existing
genuine-Qwen 20-step telephone-game study remains separate.

The next major development is a process-contract-aware weak-LLM agent
capable of proposing bounded typed changes to generated source tables
and business rules with auditable justifications, followed by matched
multi-seed experiments. More complex multi-step workflows, temporal
reconciliation, distributed retries and native Fabric/Databricks
execution require their own extensions and validations.
