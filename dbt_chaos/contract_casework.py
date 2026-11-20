"""Actual publication lifecycle for a disputed contract financial movement.

A source-only platform cannot know whether a plausible amount is authentic.
Given an explicit maintenance dispute on a concrete movement row, it can:
  - keep an unsafe correction proposal out of admitted source;
  - withhold the report group whose ancestor lineage is observable;
  - restore normal publication after an independent scoped signed receipt.

This is a synthetic reference service, using REAL SQLite SQL execution.
No production warehouse permissions or actual provider integration exist.
The original process-event truth is used only by the separate research
receipt issuer / final evaluator, never by the source-only release planner.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import secrets
from typing import Any

from .contract_agent import candidate_source
from .contract_receipt import issue_simulated_receipt, verify_scoped_correction
from .process_contract import (
    event_business_oracle, project_source, run_sqlite_reference, validate_contract,
)
from .relay_platform_replay import score_publication


def _latest(rows: list[dict], field: str) -> dict[int, dict]:
    latest: dict[int, dict] = {}
    for row in rows:
        old = latest.get(row[field])
        if old is None or (row["version"], row["row_id"]) > (
                old["version"], old["row_id"]):
            latest[row[field]] = row
    return latest


def resolve_dispute_lineage(contract: dict, delivered: dict,
                            proposal: dict) -> dict[str, Any]:
    """Source-only lookup; never accept a model note as evidence."""
    c = validate_contract(contract)
    m, d, p = (c["roles"][r] for r in ("movement","document","party"))
    def global_hold(reason: str):
        return {"group": None, "global_hold": True, "reason": reason}
    if (proposal.get("operation") != "edit_cell"
            or proposal.get("table") != m["table"]
            or proposal.get("field") != m["amount"]
            or type(proposal.get("row_id")) is not int):
        return global_hold("unsupported_dispute_scope")
    movement = next((r for r in delivered[m["table"]]
                     if r["row_id"] == proposal["row_id"]), None)
    if movement is None:
        return global_hold("movement_row_not_found")
    doc = _latest(delivered[d["table"]], d["id"]).get(
        movement[m["document_fk"]])
    if doc is None:
        return global_hold("document_ancestor_not_found")
    party = _latest(delivered[p["table"]], p["id"]).get(
        doc[d["party_fk"]])
    if party is None:
        return global_hold("party_ancestor_not_found")
    return {
        "group": (doc[d["date"]], party[p["dimension"]]),
        "global_hold": False,
        "reason": "source_ancestor_lineage_verified",
    }


def publish_pending_dispute(contract: dict, delivered: dict,
                            proposal: dict) -> dict:
    """No attempted repair is admitted; only safe reporting groups publish."""
    mapping = resolve_dispute_lineage(contract, delivered, proposal)
    whole = run_sqlite_reference(contract, delivered)
    if mapping["global_hold"]:
        held = set(whole)
        published = {}
        status = "withheld_all"
    else:
        held = {mapping["group"]}
        published = {key: amount for key, amount in whole.items()
                     if key not in held}
        status = "partially_held"
    return {
        "status": status, "published": published,
        "held_groups": sorted(held), "lineage": mapping,
        "proposed_mutation_admitted": False,
        "quarantined_source_rows": 0,
        "reason": "financial_movement_under_evidence_review",
    }


def publish_verified_correction(
    contract: dict, delivered: dict, proposed: dict, proposal: dict,
    *, receipt: dict, verifier_key: bytes,
) -> dict:
    """Read-only proof of release; no process-event ledger is accepted."""
    gate = verify_scoped_correction(contract, delivered, proposed, proposal,
                                    receipt, verifier_key)
    accepted = gate["decision"] == "accepted"
    candidate = proposed if accepted else delivered
    if not accepted:
        pending = publish_pending_dispute(contract, delivered, proposal)
        return {**pending, "receipt_gate": gate,
                "recovered": False}
    published = run_sqlite_reference(contract, candidate)
    return {
        "status": "published",
        "published": published,
        "held_groups": [], "lineage": resolve_dispute_lineage(
            contract, delivered, proposal),
        "proposed_mutation_admitted": True,
        "quarantined_source_rows": 0,
        "reason": "source_edit_admitted_by_scoped_signed_receipt",
        "receipt_gate": gate,
        "recovered": True,
    }


def demonstrate_contract_casework(contract: dict, events: list[dict],
                                   case: dict) -> dict:
    """Three stages, with separated actor/evidence privileges."""
    c = validate_contract(contract)
    if case["id"] != "attested_credit_recovery":
        raise ValueError("casework only supports authentic correction control")
    dirty = case["initial"]
    proposed, effect = candidate_source(c, dirty, case["ticket"],
                                         case["candidate"])
    if effect != "source_cell_rewritten":
        raise ValueError("expected a real candidate correction")
    truth = event_business_oracle(c, events)
    original = score_publication(truth, run_sqlite_reference(c, dirty), set())
    pending = publish_pending_dispute(c, dirty, case["candidate"])
    pending_score = score_publication(
        truth, pending["published"], set(pending["held_groups"]))
    if pending_score["false_published_groups"] or pending_score["silent_missing_groups"]:
        raise AssertionError("targeted pending hold accidentally published false data")

    # Independent issuer has the original event ledger, but the release
    # verifier only sees signed ONE-ROW evidence and separately provisioned key.
    provider = project_source(c, events)
    table = case["candidate"]["table"]
    true_row = next(row for row in provider[table]
                    if row["row_id"] == case["candidate"]["row_id"])
    verifier_key = secrets.token_bytes(32)
    receipt = issue_simulated_receipt(c, true_row, verifier_key)
    accepted = publish_verified_correction(
        c, dirty, proposed, case["candidate"],
        receipt=receipt, verifier_key=verifier_key)
    final_score = score_publication(truth, accepted["published"], set())
    if final_score["status"] != "correctly_published":
        raise AssertionError("verified correction did not fully restore business truth")
    # A public incident timeline is intentionally limited to receipt ID,
    # hashes and release metadata. No secret key is serialized.
    receipt_ref = sha256(json.dumps(receipt,sort_keys=True).encode()).hexdigest()[:20]
    return {
        "experiment": "contract_casework_evidence_arrival_v1",
        "domain": c["name"],
        "source_ledger_present_in_release_planner": False,
        "synthetic_provider_receipt_not_real_connection": True,
        "signing_key_exported": False,
        "model_did_not_author_receipt": True,
        "receipt_reference": receipt_ref,
        "stages": [
            {"stage": "unprotected_dirty_source",
             "publication_status": "published",
             "score": original},
            {"stage": "disputed_waiting_for_independent_evidence",
             "publication_status": pending["status"],
             "held_group_ids": [f"{day}|{group}" for day,group
                                in pending["held_groups"]],
             "quarantined_source_rows": 0,
             "score": pending_score},
            {"stage": "scoped_receipt_verified_and_corrected",
             "publication_status": accepted["status"],
             "gate": accepted["receipt_gate"],
             "score": final_score},
        ],
    }
