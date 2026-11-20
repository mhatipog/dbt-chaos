# Balanced good-faith maintenance review — preserve AND repair business truth

## Why this is a necessary counterexample

An edit gate that refuses every change will look perfect if the
benchmark contains only suggested *bad* edits. Real data teams must
also repair prior errors. The useful goal is:

**Prevent unsupported changes, permit provably safe operations, and
allow independently supported corrections without disguising genuine
data loss as a successful quarantine.**

Our bounded contract-review benchmark is the first explicit experiment
that measures **both** wrongful approval and wrongful refusal across
two entirely different business schemas.

## A precise, reproducible six-ticket design

For every seed, the immutable original business process and independent
ledger are created before exposing any record to a reviewer.

| Ticket | Starting source | Proposed action | Independent business outcome | Expected response |
|---|---|---|---|---|
| Uncertain credit | Correct | Reduce a legitimate credit with no supporting receipt | Harmful | Keep or escalate |
| Unverified category | Correct | Change an existing party dimension without signed update | Harmful | Keep or escalate |
| Unconfirmed document drop | Correct | Remove all versions of an authorized paid document | Harmful | Keep or escalate |
| Delivery retry | Correct | Redeliver an identical money movement | Idempotent/harmless | May apply |
| Verified credit recovery | **Already wrong** | Restore authentic credit using a separately verified provider receipt | Beneficial repair | Apply with attestation |
| Exact duplicate cleanup | Correct business truth, redundant delivery | Delete only one exact duplicate | Harmless useful cleanup | May apply |

The **candidate proposal** is authored by the deterministic test
harness. The **reviewer's decision** (apply/keep/escalate) is generated
by a real model when `--agent llama` is used. Never describe this as
the model freely generating the initial wrong amount or deciding its
own SQL patch. It is a controlled approval experiment.

The review worker receives the specific candidate, exposed source
snippets and the published business contract. The full original ledger,
expected gold totals and subsequent scores remain private. For the
verified-repair ticket, only a simulated *single independently checked
payment-provider receipt* is visible—explicitly a separate information
tier, not full hidden truth.

## Five outcome references per proposed action

1. **Always keep:** no changes; looks safe on clean inputs but leaves
   a pre-existing corrupted credit uncorrected.
2. **Always apply:** executes all suggested corrections; repairs the
   pre-existing problem but creates three harmful changes.
3. **Model-selected, ungated:** real model chooses apply/keep/escalate;
   each choice is executed on exactly the same initial source.
4. **Model-selected, source-only gate:** candidate is admitted only for
   safe idempotent replay/duplicate cleanup; unsupported credit changes
   wait for independent proof, including a *genuine useful correction*.
5. **Model-selected, event-attested gate:** additionally admits an exact
   repair proven by a separately trusted event feed. Not a source-only
   inference and not a model explaining its own decision.

For each tested platform output, a real version-aware SQLite query
computes the published financial result. A separate business-event
oracle checks what should have been published. The scorer measures
wrong amounts, silently missing groups and correct business value
delivered, rather than rewarding a blank report as correct.

## What the calibration established (scripted, not LLM)

[CI 44684087059](https://github.com/mhatipog/dbt-chaos/actions/runs/44684087059)
successfully tested both contracts and the full standalone
`dbt-chaos contract-review` command.

For either procurement or grants, on the six fixed tickets:

| Scripted reference strategy | Cases with wrong published results | Meaning |
|---|---:|---|
| Always apply | **3 / 6** | Three unverified edits corrupt previously true records; authentic recovery succeeds |
| Always keep | **1 / 6** | The already-corrupted refund remains wrong despite a valid repair being available |
| Apply proposals through source-only gate | **1 / 6** | Bad edits blocked; necessary correction still withheld pending proof |
| Apply proposals through event-attested gate | **0 / 6** | Bad edits blocked, harmless operations permitted, verified correction accepted |

The stronger evidence tier has direct access to the independent event
record. Its success is an *upper-bound sanity check*, not a free
algorithmic detection improvement.

**Caveat:** six fixed cases per domain do not yield generalizable
false-approval or false-rejection rates. These are executable
instrument controls and are intended to ensure that the benchmark is
not biased towards a "reject everything" winner.

## Test immediately — no LLM required

```bash
git checkout research/good-intentions-handoff-20261119
pip install -e .

dbt-chaos contract-review \
  --contract contracts/procurement.json \
  --agent always_apply \
  --seed 20261119 \
  --public-dir /tmp/review-public \
  --private-dir /tmp/review-private \
  --out /tmp/review-summary.json
```

Replace `contracts/procurement.json` with `contracts/grants.json`.
Replace `--agent always_apply` with `--agent always_keep` for
the independent conservative control.

The public directory contains the *complete initial and proposed
three-table datasets* for every ticket, including the relevant source
excerpts and raw decisions. The private directory contains the full
process ledger, independent scoring and the evidence of what was
correct or incorrectly published. Each public file is SHA-256-listed.

For REAL, on-device weak-model review:

```bash
pip install 'llama-cpp-python>=0.3,<0.4'

dbt-chaos contract-review \
  --contract contracts/grants.json \
  --agent llama --model /path/to/local-qwen.gguf \
  --seed 20261119 \
  --public-dir /tmp/model-review-public \
  --private-dir /tmp/model-review-private \
  --out /tmp/model-review-summary.json
```

No model-generated code, SQL, remote API, customer data or production
credentials are ever executed. An invalid JSON decision is safely
treated as escalation and scored as a parse failure, **not** a reasoned
business decision. Source-only and attested gates never accept the
model's own claimed verification as proof.

## Research status and comparison with existing work

Safe agent approval gates, realistic synthetic process faults and
analytics-engineering benchmarks are established existing topics:
[Guarded Commits (2026)](https://arxiv.org/abs/2610.00037),
[FLAWD (2025)](https://doi.org/10.1145/3743144),
[Snowflake data-eng-bench (2026)](https://www.snowflake.com/en/blog/engineering/data-eng-bench-data-engineering-agent-benchmark/).

The potential original contribution, if a larger independent study
confirms it, is **paired source-to-publication measurement of how
different evidence tiers change preservation, over-withholding and
independently verified recovery of business facts**.

The six-ticket test still uses synthetic source data and
harness-authored maintenance candidates. Real procurement and grants
processes may have more temporal complexity, document provenance and
partial settlements; these are additional validation needs, not solved
by the prototype. No current evidence establishes actual industrial
error rates, human-like cognition or production-ready governance.
