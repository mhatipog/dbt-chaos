# Independent dbt resilience benchmark — Jaffle Shop

**Scope:** dbt Labs' own Jaffle Shop project (not authored or modified by
Vecture), reproducible at upstream commit
\`20cc904370818ceab08cf19f8fd196e9e81def88\`.

Upstream: https://github.com/dbt-labs/jaffle_shop_duckdb

GitHub Actions: [independent-jaffle.yml](../.github/workflows/independent-jaffle.yml)

## Research question

Can a semantically plausible payment event mistake pass an independently
authored project's *entire* existing dbt test suite, even though the
published payment amounts disagree with the frozen input record?

**Not claiming** to discover an unknown bug in dbt, nor an error in a
real-world billing environment. This is a synthetic injection applied to
an independently authored example dbt project. Similar misses have
previously been reported by dbt-saboteur and deadcanary.

## Protocol, specified before the final result

1. Fetch the exact upstream commit. Do not rewrite its models, tests,
   dependencies, or business logic. Store the immutable SHA.
2. Construct a frozen reference *independently of dbt execution* from
   upstream's original raw payments source: map each integer cent amount
   to the corresponding currency amount, retaining payment ID, order ID,
   and method. This oracle is separately implemented but is **not**
   authenticated evidence from a payment provider.
3. Build a dedicated non-root dbt Core 1.12/DuckDB container. No source
   project's code executes during checkout or image build. Install
   dependencies only during image build.
4. Start actual reviewed project code inside Docker with:
   - \`--network none\`
   - read-only container filesystem and upstream source bind mount
   - no inherited cloud credentials, and no copied user dbt profile
   - zero added Linux capabilities, no-new-privileges, memory/pid/CPU limits
   - only disposable tmpfs and a writable evidence output mount
   This is strengthened isolation, **not a formal security sandbox**
   against container escape or kernel vulnerabilities.
5. Execute *all* upstream dbt models and *all* native dbt tests in
   separate fresh DuckDB databases, first clean then one mutation at
   a time. Compare model output row-multisets including NULL sensitivity.
6. Test three harmful scenarios:
   - A plausible raw payment amount reduced by 500 cents.
   - One otherwise valid payment record duplicated with the same key.
   - One valid payment record deleted.
   And one benign control: reverse input row ordering (same records).
7. Preserve each original test's native status, full manifest test
   population and executed count. A skipped/incomplete suite cannot
   earn a full-suite silent-error verdict.
8. Score independently checked monetary *impact* and separate benign
   false alarms/order-sensitive outcomes. Never equate one mutated
   source file with a production transaction.
9. Preserve machine-readable JSON, a hash manifest, and upstream SHA
   as CI artifacts. Row values and exact row identifiers are redacted
   from the published assessment by default.
10. Evaluate both **net numeric error** and **gross absolute error grouped
    by payment ID**, without disclosing any payment identifiers. In a
    different project, two offsetting accounting errors can yield zero
    net error while corrupting multiple groups.

## Result definitions

- **Silent mismatch:** model output differs from the independent
  frozen reference, while the complete native dbt suite passes.
- **Detected mismatch:** output differs and one or more actual dbt
  tests fail/warn.
- **Benign control passed:** same output and tests pass.
- **Benign control changed output:** supposedly innocuous ordering
  changes business output; this is not merely a false-alarm.
- **False alarm:** unchanged output but an existing test rejects it.
- **Inconclusive:** an environment, compilation, database, baseline,
  missing reference, or test execution problem prevents assessment.
- **Unverified drift:** when no independent reference is provided,
  changed output is **not automatically** interpreted as corruption.

Important: the aggregate \`signed_error\` uses the model's own
explicitly selected metric column; it is not automatically a cost,
loss, currency or harm indicator. The fixed baseline presumes upstream
source data was originally correct.

## Comparison with competitors

- [dbt-saboteur](https://github.com/johnmikel/dbt-saboteur)
  mutates **SQL transformation code** and generates verifying tests.
- [deadcanary](https://github.com/Cshearer210/claimproof/tree/main/packages/deadcanary)
  mutates **input data**, evaluates coverage and test liveness, and has
  already benchmarked multiple external projects.
- This module targets **output-level business correctness and numerical
  impact** alongside actual native test behavior and benign controls.

These capabilities overlap substantially. We cannot claim a unique
scientific discovery, superiority or commercial demand based on this
one demonstration. A true comparison must run all three unchanged
tools under pre-registered compatible experiments, not divide
unlike mutant scores.

## CI usage

Run the action \`Independent upstream dbt project — offline-chaos
assurance\`. It reports the upstream SHA, full test population, each
mutation verdict and an offline downloadable evidence bundle.

For direct local usage without the container, refer to
[EXTERNAL_DBT_ADAPTER.md](EXTERNAL_DBT_ADAPTER.md), which explains
the trust risks of running arbitrary project macros and hooks.

## What this does NOT establish

- No live customer revenue data, provider attestation, or willingness
  to pay.
- No blind zero-touch onboarding for arbitrary third-party dbt projects.
- No Fabric/Databricks compatibility or execution.
- No full uncertainty calibration, representative fault prevalence or
  rate estimates from this tiny chosen set of mutations.
- No runtime confinement on all platforms: strengthened container
  isolation is only implemented by this dedicated CI workflow.
- No verified process-level recovery, compensated publication, or
  benign-correction throughput on this upstream project.

These are distinct product/research milestones; do not roll their
absence into a claim of 10/10 maturity.
