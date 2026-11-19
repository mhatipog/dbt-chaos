"""Posthoc, no-LLM audit of longitudinal process→maintenance→dbt trajectories.

Checks exported full-source corpora and distinguishes the FIRST matched
decision divergence (same pre-edit source state) from later endogenous drift.

Task alignment and note quality are *diagnostic proxies*, not validation
that a worker actually behaved like a human or had good intentions.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any

from .audit_corpus import audit_corpus

TICKET_OPERATIONS = {
    "join_review": {"keep", "simplify_customer_join", "restore_customer_join"},
    "reconciliation": {"keep", "drop_row", "edit_cell"},
    "profile_sync": {"keep", "edit_cell", "new_customer_snapshot"},
    "delivery_retry": {"keep", "replay_delivery"},
    "order_review": {"keep", "drop_row", "edit_cell"},
    "routine_audit": {"keep"},
}
TICKET_TABLES = {
    "reconciliation": {"payments"}, "profile_sync": {"customers"},
    "delivery_retry": {"customers"}, "order_review": {"orders"},
}
NOTE_TOPICS = {
    "join_review": ("join", "version", "customer", "dedup"),
    "reconciliation": ("refund", "payment", "duplicat", "evidence"),
    "profile_sync": ("customer", "segment", "profile", "version"),
    "delivery_retry": ("deliver", "retry", "replay", "duplicat"),
    "order_review": ("order", "amount", "gross", "reconcil"),
    "routine_audit": ("audit", "month", "no change", "preserv"),
}


def _state_digest(root: Path, prefix: str) -> str:
    h = sha256()
    for table in ("customers", "orders", "payments"):
        h.update(table.encode())
        h.update((root / prefix / (table + ".csv")).read_bytes())
    return h.hexdigest()


def _decision_key(step: dict) -> tuple:
    value = step["proposal"]
    return (
        value["operation"], value.get("table"), value.get("row_id"),
        value.get("field"), json.dumps(value.get("value"), sort_keys=True),
    )


def _task_relevant(step: dict) -> bool:
    """Conservative structural relevance proxy, not proof of a correct edit."""
    ticket = step["ticket"]["ticket_id"]
    proposal = step["proposal"]
    op = proposal["operation"]
    if op not in TICKET_OPERATIONS[ticket]:
        return False
    if op == "keep" or ticket == "join_review":
        return True
    return proposal.get("table") in TICKET_TABLES.get(ticket, set())


def _note_topic_match(step: dict) -> bool:
    note = str(step["proposal"].get("note", "")).lower()
    ticket = step["ticket"]["ticket_id"]
    return len(note.strip()) >= 20 and any(
        word in note for word in NOTE_TOPICS[ticket])


def analyse(root: Path) -> dict[str, Any]:
    root = root.resolve()
    report = json.loads((root / "comparison.json").read_text(encoding="utf8"))
    if report["experiment"] != "matched_good_faith_relay_v1":
        raise ValueError("unexpected comparison experiment")
    modes = report["conditions"]
    if len(modes) != len(set(modes)) or not modes:
        raise ValueError("invalid condition list")
    records: dict[str, dict] = {}
    process_hashes = set()
    weights = set()
    for mode in modes:
        folder = root / mode
        verified = audit_corpus(folder)
        trace = json.loads((folder / "trace.json").read_text(encoding="utf8"))
        if trace["context_mode"] != mode or len(trace["steps"]) != report["steps"]:
            raise ValueError("experiment arm metadata disagrees")
        if trace["seed"] != report["seed"]:
            raise ValueError("mismatched process seed")
        weights.add(trace["model_sha256"])
        process_hashes.add(_state_digest(folder, "ledger/source_of_truth"))
        digest = [_state_digest(folder, f"steps/{i:02d}/source_delivery")
                  for i in range(1, len(trace["steps"]) + 1)]
        rows = trace["steps"]
        notes = [str(row["proposal"].get("note", "")) for row in rows]
        applied = [r for r in rows if r["edit_effect"] not in {
            "no_change", "rejected_unobserved_row", "rejected_missing_row",
            "rejected_wrong_table", "rejected_invalid_cell",
            "rejected_unknown_operation"}]
        records[mode] = {
            "trace": trace, "state_hash": digest,
            "summary": {
                "verified_snapshots": verified["snapshots"],
                "applied_operations": len(applied),
                "applied_with_substantive_note": sum(
                    len(str(r["proposal"].get("note", "")).strip()) >= 20
                    for r in applied),
                "proposal_task_alignment_proxy": sum(
                    _task_relevant(row) for row in rows),
                "notes_with_topic_evidence_proxy": sum(
                    _note_topic_match(row) for row in rows),
                "notes_with_literal_policy_id": sum(
                    bool(re.search(r"\bP0[1-6]\b", note, re.I))
                    for note in notes),
                "mean_note_length": round(sum(len(n) for n in notes)/len(notes), 1),
                "source_l1_end_eur": rows[-1]["source_absolute_error_cents"]/100,
                "real_dbt_checkpoints": {
                    r["step"]: {
                        "business_l1_eur": r["business_absolute_error_cents"]/100,
                        "source_test_alerts": r["dbt_source_alerts"],
                        "output_test_alerts": r["dbt_output_alerts"],
                    }
                    for r in rows if r["evidence_level"] == "executed_dbt_duckdb"
                },
            }
        }
    if len(process_hashes) != 1 or len(weights) != 1:
        raise ValueError("arms do not share identical initial process or model weights")
    task_tapes = {
        mode: [r["ticket"] for r in record["trace"]["steps"]]
        for mode, record in records.items()
    }
    if any(task_tapes[mode] != task_tapes[modes[0]] for mode in modes):
        raise ValueError("task tape differs between conditions")

    comparisons = []
    for i, left in enumerate(modes):
        for right in modes[i+1:]:
            a, b = records[left], records[right]
            x, y = a["trace"]["steps"], b["trace"]["steps"]
            first_decision = next((
                j for j, (p, q) in enumerate(zip(x, y), 1)
                if _decision_key(p) != _decision_key(q)), None)
            first_state = next((
                j for j, (p, q) in enumerate(zip(a["state_hash"], b["state_hash"]), 1)
                if p != q), None)
            first_note = next((
                j for j, (p, q) in enumerate(zip(x, y), 1)
                if p["proposal"].get("note", "") != q["proposal"].get("note", "")),
                None)
            pre_equal = None
            if first_decision is not None:
                pre_equal = (
                    True if first_decision == 1 else
                    a["state_hash"][first_decision-2] == b["state_hash"][first_decision-2])
            comparisons.append({
                "conditions": [left, right],
                "first_behavioral_decision_divergence": first_decision,
                "identical_delivered_source_before_decision": pre_equal,
                "first_full_source_snapshot_divergence": first_state,
                "first_handoff_note_divergence": first_note,
                "causal_caveat": (
                    "A difference with identical pre-edit sources narrows the "
                    "comparison, but model sampling and inherited notes remain "
                    "possible causes. Later drift depends on earlier decisions."
                ),
            })
    return {
        "experiment": "matched_good_faith_relay_posthoc_v1",
        "seed": report["seed"], "steps": report["steps"],
        "initial_process_identical": True, "model_weights_identical": True,
        "fixed_task_tape_identical": True,
        "arms": {mode: records[mode]["summary"] for mode in modes},
        "pairwise_first_divergences": comparisons,
        "warning": (
            "Task alignment and note-topic presence are diagnostic lexical "
            "proxies only. They do not establish that a model acted with "
            "realistic reasoning or that context caused a business mistake."
        ),
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Audit matched relay chains")
    p.add_argument("directory", type=Path)
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    result = analyse(args.directory)
    if args.output:
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True)+"\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
