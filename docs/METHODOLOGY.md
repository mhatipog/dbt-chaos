# Experimental method and scoring

## Claims
- Real dbt evidence: command exit codes, compiled query, dbt run/test artifacts, independent oracle comparison, and the exact synthetic replay plan.
- Model screening: pure Python pipeline approximations, valuable for fast discovery but **not** proof of a dbt or adapter defect.
- The original ten-case baseline demonstrates a deliberately fragile SQL timestamp watermark, **not** a defect in dbt Core.
- No chaos framework can enumerate every real-world failure. Planned fault IDs are explicitly identified and excluded from measured coverage.

## Ground truth
Every event has a globally stable event ID, entity key, source version, source event time, amount in integer cents, and optional delete operation. The source-version order (then event ID for ties) defines the canonical live state. Re-delivery of identical events is idempotent. Conflicting payloads under the same ID are rejected, not silently repaired. Logical deletes remain tombstones to avoid old versions resurrecting records.

At each checkpoint the evaluator compares the candidate visible key/version/amount state against the canonical state from **admitted/delivered records**. Missing events that have not arrived yet are a transport-delivery issue, not automatically a transformation bug. The present framework does not model a delivery deadline and does not claim to detect missing source events.

## Metrics
For each strategy, the model-screen score is:

    100 * (1 - silent_fault_checkpoints / fault_checkpoints)

Baseline checkpoints are excluded. A mismatch with no configured basic test alert is silent; a mismatch with a test alert is detected. Data-quality alerts without model mismatch are reported separately. The score is a **synthetic workload-specific** measure, not a reliability guarantee, forecast of real incidents, or proof of robustness on other engines.

Also publish: wrong checkpoints, detection checkpoints, read-work units, run count, fault domain breakdown, minimized counterexamples, and distinct evidence levels. Read-work units are not cloud-cost measurements. Averages over unequal scenario mixes cannot be compared without preserving the same manifest and weights.

## Safety
Runs are strictly synthetic and disposable. Public CI only uses GitHub-hosted ephemeral runners with read-only permissions, no environment secrets, and bounded runtimes. It never attaches the persistent private Oracle VM to the public repository. A future authenticated production integration must require separate explicit authorization and safety review; none is implemented.

## Next research
Quantified comparison among real dbt SQL strategies, ingestion-offset state tracking, and source-version CDC; deterministic fixture imports from Belgian Lakehouse Bench; transactional interruption tests limited to throwaway child processes; cross-engine adapter capability matrix; CI evidence receipts; selective pairwise/triple fault coverage and randomized model-screening negative controls.
