# Garbage In → Outcomes: Evidence-tiered protection benchmark

## Hypothesis and evaluation rule

The relevant outcome is not just "did a dbt test fail?". It is:
**When a plausible, well-intentioned data-handling mistake is introduced,
does the platform publish wrong business facts, only warn about them, safely
quarantine affected records, withhold suspect results, or reconstruct
correct results from independently attested business events?**

Every test uses the SAME event ledger and EXACT recorded accepted Qwen
interventions. No policy may use business ground truth except the explicitly
privileged `attested_replay` configuration. Scoring runs after publication
has been determined. The model never accesses the independent ledger.

## Real frozen model-generated errors

[Qwen/SmolLM original run](https://github.com/mhatipog/dbt-chaos/actions/runs/44544592101)
and [observations](FULL_DATASETS_RESULTS_20261119.md) document the
six real weak-LLM decisions; three applied. This benchmark replays those
exact three edits on the deterministic baseline:

1. Payment `row_id=30626`: change real refund €360 to €721
2. Customer `row_id=10040`: change latest segment business → retail
3. Order `row_id=21054`: remove an existing completed order, with surviving
   payment `order_id=467`

Each step is cumulative; the last case includes all three source changes.
The experiment also includes an unchanged clean control.

## Five protection strategies

| Policy | Available input | What is actually executed |
|---|---|---|
| `raw` | Delivered snapshot | Existing unchanged dbt SQL and existing dbt tests only |
| `monitor` | Delivered snapshot | Existing dbt plus extra Python pre-ingest integrity checks; alerts only, no row changes |
| `quarantine` | Delivered snapshot | Physically separate observable suspect rows; run real dbt on accepted rows; **withhold affected reporting groups** or entire report if risk cannot be localized |
| `strict_gate` | Delivered snapshot | Withhold **entire** report on an observable disqualifying fault; otherwise run existing dbt |
| `attested_replay` | Delivered snapshot **plus separately trusted business-event feed** | Compare recorded source rows to independently attested rows, record evidence-backed corrections, run unchanged real dbt |

Note the evidence asymmetry: `attested_replay` is an upper-bound **different
data-access tier**, not an algorithmic comparison on the same information.
Without a trusted upstream event log, it cannot be invoked.

The Python protection sidecar is **part of the evaluated prototype pipeline**
but the extra checks have **not been installed as native dbt tests**.
The benchmark records `policy_validators_installed_as_dbt_tests=false`.
It does not claim that existing dbt alone contains errors.

## Accounting for data *loss* and publication safety

The evaluator separately measures:

- `observed_absolute_error_cents`: sum of absolute errors over published
  day×segment groups, relative to the separate business event ledger
- `observed_signed_error_cents`: signed revenue error (can cancel)
- `incorrect_published_group_count`: wrong reporting groups **actually exposed**
- `safe_truth_value_fraction`: share of absolute genuine revenue correctly
  published, penalizing both corruption and withheld data
- `publication_status`: published, partial or withheld
- `quarantined_records`: **actually** removed from the source feed;
  alerts do not count as quarantines
- `quarantined_genuine_records`: valid original evidence-backed rows
  wrongly held; calculated by the **independent scorer**, not visible to policies
- `candidate_detector_findings`: warnings discovered by the enabled
  external monitor, distinct from existing dbt test results
- `recovered_from_attestation`: evidence-backed corrections, not guessed
  replacement values
- `dbt_executed` and `dbt_result_reused`: prevent double-counting cached
  identical dbt outputs as independent runs

Publication gating never silently fills a suspicious group with zero.
If a payment references an order that is completely absent, its original
business date/segment cannot be reconstructed from that source. The
quarantine policy therefore withholds the whole report, rather than
pretending unaffected groups can be established.

**An important impossibility:** Two different real business histories can
produce the SAME delivered snapshot when upstream events are lost or
rewritten. Any source-only algorithm then observes identical inputs in both
worlds and cannot be universally correct in both. That is why a correctly
computed output from corrupted input is still a business failure.

## How to reproduce

```bash
pip install -e '.[dbt]'
python -m unittest discover -s tests -p test_protection.py -v
python -m dbt_chaos.protection --output /tmp/protection-matrix.json
```

[Dedicated real-dbt Actions workflow](../.github/workflows/protection.yml):
four scenarios × five explicit strategies, with real dbt/DuckDB execution
reused only for identical source, logic and business truth, to keep public CI
cost bounded. Output `protection-matrix.json` is uploaded with 2-day retention.

The `raw` policy never gets credit for a Python detector that was not
installed. Monitoring with an alert is explicitly `detected_but_exposed`
when the report is still wrong; flagging is **not containment**.

## Literature-first interpretation

The novelty is not introducing data errors, SQL mutations or quarantine
tables in isolation:

- *Towards Realistic Error Models for Tabular Data* (2025),
  [DOI: 10.1145/3774914](https://doi.org/10.1145/3774914),
  demonstrates that cleaning benchmarks depend on realistic error mechanisms.
- *A Survey on Platform-Level Data Quality: From Visibility to
  Controllability* (IEEE, 2026),
  [publisher](https://ieeexplore.ieee.org/document/11454448/),
  frames why detecting an error is weaker than controlling consequences.
- HoloClean (PVLDB, 2017),
  [paper](https://www.vldb.org/pvldb/vol10/p1190-rekatsinas.pdf),
  already developed constraint- and probabilistic-evidence-based data repair.
- [Snowflake data-eng-bench](https://github.com/Snowflake-Labs/data-eng-bench)
  and [Astronomer de-bench](https://github.com/astronomer/de-bench)
  already test data-engineering agents on real pipelines.

Our potentially distinctive contribution, **if robustly established**, would
be a *longitudinal* controlled benchmark of good-faith agent handoffs that
measures end-to-end **correctly preserved information, wrong published facts,
and over-quarantined good data** across real data platforms and evidence tiers.

## Scientific restrictions / follow-ups

1. Three applied Qwen edits from one trajectory are case studies; results
   are **not detection rates** or a sample of independent agents.
2. Compare multiple seeds, models and task paraphrases. One trajectory,
   not one payment/row, must be the statistical unit.
3. Quarantine needs operational artifacts: rejected rows, reason IDs,
   accepted rows, blocked group IDs, release decision, incident tickets.
   The prototype emits a machine-readable manifest; a later stage should
   persist these as actual warehouse tables with native dbt tests.
4. Compare available evidence fairly: basic policy checks without ledger,
   external reference feeds and event-log replay **separately**. Perfect
   recovery when the exact ledger is supplied is a sanity bound, not a
   machine-learning breakthrough.
5. Record holdback cost and mistakes made by overzealous policy (e.g.
   benign retries or temporary delayed refunds), alongside prevented harm.
6. Test LLM **free-form** source and SQL code changes in an offline,
   resource-limited disposable sandbox after bounded action testing. No
   generated SQL touches a repository or production environment.
