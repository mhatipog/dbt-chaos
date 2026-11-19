# Commerce source data for dbt-chaos

Clean, relationship-aware source data for the commerce workload (`dbt_chaos/commerce.py`),
plus two planted multi-table faults from the catalogue of issue #1 (`missing_dimension` and
a duplicate join key, which fans out like `join_fanout`), each with a negative control. model2data generates the data; dbt-chaos injects its own faults, runs dbt and
decides what the right answer is. Nothing here computes revenue or any other business result.

```
schema.dbml                        the three tables, column for column as dbt-chaos loads them
missing_dimension.model2data.yml   schema.dbml plus the orphan-key defect (written by generate.py)
generate.py                        one command regenerates everything below
run_with_dbt_chaos.py              runs the variants through dbt-chaos's own commerce runner
dbt_results.json                   the full result of each of those runs (dbt-core 1.10.15)
manifest.json                      seed, model2data version, row counts, sha256 per file, planted rows
data/
  baseline/                        customers.csv  orders.csv  payments.csv
  missing_dimension/fault/
  missing_dimension/control/
  duplicate_join_key/fault/
  duplicate_join_key/control/
```

## Regenerate

```bash
uv run generate.py            # data/, manifest.json, missing_dimension.model2data.yml
uv run generate.py --check    # regenerate in a temporary folder; fails unless every byte matches
uv run generate.py --zip dbt-chaos-commerce.zip
```

The script pins `model2data==1.20.0` in its inline metadata, runs with seed `20261119` and
anchor day `2026-10-31`, and gives the same bytes on every run (`--check` proves it). The
sha256 of every CSV is in `manifest.json`.

## How it maps to the dbt-chaos contract

The column names and order are `COLUMNS` in `dbt_chaos/commerce_runner.py`, so each CSV loads
into the matching `raw.*` table of its DDL as it is.

| Table | Column | Here | Notes |
| --- | --- | --- | --- |
| customers | `row_id` | integer, unique, 100000-199999 | the tie-breaker of the latest-version dedup |
| | `customer_id` | integer key, 1..200 | |
| | `version` | always 1 | |
| | `segment` | `retail` 3 : `business` 1 | |
| orders | `row_id` | integer, unique, 300000-399999 | |
| | `order_id` | integer key, 1..2000 | |
| | `customer_id` | references customers | every one resolves in the baseline |
| | `version` | always 1 | |
| | `order_day` | `YYYY-MM-DD`, Oct 2024 to Oct 2026 | the runner's DDL loads it as `varchar` |
| | `gross_cents` | integer cents, lognormal around 45.00 EUR, 5.00-500.00 | |
| | `status` | `completed` 9 : `cancelled` 1 | only the two values the contract accepts |
| | `currency` | always `EUR` | |
| payments | `row_id` | integer, unique, 200000-299999 | |
| | `payment_id` | integer key; not contiguous (see below) | |
| | `order_id` | references orders | |
| | `version` | always 1 | |
| | `kind` | `capture` or `refund` | |
| | `amount_cents` | integer cents | a capture equals its order's `gross_cents` |

### What model2data does not do, and the step that covers it

