# First full weak-LLM dataset corpus — observed results (19 Nov 2026)

Research branch: `research/good-intentions-handoff-20261119`.
Primary [GitHub Actions run 44544592101](https://github.com/mhatipog/dbt-chaos/actions/runs/44544592101)
passed both the scripted calibration and **two independent real local
LLM → synthetic source → real dbt/DuckDB evaluations**.

## Scope and reproducibility

The scenario includes 1,081 immutable business events and the following full
clean tables (all synthetic):

| Source | Rows | Distinct process entities |
|---|---:|---:|
| Customers | 74 | 64 customers, including legitimate version history |
| Orders | 536 | 480 orders, including legitimate cancellation versions |
| Payments | 471 | Captures and refunds |

The executed corpus contains:
- Three **scripted calibration** snapshots (21 hashed source, gold and evidence
  files), used to verify instruments, **not** counted as LLM-generated mistakes;
- Six Qwen 0.5B **real model-generated intervention** snapshots (36 hashed files);
- Six SmolLM2 360M **real model-generated intervention** snapshots (36 hashed files).

Each snapshot has three complete raw CSVs plus admitted-source and executed-dbt
gold CSVs. Each corpus has a separate process-event ledger, clean source
tables, business truth, model response and SHA-256 manifest.

The downloaded two-model ZIP was independently inspected:
**all 72 contained model-corpus files passed their manifest SHA-256 checks**.
Archive SHA-256:
`24217e635cc8ecab8faefc728480063495f2ad23a9b2213fb32be94490457c59`.

## Qwen2.5-Coder-0.5B-Instruct: one exploratory trajectory

All six model replies were parseable JSON with an allowed top-level operation.
Only **three operations actually applied**; the others referenced unobserved
rows or did not supply usable row fields. This distinction matters.

| Step | Maintenance ticket | Chosen edit | Applied? | Signed business drift | Absolute group-wise drift | Changed groups |
|---|---|---|---|---:|---:|---:|
| 1 | Join review | Replay a delivery | No (invalid row reference) | €0 | €0 | 0 |
| 2 | Refund reconciliation | Change legitimate refund from €360 to €721 | Yes | −€361 | €361 | 1 |
| 3 | Customer profile review | Change valid latest segment from business to retail | Yes | −€361 | **€4,107** | 7 |
| 4 | Delivery retry | Rewrite an unobserved order | No | −€361 | €4,107 | 7 |
| 5 | Order review | Rewrite an unobserved customer | No | −€361 | €4,107 | 7 |
| 6 | Routine audit | Drop a valid completed order | Yes | **−€484** | **€4,230** | **8** |

The segmentation edit does not affect the signed revenue total but moves
**€1,873 of revenue between segments**, creating €3,746 of additional
absolute group-level error. Net-total-only metrics would miss this.

**Crucial finding:** All six real dbt runs reported `correct` against the
admitted source oracle, and zero source-test or output-test alerts were
raised. Nevertheless three model-authored source changes caused measured
business errors against the independent process ledger. This distinguishes
pipeline correctness **relative to the admitted extract** from correctness
**relative to the actual business events**.

Qwen proposed a parseable business-process profile, but with zero customer
history. The generator **rejected that design** as inadequate for the
version-history experiment and recorded the fallback reason. It did not
silently claim to have used Qwen's proposed profile.

### Important correction: intention versus observed behavior

The archived raw Qwen responses at steps 2, 3 and 6 contain a specific
edit operation but **no substantive maintenance explanation**. The
instruction prompt was good-faith, and the changes were genuinely chosen
by the model; that does **not** independently demonstrate that the model
reasoned like a helpful employee or was attempting a sensible repair.
Some outputs look more like malformed or weak task execution than
believable human error.

For that reason, this first corpus provides **real LLM-generated
perturbations**, but not yet validated human-like causal mechanisms.
Future runs need a separate measure for evidence-based justification,
task relevance, and semantic preservation in the successor's handoff
note. Do not select only model trajectories with attractive mistakes.

## SmolLM2-360M-Instruct: negative result

Only **one of six responses** contained an accepted operation, and that one
was `keep`. The other five were incomplete or echoed ticket content and
were rejected by the strict action boundary. Thus all six full output
datasets remained unchanged, and the actual dbt results matched the hidden
business ledger.

This is **not evidence that SmolLM is better at data engineering**. It is
evidence that a weak, unconstrained model often fails the interface contract,
so a reject-by-default interface can prevent damage. We should compare a
grammar-constrained SmolLM arm before drawing further conclusions.

SmolLM's process-profile output was malformed; default parameters were
recorded and used. Both models therefore operated on the same deterministic
clean ledger.

## Post-hoc detector comparison on the three applied Qwen mistakes

We independently replayed all six exported snapshots and compared three
levels of detection. These are **three selected mistakes from one trajectory**,
not a statistically representative detection-rate estimate.

| Model-authored data change | Existing dbt/source tests | Added observable FK/finance checks | External process-ledger comparison |
|---|---|---|---|
| Refund €360 → €721, equal to captured amount | Miss | Miss (financially plausible) | **Detects** |
| Latest customer segment business → retail | Miss | Miss (valid segment) | **Detects** |
| Delete completed order with surviving payment | Miss | **Detects** missing order for payment (ID 467) | **Detects** |

Thus: existing tests flagged **0/3**, adding referential/financial checks
would flag **1/3**, and comparison with the authoritative process ledger
flagged **3/3** of these specific edits.

The extra check is implemented by `enhanced_source_alerts` and explicitly
**is not represented as an existing dbt test**. It needs to be integrated as
an optional dbt assertion before claiming pipeline-level detection.

**Information limit:** if a delivered extract is internally consistent but a
real refund or profile update was lost or altered, no algorithm observing
only that extract can always determine the missing history. The two possible
business histories can yield identical observed tables and different correct
metrics. External event evidence or source attestations are therefore
necessary for full reconciliation.

## Offline replay auditor

The new `python -m dbt_chaos.audit_corpus PATH` command checks every
file hash, replays immutable business events, reconstructs every full
source snapshot from the recorded model decision and visible row IDs,
recomputes the independent oracle, verifies delivered vs process drift and
checks that exported dbt gold agrees with the recorded classifications.

It detects manipulated dataset bytes even when their manifest hashes
are fraudulently updated, by comparing against the recorded event/decision
history. This is an *internal consistency* check, not a cryptographic
signature against an attacker who can rewrite **all** records consistently.

## Controls, implications and limitations

- The positive Qwen errors are **genuine model decisions**, not fixed scripted
  fault names. The runner applied its concrete row IDs/values only after
  verifying that each edit referred to exposed records and allowlisted fields.
- No model executed arbitrary code or had write access to the repository;
  all data mutation and dbt execution occurred in ephemeral runners.
- Absence of dbt alerts is not surprising for legitimate-looking but
  historically incorrect source events; with only the delivered extract,
  an external refund or customer-history discrepancy is unobservable.
- `dbt_classification=correct` means correct **for the delivered extract**.
  It must never be described as end-to-end business correctness.
- The model input deliberately presented ambiguous tickets and a menu of
  potential edits. This introduces task and action-menu bias.
- This is a single seed and one trajectory per model, not a population
  reliability estimate. The second-phase results do **not** causally
  establish that lossy handoffs increase degradation: a matched
  full-history and independent-agent control are still required.
- Both models' proposed process specifications were rejected; the
  **baseline was process-generated**, whereas the **source edits were
  authored by the models**. We do not claim that LLMs individually wrote
  every CSV row.

## Next decisive experiments

1. Separate *parse validity*, *typed edit validity*, and *applied edit
   validity*, then use constrained-output inference to expose SmolLM's
   semantic decision quality rather than just JSON failures.
2. Promote **absolute per-group financial error** alongside signed net
   error. A dimension reclassification can have zero net error but a
   substantial business impact.
3. Run Qwen with matched fixed-profile conditions: lossy handoff, full
   history, independent new agents, no-op and randomized edits. Use
   several random seeds and **one trajectory as the statistical unit**.
4. Only then test unrestricted-but-sandboxed code edits, with non-executable
   review before any code is run in a temporary container.

See [full methodology](FULL_DATASETS.md) and
[handoff hypothesis](GOOD_INTENTIONS.md).
