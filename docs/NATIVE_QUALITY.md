# Native dbt/DuckDB quarantine and publication gate (opt-in)

**Status (19 Nov 2026):** [GitHub Actions run 44557372785](https://github.com/mhatipog/dbt-chaos/actions/runs/44557372785) passed
**six real dbt-native protection tests**, ten original commerce regression
tests, and eleven full-dataset generator tests. The new native path runs
only when `enable_quality_models: true`. The default dbt models and
existing public benchmarks remain unchanged when that flag is absent.

## Five new warehouse models

| dbt model | Materialization | Specific role |
|---|---|---|
| `quality_quarantine_payments` | table | Physical rejected-payment table: record identity, original values and a reason code |
| `quality_accepted_payments` | table | Raw payments minus quarantined deliveries; consumed by `stg_payments` when opt-in mode is enabled |
| `quality_held_groups` | table | Affected day×segment groups whose corresponding payment records were withheld |
| `quality_release_gate` | table | Publication status (`published`, `partial`, `withheld_all`) plus suspicious-row counts |
| `quality_gold_published` | table | Actual publishable output, excluding held groups, or empty when whole-report risk cannot be localized |

These are real dbt models executed against DuckDB, not externally simulated
classifications. In native mode, **downstream consumers should query
`quality_gold_published`, not the ordinary `gold_daily_revenue` debug
comparison table**. A truly fail-closed operational system must enforce
this publishing boundary through authorization/permissions, which is
NOT implemented by the research PoC.

### Observable rules actually enforced in SQL

1. A payment whose order is missing is quarantined; without that missing
   order's original date and segment, the publication gate withholds the
   entire report.
2. Invalid payment amounts/kinds are quarantined; reporting groups
   associated with their orders are withheld while the rest can publish.
3. An exactly repeated payment delivery is deduplicated in the accepted
   payment source, but does **not** cause business output to be blocked.
4. A conflicting same-key/same-version payment is treated as ambiguous,
   and the whole report is withheld rather than picking a winner.

No external business-event ledger is available to the native SQL
detectors. Thus Qwen's plausible refund and segment mistakes still
cause silent errors; native SQL cannot infer facts absent from its input.

The native proof covers **payment-side** protection. The earlier Python
sidecar also screens customer/order contracts and aggregated payment
balances. The two implementations must not be described as fully
equivalent until additional SQL rules are added and independently tested.

## Run locally

```bash
pip install -e '.[dbt]'
python -m unittest discover -s tests -p test_native_quality.py -v
```

Programmatic real-DuckDB execution:

```python
from dbt_chaos.commerce import CommerceCase
from dbt_chaos.full_datasets import clean_dataset, Profile
from dbt_chaos.commerce_runner import run_case

_, process_truth = clean_dataset(Profile())
report = run_case(
    CommerceCase(), admitted_data=process_truth,
    process_data=process_truth, quality_enabled=True,
)
quality = report["native_quality"]
assert quality["release_status"] == "published"
assert not quality["quarantine"]
print(quality["released_gold"])
```

The execution returns original dbt test statuses as well as the native
quarantine rows, held group IDs, release status and physically published
gold table. This avoids falsely counting a warning as a quarantine
operation. The true business ledger in this code example is supplied
only for **independent evaluation**; native detectors never query it.

## Result and limitations

All six native cases passed:

- Clean inputs stay published, with no quarantines.
- A genuine retry produces one `exact_delivery_replay` row and a correct
  published report, avoiding the sidecar strict gate's unnecessary
  all-group withholding.
- Qwen's two internally plausible mistakes publish incorrect business
  metrics without an alert.
- Qwen's missing-order payments enter the quarantine table with reason
  `missing_order`, and publication is withheld.
- Negative payment values are quarantined and their day×segment group
  excluded, leaving other groups correct.
- Conflicting same-version payment deliveries cause whole-report
  withholding.

This is a **research prototype**, not a production-grade quarantine
service. It lacks persisted governance approvals, role-based release
control, delayed remediation procedures, backfill/CDC semantics,
transaction-level audit trails and formal source attestations.
The native SQL model's current scope is intentionally narrow; source
integrity and complex refund correctness still require more work.

## Next research questions

- Native/sidecar parity across more errors and process seeds: what
  observable controls measurably help without destroying availability?
- Test external payment settlement/refund event evidence as a *separately
  priced or accessible source of truth*, not as hidden oracle leakage.
- Verify conservation laws (capture balances, refunds, allocation)
  **without** over-quarantining real delayed or partial payment flows.
- Test 20 handoffs of genuine well-intentioned weak-model source and SQL
  maintenance, with independent full-history/no-history controls.
- Holdout datasets from different process patterns and industries;
  the current corpus is one synthetic commerce process, not a
  demonstration of general robustness.

See [measured 25-case sidecar results](PROTECTION_RESULTS_20261119.md),
[framework](PROTECTION_BENCHMARK.md) and
[model-generated datasets](FULL_DATASETS_RESULTS_20261119.md).
