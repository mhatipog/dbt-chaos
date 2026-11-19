# Process-contract research results — 19 November 2026

[Verified GitHub Actions run 44615377506](https://github.com/mhatipog/dbt-chaos/actions/runs/44615377506)
tested the constrained `party → document → money movement` process DSL on
two genuinely different contract definitions. All **26 unit/regression
tests** passed (12 process-contract, 4 generated SQL, 10 prior
external-platform tests). Ten complete cases were executed in **SQLite
from public source CSVs only**. The generator's immutable business
events and private oracle were not provided to the platform.

The wheel was built and installed into a fresh virtual environment
outside the repository; both built-in contract aliases loaded from its
packaged JSON resources. This is a packaging validation, not a PyPI
release or a production-adapter test.

## Two process models, ten complete executions

| Business process | Immutable business events | Public source tables |
|---|---:|---|
| Procurement | 832 | 51 supplier-version rows, 500 invoice-version rows, 281 settlement rows |
| Grant disbursement | 622 | Beneficiary, grant-award and disbursement tables with independent naming, statuses, movement kinds and region dimensions |

Both domains have genuine party versions, document status revisions,
partial credits, corrections and idempotent delivery retries in their
initial clean data. Clean SQL reports agree with independently computed
business-event gold.

## Signed totals are insufficient: actual results

One common seed, 20261119. Each line runs the *same original process*
through a deterministic source edit, then an independently executed
SQLite query. The model does **not** access the private event ledger.
These faults are SCRIPTED good-faith calibration, **not genuine new
LLM-authored mutations**.

| Domain | Fault | Outcome | Absolute group-level business error | Wrong published groups | Silently missing groups |
|---|---|---|---:|---:|---:|
| Procurement | None | Business correct | €0 | 0 | 0 |
| Procurement | Rewrite credit | Garbage passed through | **€20** | 1 | 0 |
| Procurement | Reclassify party | Garbage passed through | **€4,215.78** | 9 | 7 |
| Procurement | Delete document | Garbage passed through | **€197.72** | 0 | 1 |
| Procurement | Duplicate delivery | Business correct | €0 | 0 | 0 |
| Grants | None | Business correct | €0 | 0 | 0 |
| Grants | Rewrite credit | Garbage passed through | **€20** | 1 | 0 |
| Grants | Reclassify party | Garbage passed through | **€1,728.76** | 10 | 0 |
| Grants | Delete document | Garbage passed through | **€150.92** | 1 | 0 |
| Grants | Duplicate delivery | Business correct | €0 | 0 | 0 |

These cases are intentionally selected to exercise different
mechanisms. Their counts are **not statistical rates, reliability
estimates or expected customer losses**.

### Three findings

1. A believable financial edit may pass every structural check:
   `rewrite_credit` changed an authentic credit by €20 while leaving
   relational integrity intact. In both domains the generated
   source-only SQL probes reported **zero blocking findings** for
   the altered amount. The independent event oracle detected it.
2. A reclassification may preserve signed grand-total money while
   corrupting numerous reporting groups. Procurement had 16 affected
   groups, of which 7 disappeared entirely; merely checking
   `published rows with a wrong amount` would undercount harm.
3. An absent document can cause an orphan movement, which *is*
   observable using the generated foreign-key-like SQL probe. The
   reference SQL, which does not implement quarantine or gating,
   nevertheless passed incomplete results into the report. This
   separates **detectability** from **actual containment**.

The harmless retry was included to prevent rewarding overaggressive
rejection: clean/version-aware SQL preserves the same correct business
totals.

## Independent validation

Three measurements are kept separate:

- **Business-event oracle**: folds the immutable original `process_events.jsonl`,
  never using a source-row projection.
- **Admitted-source oracle**: deduplicates and joins the tables actually
  delivered to the platform, potentially corrupted.
- **SQL execution**: runs an independently implemented version-aware query
  on public CSVs, with no access to either hidden oracle.

The generated `sql/reference_query.sql` and
`sql/quality_checks.sql` are in the public challenge and are
SHA-256-checked by the evaluator. Their source-only limitations are
documented explicitly. They are **not claimed to be native dbt,
Fabric or Databricks policy installations**.

Both artifacts and full machine-readable cross-domain results can be
retrieved from [the CI run](https://github.com/mhatipog/dbt-chaos/actions/runs/44615377506).
CI artifacts have short retention; the canonical reproducible source
is on the research branch.

## Limitations and next decisive work

The DSL is a bounded three-role **transactional** process family.
Different table names, fields, signs, statuses and data distributions
are configurable, but it is not a universal arbitrary-process
generator. The next valuable extensions are:

- **Contract-aware well-intentioned weak LLM**: an agent receives
  realistic maintenance tickets and exposed source evidence, proposes
  bounded actual edits and leaves a handoff note. Compare its decisions
  against a no-op and fixed-script control without instructing it to
  create faults deliberately.
- **Evidence-aware quarantine**: compare optional source SQL probes,
  a strict publication gate, a targeted hold with proven data lineage
  and external process attestations, scoring both wrong publication
  and unnecessary rejection.
- **Multiple independent seeds and real native adapters**: a staged
  study comparing dbt, Fabric and Databricks on the same exported
  challenges, using actual published tables and quarantines rather
  than speculative classifications.

For runnable commands see [the process-contract guide](PROCESS_CONTRACTS.md).
For the earlier genuine Qwen 20-handoff experiment and its important
negative controls see [the longitudinal results](RELAY_RESULTS_20261119.md).
