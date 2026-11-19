# Process-grounded full dataset generation with weak local LLMs

**Research phase:** v1, 19 November 2026. This extends
[GOOD_INTENTIONS.md](GOOD_INTENTIONS.md) rather than replacing the original
commerce chaos engine. Experimental only, synthetic data, zero production
credentials.

## What is genuinely generated?

An inexpensive local language model may author:
1. A **business-process scenario specification**: size of customer/order
   population and proportions of cancellations, captured payments, refunds,
   and valid customer-profile history.
2. A succession of **operational maintenance edits** in response to
   realistic ambiguous tickets. The model selects among `keep`, deleting
   a visible source row, replaying a delivery, rewriting one visible cell,
   appending a customer snapshot, or modifying the join policy. Its own
   explanation is passed to the next agent.

A deterministic event simulator then expands the proposed scenario to
**hundreds of customers/orders/payments**. The LLM does *not* literally write
hundreds of individual CSV lines; such a method would be expensive, incoherent,
difficult to reproduce, and would compromise the independent ledger.

**Full exported files** include:
- `ledger/process_events.jsonl`: authoritative process events
- `ledger/source_of_truth/{customers,orders,payments}.csv`
- `ledger/business_gold.csv`: independent Python business oracle by day/segment
- `steps/01..N/source_delivery/{customers,orders,payments}.csv`:
  complete source tables after each good-intention intervention
- `steps/01..N/admitted_gold.csv`: source-only business truth
- `steps/01..N/dbt_gold.csv` when actual dbt runs
- `trace.json`: prompts' ticket context, model output, validated operations,
  tests, classifications, business truth discrepancies
- `manifest.json`: seed, process profile, counts, per-file SHA-256 and sizes

Each dataset is self-contained. The source-of-truth events cannot be changed
by an agent; tickets deliberately do not show them. All simulation randomness
is locally seeded and independent of the model sampler.

## Experimental mechanism and meaningful controls

A schema-only generator can satisfy foreign keys without knowing that a
refund happened or that a customer was legitimately re-versioned. The
**event-process-first** generator preserves those facts separately.

For each reporting group `g` the experiment measures:

```text
dbt_output[g] - business_ledger_gold[g]
  = (dbt_output[g] - admitted_source_gold[g])
  + (admitted_source_gold[g] - business_ledger_gold[g])
        transformation error     +     delivery/source error
```

This exposes clean-looking yet factually incomplete source extracts and
cases where source and SQL errors counteract each other.

A tiny model can also propose bad or nonsensical edits. Every step therefore
records **rejected proposals** alongside accepted ones. A rejected action is
not silently repaired to look like a successful mutation. The code only
supports a bounded typed edit language, not unrestricted SQL/Python execution.

**Current controlled baseline:** the scripted planner deliberately simplifies
a customer join then removes a *valid* refund from the admitted dataset.
This tests the full pipeline and export machinery, **not** agent reasoning.

**Two weak models:** Qwen2.5-Coder-0.5B-Instruct and
SmolLM2-360M-Instruct are run locally on a public Ubuntu GitHub Actions
runner, with quantized weights downloaded to temporary space. The two
models may produce entirely different scenario specifications and edits.
Invalid scenario JSON triggers a **recorded deterministic default**, not a
false claim that the model designed that dataset.

## Reproduce

Unit-test event consistency, data provenance, constraints, file hashes:

```bash
python -m unittest discover -s tests -p 'test_full_datasets.py' -v
```

A complete deterministic calibration with actual dbt/DuckDB:

```bash
pip install -e '.[dbt]'
python -m dbt_chaos.full_datasets --agent scripted \
  --seed 20261119 --steps 3 --execute-dbt \
  --output-dir /tmp/full-datasets/calibration
```

Local genuine language model, with package `llama-cpp-python`:

```bash
python -m dbt_chaos.full_datasets --agent llama \
  --model /path/to/model.gguf --steps 6 --execute-dbt \
  --output-dir /tmp/full-datasets/qwen
```

For matched model-behaviour controls, add `--fixed-profile` to remove
scenario-size confounding, then compare `--context-mode handoff` against
`--context-mode full_history` or `--context-mode no_notes`. Use *different
output directories* for each run. The exported artifacts are immutable
per-run; reusing a nonempty folder raises an error.

[GitHub Actions dataset workflow](../.github/workflows/full-datasets.yml)
checks the deterministic calibration, then runs two genuine CPU-only models,
exports the complete datasets and uploads tiny 1-day retention artifacts.
No cache or full model weights are uploaded, and no code changes are pushed
from model output. Outputs can be downloaded from the corresponding Actions
run's artifact section.

## Quality and scientific caveats

1. The generated business process is a minimal **orders → capture/refund**
   simulator. It still simplifies many real business rules (chargebacks,
   temporal customer attribution, partial fulfillment, taxes, multiple
   currencies). It should not be called a digital twin of production.
2. The model selects concrete operations on **visible source rows** and a
   current transformation choice. It does *not* freely author SQL or source
   ingestion code; that remains a separate sandboxing milestone.
3. Single trajectories do not establish a telephone-game effect. Compare
   randomized seeds, multiple models, full-context controls, task order and
   benign/no-op baselines, and report **negative results**. Pre-register
   evaluation thresholds before ranking models.
4. A model-proposed profile changes the difficulty of the task. Cross-model
   comparisons need **fixed-profile matched trials**, not naive comparison
   of different generated populations.
5. Guarding values against simple structural and business-invalid mutations
   does not make the extracted dataset trustworthy. The independent event
   ledger is essential to detect silent source loss.
6. Our benchmark's novelty would be **multi-stage cumulative process-to-data
   semantic drift with independent executable truth**, not the existence
   of dbt tests, code agents, random corruptions or the telephone game
   alone. Data-eng-bench already evaluates real dbt engineering agents
   ([Snowflake, 2026](https://www.snowflake.com/en/blog/engineering/data-eng-bench-data-engineering-agent-benchmark/));
   ELT-Bench evaluates end-to-end pipeline generation
   ([PVLDB, 2025](https://doi.org/10.14778/3773749.3773750)).

## Follow-up experiment

The immediate next step after these first **full datasets** is an equally
seeded comparison of scripted, two LLMs, clean no-op, and randomized edits;
each under lossy vs full-history handoff, with at least 20 task seeds and
explicit unit-of-analysis per trajectory (not per row). We then test
restricted natural-language-to-SQL code editing only inside disposable
read-only, resource-limited containers. This can reveal genuinely new
mistake types without permitting model-generated code to touch the
repository or a real account.