model2data has no way to make one table's value depend on another table's row: a payment's
amount cannot follow its order's gross, and whether a payment exists cannot depend on the
order's status. Left as generated, the baseline would hold captures on cancelled orders
(dbt-chaos's `cancelled_with_payment` fault) and orders refunded beyond what was captured. So
`generate.py` lines payments up with their orders, by fixed rules and without randomness:

1. a cancelled order keeps no payments (cancelled before payment was taken);
2. on a completed order the first payment becomes the capture of the order's `gross_cents`;
3. the first later payment model2data drew as a refund stays a refund, of
   `min(amount_cents, gross_cents)`, so no order nets below zero;
4. every other payment is dropped: one capture and at most one refund per order.

model2data generates 4,000 payments and 2,009 remain; the counts are in `manifest.json`
(`payment_alignment`). The dropped rows leave gaps in `payment_id`. About 13% of completed
orders have no payment at all, and about 24% have a partial or full refund.

## The variants

Each variant is the baseline with the rows listed under `planted` in `manifest.json` changed
and nothing else. Each control changes the same rows, or rows of the same kind, in a way that
must not change the business result, so a difference between fault and control is caused by
the fault and not by the change itself.

### `missing_dimension`

**Fault.** Five orders reference a customer that is not in `customers` (orphan foreign keys).
These are planted by model2data's own `orphan_foreign_keys` defect
(`missing_dimension.model2data.yml`): orders 907, 1022, 1049, 1422 and 1504 point at customers
201-205, past the largest customer key. Because defects come from their own random stream,
every other row is byte-identical to the baseline. All five orders are completed; three carry
payments (907 has a capture and a refund, 1022 and 1049 a capture) and two have none, so the
fault moves revenue on three day/segment rows. model2data's `defects_report.json` is copied
into the manifest.

**Control.** The same five orders are re-pointed to another *existing* customer of the same
segment. The same rows and the same column change, but every key still resolves and every
order stays in its day/segment. A correct pipeline gives exactly the baseline's result with no
source alert. It shows that the fault's effect comes from the key not resolving, not from the
key changing.

### `duplicate_join_key`

**Fault.** Customers 59, 124 and 157 each get a second row with the same `customer_id`, the
same `version` and the same segment, under a new `row_id`: an exact repeat of the join key. A
join that does not deduplicate fans out every order of those customers (8, 6 and 5 orders) and
their payments. The repeat breaks the uniqueness of `(customer_id, version)`.

**Control.** The same three customers get a row with `version = 2` and an unchanged segment,
under the same new `row_id`: a legitimate re-delivery of a newer version that changes nothing.
`(customer_id, version)` stays unique, so no source check should fire. A correct
latest-version dedup gives exactly the baseline's result. A pipeline that joins without
deduplicating fans out here too. So the control separates a source that breaks its contract
(fault) from a pipeline that only works while every key happens to appear once (control).

## Run it through dbt-chaos

`run_with_dbt_chaos.py` feeds these CSVs to dbt-chaos's real commerce runner: it replaces only
`baseline()` and `inject_source()`, and only while the runs last, so dbt-chaos's SQL, its tests,
its reference calculation and its classification run unchanged.

```bash
pip install -e '.[dbt]'                                   # from the repository root
python examples/model2data_commerce/run_with_dbt_chaos.py --out results.json
```

It runs eight cases: the baseline, each fault and control with dbt-chaos's correct SQL, and the
baseline and `duplicate_join_key` variants with its `skip_customer_dedup` SQL fault. With
dbt-chaos 0.2.0 on dbt-core 1.10.15, the baseline and both controls came out `correct`, and
both faults `contained` (the source test for orphan orders, and the one for duplicate
customers, fired). With `skip_customer_dedup`, both the duplicate fault and its control came
out `silent_corruption` on 14 day/segment rows, the control without any source alert.
`dbt_results.json` holds every field of those eight results.

## In CI

The *Commerce source x SQL chaos* workflow covers this folder in two jobs:

- `actual-dbt` runs `tests/test_commerce_model2data.py`: every CSV against its sha256 in
  `manifest.json`, the column order against the runner's contract, and the eight runs on real
  dbt/DuckDB against `dbt_results.json` (timings aside).
- `model2data-regenerate` runs `generate.py --check` with uv, in its own environment, and fails
  unless every regenerated file is byte-identical to the committed one.

## Checks

`generate.py` refuses to write anything unless, in every variant:

- `row_id` is unique per table, and `(key, version)` is unique per table, except the planted
  repeats of `duplicate_join_key/fault`;
- every order's customer exists, except the planted orphans of `missing_dimension/fault`, and
  every payment's order exists;
- every order is `EUR`, `completed` or `cancelled`, with `gross_cents > 0`, and every payment
  is a `capture` or `refund` with `amount_cents >= 0`;
- the model2data defect run changed `orders.customer_id` on exactly the five planted rows and
  nothing else.

## dbt versions

The data is plain CSV and does not depend on dbt; the runs above use the dbt-core 1.10.15
pinned in the `dbt` extra. Generating it installs model2data 1.20.0, which brings dbt-core 1.11
or newer for its own dbt project (not used here), so `generate.py` runs in a separate
environment (`uv run` reads the pin from the script itself).
