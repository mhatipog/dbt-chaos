"""Independent payment evidence ecosystem and observable reconciliation.

A synthetic business EVENT ledger is used ONLY to construct separate upstream
feeds and (later) to score results. The reconciler receives source tables and
evidence feeds, NEVER the original business event ledger or oracle.

Evidence roots model independence: the internal accounting journal is a
copy of the operational ledger, not a second independent vote. PSP receipts
and bank batch totals represent distinct *simulated* external observations.
None of these are signed real-world statements or production trust anchors.

Financial simplification: settlement batch_id is based on synthetic order day
with zero fees/FX. This is NOT a real PSP payout or real bank settlement model.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any

from .commerce import oracle
from .full_datasets import Profile, clean_dataset, absolute_group_error

EVIDENCE_ROOTS = {
    "operational_payments": "merchant_application",
    "accounting_journal": "merchant_application",
    "provider_transactions": "independent_psp",
    "bank_batches": "independent_bank",
}
MAX_PROVIDER_DELAY_DAYS = 2
MAX_BANK_DELAY_DAYS = 4


def _latest(rows: list[dict], key: str) -> dict[int, dict]:
    result = {}
    for row in rows:
        existing = result.get(row[key])
        if existing is None or (
            row["version"], row["row_id"]) > (
            existing["version"], existing["row_id"]):
            result[row[key]] = row
    return result


def _group_map(source: dict[str, list[dict]]) -> tuple[dict[int, tuple[str, str]],
                                                        dict[int, str]]:
    customers = _latest(source["customers"], "customer_id")
    orders = _latest(source["orders"], "order_id")
    by_order = {}
    day_by_order = {}
    for oid, row in orders.items():
        day_by_order[oid] = row["order_day"]
        customer = customers.get(row["customer_id"])
        if customer is not None:
            by_order[oid] = (row["order_day"], customer["segment"])
    return by_order, day_by_order


def evidence_from_process(events: list[dict], source_truth: dict[str, list[dict]]
                          ) -> dict[str, list[dict]]:
    """Create independently sourced upstream observations BEFORE injecting faults.

    Only this test-fixture builder has process truth. The reconciliation engine
    below cannot accept events, the truth oracle, or a source_truth parameter.
    """
    _, days = _group_map(source_truth)
    provider = []
    journal = []
    bank_totals: dict[str, int] = defaultdict(int)
    for event in events:
        if event["type"] not in ("payment_captured", "payment_refunded"):
            continue
        kind = "capture" if event["type"] == "payment_captured" else "refund"
        sign = 1 if kind == "capture" else -1
        pid = event["payment_id"]
        day = days[event["order_id"]]
        provider.append({
            "payment_id": pid, "order_id": event["order_id"],
            "kind": kind, "amount_cents": event["amount_cents"],
            "batch_day": day, "available_after_days": 1 + pid % 2,
            "origin_root": "independent_psp",
            "reference": f"PSP-{pid:07d}",
        })
        # A simulated GL posting derived from the merchant's internal event
        # flow, so it shares a root with merchant/operational payments.
        journal.append({
            "payment_id": pid,
            "signed_cents": sign * event["amount_cents"],
            "available_after_days": 0,
            "origin_root": "merchant_application",
            "reference": f"GL-{pid:07d}",
        })
        bank_totals[day] += sign * event["amount_cents"]
    bank = [
        {
            "batch_day": day, "net_cents": total,
            "available_after_days": 3 + (i % 2),
            "origin_root": "independent_bank",
            "reference": f"BANK-{day}",
        }
        for i, (day, total) in enumerate(sorted(bank_totals.items()))
    ]
    evidence = {
        "provider_transactions": provider,
        "accounting_journal": journal,
        "bank_batches": bank,
    }
    validate_evidence(evidence)
    return evidence


def validate_evidence(evidence: dict[str, list[dict]]) -> None:
    if set(evidence) != set(EVIDENCE_ROOTS) - {"operational_payments"}:
        raise ValueError("expected exactly provider, journal and bank feeds")
    for name, rows in evidence.items():
        if not isinstance(rows, list):
            raise ValueError(f"invalid evidence rows in {name}")
        seen = set()
        key_field = "batch_day" if name == "bank_batches" else "payment_id"
        for record in rows:
            key = record.get(key_field)
            if key in seen:
                raise ValueError(f"duplicate evidence key in {name}: {key}")
            seen.add(key)
            if record.get("origin_root") != EVIDENCE_ROOTS[name]:
                raise ValueError(f"forged or incorrect evidence provenance in {name}")
            lag = record.get("available_after_days")
            if type(lag) is not int or not 0 <= lag <= 10:
                raise ValueError(f"invalid evidence availability in {name}")
            if name == "bank_batches":
                if type(record.get("net_cents")) is not int:
                    raise ValueError("invalid bank net")
            elif name == "provider_transactions":
                if (record.get("kind") not in ("capture", "refund") or
                        type(record.get("amount_cents")) is not int or
                        record["amount_cents"] < 0 or
                        type(record.get("order_id")) is not int or
                        not isinstance(record.get("batch_day"), str)):
                    raise ValueError("invalid provider record")
            else:
                if type(record.get("signed_cents")) is not int:
                    raise ValueError("invalid internal journal amount")


def make_scenarios(seed: int = 20261119) -> dict[str, Any]:
    """Deterministic, named cases with *explicit* corruption and provenance.

    The original Qwen edit is genuine historical model output from the
    20-step experiment. Other cases here are *scripted controls* and must not
    be misrepresented as newly generated LLM errors.
    """
    events, truth = clean_dataset(Profile(seed=seed))
    if seed != 20261119:
        raise ValueError("recorded Qwen refund reference is seed-specific")
    evidence = evidence_from_process(events, truth)
    victim = next(p for p in truth["payments"] if p["row_id"] == 30669)
    if victim["payment_id"] != 288 or victim["kind"] != "refund" or victim["amount_cents"] != 4900:
        raise AssertionError("recorded Qwen refund event precondition changed")
    op = deepcopy(truth)
    target = next(p for p in op["payments"] if p["payment_id"] == 288)
    target["amount_cents"] = 2900

    cases: dict[str, dict] = {}
    def insert(name: str, source: dict, streams: dict, lag: int, origin: str):
        cases[name] = {
            "source": deepcopy(source), "evidence": deepcopy(streams),
            "as_of_lag_days": lag, "provenance": origin,
        }

    insert("clean_mature", truth, evidence, 5,
           "Unmodified synthetic truth; all evidence arrived")
    insert("qwen_refund_source_only", op, evidence, 5,
           "Archived real Qwen €49→€29 operational payment edit")
    correlated = deepcopy(evidence)
    entry = next(r for r in correlated["accounting_journal"]
                 if r["payment_id"] == 288)
    entry["signed_cents"] = -2900
    insert("qwen_refund_and_correlated_gl", op, correlated, 5,
           "Qwen operational edit + scripted internal journal copy of error")
    insert("clean_before_settlement", truth, evidence, 0,
           "Legitimate clean transaction before external feeds arrive")
    insert("clean_after_provider_before_bank", truth, evidence, 2,
           "Legitimate on-time provider evidence; bank batches pending")
    insert("qwen_before_provider", op, evidence, 0,
           "Qwen source edit while independent provider/bank feeds pending")
    missing = deepcopy(evidence)
    missing["provider_transactions"] = [
        r for r in missing["provider_transactions"] if r["payment_id"] != 288]
    insert("missing_provider_after_sla", truth, missing, 5,
           "Scripted permanently missing PSP transaction record")
    wrong_psp = deepcopy(correlated)
    provider = next(r for r in wrong_psp["provider_transactions"]
                    if r["payment_id"] == 288)
    provider["amount_cents"] = 2900
    insert("psp_and_gl_corrupted_bank_catches", op, wrong_psp, 5,
           "Scripted PSP plus internal journal error; independent bank remains correct")
    bank_derived_psp = deepcopy(wrong_psp)
    for row in bank_derived_psp["bank_batches"]:
        row["origin_root"] = "independent_psp"  # invalid: cannot masquerade as bank
    # We do NOT insert a forged independent bank case as valid evidence.
    return {"seed": seed, "events": events, "truth": truth,
            "cases": cases, "original_provider": evidence}


def reconcile(source: dict[str, list[dict]], evidence: dict[str, list[dict]],
              *, as_of_lag_days: int, require_bank: bool = True) -> dict:
    """Observable reconciliation ONLY. No business process truth argument.

    Available provider records must match transaction ID, order, kind, amount
    and batch. Batch bank totals reconcile aggregated *operational* payments
    (not a second copy of PSP); they cannot locate the wrong payment alone.

    If an evidence source is due but missing, flag. If not yet due,
    classify as pending, not corruption.
    """
    if type(as_of_lag_days) is not int or not 0 <= as_of_lag_days <= 10:
        raise ValueError("invalid as-of evidence lag")
    validate_evidence(evidence)
    groups, days = _group_map(source)
    current = _latest(source["payments"], "payment_id")
    provider = {r["payment_id"]: r for r in evidence["provider_transactions"]
                if r["available_after_days"] <= as_of_lag_days}
    journal = {r["payment_id"]: r for r in evidence["accounting_journal"]
               if r["available_after_days"] <= as_of_lag_days}
    banks = {r["batch_day"]: r for r in evidence["bank_batches"]
             if r["available_after_days"] <= as_of_lag_days}
    day_totals: dict[str, int] = defaultdict(int)
    all_days = set(days.values())
    flags = []
    held_groups = set()
    held_days = set()
    pending_ids = set()
    verified_ids = set()
    source_only = set()
    per_payment = {}
    for pid, payment in sorted(current.items()):
        oid = payment["order_id"]
        day = days.get(oid)
        group = groups.get(oid)
        if day is None or group is None:
            flags.append({"code": "payment_order_unresolvable", "payment_id": pid,
                          "day": day, "severity": "dispute"})
            held_days.update(all_days)
            continue
        signed = payment["amount_cents"] * (
            -1 if payment["kind"] == "refund" else 1)
        day_totals[day] += signed
        if pid in journal and journal[pid]["signed_cents"] != signed:
            flags.append({"code": "correlated_internal_gl_mismatch",
                          "payment_id": pid, "day": day, "severity": "dispute"})
            held_groups.add(group)
        match = provider.get(pid)
        if match is None:
            if as_of_lag_days >= MAX_PROVIDER_DELAY_DAYS:
                code = "provider_record_missing_after_sla"
                flags.append({"code": code, "payment_id": pid,
                              "day": day, "severity": "dispute"})
                held_groups.add(group)
            else:
                pending_ids.add(pid)
            per_payment[pid] = "missing_or_pending"
            continue
        if (match["amount_cents"] != payment["amount_cents"] or
                match["kind"] != payment["kind"] or
                match["order_id"] != oid or
                match["batch_day"] != day):
            flags.append({"code": "provider_transaction_mismatch",
                          "payment_id": pid, "day": day, "severity": "dispute"})
            held_groups.add(group)
            per_payment[pid] = "mismatched"
        else:
            verified_ids.add(pid)
            per_payment[pid] = "provider_matched"
    # Provider-only extra transactions are important, but a legitimate
    # reconciliation without settlement due must not call them a missing
    # source. Localize using provider order reference if possible.
    for pid, record in sorted(provider.items()):
        if pid in current:
            continue
        group = groups.get(record["order_id"])
        day = days.get(record["order_id"])
        flags.append({"code": "source_payment_missing", "payment_id": pid,
                      "day": day, "severity": "dispute"})
        if group is not None:
            held_groups.add(group)
        else:
            held_days.update(all_days)
    for day in sorted(all_days):
        bank = banks.get(day)
        if bank is None:
            if as_of_lag_days < MAX_BANK_DELAY_DAYS:
                # An expected (late) bank batch is pending, not corrupt.
                continue
            if day not in {r["batch_day"] for r in evidence["bank_batches"]}:
                flags.append({"code": "bank_batch_missing_after_sla",
                              "payment_id": None, "day": day,
                              "severity": "dispute"})
                held_days.add(day)
            continue
        if day_totals.get(day, 0) != bank["net_cents"]:
            flags.append({"code": "independent_bank_balance_mismatch",
                          "payment_id": None, "day": day,
                          "severity": "dispute"})
            held_days.add(day)
    source_group_keys = set(oracle(source))
    for group in source_group_keys:
        if group[0] in held_days:
            held_groups.add(group)
    group_days = {group[0] for group in source_group_keys}
    if require_bank and as_of_lag_days < MAX_BANK_DELAY_DAYS:
        # Hold pending bank-coverage days; a pending settlement is NOT a
        # false data quality alert and cannot be counted as recovered.
        held_groups |= source_group_keys
    elif require_bank:
        for day in group_days:
            if day not in banks:
                held_groups |= {group for group in source_group_keys
                                if group[0] == day}
    if pending_ids:
        for pid in pending_ids:
            p = current[pid]
            group = groups.get(p["order_id"])
            if group is not None:
                held_groups.add(group)
    # No vote counting: journal is a correlated merchant copy; only two
    # external roots (PSP, bank) may provide two independent observations.
    bank_root_present = as_of_lag_days >= MAX_BANK_DELAY_DAYS and bool(banks)
    return {
        "status": ("disputed" if flags else "pending_evidence" if
                   (pending_ids or (require_bank and not bank_root_present))
                   else "verified"),
        "findings": flags,
        "held_groups": sorted(f"{d}|{seg}" for d, seg in held_groups),
        "pending_provider_payment_ids": sorted(pending_ids),
        "provider_matched_payment_ids": sorted(verified_ids),
        "matched_provider_count": len(verified_ids),
        "operational_payment_count": len(current),
        "external_roots": ["independent_psp", "independent_bank"],
        "correlated_journal_root": "merchant_application",
        "independent_external_root_count": (
            int(bool(provider)) + int(bool(banks))),
        "evidence_lag_days": as_of_lag_days,
        "require_bank": require_bank,
        "publication_policy": "withhold_affected_groups_without_guessing",
        "observable_source_only": True,
        "per_payment_status": per_payment,
    }


def score_against_process(source: dict, reconciled: dict,
                          truth: dict) -> dict:
    """Only posthoc scoring; forbidden from the observable reconciler."""
    from .relay_platform_replay import score_publication
    expected = oracle(truth)
    candidate = oracle(source)
    held = {tuple(key.split("|", 1)) for key in reconciled["held_groups"]}
    released = {key: value for key, value in candidate.items()
                if key not in held}
    score = score_publication(expected, released, held)
    return {
        **score, "source_error_l1_cents": absolute_group_error(expected, candidate),
        "detected_dispute_count": len(reconciled["findings"]),
        "undetectable_from_delivered_snapshot": (
            score["status"] == "silently_wrong" and
            not reconciled["findings"]),
    }


def evaluate_scenarios(seed: int = 20261119) -> dict:
    original = make_scenarios(seed)
    out = []
    for name, scenario in original["cases"].items():
        rec = reconcile(scenario["source"], scenario["evidence"],
                        as_of_lag_days=scenario["as_of_lag_days"])
        scored = score_against_process(
            scenario["source"], rec, original["truth"])
        out.append({"scenario": name, "origin": scenario["provenance"],
                    "reconciliation": rec, "scoring": scored})
    return {
        "experiment": "multisource_reconciliation_reference_v1",
        "seed": seed,
        "source": "synthetic business process plus archived real Qwen refund edit",
        "cases": out,
        "caveats": [
            "Provider and bank are modeled as independent roots; their authenticity is assumed.",
            "The journal is derived from merchant records and does not count as independent vote.",
            "Synthetic bank batches exclude real-world delays, fees, FX, reversals and chargebacks.",
            "The observable reconciler never reads process truth; the scorer does.",
            "This reference report is Python logic; dbt-native execution is tested separately.",
        ],
    }
