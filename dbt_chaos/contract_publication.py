"""Observable, lineage-aware reporting release policy for process contracts.

This policy receives only delivered source tables and results of real
SQLite source-quality SQL. It must NOT access the hidden event ledger.

An integrity failure whose reporting group can be derived from valid
document→party ancestors withholds ONLY that group. Missing ancestors
or conflicting cross-document versions fail closed for the entire report.
This is a publication gate, not a physical source quarantine or repair.
"""
from __future__ import annotations
from typing import Any

from .process_contract import validate_contract, delivered_source_oracle

GLOBAL_RISKS = {
    "orphan_movement", "orphan_document_party",
    "conflicting_movement_version",
}
LOCAL_RISKS = {
    "invalid_movement_kind", "negative_movement_amount",
    "credit_exceeds_settlement",
}


def _latest(rows: list[dict], field: str) -> dict[int, dict]:
    output: dict[int, dict] = {}
    for row in rows:
        ident = row[field]
        old = output.get(ident)
        if old is None or (row["version"], row["row_id"]) > (
                old["version"], old["row_id"]):
            output[ident] = row
    return output


def plan_publication(contract: dict, delivered: dict,
                     issues: list[dict]) -> dict[str, Any]:
    """Calculate a release plan using source evidence alone."""
    c = validate_contract(contract)
    party, document, movement = (c["roles"][r] for r in
                                 ("party", "document", "movement"))
    parties = _latest(delivered[party["table"]], party["id"])
    documents = _latest(delivered[document["table"]], document["id"])
    held: set[tuple[str, str]] = set()
    reasons: list[dict] = []
    global_hold = False
    for issue in issues:
        if issue.get("severity") == "info":
            continue
        if issue.get("severity") != "block":
            # Treat unknown issue severity conservatively.
            global_hold = True
            reasons.append({"check": issue.get("check_name"),
                            "scope": "global", "reason": "unknown_severity"})
            continue
        name = issue.get("check_name")
        if name in GLOBAL_RISKS or name not in LOCAL_RISKS:
            global_hold = True
            reasons.append({"check": name, "scope": "global",
                            "reason": "missing_or_ambiguous_lineage"})
            continue
        related = issue.get("related_id")
        doc = documents.get(related)
        person = parties.get(doc[document["party_fk"]]) if doc else None
        if doc is None or person is None:
            global_hold = True
            reasons.append({"check": name, "scope": "global",
                            "reason": "ancestor_unavailable"})
            continue
        key = (doc[document["date"]], person[party["dimension"]])
        held.add(key)
        reasons.append({"check": name, "scope": "group",
                        "group_key": f"{key[0]}|{key[1]}",
                        "reason": "observable_ancestor"})
    raw = delivered_source_oracle(c, delivered)
    if global_hold:
        released = {}
        status = "withheld_all"
    else:
        released = {key: value for key, value in raw.items() if key not in held}
        status = "partially_held" if held else "published"
    return {
        "status": status, "global_hold": global_hold,
        "known_held_groups": [f"{day}|{group}" for day, group in sorted(held)],
        "released": released, "reasons": reasons,
        "blocked_issue_count": sum(i.get("severity") == "block" for i in issues),
        "informational_count": sum(i.get("severity") == "info" for i in issues),
        "basis": "delivered_source_and_observable_sql_checks_only",
        "quarantined_physical_rows": 0,
    }
