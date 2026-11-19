# Matched good-faith relay experiment — process → handoffs → dbt → business truth

Research specification: 19 November 2026. **Exploratory pilot, not a statistical
claim.** Extends [full event-grounded datasets](FULL_DATASETS.md),
[protection controls](PROTECTION_BENCHMARK.md), and
[native dbt quarantine](NATIVE_QUALITY.md).

## Research question

When a succession of well-intentioned but imperfect maintainers performs
routine data-platform work, does dependence on the previous worker's short
handoff note (rather than access to the original business policy) increase
**actual error in published business metrics**?

The model is told to **preserve correctness**, never to inject failures.
Random malformed output is recorded as a rejected proposal, not disguised as
a successful change.

## Pre-specified experiment

Each matched arm receives:

- Exactly the same immutable process-event ledger and clean initial tables.
- Exactly the same 20 business-maintenance tickets and exposed source rows,
  generated ONCE before any edits. Both tasks and initial process depend on
  the fixed seed.
- The same CPU-only local open-weights model and sampling settings, freshly
  instantiated per arm. Its own context is not carried across arms.
- The same bounded source edit operations and dbt SQL mutation choices;
  changes are **not** model-generated code and cannot touch production.
- The same independent Python business oracle; every step's **full source
  tables** are exported with SHA-256 manifests, and real dbt/DuckDB is
  executed at steps 1, 5, 10, 15 and 20.

Experimental conditions:

| Arm | Original business policy | Inherited predecessor note |
|---|---|---|
| `relay` | Initially only, then unavailable | Last note after each handoff |
| `anchored` | Repeated verbatim at every handoff | Last note after each handoff |
| `fresh` | Repeated verbatim at every handoff | Never |

The original policy includes six separate data-engineering invariants:
genuine refunds require evidence before removal; valid customer history
must not turn into join fan-out; retries should be idempotent; completed EUR
net revenue adds captures and subtracts refunds; delivered data can omit
real upstream events; uncertainty should not be silently resolved through
invented source changes.

**What is being isolated:** the presence versus loss of the *original written
policy* during a handoff. This is not a complete isolation of every possible
telephone-game mechanism. Successors in the relay condition still receive
the current delivered-source metadata and the actual ticket. That is
intentional and makes the test less artificial than text-only relay chains.

## Primary outcomes

- **Absolute business error (cents):** sum of |actual dbt revenue −
  independent event-ledger revenue| across all day × segment groups, measured
  on each REAL dbt checkpoint. A dimension-reclassification error can have
  zero net error but a large absolute error.
- **Source-only L1 error (cents):** independent admitted-source oracle versus
  original process-ledger gold, measured at EVERY handoff. It is not a
  substitute for real SQL output when the model changes the transformation.
- First handoff when nonzero source error emerges; first CHECKPOINT when real
  output error is observed (its actual onset could be earlier).
- Model proposal JSON validity, allowed operations, applied vs rejected edits.
- Source tests and output tests that the existing dbt project actually ran,
  separately from optional richer checks.
- Number of notes with literal policy IDs (`P01` etc.), **diagnostic only**:
  repeating an ID does not demonstrate correct semantic transmission.

The experiment exports `comparison.json` with full trajectories and
one complete corpus per arm, including all intermediate tables and model
responses. `python -m dbt_chaos.audit_corpus PATH` independently replays
all accepted proposals and recomputes admitted-source oracle results.

## Calibration and controls

Before making model claims, CI checks:

1. **No-op worker:** 20 clean full-table snapshots per arm, zero source
   error, independently reproducible and auditable.
2. **Scripted context-sensitive worker:** deliberately drops a real refund
   when original policy is absent, demonstrating that the *experiment itself*
   is sensitive to losing the charter; this is **not LLM evidence**.
3. **Existing corpus and dbt regression tests:** guard against an unrelated
   change to the existing benchmark.
4. **Genuine weak-model arms:** real local Qwen2.5-Coder 0.5B,
   `relay`/`anchored` for two matched process seeds, with `fresh` also
   tested on the first seed. The model decisions can be harmless or invalid;
   failures must not be injected to force a positive result.

No remote inference API, credentials, persistent model weights or paid
compute tiers are required. GitHub public runners are ephemeral and the
full-source evidence artifact is retained only briefly.

## Execute

```bash
python -m unittest discover -s tests -p test_relay_benchmark.py -v

# Causal PLUMBING calibration; do not cite as model evidence:
python -m dbt_chaos.relay_benchmark \
  --agent scripted --seed 20261119 --steps 8 \
  --modes relay anchored fresh --checkpoints 2 8 \
  --output-dir /tmp/relay-calibration

# Real model (requires llama-cpp-python and local GGUF weights):
python -m dbt_chaos.relay_benchmark \
  --agent llama --seed 20261119 --steps 20 \
  --modes relay anchored fresh --checkpoints 1 5 10 15 20 \
  --model /path/to/model.gguf \
  --output-dir /tmp/relay-actual

python -m dbt_chaos.audit_corpus /tmp/relay-actual/relay
```

[GitHub workflow](../.github/workflows/relay-20.yml).

## Prior work and what would truly be new

- [When LLMs Play the Telephone Game (ICLR 2025)](https://proceedings.iclr.cc/paper_files/paper/2025/hash/dbdea7859f1d2fc10f2c9e79b8f5ae54-Abstract-Conference.html)
  already studies chained transmission drift. Chaining models is *not* novel.
- [A ground truth approach for assessing process mining techniques (2025)](https://link.springer.com/article/10.1007/s44311-025-00006-8)
  demonstrates process-model-based synthetic defects against independent truth.
- [Synthetic event data generation systematic review (2026)](https://link.springer.com/article/10.1007/s44311-026-00060-w)
  discusses how synthetic event logs need structural and temporal fidelity.
- [Data quality in object-centric event data (2026)](https://link.springer.com/article/10.1007/s44311-026-00043-x)
  classifies imperfect event records in process analytics.
- [Snowflake data-eng-bench (2026)](https://www.snowflake.com/en/blog/engineering/data-eng-bench-data-engineering-agent-benchmark/)
  and [dbt Labs ADE-bench](https://www.getdbt.com/blog/ade-bench-dbt-data-benchmarking)
  already evaluate data-agent tasks and business correctness.

Our *potential* differentiator is the effect of inherited operational
context on a succession of genuinely applied **data-engineering changes**,
measured against real pipeline output and independent executable process
truth—and then the impact of **quarantine vs safe publication** on usefulness.

## Threats to validity and follow-up

- Two process seeds are *exploratory pilot evidence*, not a reliable
  population estimate. For inferential claims, freeze a preregistered design
  and use many independent seeds/model runs with **whole trajectories** as
  analysis units; never count rows or checkpoints as independent replicates.
- Context-dependent changes cause later source states to diverge between
  arms. A stronger next experiment can pair **counterfactual decisions from
  identical pre-edit states** as well as end-to-end trajectories.
- The operations menu is bounded. Source modifications are concrete but
  SQL changes are pre-defined allowlisted options; later free-form SQL
  editing requires separate disposable, network-isolated execution.
- The model could misunderstand the ticket because it is simply weak,
  irrespective of the inherited note. A lossiness effect is established
  only through **matched control differences**, not by bad outcomes alone.
- Real source truth is only observable to the *evaluator* through a
  synthetic upstream event ledger. A deployed platform without access
  to that evidence cannot generally infer a missing genuine refund.
- Better protective pipelines must be judged by both *incorrectly published*
  facts and *genuinely correct business information withheld*.
