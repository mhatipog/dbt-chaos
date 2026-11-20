# dbt-chaos

**Vecture open-source R&D: engineer adverse data conditions, prove whether transformations remain correct, and measure tradeoffs.**

Status: experimental v0.2. The framework is synthetic-only and makes no claim to exercise every possible real-world fault.

## New: one-command executed-SQL resilience assessment

Run a full synthetic **procurement + grants** assessment without API keys,
model downloads or warehouse access. It compares six operational review cases
per domain under different evidence gates, demonstrates a held reporting group
and a signed simulated receipt recovery, and writes JSON/Markdown/HTML evidence.

```bash
pip install -e .
dbt-chaos assess-demo --out-dir /tmp/business-truth-assessment --fail-on-unsafe
```

All SQL in this command runs against the **local SQLite reference**, not a
connected dbt/Fabric/Databricks warehouse. No real LLM authors the proposed
edits; do not interpret green controls as production assurance.
[Complete scope, outputs and limitations](docs/ASSESSMENT_PACK.md).

## Start here: measure garbage in → trustworthy output

The **[practical user guide](docs/USABLE_WORKFLOW.md)** now provides three
fully reproducible workflows:

1. **Immediate real dbt demonstration** (no LLM needed): reapply a
   previously recorded genuine weak-model refund mistake, then compare
   unprotected dbt, native quarantine and an evidence-gated maintainer.
2. **Actual local weak-LLM chain**: ask a free 0.5B model to act in good faith
   over 20 data maintenance handoffs; export every synthetic source snapshot
   and grade final business output independently.
3. **Bring your own data platform**: load public clean and chaotic CSVs into
   your own isolated dbt/Fabric/Databricks pipeline, keep the process oracle
   private, then score the platform's `clean.csv` / `chaos.csv` output.
   No production credentials or remote actions required.

After installing real dbt dependencies:

```bash
pip install -e '.[dbt]'
dbt-chaos evidence-demo --out demo.json --markdown-out demo.md
```

To test your own isolated platform immediately **without installing
a model or dbt**, replay our previously recorded real Qwen mistake:

```bash
pip install -e .
dbt-chaos export-challenge --starter \
  --public-dir challenge-public --private-dir challenge-private
```

For fresh weak-LLM scenarios, replace `--starter` with a generated corpus:

```bash
dbt-chaos export-challenge /path/to/corpus/relay \
  --public-dir challenge-public --private-dir challenge-private
```

Then score whatever that platform actually published:

```bash
dbt-chaos score-challenge \
  --public-dir challenge-public \
  --answer-key challenge-private/answer_key.json \
  --published-dir your-platform-outputs \
  --out platform-assessment.json --fail-on-silent
```

This evaluates the **reference synthetic commerce contract** on any platform;
it does not yet infer the semantics of arbitrary user schemas. It deliberately
distinguishes **an LLM edit held for review**, **a source row quarantined**,
**an alert raised**, and **a wrong business value actually published**.

## New: process-first chaos for multiple business domains

The [declarative process-contract guide](docs/PROCESS_CONTRACTS.md) expands
the synthetic benchmark beyond hardcoded commerce. It ships validated
[procurement](contracts/procurement.json) and
[grant-disbursement](contracts/grants.json) contracts: configurable
party→document→money-movement tables, legitimate history and retries,
business status/currency rules, and positive/negative money movements.

The contracts generate public clean/chaos CSVs, a **separate private
process-event oracle**, optional source-only quality SQL probes and a
reference SQL transformation. No model download, production data, dbt
adapter or cloud account is needed for the reference implementation.

```bash
pip install -e .
dbt-chaos contract-generate \
  --contract procurement --fault rewrite_credit \
  --seed 20261119 --public-dir procurement-public \
  --private-dir procurement-secret

dbt-chaos contract-reference \
  --public-dir procurement-public --output-dir procurement-reference
dbt-chaos contract-probe \
  --public-dir procurement-public --out procurement-probes.json
dbt-chaos contract-score \
  --public-dir procurement-public \
  --answer-key procurement-secret/answer_key.json \
  --published-dir procurement-reference --out procurement-assessment.json
```

