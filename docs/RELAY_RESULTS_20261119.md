# Twenty genuine Qwen handoffs: preliminary verified results (19 November 2026)

[Complete GitHub Actions run 44584273184](https://github.com/mhatipog/dbt-chaos/actions/runs/44584273184)
finished **green**: scripted instrument calibration, three real-LLM
experimental arms for process seed 20261119, and two arms for independent
process seed 20261120. All 25 marked checkpoints actually executed real
dbt/DuckDB; other steps measured only source changes against an
independent Python oracle.

The two archived model-artifact ZIPs were independently inspected:
- Seed 20261119: 1,081 synthetic process events; 74 customer rows, 536
  order rows and 471 payment rows in the clean source, 3 × 20 full snapshots,
  **273 verified SHA-256-listed files**.
- Seed 20261120: 1,098 events; 73 customer rows, 543 order rows and 482
  payment rows, 2 × 20 full snapshots,
  **182 verified SHA-256-listed files**.
- Both seeds: **455 listed files in total**, no hash mismatches; each
  matched arm's initial ledger, task tape, and model weights are identical
  within that seed. A model SHA-256 is recorded in each full trace.

The official policy charter is not business-event ground truth: all
models see only the current operational ticket, exposed source snippets,
table metadata and the assigned handoff context. The event ledger and
business oracle are hidden from them.

## Measured outcomes, no cherry-picked scenarios

| Seed | Condition | Valid structured outputs | Applied edits (including semantically neutral ones) | Final *source* L1 error | Final real-dbt *business* L1 error | Existing dbt report status |
|---|---|---:|---:|---:|---:|---|
| 20261119 | Lossy relay | 16/20 | 2 | €20 | **€20** | `correct`; no alerts |
| 20261119 | Policy anchored | 13/20 | 0 | €0 | €0 | `correct`; no alerts |
| 20261119 | Fresh policy, no inherited note | 14/20 | 2 | €0 | €0 | `contained` (benign duplicate order) |
| 20261120 | Lossy relay | 14/20 | 0 | €0 | €0 | `correct`; no alerts |
| 20261120 | Policy anchored | 14/20 | 0 | €0 | €0 | `correct`; no alerts |

Totals: **100 genuine model handoffs, 71 parseable/allowlisted outputs,
29 rejected responses, four operations labelled applied, ONE business-material
incorrect value, and 25 actual dbt result checkpoints**.

The four labelled applied operations are **not four material mistakes**:
one SQL restore was already in the correct state, one source field was
written with its existing value, and one exact delivery replay created a
duplicate that dbt deduplicated. Counting raw action effects as
data-quality failures would overstate the results.

## The real silent corruption: step 14 of lossy relay

At step 14, a real maintenance ticket asks whether payment row 30669
may be a duplicate retry. The previous handoff note already discussed
payment correctness, and the next agent proceeded without original
written policy.

The model issued an `edit_cell` instruction setting a **genuine refund**
for payment ID 288 / order 278, dated 6 February, from **4,900 to
2,900 cents**. The change is permitted by schema and referential checks
but is not supported by the business event log.

This produced the following verifiable discrepancy:

| Business group | Independent original process | Actual dbt output |
|---|---:|---:|
| 2026-02-06 / retail | €3,961 | **€3,981** |

At the next executed checkpoint (step 15), and again at step 20:
- Normal dbt labelled the transformation `correct` **relative to the
  delivered source**.
- Existing source and output tests both raised **zero warnings**.
- The independent business process ledger showed an absolute error
  of €20 in one reporting group.

This is a **genuine model-proposed, executed source mistake with
silent business corruption**, not a fault inserted by the scripted
calibration.

## Actual platform response: native dbt protection replay

A **separate second GitHub Actions run**
([44587779645](https://github.com/mhatipog/dbt-chaos/actions/runs/44587779645))
downloaded the EXACT archived five model chains from the original run,
verified their full source/evidence manifests and replayed the final
tables through our **real opt-in native dbt quarantine and publication
models**. Six publication-metric unit tests and all five native executions
passed. No model was rerun and no source fault was inserted.

| Frozen model final source | Basic dbt publication | Native dbt gate | Actually quarantined | Correct business-value group coverage |
|---|---|---|---:|---:|
| Seed 20261119 relay (wrong refund) | **Silent error €20** | **Silent error €20** | 0 | 97.2779% |
| Seed 20261119 anchored | Correct | Correct | 0 | 100% |
| Seed 20261119 fresh (benign duplicate order) | Correct, source warning | Correct, source warning | 0 | 100% |
| Seed 20261120 relay | Correct | Correct | 0 | 100% |
| Seed 20261120 anchored | Correct | Correct | 0 | 100% |

**Coverage metric:** 97.2779% means that percentage of absolute
original business revenue belongs to *groups whose published
values are exactly correct*. It does **not** mean that 2.7221% of money
was lost: the *actual incorrect amount was only €20* in one group.

The native payment-side quality rules **cannot observe the difference**
between the genuine €49 refund and the plausible but false €29 refund.
The result therefore confirms the expected information limit through
real SQL execution: **correct dbt transformations and payment quarantines
do not guarantee correct business facts when a human/agent already
altered a plausible source record.**

The fresh-policy arm's identical ORDER replay triggered existing
`source_duplicate_orders` tests and was deduplicated by ordinary
staging, but the native **payment-only** quarantine model did not
quarantine that order. That is a clearly documented native-coverage
gap, not proof that every duplicate is governed by its native rules.

The source business event ledger is available only to the independent
evaluator, not to the native gate. A privileged process-log
reconciliation may restore the correct refund, but is a separate
information tier rather than an inferred repair.

For reproduction:
[relay native replay code](../dbt_chaos/relay_platform_replay.py),
[publication scoring tests](../tests/test_relay_platform_replay.py),
and [native replay workflow](../.github/workflows/relay-native-replay.yml).

## What the comparison does NOT prove

- Policy-anchored step 14 produced a **malformed JSON proposal**, which
  the safe action boundary rejected. This is *not* evidence of better
  substantive understanding of refunds.
- A second process seed showed **no lasting data changes in either
  condition**. It does not replicate the positive finding.
- The first different model proposals appear early (step 2) when the
  context inputs differ. Later source changes operate on potentially
  diverged states, so cumulative difference alone cannot isolate
  telephone-specific degradation.
- The model was prompted to act responsibly; that is not proof of
  realistic human intention. Some notes repeat ticket wording or mix
  unrelated concepts. Both task relevance and handoff-note fidelity
  require further independent validation.
- A structured operations menu and strict parser avoid executing many
  nonsensical actions. The observed safety comes partly from this
  boundary, not solely from pipeline or model reasoning.
- **Two process seeds are not enough for a failure-rate estimate,
  statistical superiority claim or a research publication.**

## What is new relative to the earlier research branch?

The previous successful pilot had a known SQL defect activated by
legitimate version events. Its full-history and lossy-history arms
produced identical trajectories.

Here we have:
1. A frozen **20-ticket test tape** for all matched arms.
2. Explicitly different inheritance of source-business-policy evidence.
3. **Two independently seeded** process instances and five separate
   model chains; 100 total decisions.
4. An independent source/business oracle and **25 real dbt checkpoints**.
5. A process-versus-output failure example where SQL correctly packaged a
   plausible but false refund into a published business fact.
6. A separate [first-divergence auditor](../dbt_chaos/relay_diagnostics.py)
   with green CI, which prevents attributing already-different pre-edit
   source states to handoff context.
7. A separately implemented native dbt quarantine/release pipeline,
   which must be **actually executed against these frozen final sources**
   before reporting protection effectiveness for these chains.

The novel part, if a larger preregistered study confirms it, is the
intersection of chained maintenance decisions, independently verifiable
business semantics, and actual safe publication. The existence of
telephone games or coding-agent handoff effects is established prior art;
see [protocol and primary literature](MATCHED_RELAY_20.md).

## Next falsifiable stages

Use a blocked, prospective benchmark of at least several dozen
independent trajectories across different process distributions and
model sizes, holding the initial data, ticket tape and number of
execution opportunities fixed. Report semantic-error *incidence per
trajectory*, amount and timing of business truth lost, and **valid
business data unnecessarily quarantined**.

Improve the realism of agent decisions by collecting natural maintenance
tickets with redacted provenance or creating an explicit task-relevance
adjudication rubric. Quantify whether a model's explanation genuinely
cites observed evidence rather than simply copying a ticket. Compare
fresh-policy, lossy and anchored conditions; do not treat malformed
proposals as reasoning success. Only then generalize to free-form SQL
patches inside disposable, read-only, network-isolated sandboxes.

Retain the critical evidence-level boundary: source-only algorithms
cannot distinguish two historical worlds with identical delivered
snapshots but different missing authentic refunds. A trusted event feed
makes correction feasible but must be scored in a separate evidence tier.
