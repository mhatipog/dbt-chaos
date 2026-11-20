# One-command Business Truth Resilience assessment

This is an **implemented, synthetic-only** end-to-end demo of a useful
release-safety question: when somebody makes an apparently reasonable but
incorrect operational edit, does the platform continue to publish wrong
financial numbers, safely hold affected groups, or restore service after
**independent** evidence arrives?

The current feature branch is
`feature/assessment-pack-20261120`, based on
`research/good-intentions-handoff-20261119`. The public `main`
branch does not yet contain these experimental capabilities.

## Run

Python 3.10 or later, no live dbt/Fabric/Databricks, cloud account,
external API, model download, or customer data:

```bash
python -m pip install -e .
dbt-chaos assess-demo --seed 20261119 \
  --out-dir /tmp/business-truth-assessment --fail-on-unsafe
```

This executes the **real, built-in SQLite reference transformations**;
it is **not** a Python-only model-screen prediction or a live dbt adapter
test. Running without `--fail-on-unsafe` still emits the same evidence.

Four small files are written to a **new or empty directory**:

- `assessment.json`: machine-readable source-vs-business controls and case
  summaries, the stages of held / published financial output, explicit
  methodological limitations and evidence tier.
- `assessment.md`: shareable, concise report.
- `assessment.html`: self-contained offline report; no scripts, network
  calls, private process events or signing keys.
- `SHA256SUMS`: SHA-256 checksum of the JSON report, for reproduction and
  transport-integrity checks (**not an external provenance signature**).

The CLI explicitly refuses to overwrite a populated output directory.

## What is measured?

Two different business-process contracts, *procurement* and *grant
disbursement*, each produce six matched maintenance cases using a fixed
synthetic seed: three unsupported harmful edits, a legitimate retry, a
necessary independently receipted correction, and harmless duplicate
cleanup. The original business truth comes from an **immutable event
ledger**, not from reading the already altered operational source data.

For each contract, the tool executes real SQL and compares:

| Policy | Meaning |
| --- | --- |
| Always apply | Apply **every scripted candidate**; detects over-permissiveness |
| Always keep | Leave every record unchanged; exposes failed useful repairs |
| Source-only edit gate | Admit locally verifiable idempotent operations, hold questionable changes |
| Full event attestation | Upper-bound control with access to stronger external evidence |
| Narrow signed receipt | Simulated signed evidence for one transaction, without granting the whole event ledger |

A separate three-stage publication case explicitly records:

1. A previously wrong financial record was published as a wrong number.
2. A review case **withheld one affected reporting group** while still
   publishing correct unaffected groups. Withholding is not silently
   replaced with a false zero or claimed as physical row quarantine.
3. A single scoped simulated external-provider receipt was verified,
   the legitimate source correction admitted, and the original correct
   business output published. Signing keys are not exported.

Example expected calibrated finding for the fixed six-ticket suite:
always-apply produces **three harmful business outcomes**, always-keep
leaves **one true defect unrepaired**, and the full-event attestation
reference yields no wrong cases. These counts are **synthetic selected
cases**, not error rates, control efficacy probabilities, or proof that a
production pipeline is reliable.

## Safety and scientific boundaries

- All data and operational proposals are synthetic; proposed candidates
  are scripted, **not** independently authored by an LLM. This demo makes
  no telephone-game causal claims.
- Real SQL uses a **local SQLite reference** rather than an installed
  customer dbt, Fabric or Databricks pipeline. Use the existing
  `contract-generate` and `contract-score` CSV boundary to test a
  platform's *actually published* outputs.
- Source-only controls cannot know whether a plausible source value is
  wrong when every observable source reports the same mistake.
- The stronger event-ledger and simulated provider-receipt controls use
  explicitly *additional independent evidence*. Their successful
  recovery is not an algorithmic inference from corrupted input alone.
- A financial group held for review remains unavailable. The report
  exposes that loss of usefulness instead of rewarding `withhold all`.
- The checksum is for content integrity only, not a cryptographic signed
  third-party attestation or anti-tamper guarantee.
- `--fail-on-unsafe` returns nonzero only when the **known calibration
  controls fail**; it does not fail merely because the intentionally weak
  baseline publishes errors.

## CI verification

`.github/workflows/assessment-pack.yml` runs focused unit/CLI tests,
the complete two-domain assessment, and SHA-256 verification on
an ephemeral public GitHub runner. It does not upload artifacts or use
any self-hosted Oracle VM / production secrets. The existing framework
PR checks remain in force.

**Next product gate:** execute the same portable challenge through actual
Fabric and Databricks sandbox pipelines and compare *their published
outputs*, not only local reference SQL, while keeping the independent
truth outside the target environment. Then ask two external engineers to
run the package and report onboarding friction and actionable findings.