The same engine also executes `contracts/grants.json` with different
table names, movement kinds and business statuses. Five fault scenarios
per domain are validated using the **event-ledger oracle, delivered-source
oracle and actual SQL execution**, with no answer-key leakage.
[Exact measured findings](docs/PROCESS_CONTRACT_RESULTS_20261119.md) ·
[Verified 26-test / 10-case CI run](https://github.com/mhatipog/dbt-chaos/actions/runs/44615377506).

**Important:** These new domain faults are scripted *human-like
calibration*, **not fresh LLM-generated errors**. The process-contract DSL
currently covers a constrained three-role transactional family, not
arbitrary inferred workflows or production-ready Fabric/Databricks
deployment. Optional SQL checks are not native installed quarantine
controls; plausible incorrect money can still pass them.

## New: reconcile across six sources, not just test individual tables

An actual data platform can sometimes detect a seemingly plausible
**€49 → €29 refund error**—but only if it has additional, independently
observable information. dbt-chaos now simulates an operational extract,
**payment-provider receipts**, a correlated internal accounting journal
and **bank-like aggregate settlement evidence**, with configurable
arrival delays and an independent process oracle.

The opt-in native SQL implementation catches the real previously recorded
Qwen agent error and **withholds only two affected reporting groups**.
In the verified dbt run, the ungated report silently overstated revenue
by **€20**. The reconciliation publication surface exposes **€0 incorrect
revenue** while still delivering correct values for the other 56 groups.
It neither guesses the correct refund nor claims the held groups were
published. [Real execution](https://github.com/mhatipog/dbt-chaos/actions/runs/44608231036).

```bash
pip install -e '.[dbt]'
dbt-chaos reconcile-demo \
  --scenario qwen_refund_source_only \
  --out reconciliation.json --fail-on-silent
```

Or test your own **isolated** data platform with six complete synthetic
source/evidence CSV files, without dbt or an LLM:

```bash
pip install -e .
dbt-chaos export-reconciliation \
  --scenario qwen_refund_source_only \
  --public-dir six-source-inputs \
  --private-dir hidden-process-gold
```

The platform returns its *actually published* `published.csv` and optional
`held.csv`. Run `dbt-chaos score-reconciliation` against the private
answer key afterward. No production credentials are handled.

Crucial negative control: **when every supplied source consistently
reports €29 instead of €49**, even the new reconciler cannot know it
is wrong. The benchmark labels that case *unobservable with provided
evidence*, rather than unfairly attributing a detection failure to the
platform. Provenance labels alone are not cryptographic attestation.

[Detailed six-source methodology, cases, commands and limitations](docs/MULTISOURCE_RECONCILIATION.md).

## Verified results

On 17 November 2026, **120 actual dbt/DuckDB experiments** completed on public GitHub-hosted runners: 20 synthetic individual faults × 6 strategies, without infrastructure errors. Correct scenarios: full refresh 20/20, source-version CDC 20/20, ingestion-offset 20/20, rolling lookback 17/20, inclusive watermark 15/20, strict watermark 13/20. Incorrect results escaped the four basic dbt tests. The 20/20 outcomes are limited to this suite, not general reliability guarantees.

[Full evidence and caveats](docs/RESULTS.md) · [Machine-readable aggregate](docs/results/full-matrix-2026-11-17.json) · [Public 120-test run](https://github.com/mhatipog/dbt-chaos/actions/runs/44039321822)


## Source x SQL chaos: real three-table commerce platform

The separate commerce workload joins synthetic orders, customers and payments.
Its first 30-case real dbt benchmark completed successfully: 10 correct, 10 contained,
1 detected failure, 9 silent output corruptions, and no execution errors.
[Verified two-axis evidence](https://github.com/mhatipog/dbt-chaos/actions/runs/44056498668).

It compares daily net EUR revenue with an independent Python business contract.

Source chaos covers duplicates, orphan customers, invalid payments, wrong
currency, cancellations, version changes, missing refunds and split captures.
SQL chaos covers missing deduplication, wrong joins, sign reversals, ignored refunds,
omitted filters and incorrect aggregation grain. Pair cases test interactions.

The output explicitly distinguishes correct, contained, detected_failure,
silent_corruption and execution_failure. Source data-quality alerts are
recorded separately from errors in published gold metrics.

Run real dbt in a disposable local DuckDB environment:

~~~bash
python -m pip install -e '.[dbt]'
dbt-chaos commerce --source duplicate_customer --sql skip_customer_dedup
dbt-chaos commerce-bench --selection representative --out commerce-results.json
dbt-chaos commerce-report commerce-results.json --out commerce.html
~~~

The reference contract cannot infer missing source events without an external
reconciliation feed. See docs/COMMERCE_CHAOS.md for the exact workload contract.

## Experimental good-intentions LLM dataset corpus (research branch only)

The `research/good-intentions-handoff-20261119` branch adds a bounded
**process-first** data-generation experiment:

- Generate an immutable synthetic commerce event ledger; expand it into
  complete relational source CSVs with a separately computed gold oracle.
- Give tiny, CPU-only, open-weights LLMs plausible operational tickets and
  let them propose concrete source-cell edits, delivery changes or an
  allowlisted SQL transformation choice.
- Re-run actual dbt/DuckDB on every complete source snapshot, measure
  signed and absolute **business** drift against the independent process
  ledger, and record rejected/invalid model output without faking an edit.
- Export complete reproducible datasets, manifests, hashes and model
  responses; verify their provenance with
  `python -m dbt_chaos.audit_corpus PATH`.

The [first verified two-model run](https://github.com/mhatipog/dbt-chaos/actions/runs/44544592101)
produced six full snapshots each for Qwen2.5-Coder-0.5B and SmolLM2-360M,
plus a separate scripted three-snapshot calibration. In one Qwen trajectory,
three model-authored source mistakes passed existing dbt tests but deviated
from business-ledger truth. SmolLM mostly produced malformed instructions,
safely rejected by the experiment.

**Do not infer a population failure rate or a causal telephone-game effect
from these single trajectories.** Neither model generated a valid initial
process profile; the baseline event ledger came from our deterministic
simulator, while the model-authored edits were genuinely executed.

The [25-case protection matrix](https://github.com/mhatipog/dbt-chaos/actions/runs/44554736365)
evaluates unprotected dbt, monitoring, row quarantine, strict release
gating and external-ledger recovery against the SAME source mistakes.
It includes a benign retry to measure unnecessary rejection of good data.
A separate [native dbt quarantine implementation](https://github.com/mhatipog/dbt-chaos/actions/runs/44557372785)
also passed actual DuckDB tests, with opt-in SQL tables for rejected rows,
accepted payments, held reporting groups and released gold output.

**Protection evidence is tiered:** source-only policies must not access the
business ledger; fully trusted event replay is a separate upper bound, not
an inferred repair. The default SQL and benchmarks remain unchanged.

**New longitudinal result (19 Nov 2026):** Five genuine 20-step
Qwen0.5B maintenance chains, with frozen business-process task tapes,
produced one €20 silent refund error in the lossy relay arm and none
in its anchored/fresh controls or the second seed. Real dbt (and even
the new native payment quarantine model) published the plausible but
false revenue without an alert. This is a single exploratory positive
example, **not yet causal evidence for a telephone-game effect**:
the matched anchored proposal was malformed and rejected.
[Actual model run](https://github.com/mhatipog/dbt-chaos/actions/runs/44584273184)
· [native dbt replay](https://github.com/mhatipog/dbt-chaos/actions/runs/44587779645).

Details: [longitudinal results](docs/RELAY_RESULTS_20261119.md) ·
[matched experimental protocol](docs/MATCHED_RELAY_20.md) ·
[full dataset method](docs/FULL_DATASETS.md) ·
[model-generated data results](docs/FULL_DATASETS_RESULTS_20261119.md) ·
[protection policy findings](docs/PROTECTION_RESULTS_20261119.md) ·
[native dbt implementation](docs/NATIVE_QUALITY.md).

## What is actually implemented?

- A versioned, seed-independent JSON replay format with event IDs, source versions, logical timestamps, amounts in integer cents, and CDC tombstones.
- Twenty executable reproducible fault recipes across temporal, delivery, CDC, validation, scale and execution scheduling categories, with twelve additional categories clearly marked *planned*.
- Deterministic compound-fault generation (up to three operators), stable independent source-version business oracle, replay, and bounded failure minimization.
- Six comparison strategies: strict and inclusive timestamp watermarks, bounded lookback, ingestion-offset processing, source-version CDC, full refresh.
- Transparent model-screening metrics: silent corruption, detection, domain coverage, processed work units and a workload-specific score.
- Independent real dbt Core and DuckDB integration, real dbt test outcomes, reference full refresh, bounded benchmark runner, and separate real-evidence scoring.
- The original ten-case dbt benchmark retained under `benchmarks/legacy`.

## Quick start — no warehouse or API credentials

Python 3.10 or newer:

```bash
python -m pip install -e .
dbt-chaos faults
dbt-chaos generate --seed 20261117 --count 100 --out campaign
dbt-chaos bench --seed 20261117 --count 100 --out scores.json
dbt-chaos report scores.json --out report.html
dbt-chaos replay campaign/0001.json --strategy strict
dbt-chaos minimize campaign/0001.json --strategy strict --out minimized.json
```

**Important:** `bench` reports `python_model_screen`, not actual dbt execution.

To confirm with real dbt and a fresh, disposable DuckDB warehouse:

```bash
python -m pip install -e '.[dbt]'
dbt-chaos verify-dbt campaign/0001.json --strategy strict --out result.json
dbt-chaos bench-dbt --count 3 --strategies strict,offset,full --out verified.json
```

The real benchmark has a default maximum of 12 pipeline/case combinations and a 900-second scheduling budget; each dbt subprocess has a 100-second timeout. A GitHub Actions job also has a hard timeout.

See the public [verified experiment results](docs/RESULTS.md) and [fault coverage matrix](docs/COVERAGE.md).

## Interpreting results

The score is `100 × (1 - silent fault checkpoints / all evaluated fault checkpoints)`. An existing test alert and a model mismatch are recorded separately. An interrupted or invalid experiment is **not** a pass. The absolute score is workload-specific; it is not a probability of real failures. Equal case manifests are required for fair comparisons.

See [the experimental methodology](docs/METHODOLOGY.md). The original experiment can be inspected in [the legacy benchmark](benchmarks/legacy/README.md), and its CI is tracked in GitHub Actions.

## Safety and engineering constraints

All inputs are synthetic. Real dbt execution creates its own throwaway local DuckDB database and project, uses an allowlisted environment, and never accepts an external profile, customer SQL or production connection. No arbitrary server failures or system-level network faults are injected. Public CI uses fresh GitHub-hosted runners, **not** our private persistent Oracle VM. All job permissions are read-only.

## Research gaps

Multi-table relationship faults, transaction interruption and concurrency, true source-delivery deadline reconciliation, schema evolution, SQL-level mutation, cross-adapter Fabric/Databricks parity, financial-domain oracles, and cost measurement remain future research. These are not advertised as verified capabilities.

## Project

Copyright 2026 Vecture. Apache-2.0. Independent open-source research, not affiliated with dbt Labs or Netflix.
