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
  --model /path/to/qwen2.5-coder-0.5b-instruct-q4_k_m.gguf \
  --output /tmp/handoff-model.json
```

The GitHub Actions workflow runs the five scripted calibration steps on real
dbt, then runs a separate model-driven arm on ephemeral GitHub public runners.
The model arm is *not guaranteed to make a mistake*. It records actual actions,
parsing failures and outcomes. It does not use a paid inference API, persistent
artifacts, a runner cache, credentials, or external production datasets.

## Quantitative error attribution and counterfactual context control

For every output group `g`, the error is decomposed exactly as:

```text
dbt_output[g] - process_truth[g]
    = (dbt_output[g] - oracle(admitted_source)[g])
    + (oracle(admitted_source)[g] - process_truth[g])
        transformation drift                source-delivery drift
```

The runner retains group-wise mismatches and signed aggregate cents across
these three views. **A clean result relative to admitted data does not prove
business correctness.** If the two error components cancel out, the state is
marked `masked_errors`, rather than falsely called genuinely correct.

The local LLM workflow now runs two paired arms, using the same weights,
same seed and same task sequence (but separate model sessions):

- `--context-mode handoff`: only the previous agent's summary.
- `--context-mode full_history`: previous summaries, actions and tasks.

The default is the lossy `handoff` condition. `--context-mode no_notes`
is also available for a later negative control. The agent's current
observable table metadata remains identical across modes, and none can
see the independent ledger or correctness results.

**Initial observed pilot (2026-11-19):** [GitHub Actions run 44532494665](https://github.com/mhatipog/dbt-chaos/actions/runs/44532494665)
used real CPU-only Qwen2.5-Coder-0.5B and real dbt. Its four actions
were `simplify_customer_lookup`, then three consecutive
`record_customer_version` operations; silent output corruption appeared
at step two. The model made irrelevant choices on later tasks, so this
single run illustrates weak-agent misinterpretation, **not proven
telephone-specific degradation**. A full-history matched control is
required to test that claim.

### Paired handoff-context result — 19 November 2026

[GitHub Actions run 44533873836](https://github.com/mhatipog/dbt-chaos/actions/runs/44533873836)
**passed** both scripted real-dbt calibration and two separate local 0.5B
Qwen-driven real-dbt runs. With the same seed, weights, tasks, and clean
initial state, the two context policies produced **identical trajectories**:

| Iteration | Handoff-only action | Full-history action | Signed business error in *both* |
|---|---|---|---|
| 1 | `simplify_customer_lookup` | same | 0 cents |
| 2 | `record_customer_version` | same | +10,000 cents |
| 3 | `record_customer_version` | same | +20,000 cents |
| 4 | `record_customer_version` | same | +30,000 cents |

Both first diverged from process truth at iteration 2, with silent output
corruption and zero invalid model outputs.

**Negative but important result:** Under this seed and action menu, **full
history was not better than the lossy telephone-game condition**. Thus the
pilot does *not* support a causal claim that handoff information loss caused
the observed corruption. A likely alternative is that the low-capability
model repeatedly selects an irrelevant action from a restricted menu, and
that the explicitly offered SQL simplification directly seeds a known
failure. This is now a verified technical research platform, not yet
evidence of the desired telephone-game mechanism.

A stronger follow-up must provide per-task actionable documentation,
counterbalance task wording, compare multiple models/seeds and action
menus, and especially permit independently sandboxed free-form edits.
Report negative results, not just the highest-error trajectories.

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
- [When LLMs Play the Telephone Game (ICLR 2025)](https://proceedings.iclr.cc/paper_files/paper/2025/hash/dbdea7859f1d2fc10f2c9e79b8f5ae54-Abstract-Conference.html):
  iterated LLM cultural transmission is established prior art; the mere idea
  of 20 sequential reinterpretations is **not** novel.
- [LLM as a Broken Telephone (ACL 2025)](https://aclanthology.org/2025.acl-long.371/):
  semantic information distortion through iterative generation.
- [Handoff State Continuity Benchmark (2026)](https://www.alphaxiv.org/abs/2610.36523):
  work continuation and repository-evidence retrieval under inherited state.
- [The Handoff Tax (2026)](https://www.alphaxiv.org/abs/2608.24358):
  impact of inherited information on coding-agent task quality.
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
