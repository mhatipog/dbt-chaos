"""Independently audit an exported full LLM corpus without any model/API/dbt run.

Checks SHA-256, the original event log, reconstructed source snapshots, each
model's recorded action, oracle metrics, and silent business mismatches.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import csv
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath

from .commerce import classify, difference, oracle, source_contract_alerts
from .commerce_runner import COLUMNS
from .full_datasets import (
    absolute_group_error, apply_proposal, enhanced_source_alerts,
    parse_proposal, replay_events,
)

INTEGER_FIELDS = {
    "row_id", "customer_id", "order_id", "payment_id",
    "version", "gross_cents", "amount_cents", "revenue_cents",
}
GOLD_COLUMNS = ("order_day", "segment", "revenue_cents")


def read_rows(root: Path, relative: str, columns: tuple[str, ...]) -> list[dict]:
    file = root / relative
    with file.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != columns:
            raise ValueError(f"unexpected columns: {relative}")
        parsed = []
        for record in reader:
            result = {}
            for col in columns:
                raw = record[col]
                if raw is None:
                    raise ValueError(f"missing column {col}: {relative}")
                try:
                    result[col] = int(raw) if col in INTEGER_FIELDS else raw
                except ValueError as exc:
                    raise ValueError(f"invalid integer in {relative}: {col}") from exc
            parsed.append(result)
        return parsed


def read_gold(root: Path, relative: str) -> dict[tuple[str, str], int]:
    values = {}
    for row in read_rows(root, relative, GOLD_COLUMNS):
        key = (row["order_day"], row["segment"])
        if key in values:
            raise ValueError(f"duplicate gold output key: {relative}")
        values[key] = row["revenue_cents"]
    return values


def read_tables(root: Path, prefix: str) -> dict[str, list[dict]]:
    return {name: read_rows(root, f"{prefix}/{name}.csv", COLUMNS[name])
            for name in ("customers", "orders", "payments")}


def audit_corpus(root: Path) -> dict:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError("corpus folder not found")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    trace = json.loads((root / "trace.json").read_text(encoding="utf-8"))
    if manifest["schema_version"] != 1:
        raise ValueError("unsupported schema version")
    for name, file in manifest["files"].items():
        if (PurePosixPath(name).is_absolute() or
                ".." in PurePosixPath(name).parts):
            raise ValueError(f"unsafe manifest path: {name}")
        raw = (root / name).read_bytes()
        if sha256(raw).hexdigest() != file["sha256"]:
            raise ValueError(f"hash mismatch: {name}")
        if len(raw) != file["size_bytes"]:
            raise ValueError(f"size mismatch: {name}")
        if file.get("rows") is not None:
            actual_rows = (raw.count(b"\n") if name.endswith(".jsonl")
                           else raw.count(b"\n") - 1)
            if file["rows"] != actual_rows:
                raise ValueError(f"row count mismatch: {name}")

    events = [json.loads(line) for line in
              (root / "ledger/process_events.jsonl").read_text().splitlines()]
    if len(events) != manifest["event_count"]:
        raise ValueError("process event count mismatch")
    if [e["event_id"] for e in events] != list(range(1, len(events) + 1)):
        raise ValueError("discontinuous process event sequence")
    truth = replay_events(events)
    clean = read_tables(root, "ledger/source_of_truth")
    if truth != clean:
        raise ValueError("exported clean sources differ from process event replay")
    if {name: len(rows) for name, rows in truth.items()} != manifest["initial_rows"]:
        raise ValueError("baseline row counts mismatch")
    true_gold = oracle(truth)
    if true_gold != read_gold(root, "ledger/business_gold.csv"):
        raise ValueError("business ledger gold mismatch")
    if manifest["full_dataset_snapshots"] != len(trace["steps"]):
        raise ValueError("snapshot count mismatch")
    if trace["seed"] != manifest["seed"]:
        raise ValueError("profile seed mismatch")

    delivered = deepcopy(truth)
    logic_fault = "none"
    step_results = []
    for index, step in enumerate(trace["steps"], 1):
        if step["step"] != index:
            raise ValueError("unexpected snapshot order")
        proposal, valid = parse_proposal(step["raw_model_output"])
        if proposal != step["proposal"] or valid != step["model_output_valid"]:
            raise ValueError(f"model proposal is not reproducible: step {index}")
        exposed_ids = {
            name: {r["row_id"] for r in rows}
            for name, rows in step["ticket"]["exposed_rows"].items()
        }
        logic_fault, effect = apply_proposal(delivered, logic_fault, proposal, exposed_ids)
        if effect != step["edit_effect"] or logic_fault != step["logic_fault"]:
            raise ValueError(f"applied action mismatch: step {index}")

        prefix = f"steps/{index:02d}"
        exported = read_tables(root, f"{prefix}/source_delivery")
        if exported != delivered:
            raise ValueError(f"snapshot does not replay from proposals: step {index}")

        admitted_gold = oracle(delivered)
        if admitted_gold != read_gold(root, f"{prefix}/admitted_gold.csv"):
            raise ValueError(f"admitted oracle mismatch: step {index}")
        if difference(true_gold, admitted_gold) != step["input_vs_process"]:
            raise ValueError(f"source discrepancy mismatch: step {index}")
        if source_contract_alerts(delivered) != step["source_contract_alerts"]:
            raise ValueError(f"source alert mismatch: step {index}")
        if step.get("enhanced_source_alerts") is not None:
            if enhanced_source_alerts(delivered) != step["enhanced_source_alerts"]:
                raise ValueError(f"enhanced alert mismatch: step {index}")
        source_l1 = absolute_group_error(true_gold, admitted_gold)
        if step.get("source_absolute_error_cents") is not None:
            if source_l1 != step["source_absolute_error_cents"]:
                raise ValueError(f"source L1 mismatch: step {index}")
        signed_source = sum(admitted_gold.values()) - sum(true_gold.values())
        if step["source_drift_cents"] != signed_source:
            raise ValueError(f"signed source mismatch: step {index}")
        dbt_correct = None
        reported_alerts = {"source": [], "output": []}
        business_l1 = None
        if step["evidence_level"] == "executed_dbt_duckdb":
            observed = read_gold(root, f"{prefix}/dbt_gold.csv")
            reported_alerts = {"source": step["dbt_source_alerts"],
                               "output": step["dbt_output_alerts"]}
            if difference(true_gold, observed) != step["output_vs_process"]:
                raise ValueError(f"output discrepancy mismatch: step {index}")
            label = classify(admitted_gold, observed, reported_alerts["source"],
                             reported_alerts["output"])
            if label != step["dbt_classification"]:
                raise ValueError(f"dbt classification mismatch: step {index}")
            signed_business = sum(observed.values()) - sum(true_gold.values())
            if signed_business != step["business_drift_cents"]:
                raise ValueError(f"business drift mismatch: step {index}")
            business_l1 = absolute_group_error(true_gold, observed)
            if step.get("business_absolute_error_cents") is not None:
                if business_l1 != step["business_absolute_error_cents"]:
                    raise ValueError(f"business L1 mismatch: step {index}")
            dbt_correct = (observed == true_gold)
            if step["end_to_end_correct"] != dbt_correct:
                raise ValueError(f"end-to-end status mismatch: step {index}")
        step_results.append({
            "step": index, "effect": effect, "source_l1_cents": source_l1,
            "business_l1_cents": business_l1,
            "business_correct": dbt_correct,
            "source_contract_alerts": source_contract_alerts(delivered),
            "enhanced_source_alerts": enhanced_source_alerts(delivered),
            "dbt_alerts": reported_alerts,
        })
    return {
        "schema_version": 1, "verified": True,
        "model": trace["model"], "model_sha256": trace["model_sha256"],
        "seed": trace["seed"], "events": len(events),
        "files_verified": len(manifest["files"]), "snapshots": len(step_results),
        "baseline_rows": manifest["initial_rows"],
        "steps": step_results,
    }


def main():
    parser = argparse.ArgumentParser(description="Offline audit of complete LLM dataset corpus")
    parser.add_argument("directory", type=Path, help="extracted Qwen or SmolLM corpus directory")
    args = parser.parse_args()
    result = audit_corpus(args.directory)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
