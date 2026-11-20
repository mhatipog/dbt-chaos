# Real dbt project chaos — external-project adapter (experimental)

The original dbt-chaos suite tests controlled failures on our own synthetic
projects. This adapter accepts **another local dbt project** and actually
runs its dbt models and declared tests against new temporary DuckDB
databases containing controlled source faults.

## Supported scope

- Local dbt Core 1.10 projects with DuckDB-compatible **CSV seed-backed**
  models; not cloud sources or connected production tables
- One matching seed CSV row, selected by exact column/value equality
- Three independent faults: amount_shift, duplicate_row, drop_row
- Genuine dbt seed, run and test commands, actual model output comparison,
  and native run_results.json test-status verification
- Two comparison levels: clean baseline output drift and independently
  supplied business expected-output CSV
- Full separate temporary project / database for every case, with no
  changes to the original local project or warehouse

Not supported yet: dbt package installs, cloud-only SQL, custom source
tables, multi-seed mutations, non-integer-cent values, incremental
watermark replay, or ephemeral target models.

## Reproducible fixture

Install optional pinned dependencies:

~~~bash
python -m pip install -e '.[dbt]'
~~~

First inspect a local project's seed tables, candidate keys and
amount columns without running SQL, macros, hooks, or showing source values:

~~~bash
dbt-chaos external-dbt-inspect \
  --project-dir tests/fixtures/foreign_dbt_project \
  --out /tmp/dbt-chaos-inspection.json
~~~

Names and likely-key selection are heuristics, not verified constraints.

Run the internally reviewed synthetic unfamiliar project:

~~~bash
dbt-chaos external-dbt \
  --project-dir tests/fixtures/foreign_dbt_project \
  --model gold_revenue \
  --seed-table payments \
  --column amount_cents \
  --match-column payment_id --match-value 2 \
  --delta 2000 \
  --faults amount_shift,duplicate_row,drop_row,reorder_rows \
  --test-scope full --metric-column revenue_cents --business-key order_id \
  --independent-expected tests/fixtures/foreign_expected_gold.csv \
  --acknowledge-project-code-execution \
  --out /tmp/external-dbt-report.json
~~~

Results are machine-readable JSON, including test counts, row diffs,
and provenance distinctions. For CI gates, add --fail-on-silent: it exits
with code 2 if a proven independently attested business error was
published despite green dbt tests. A green exit is NOT a certification.

Without --independent-expected, changed outputs are classified
unverified_output_drift. A clean pipeline result is not an independently
proven business fact.

## Controlled expected findings

The fixture represents an unrelated project with a payment capture and
refund ledger. Independent CSV truth contains revenue of €51 and €175.

| Fault | dbt schema tests | Financial outcome |
| --- | --- | --- |
| Plausibly reduce one €49 refund to €29 | Expected pass | €20 false revenue, silent mismatch |
| Duplicate payment row and payment ID | Expected unique failure | Business mismatch detected |
| Drop one payment | Expected pass | Missing money, silent mismatch |

These are designed fixture predictions until verified by CI running
**real dbt**; they are not customer incidents, errors authored by a
live LLM, or representative probability estimates.

## Threat model — essential

**Copying a dbt project is not a security sandbox.** Project Jinja,
macros, SQL and hooks can execute code, send network requests or
access ambient credentials. The CLI requires explicit
--acknowledge-project-code-execution and should be run only with
trusted/reviewed dbt project code in an ephemeral dedicated VM or
container without networking, production access or credentials.

The adapter does not copy dotfiles, profiles.yml, dependency manifests,
dbt_packages or symlinks and minimizes inherited environment variables.
This reduces accidental leakage, but does NOT enforce network confinement
or prevent deliberate execution of hostile code.

The supplied independent expected-output CSV must be created by a
separately checked legitimate business process, NOT copied from the
target model's baseline. A wrong clean baseline is rejected before any
fault outcomes are called silent corruption. The adapter cannot prove
that the caller's reference truly comes from an independent source or
cryptographically authenticate its origin; the JSON report explicitly
records this trust assumption.

CI: .github/workflows/external-dbt.yml.

## Next product step

Run a customer-supplied synthetic or legally shareable seed-backed
dbt model in a separate credential-free runner; collect usability and
defect evidence. For Fabric and Databricks, add dedicated **scoped**
adapters with clear dataset ownership, no arbitrary production
connections and an independent truth boundary. Add join, SCD and
late-arrival faults only after real external pilots show value.
