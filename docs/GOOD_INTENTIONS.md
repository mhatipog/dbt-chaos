# Good-intentions handoff experiment (research PoC, 2026-11-19)

**Research question:** Can a succession of reasonably motivated maintenance
decisions create latent semantic data corruption that ordinary dbt tests do not
detect, even when the original input data is valid?

This is a **bounded first prototype**, not a production-ready human simulator or
a claim of general agent reliability. The repository's existing real
dbt/DuckDB commerce SQL, tests, and independent Python oracle remain in use.

## Process before schema

The declared source-of-truth is a small **commerce process ledger**: customer
profiles may have legitimate new versions, orders are completed or cancelled,
and payments include captures/refunds. The schema is an implementation of that
process, not enough on its own to infer missing refunds or valid customer
history. For now we start from the existing 3-customer commerce baseline.

Each handoff maintains three separate objects:

1. **Process ledger** (hidden authoritative history). Only genuine process
   events, e.g. a legitimate customer version update, modify this.
2. **Admitted source extract** (what dbt actually receives). Good-faith
   operational mistakes can omit or duplicate delivered events.
3. **Transformation state** (the selected SQL staging variant). The existing
   allowlisted SQL mutation uses direct customer joins instead of a
   latest-version selection.

The agent sees only task instructions, table names/counts/columns, current
lookup description and the *previous agent's note*. It cannot read the hidden
ledger, independent oracle, full previous prompts or test outcomes. Every
decision is one of six allowlisted operations; arbitrary model-proposed SQL,
shell commands and network destinations are never executed.

## Causal calibration sequence (scripted, not an LLM result)

| Step | Plausible maintenance action | Expected diagnostic observation |
|---|---|---|
| 1 | Simplify customer join by removing latest-version selection | Currently harmless with one version per customer; source & gold tests pass |
| 2 | Record a **valid** new version of customer 1, same segment | Earlier SQL shortcut becomes wrong; fan-out and silent gold corruption, no source alert |
| 3 | Remove a refund mistakenly thought duplicated | Source extract loses a real event; the process ledger still contains it |
| 4 | Restore latest-version customer selection | Output matches admitted-source oracle again, but the loss of the true refund remains invisible to source-only tests |
| 5 | Retry delivery of a customer snapshot | Source duplicate test flags invalid delivery; output remains correct with restored dedup |

This tests **latent defects activated by legitimate process evolution**, and
separately tests **source correctness versus process correctness**.

Important: The source-loss mismatch cannot be inferred from the admitted
snapshot alone. Its ground truth comes from our synthetic hidden process
ledger. We must never claim that the pipeline could self-detect the missing
refund without an external event ledger.

## Run

Fast, standard-library state tests:

```bash
python -m unittest discover -s tests -p test_handoff.py -v
python -m dbt_chaos.handoff --agent scripted --steps 5
```

Real dbt/DuckDB checks (existing pinned dependencies):

```bash
pip install -e '.[dbt]'
python -m dbt_chaos.handoff --agent scripted --steps 5 --execute-dbt --output /tmp/handoff.json
```

Optional genuine **small local model**: install `llama-cpp-python`, obtain
Qwen2.5-Coder-0.5B-Instruct Q4_K_M GGUF, then:

```bash
python -m dbt_chaos.handoff --agent llama --steps 4 --execute-dbt \
  --model /path/to/qwen2.5-0.5b-coder-instruct-q4_k_m.gguf \
  --output /tmp/handoff-model.json
```

The GitHub Actions workflow runs the five scripted calibration steps on real
dbt, then runs a separate model-driven arm on ephemeral GitHub public runners.
The model arm is *not guaranteed to make a mistake*. It records actual actions,
parsing failures and outcomes. It does not use a paid inference API, persistent
artifacts, a runner cache, credentials, or external production datasets.

## What this does NOT establish

- The PoC's operations are predefined; the model chooses them using natural
  language, but does not freely edit SQL. A later phase should test arbitrary
  patches in a stronger disposable sandbox and compare against this baseline.
- The scripted trajectory deliberately contains faults and is **not evidence**
  that a model or human would choose them.
- A single weak model trajectory is anecdotal. Use many seeds, tasks, models,
  benign controls, shuffled order and repeated full-context controls before
  making any statistical statements.
- The initial ledger is a hand-built process snapshot, not a realistic
  event-driven domain simulator. A future generator should derive data from
  executable event/process rules, perhaps with model2data materializing clean
  relational starting fixtures.
- There is no assertion that schema inference alone reveals business intent.

## Design rationale and literature check

The PoC targets *semantic* correctness missed by routine test-based evaluation.
Adjacent work already studies coding-agent reasoning failures and error
propagation; our possible contribution would be a measured connection between
**sequential, good-faith data-engineering decisions**, real dbt semantics,
process-ledger truth and test outcomes. It is currently a hypothesis, **not
a proven novel result**.

Relevant recent work (not exhaustive):

**Closest prior benchmarks to investigate before claiming novelty:**
- [Snowflake data-eng-bench (2026)](https://github.com/Snowflake-Labs/data-eng-bench):
  103 real dbt/data-engineering tasks, hidden row-level verifiers, substantial
  business-process semantics. Our differentiator must be **longitudinal,
  good-faith drift with previous-agent context**, not just dbt + an oracle.
- [Astronomer de-bench (2026)](https://github.com/astronomer/de-bench):
  139 data-engineering tasks including Airflow and dbt, with execution grading.
  Again, individual task success is not itself novel.
- [DataClawEval (2026)](https://arxiv.org/abs/2607.28033):
  end-to-end real-engine data engineering agent tasks and deterministic graders.
- [Synthetic event generation systematic review (2026)](https://link.springer.com/article/10.1007/s44311-026-00060-w):
  process-control-flow and attribute-dependency realism remain challenging;
  supports moving from schema-derived fake tables to process-event generation.

- [From Faulty Claims to Incorrect Patches (2026)](https://arxiv.org/abs/2610.32338):
  flawed reasoning during code agent tasks.
- [SWE-Bench Pro Verified (2026)](https://arxiv.org/abs/2609.08149):
  limits of judging software engineering agents with available benchmarks.
- [Agent Error Simulator (2026)](https://cs.iit.edu/~scs/assets/files/bateman2026agenterrorsimulator.pdf):
  controlled faults in agent workflows.
- [SABER: Small Actions, Big Errors (2025)](https://cdn.amazon.science/74/ec/867848fa44bda73d6237dfd6183d/saber-tau-bench-verified.pdf):
  consequences of mutating agent actions.
- [GitHub standard public runners](https://docs.github.com/en/actions/how-tos/write-workflows/choose-where-workflows-run/choose-the-runner-for-a-job):
  standard runners are free for public repositories.
- [Qwen2.5-Coder 0.5B GGUF](https://huggingface.co/Qwen/Qwen2.5-Coder-0.5B-Instruct-GGUF):
  local GGUF model distribution, rather than a paid API.

## Next falsifiable experiment

For fixed business tasks, compare: (A) scripted faults, (B) independent
randomized bounded edits, (C) local weak LLM with each handoff seeing only the
previous summary, and (D) identical model with full context. Collect:
semantic output drift, source-vs-ledger discrepancy, detection rate, first
harmful decision, valid patch rate, and agent output parsing success, all on
**genuinely held-out process cases**. Report failure modes and negative results.
