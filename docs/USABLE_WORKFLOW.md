# dbt-chaos — test what happens to business truth

This guide is for **data engineers evaluating what a platform does when
well-intentioned operators or agents make realistic maintenance mistakes.**
It is not a model leaderboard or a tool that should touch a production system.

**What is actually supported:** a repeatable **synthetic commerce** workload
(customers, orders, payments, legitimate customer/order versions, captures,
refunds and cancellations), local real dbt/DuckDB execution, recorded
small-LLM source and transformation choices, independent event-ledger truth,
action evidence gates, and platform-neutral CSV scoring.

**What is not supported yet:** automatic import/inspection of an arbitrary
user's schema, safe execution of their own SQL, automatic deployment to
Fabric/Databricks, real-world incident-rate estimates, or a claim that
every weak-model decision represents a realistic human intention.

## 1. One-command real-dbt demonstration — no LLM to install

From the checked-out research branch:

```bash
python -m pip install -e '.[dbt]'

dbt-chaos evidence-demo \
  --out assessments/refund-demo.json \
  --markdown-out assessments/refund-demo.md
```

This replays one **recorded genuine Qwen2.5-Coder-0.5B** maintenance
proposal (from [the original run](https://github.com/mhatipog/dbt-chaos/actions/runs/44584273184));
it does **not run Qwen again**. In this scenario the agent changed an
authentic €49 refund to €29 while attempting a routine review.

The tool runs real dbt against three versions of the same initial process:

| Mode | Who decides whether to admit the edit? | What should be tested |
|---|---|---|
| Ungated | Accept any typed model proposal | Silent false revenue published (€20) |
| Source-only evidence gate | Admit only proven safe/idempotent edits | Unsupported refund modification held for review; original revenue preserved |
| Attested event evidence | Independently trusted process ledger | Unsupported modification rejected; authentic repairs may be accepted |

Native dbt quality tables are executed alongside the comparison.
**An action awaiting review is not a quarantined source record.**
The report records model action decisions, actual released output and dbt
test results separately.

The command outputs local JSON evidence and a readable Markdown table;
it needs no production connection strings, external profiles or paid API.

## 2. Generate realistic good-faith mistakes with a free small LLM

Install optional local llama.cpp bindings and download a freely licensed
GGUF model yourself. For example, use the same Qwen0.5B version tested
in our reproducible GitHub workflow:

```bash
python -m pip install 'llama-cpp-python>=0.3,<0.4'

python -m dbt_chaos.relay_benchmark \
  --agent llama \
  --model /path/to/qwen2.5-coder-0.5b-instruct-q4_k_m.gguf \
  --seed 20261119 --steps 20 \
  --modes relay anchored fresh \
  --checkpoints 1 5 10 15 20 \
  --output-dir assessments/agent-corpus
```

The model is told to preserve business meaning, never deliberately corrupt
data. It receives business-maintenance tickets with only the source snippets
a worker could plausibly see; the business event ledger stays hidden.
The `relay` mode inherits a short predecessor note, while `anchored`
receives the original business charter on every step.

Every step exports complete source CSVs and recorded decisions. Use the
independent offline auditor before making claims:

```bash
python -m dbt_chaos.audit_corpus assessments/agent-corpus/relay

dbt-chaos evaluate-chain assessments/agent-corpus/relay \
  --tier source_only \
  --out assessments/relay-gated.json \
  --markdown-out assessments/relay-gated.md \
  --fail-on-silent
```

This second command does NOT rerun the LLM. It replays exactly the original
model proposals behind the new evidence gate and tests the resulting source
with real dbt. The experimental questions are: what harmful edits were held
for review, how many safe operations were permitted, and what wrong business
results actually reached the gold reporting table?

When `--tier attested` is selected, independent original event evidence is
explicitly available to the gate. Treat its results as a **different evidence
tier**, not a superior source-only detector.

## 3. Test your own SQL platform without connecting it to dbt-chaos

**Fastest onboarding — no LLM, database, dbt, or paid API required:**

```bash
python -m pip install -e .
dbt-chaos export-challenge --starter \
  --public-dir assessments/public-platform-challenge \
  --private-dir assessments/hidden-answer-key
```

This creates the clean-versus-corrupted three-table datasets by
**replaying the actual accepted €49 → €29 refund edit captured from Qwen
on 19 Nov 2026**. The new command itself does *not* run an LLM, generate
a different model decision, or claim to reproduce a 20-step model run.
It is a real model-action regression fixture for a first-time user.

**More varied challenges:** use any previously generated full corpus (`relay`, `anchored`, or another
`full_datasets` run) to create a **portable two-case challenge**.

```bash
dbt-chaos export-challenge assessments/agent-corpus/relay \
  --step 20 \
  --public-dir assessments/public-platform-challenge \
  --private-dir assessments/hidden-answer-key
```

Share with the platform **only**
`assessments/public-platform-challenge/inputs/`.
The folder has `clean/` and `chaos/`, each with complete
`customers.csv`, `orders.csv`, and `payments.csv`.
Both must run through the **same** candidate transformations and source
tests, just with different inputs.

The business contract is intentionally simple and published in the
challenge's `README.md`: latest customer/order versions, completed EUR
orders, captures minus refunds, output by order date and segment.

Export what the pipeline actually publishes in two CSV files:

```text
assessments/platform-outputs/
    clean.csv
    chaos.csv
```

Each CSV has columns
`order_day,segment,revenue_cents` and **one row per published group**.
If some groups were intentionally held, optionally supply
`--held-dir` with `clean.csv` and/or `chaos.csv` listing
`order_day,segment`. Do not fabricate zero-valued rows as a substitute
for withheld output. If the platform emitted actual alerts, optionally
pass `--alerts-json` containing arrays for both scenarios.

```bash
dbt-chaos score-challenge \
  --public-dir assessments/public-platform-challenge \
  --answer-key assessments/hidden-answer-key/answer_key.json \
  --published-dir assessments/platform-outputs \
  --out assessments/platform-score.json \
  --fail-on-silent
```

`score-challenge` requires **no dbt, database, LLM or API credentials**.
It verifies every public source CSV against the original challenge and
compares independently produced outputs with the immutable synthetic
business process.

### Interpreting the outcome

| Label | What it means |
|---|---|
| `business_correct` | Published clean truth matches the expected original business events |
| `garbage_passed_through` | Correct relative to the **delivered corrupted source**, but incorrect relative to original business truth |
| `detected_but_exposed` | The platform raised an alert but still published wrong results |
| `transformation_or_unexplained_output_error` | Output disagrees with even the correct oracle for the delivered data |
| `safe_partial_hold` | No wrong groups published; some deliberately withheld |
| `all_withheld` | No published results; no wrong numbers, but **zero availability** |
| `correct_output_external_evidence_not_verified` | The output is correct despite corrupted inputs, but the scorer cannot independently establish how it recovered |
| `silent_corruption_or_missing_source` | Business facts missing or incorrect without declared detection/withholding |

The scorer also reports source-error L1, delivered-input transformation
error L1, business-output error, incorrectly published reporting groups
and the **share of correct absolute business value actually delivered**.
Do not add the L1 components directly; only the signed group-wise errors
decompose linearly.

**Important:** A claimed quarantine table or a validation warning is not
itself proof of safe publication. The scorer checks actual output and
intentional withholding separately. A team can additionally attach
rejected-row evidence for human review.

## 4. Advanced: test multi-source reconciliation, not only data validation

The original three-source challenge intentionally demonstrated an
**information-theoretically impossible** validation case: when the only
observed record says €29, no schema or SQL rule can prove the actual
business refund was €49.

The new [multi-source reconciliation module](MULTISOURCE_RECONCILIATION.md)
makes that fact *observable* by supplying independently derived payment
provider receipts, a correlated merchant accounting journal, and a bank-like
net batch feed with explicit availability delays.

Real local dbt:

```bash
pip install -e '.[dbt]'
dbt-chaos reconcile-demo \
  --scenario qwen_refund_source_only \
  --out reconciled.json --fail-on-silent
```

For Fabric, Databricks or another isolated SQL system:

```bash
dbt-chaos export-reconciliation \
  --scenario qwen_refund_source_only \
  --public-dir six-source-challenge \
  --private-dir sealed-original-events

# Load only public CSVs into your test workspace.
# Export actually published reporting groups as published.csv;
# optionally list withheld day/segment groups as held.csv.

dbt-chaos score-reconciliation \
  --public-dir six-source-challenge \
  --answer-key sealed-original-events/answer_key.json \
  --published published.csv \
  --held held.csv \
  --out multi-source-score.json --fail-on-silent
```

This is **six fully populated source/evidence tables**, not a text-only
example. The reference reconciler catches the recorded €20 refund error;
its native dbt publication path withholds affected groups without
fabricating corrected values. A separate test intentionally corrupts
every evidence channel consistently: that case is *unobservable from the
supplied data* and must not be counted as a missed detectable fault.

Both the bank-like buckets and evidence origins are **simulated**.
A real implementation would need authenticated PSP/bank feeds, genuine
payout/settlement calendars, fees and independent provenance controls.

## 5. CI and operational safety

Use `--fail-on-silent` for a job that should fail when the evaluated
platform still exposes incorrect business results. The JSON report is
written before the nonzero exit, so the pipeline can upload evidence.

Each reference dbt execution runs on a new temporary DuckDB database and
a copied project, using pinned dependencies and a restricted subprocess
environment. External vendor-neutral mode only writes and reads CSV;
it **never** connects to Fabric, Databricks or a customer's warehouse,
and it never executes user-provided SQL.

The external platform owner controls how to load the public synthetic
data and where to run transformations. For production-adjacent workflows,
run in an isolated development workspace with synthetic objects only.

## What this still needs before real production adoption

A truly generic platform adapter must handle user-defined schemas,
configurable grain and business oracles, upstream provenance,
source-level process simulation beyond commerce, and independently
verifiable quarantine tables. A generic schema inference alone cannot
tell whether a refund actually happened; process semantics or external
attestation is indispensable.

The short-term roadmap is (a) business-process contract plugins,
(b) safe workflow-driven adapters for Fabric/Databricks/dbt, (c) explicit
trusted evidence inputs, (d) free-form—but sandboxed—maintenance
modifications, and (e) repeated, preregistered trials across many
processes and weak models.

## Research evidence and reproducibility

- [Good-faith 20-handoff experiment](RELAY_RESULTS_20261119.md)
- [Native warehouse protection benchmark](PROTECTION_RESULTS_20261119.md)
- [Native dbt quarantine details](NATIVE_QUALITY.md)
- [Experiment and confidence limitations](MATCHED_RELAY_20.md)

Recent work on LLM-assisted scientific workflows likewise emphasizes
keeping language models off the critical data path where possible,
preserving all model artifacts and independently verifying outcomes
([Patterns 2026](https://pmc.ncbi.nlm.nih.gov/articles/PMC13576654/)).
This is why the LLM proposes errors **without controlling their
classification or the hidden correctness oracle**.
