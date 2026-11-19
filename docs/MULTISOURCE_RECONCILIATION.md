# Multi-source business-truth reconciliation (research preview)

This extension addresses a fundamental limit of ordinary dbt tests:
**a perfectly plausible but incorrect refund amount cannot be validated
using only the corrupted payment record**. But a real, mature data platform
can reconcile it against independently obtained evidence, provided it
tracks identity, origin, settlement timing and publication decisions.

[Native dbt / DuckDB CI](https://github.com/mhatipog/dbt-chaos/actions/runs/44607118245)
and [portable benchmark CI](https://github.com/mhatipog/dbt-chaos/actions/runs/44608231036)
demonstrate an opt-in implementation and a portable six-source challenge.

## What actually runs

The complete synthetic commerce workload is still defined by an immutable
event process, with customers, latest customer histories, orders, payment
captures/refunds and cancellations. The events produce:

| Source | Independent origin (simulated) | Role |
|---|---|---|
| `customers`, `orders`, `payments` | Merchant application | Mutatable data-platform input |
| `accounting_journal` | **Same** merchant application | Internal ledger consistency check; NOT an independent vote |
| `provider_transactions` | Payment service provider | Transaction-by-transaction external reconciliation |
| `bank_batches` | Bank | Independent *aggregate* net settlement buckets; cannot localize a particular payment alone |

A matched canonical `payment_id` identifies the transaction (including
kind, order ID, amount and synthetic batch date). The journal stores
**signed** cents. Bank entries store net batch cents.

**Important simplification:** Bank batches here are grouped by the order
date, with no fees, FX, payout calendars or partial bank settlement.
This is an executable **synthetic testing contract**, NOT a model of real
merchant bank reconciliation. In a real deployment the payment gateway
and bank would use stable payout IDs, cutoff rules and clearing windows.

### Evidence is allowed to arrive late

The receipts have `available_after_days` and the platform sees only records
whose delay is no greater than the evaluation's `as_of_lag_days`.

- Before the provider SLA, a missing receipt is `pending_provider`,
  **not** a corrupt source record.
- After the SLA, a missing receipt is a reconciliation dispute.
- Before the bank reconciliation deadline, the batch is
  `pending_bank`; after that, a missing or non-balancing batch becomes
  a dispute.
- Groups depending on unreconciled evidence are **withheld**, not silently
  published as zeros or automatically overwritten.

These SLA thresholds are configured by the synthetic reference policy:
provider up to **2 days**, bank up to **4 days**. They are not proposed as
universal real banking service levels.

## Real native SQL

Five optional models in
[`commerce_sql/models/reconciliation/`](../dbt_chaos/commerce_sql/models/reconciliation/)
execute in DuckDB when `enable_reconciliation_models: true`.

| Model | Actual result |
|---|---|
| `rec_payment_evidence` | Per-payment PSP, operational and internal GL consistency status |
| `rec_bank_evidence` | Batch-day net comparison to bank feed, including pending status |
| `rec_held_groups` | Exact day × segment groups withheld from trusted reporting |
| `rec_release_gate` | Report-level release status and dispute/pending counts |
| `rec_gold_published` | **Actual publication surface** with disputed/pending groups excluded |

These models can be combined with the earlier native payment quarantine
path, and both remain OFF by default. The existing ordinary
`gold_daily_revenue` remains the ungated comparison and **must not be
advertised as the trusted published output** when this mode is enabled.

**This is a scientific prototype, not an access-control system.** Enforcing
that consumers can only query `rec_gold_published` still requires warehouse
permissions, deployment and governance controls.

## Try the real Qwen refund failure

The exact source change below was originally proposed by a real locally
run 0.5B-parameter Qwen agent in the earlier 20-handoff experiment.
This command **replays** the recorded mistake; it does NOT rerun the model.

```bash
pip install -e '.[dbt]'
dbt-chaos reconcile-demo \
  --scenario qwen_refund_source_only \
  --out assessment.json --fail-on-silent
```

The source has an authentic €49 refund rewritten to €29. The standard dbt
transformation passes its existing tests, but publishes €20 too much.
The independent PSP receipt still says €49; the original internal GL
also says €49; the bank batch net differs by €20.

Our opt-in SQL holds the affected revenue groups for investigation,
while preserving unaffected groups. **It does not manufacture a €49 repair
or claim to know which external document is authentic.**

## Use it with another data platform

You do NOT need Python dbt, an LLM API, or database credentials to
generate the challenge:

```bash
pip install -e .
dbt-chaos export-reconciliation \
  --scenario qwen_refund_source_only \
  --public-dir ./public-six-source-challenge \
  --private-dir ./sealed-oracle
```

Share only the six `public-six-source-challenge/inputs/*.csv` files with
your isolated **dbt, Fabric, Databricks, or other** test workspace.
Run your own reconciliation transformations on those files, honoring the
`available_after_days` constraint. Export what it *actually publishes*:

```text
published.csv: order_day,segment,revenue_cents
held.csv:      order_day,segment     (optional)
```

Score the result in a separate trusted evaluator:

```bash
dbt-chaos score-reconciliation \
  --public-dir ./public-six-source-challenge \
  --answer-key ./sealed-oracle/answer_key.json \
  --published ./published.csv \
  --held ./held.csv \
  --out ./reconciliation-score.json --fail-on-silent
```

Without `held.csv`, an absent publication group is a **silent omission**,
not successful quarantine. A fully withheld report has zero false
numbers but also **zero correctly delivered business value**.

The private answer key contains synthetic original business events, expected
business metrics and reference observable disputes. It must NOT be mounted
into the data-platform worker being tested.

## Ten test cases — with an important impossible control

| Case | Designed observable behaviour |
|---|---|
| `clean_mature` | Verified available feeds; full correct publication |
| `qwen_refund_source_only` | PSP and bank reveal €49 → €29 source corruption |
| `qwen_refund_and_correlated_gl` | Wrong operational + GL agreement still exposed by PSP/bank |
| `psp_and_gl_corrupted_bank_catches` | Bank batch disagrees despite transaction-level PSP match |
| `qwen_internal_gl_detects_early` | Intact internal GL flags discrepancy before external evidence arrives |
| `clean_before_settlement` | Pending evidence, not a data-quality fault; publication withheld |
| `clean_after_provider_before_bank` | Mature provider, pending bank; publication withheld |
| `qwen_before_provider` | Correlated wrong merchant copies, provider/bank pending |
| `missing_provider_after_sla` | Missing transaction after SLA becomes observable dispute |
| `all_claimed_feeds_agree_on_wrong_value` | ALL supplied amounts agree incorrectly: **not detectable** from those data alone |

The last case is a **scripted impossibility control**: the operational
record, internal GL, PSP receipt and bank aggregate are all changed to
agree at €29. Even our new SQL must then report a consistent snapshot,
despite hidden synthetic business truth being €49.

Do not penalize a platform for failing to detect an undetectable case.
A text field such as `origin_root = independent_bank` is an *assertion*,
not cryptographic proof that a bank independently observed the amount.
True independence, authenticated statements and tamper-resistant
provenance require infrastructure outside this prototype.

**Crucial source provenance:** only the original €49→€29 change came
from the previously recorded real Qwen experiment. The other corruption,
delay and provenance cases are controlled SCRIPTED experiments—not
additional claims about what a model generated.

## Metrics and what they mean

The benchmark independently reports:

- Number of actual source/payment and batch-level reconciliation findings
- Evidence `pending` versus `disputed`, conditioned on reporting delay
- Affected report groups held back and correct business value not delivered
- Incorrect business facts actually published, with absolute cent error
- Whether incorrect output was exposed **despite an observable discrepancy**
- Whether the difference was **not yet observable** or **unobservable even
  when all supplied feeds were mature**

The expected business gold never enters the observable reconciliation SQL;
it is exclusively a *post-execution evaluator*.

This is not simply a new form of source freshness. dbt already provides
source freshness, generic and singular data tests, and stored failures.
The contribution is an *end-to-end reproducible test* of which independent
business evidence each platform **needs** to catch a realistic corruption,
and what it actually does with that evidence.

Relevant authoritative references:

- [dbt data tests and stored failures](https://docs.getdbt.com/docs/build/data-tests)
- [dbt source freshness](https://docs.getdbt.com/docs/deploy/source-freshness)
- [Federal Reserve Bank of New York: payment clearing and settlement practices](https://www.newyorkfed.org/medialibrary/microsites/prc/files/PRC-Best-Practices-Document-Payment-Lifecycle.pdf)
- [Washington State Auditor: 2026 bank reconciliation best practices](https://sao.wa.gov/sites/default/files/2026-03/2026%20Best%20Practices%20for%20Bank%20Reconciliations.pdf)

## Major next steps

1. Replace synthetic order-day bank buckets with explicit PSP payout events,
   posted fees, cash clearing and T+N settlement calendars.
2. Add a **genuine multi-source evidence authenticity layer** (signed
   receipts, event identifiers, source ownership and provenance DAG),
   rather than trusting origin labels.
3. Introduce business-process contract plugins beyond commerce and
   independently validated hold/release policies for external platforms.
4. Extend agent tasks so a well-intentioned model sometimes troubleshoots
   reconciliation exceptions, with explicit authorization controls and
   explainable refusal when evidence is inadequate.
5. Evaluate cost of false positives, delayed verification and time to
   release, not only silent corruption rates.

Until these milestones, this remains a strong, reproducible research
instrument rather than a universally ready autonomous data platform.
