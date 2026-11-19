# Protection benchmark: observed results — 19 November 2026

**Verified:** [GitHub Actions run 44555458302](https://github.com/mhatipog/dbt-chaos/actions/runs/44555458302)
passed the real dbt/DuckDB matrix and the materialized evidence-dossier
verification. Total: **5 scenarios × 5 policies = 25 matched evaluations**,
built from **five distinct real dbt executions** (identical source,
transformation and process-truth inputs reuse the exact prior dbt result).

**Control:** 1,081 synthetic business events; 64 customers, 480 unique
orders, 471 payment rows before extra legitimate versions. Each run uses
the identical original process, including legitimate history, payments,
refunds, and cancellation events.

Three harmful edits are the **frozen actual Qwen2.5-Coder-0.5B outputs**
from [original Actions run 44544592101](https://github.com/mhatipog/dbt-chaos/actions/runs/44544592101).
The fifth case, an exact duplicate-delivery retry, is a **separately
scripted benign control**—not falsely attributed to a model.

## What was published, detected or blocked?

| Scenario | Raw dbt | Extra monitor | Quarantine | Strict gate | Trusted replay |
|---|---|---|---|---|---|
| Clean control | Correct | Correct | Correct | Correct | Correct |
| Wrong refund (€360 → €721) | Silent error | Silent error | Silent error | Silent error | Evidence recovered |
| Wrong customer segment | Silent error | Silent error | Silent error | Silent error | Evidence recovered |
| Deleted order, orphan payments | Silent error | Detected, **still published wrong data** | Entire report withheld | Entire report withheld | Evidence recovered |
| Benign identical payment retry | Correct (source warning) | Correct (warning) | Redundant row safely removed; correct | **Entire report unnecessarily withheld** | Correct after attested dedup |

**Caution:** a source warning alone is not a root-cause diagnosis or proof
of containment. No policy without external evidence inferred the correct
refund or original customer segment from the observed, internally valid data.

## Report-level consequences

58 date×segment reporting groups exist in the original truth.

| Policy | Case outcomes (5 non-independent scenarios) | Incorrect reporting groups actually published, summed over cases | Reporting groups withheld, summed over cases | Mean correctly delivered absolute business value over the 5 cases |
|---|---|---:|---:|---:|
| Existing raw dbt | 2 correct; 3 silently wrong | 16 | 0 | 93.0% |
| Monitor only | 2 correct; 2 silent; 1 warned but still wrong | 16 | 0 | 93.0% |
| Record quarantine | 2 correct; 2 silent; 1 entirely withheld | 8 | 58 | 76.5% |
| Strict gate | 1 correct; 2 silent; 2 entirely withheld | 8 | 116 | 56.5% |
| Trusted replay | 1 correct; 4 evidence-recovered | 0 | 0 | 100.0% |

**These percentages are descriptive summaries of five deliberately chosen,
cumulative scenarios. They are NOT expected production protection rates,
statistical confidence intervals or an advantage of an LLM cleaner.**
The latter strategy uses a *stronger information source*. It is an
upper bound when fully reliable business events actually exist.

### Error magnitudes

| Scenario | Signed business revenue error in raw output | Sum of absolute date×segment errors | Wrong groups |
|---|---:|---:|---:|
| Wrong refund only | −€361 | €361 | 1 |
| Refund + changed customer segment | −€361 | €4,107 | 7 |
| Previous faults + deleted order | −€484 | €4,230 | 8 |

The second scenario is important: the incorrect customer classification
shifts revenue across segments and therefore produces **substantially
more incorrect group-level information** even though net revenue is
unchanged relative to the first scenario. A total-only reconciliation
would understate harm.

In the last scenario, an observable payment→order orphan means the
quarantine strategy cannot identify the original business group of
the lost order. It therefore withholds all 58 groups instead of
falsely advertising a correct partial report.

In the separate benign retry, a naive strict gate withholds all 58
groups despite the original dbt output already being correct. Thus
stricter rejection **does not monotonically improve utility**.

## What the evidence-backed recovery actually did

The privileged event-ledger replay corrected exactly three records
in the final harmful scenario:

- `customers.row_id=10040`: restore attested segment
- `payments.row_id=30626`: restore attested refund amount
- `orders.row_id=21054`: restore the missing attested order

These are exact, separately attested corrections—not guesses made
by a weak LLM or inferences from the broken snapshot. The result
demonstrates what evidence-based recovery *could* achieve, contingent
on a trustworthy upstream log or signed independent record.

## Inspectable output data

The experiment now exports **228 SHA-256-verified evidence files** plus
`manifest.json` and `protection-matrix.json`. For *every* case and
policy, the downloadable dossier includes the full source tables sent
to dbt, or clearly labelled *unexecuted candidates* if a protection gate
withheld them, and:

- `quarantined_rows.csv` with the actual rejected source row and reason
- `detector_findings.csv` for enabled, non-native detectors
- `held_reporting_groups.csv`
- `published_revenue.csv` containing only actually released output
- `attested_corrections.csv`, populated only for ledger replay
- `publication_decision.json` with scored errors, evidence tiers and
  execution/reuse provenance

[CI artifact](https://github.com/mhatipog/dbt-chaos/actions/runs/44555458302)
is short-lived; the experiment and corpus exporter are permanently
reproducible through code on the research branch.

## Research interpretation and next experiment

The result corroborates the *need* for a benchmark that distinguishes
identifying errors, safely blocking publication, unnecessarily rejecting
good data and genuinely correcting mistakes.

It **does not** establish the hypothesized causal advantage or disadvantage
of lossy inter-agent telephone-game handoffs. That requires matched
20-handoff trajectories, multiple independent seeds and models, fixed
business processes, context controls, and a statistically justified
independent trajectory unit. It also does not establish that our
protections improve on established cleaning or observability products.

Next: implement a **native dbt warehouse-side quarantine** with explicit
accepted/rejected tables and group-level release semantics, and compare
with this external sidecar on the same frozen source snapshots. Add
time-delayed correction evidence to model operational recovery latency
and publishable-data availability.

See [methodology](PROTECTION_BENCHMARK.md) and
[full weak-LLM dataset corpus](FULL_DATASETS_RESULTS_20261119.md).
