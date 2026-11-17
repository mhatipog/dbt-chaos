# Contributing

This is experimental open-source research, not a production fault-injection service.

1. Write a deterministic fault recipe in dbt_chaos/faults.py and classify its domain in dbt_chaos/core.py.
2. Supply a versioned JSON plan with stable source event IDs, source versions, delivery sequence and explicit checkpoints.
3. Add a unit test proving that the independent source-version oracle is not copied from the candidate.
4. Validate a clean control and a detectable invalid-input control; do not conflate expected rejection with infrastructure failure.
5. If claiming a dbt finding, confirm it using dbt_chaos/dbt_runner.py with an isolated disposable DuckDB database and attach public Actions evidence.
6. Measure correctness, alerting, recovery, workload cost and fault coverage separately. Never imply that synthetic fault percentages are production reliability rates.

Submit PRs without secrets, customer data or external connection strings. **Do not run untrusted contributors' PRs on self-hosted runners.** CI uses GitHub-hosted ephemeral runners with read-only permissions.

Larger changes should include a minimized reproducible scenario and an explicit note about unsupported adapters or transaction semantics.
