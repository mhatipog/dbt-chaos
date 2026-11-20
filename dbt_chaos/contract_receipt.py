"""Cryptographically bound, narrow-scope synthetic provider receipt gate.

The verifier does NOT need a complete process ledger. It holds a secret
verifier key provisioned independently of the LLM and receives a provider
receipt for exactly one transaction amount. It permits a proposed source
correction only if the signed receipt matches the contract, transaction
identity, parent document, version, kind, field and proposed cents.

The synthetic demo uses HMAC-SHA256 so Python stdlib is sufficient.
Production providers should use independently authenticated public-key
signatures and managed keys. This is NOT a real payment provider.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import hmac
import json
import secrets
from typing import Any

from .process_contract import validate_contract

FORMAT = "dbt_chaos_simulated_signed_provider_receipt_v1"


def _canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("utf8")


def issue_simulated_receipt(contract: dict, authoritative_row: dict,
                            signer_key: bytes) -> dict:
    c=validate_contract(contract)
    m=c["roles"]["movement"]
    if not isinstance(signer_key,bytes) or len(signer_key)<32:
        raise ValueError("use a separately managed 256-bit signer key")
    required={"row_id",m["id"],m["document_fk"],"version",m["kind"],m["amount"]}
    if set(authoritative_row)!=required:
        raise ValueError("receipt must correspond to one complete authoritative movement row")
    if type(authoritative_row[m["amount"]]) is not int or authoritative_row[m["amount"]] < 0:
        raise ValueError("invalid authoritative amount")
    if authoritative_row[m["kind"]] not in c["semantics"]["signs"]:
        raise ValueError("unrecognized financial movement kind")
    payload={
        "format":FORMAT,
        "issuer":"simulated_external_payment_provider",
        "contract":c["name"],
        "table":m["table"],
        "row_id":authoritative_row["row_id"],
        "business_id":authoritative_row[m["id"]],
        "document_id":authoritative_row[m["document_fk"]],
        "version":authoritative_row["version"],
        "kind":authoritative_row[m["kind"]],
        "amount_field":m["amount"],
        "authentic_amount_cents":authoritative_row[m["amount"]],
    }
    return {"payload":payload,
            "hmac_sha256":hmac.new(signer_key,_canonical(payload),
                                   hashlib.sha256).hexdigest()}


def verify_scoped_correction(contract: dict, delivered: dict,
                             candidate: dict, proposal: dict,
                             receipt: dict, verifier_key: bytes) -> dict[str, Any]:
    """Source-only + signature evidence; NEVER receives independent gold."""
    def reject(reason):
        return {"decision":"review_required","reason":reason,
                "evidence":"simulated_provider_receipt_hmac","applied":False}
    c=validate_contract(contract)
    m=c["roles"]["movement"]
    if not isinstance(verifier_key,bytes) or len(verifier_key)<32:
        return reject("verifier_key_missing")
    if (not isinstance(receipt,dict) or set(receipt)!={"payload","hmac_sha256"}
            or not isinstance(receipt["payload"],dict)
            or not isinstance(receipt["hmac_sha256"],str)):
        return reject("receipt_schema_invalid")
    payload=receipt["payload"]
    allowed={"format","issuer","contract","table","row_id","business_id",
             "document_id","version","kind","amount_field","authentic_amount_cents"}
    if set(payload)!=allowed:
        return reject("receipt_schema_invalid")
    if (payload["format"]!=FORMAT or
            payload["issuer"]!="simulated_external_payment_provider" or
            payload["contract"]!=c["name"] or
            payload["table"]!=m["table"] or
            payload["amount_field"]!=m["amount"]):
        return reject("receipt_contract_mismatch")
    expected=hmac.new(verifier_key,_canonical(payload),
                      hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected,receipt["hmac_sha256"]):
        return reject("receipt_signature_invalid")
    if (proposal.get("operation")!="edit_cell"
            or proposal.get("table")!=m["table"]
            or type(proposal.get("row_id")) is not int
            or proposal.get("field")!=m["amount"]
            or type(proposal.get("value")) is not int):
        return reject("proposal_not_a_scoped_amount_edit")
    row_id=proposal["row_id"]
    original=next((r for r in delivered[m["table"]]
                   if r["row_id"]==row_id),None)
    updated=next((r for r in candidate[m["table"]]
                  if r["row_id"]==row_id),None)
    if original is None or updated is None:
        return reject("original_or_proposed_row_missing")
    if (payload["row_id"]!=row_id
            or payload["business_id"]!=original[m["id"]]
            or payload["document_id"]!=original[m["document_fk"]]
            or payload["version"]!=original["version"]
            or payload["kind"]!=original[m["kind"]]
            or payload["authentic_amount_cents"]!=proposal["value"]):
        return reject("receipt_not_bound_to_proposed_row_and_amount")
    # Verify no other source row, column or business entity changes.
    expected_candidate=deepcopy(delivered)
    expected_row=next(r for r in expected_candidate[m["table"]]
                      if r["row_id"]==row_id)
    expected_row[m["amount"]]=proposal["value"]
    if expected_candidate!=candidate:
        return reject("proposal_changes_outside_scoped_receipt")
    if original[m["amount"]]==proposal["value"]:
        return {"decision":"accepted","reason":"already_equal_no_change",
                "evidence":"simulated_provider_receipt_hmac","applied":False}
    return {"decision":"accepted","reason":"authentic_scoped_provider_receipt",
            "evidence":"simulated_provider_receipt_hmac","applied":True}


def demonstrate_receipt_gate(contract: dict, events: list[dict],
                             dirty_source: dict, corrected_source: dict,
                             correction_proposal: dict) -> dict:
    """Synthetic proof of one independently receipted financial correction.

    The event ledger is used by the *issuer only* to create a signed
    one-row receipt. The verifier sees just source rows, proposal,
    receipt and a separately provisioned HMAC key.
    """
    from .process_contract import project_source, event_business_oracle, run_sqlite_reference
    from .relay_platform_replay import score_publication

    c=validate_contract(contract)
    authoritative=project_source(c,events)
    table=correction_proposal["table"]
    record=next(r for r in authoritative[table]
                if r["row_id"]==correction_proposal["row_id"])
    signing_key=secrets.token_bytes(32)  # Never shown to the LLM.
    receipt=issue_simulated_receipt(c,record,signing_key)
    accepted=verify_scoped_correction(
        c,dirty_source,corrected_source,correction_proposal,
        receipt,signing_key)
    truth=event_business_oracle(c,events)
    before=run_sqlite_reference(c,dirty_source)
    after=run_sqlite_reference(
        c,corrected_source if accepted["decision"]=="accepted" else dirty_source)
    return {
        "receipt":receipt,
        "gate":accepted,
        "before":score_publication(truth,before,set()),
        "after":score_publication(truth,after,set()),
        "model_authored_evidence":False,
        "full_private_ledger_given_to_gate":False,
        "real_external_provider_connected":False,
        "signing_key_exported":False,
    }
