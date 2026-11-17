# dbt-chaos: source-data × SQL-transformation faults

A deliberately small sales data platform tests both kinds of errors independently
or together. There is a third separate category, runtime failures, for later.

## Verified real dbt/DuckDB evidence — 17 November 2026

The first complete representative matrix executed **30/30 combinations successfully**
on a public, ephemeral GitHub-hosted runner with dbt Core and DuckDB.

[Primary GitHub Actions evidence](https://github.com/mhatipog/dbt-chaos/actions/runs/44056498668)
(source commit: 652eb0a80e40569aab403f508c9ebc802a55d2c0).

| Origin | Correct | Contained | Detected failure | Silent corruption |
|---|---:|---:|---:|---:|
| Clean control | 1 | 0 | 0 | 0 |
| Source defects only | 4 | 9 | 0 | 0 |
| SQL defects only | 4 | 0 | 1 | 4 |
| Source + SQL defects | 1 | 1 | 0 | 5 |
| **Total** | **10** | **10** | **1** | **9** |

The 7 combined cases produced four emergent corruptions, two masked
corruptions and one persistent corruption. There were no unexpected
execution errors. A SQL sign-reversal defect generated invalid negative
revenue and was **detected** by the gold-output data test; other incorrect
gold results were not caught by the configured gold checks (three
not-null tests and two singular grain/nonnegative tests). Input-specific alerts were reported separately.

This is a deliberately selected synthetic corpus, not a random
sample of production incidents or a percentage reliability claim.
The result does not prove any general dbt Core defect. The new
denominator-aware scorecard can be reproduced locally from the same
fixtures and contract.

---

## One contract, three sources, one business metric

    raw.orders --+
                 +--> dbt stage --> dbt gold_daily_revenue (day × segment)
    raw.customers+
    raw.payments-+

The contract is precise: use the latest source version of each natural key;
only completed EUR orders with positive gross and an existing customer count.
Daily revenue in integer cents equals captured payments minus refunds, grouped
by the order day and latest customer segment. Duplicate deliveries are
deduplicated. Invalid payment amounts are quarantined, not recognized.

Independent Python logic calculates the expected gold output from *admitted*
source records. The real dbt pipeline executes the SQL against a clean, disposable
DuckDB database. It runs dbt source-quality tests and gold-output tests.

## Fault taxonomy, supported v1

| Axis | Mechanisms |
|---|---|
| Source: identity | duplicate_customer, duplicate_payment, duplicate_order |
| Source: reference | orphan_customer |
| Source: value | null_payment, negative_payment, null_order_gross |
| Source: semantics | usd_order, invalid_order_status |
| Source: history | customer_version_change |
| Source: business operation | cancelled_with_payment, missing_refund, split_capture |
| SQL: dedup | skip_customer_dedup, skip_payment_dedup |
| SQL: joins | wrong_payment_join, wrong_customer_join |
| SQL: filters | include_cancelled, ignore_currency |
| SQL: arithmetic | ignore_refunds, invert_capture_sign (detected by negative-revenue test) |
| SQL: aggregation | wrong_grain |

There are 13 source mutants, 9 SQL mutants, seven targeted combinations, and
one clean control: 30 representative cases. Additional Cartesian combinations
can be selected using the library API. A missing refund is intentionally an
*unobservable source omission* under the admitted-data-only contract: detecting
it requires an independently reconciled external source or expected delivery
manifest. The experiment reports the gap against the synthetic original
business snapshot, without claiming the pipeline could infer that refund.

## Outcomes: one primary verdict, orthogonal evidence

| Outcome | Definition |
|---|---|
| correct | Gold equals admitted-source truth; no source quality alert |
| contained | Gold equals truth; source quality tests identified bad input |
| detected_failure | Gold differs; a gold-specific test flagged an error |
| silent_corruption | Gold differs and no gold-specific test flagged an error |
| execution_failure | dbt could not run or its results are not interpretable |

A source alert alone does NOT prove that an incorrect gold result was detected.
For example, duplicated customers can be flagged, while a bad join still
double-counts revenue. This is reported as silent gold corruption plus a
separate source alert.

An additional field reports the difference between original synthetic
business truth and contract truth calculated from altered admitted inputs.
That field is informative only: a legitimate source correction can also
change revenue. Do not label every such change platform corruption.

The combined missing-refund + ignore-refunds case illustrates *fault masking*:
the wrong transformation appears correct against the already-incomplete source.
A source contract by itself cannot prove complete upstream delivery.

## Reproduction and scope

~~~bash
python -m pip install -e '.[dbt]'
dbt-chaos commerce --source duplicate_customer --sql skip_customer_dedup
dbt-chaos commerce-bench --selection representative --out commerce.json
~~~

Experiments are confined to bundled, synthetic SQL and a temporary local
DuckDB project. The public CI uses GitHub-hosted ephemeral runners, not the
persistent private Oracle VM.

The v1 suite has not proven transaction restart resilience, schema evolution,
cross-adapter SQL behavior, late CDC scheduling, real currency conversions,
SCD2 temporal joins, general financial reconciliation, or all combinations.
The previously verified 20×6 incremental benchmark remains separate.

## Planned additional workload contracts

- Payments and invoices: captured/refunded versus independent ledger entries.
- Customer SCD2: exactly one valid dimension interval per effective date.
- Inventory: stock conservation over receipts, sales and returns.
- CDC and late data: stateful delivery, ordering, watermark recovery.

Every new workload needs a separate independent truth oracle and explicit
acceptable behavior before declaring its faults detectable.
