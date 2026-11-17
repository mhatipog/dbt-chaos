"""A miniature sales data platform with independent source and SQL chaos.

Contract: only completed EUR orders with positive gross and an existing customer
are reportable; latest version per natural key wins; captured payments less
refunds are grouped by order day and customer segment. Invalid payment values
are quarantined. Missing events cannot be inferred from the admitted source.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

SOURCE_FAULTS = (
    "none", "duplicate_customer", "duplicate_payment", "duplicate_order",
    "orphan_customer", "null_payment", "negative_payment", "usd_order",
    "cancelled_with_payment", "customer_version_change", "missing_refund",
    "split_capture", "invalid_order_status", "null_order_gross",
)
LOGIC_FAULTS = (
    "none", "skip_customer_dedup", "skip_payment_dedup",
    "ignore_refunds", "wrong_payment_join", "include_cancelled",
    "ignore_currency", "wrong_customer_join", "wrong_grain",
)
PAIR_PROBES = (
    ("duplicate_customer", "skip_customer_dedup"),
    ("duplicate_payment", "skip_payment_dedup"),
    ("cancelled_with_payment", "include_cancelled"),
    ("usd_order", "ignore_currency"),
    ("missing_refund", "ignore_refunds"),  # two faults may mask one another
    ("orphan_customer", "wrong_customer_join"),
    ("split_capture", "wrong_grain"),
)
TABLES = ("customers", "orders", "payments")

@dataclass(frozen=True)
class CommerceCase:
    source_fault: str = "none"
    logic_fault: str = "none"

    def __post_init__(self) -> None:
        if self.source_fault not in SOURCE_FAULTS:
            raise ValueError("unsupported source fault")
        if self.logic_fault not in LOGIC_FAULTS:
            raise ValueError("unsupported logic fault")

    @property
    def name(self) -> str:
        return f"source={self.source_fault};logic={self.logic_fault}"

    @property
    def origin(self) -> str:
        if self.source_fault != "none" and self.logic_fault != "none":
            return "combined"
        if self.source_fault != "none":
            return "source"
        if self.logic_fault != "none":
            return "transformation"
        return "control"

def cases(include_cross_product: bool = False) -> list[CommerceCase]:
    """Small explained corpus; full pair matrix is opt-in."""
    result = [CommerceCase()]
    result += [CommerceCase(source_fault=f) for f in SOURCE_FAULTS if f != "none"]
    result += [CommerceCase(logic_fault=f) for f in LOGIC_FAULTS if f != "none"]
    result += [CommerceCase(*pair) for pair in PAIR_PROBES]
    if include_cross_product:
        result += [CommerceCase(src, sql) for src in SOURCE_FAULTS[1:]
                   for sql in LOGIC_FAULTS[1:]]
    return list(dict.fromkeys(result))

def baseline() -> dict[str, list[dict[str, Any]]]:
    return {
        "customers": [
            {"row_id": 101, "customer_id": 1, "version": 1, "segment": "retail"},
            {"row_id": 102, "customer_id": 2, "version": 1, "segment": "business"},
            {"row_id": 103, "customer_id": 3, "version": 1, "segment": "retail"},
        ],
        "orders": [
            {"row_id": 301, "order_id": 1, "customer_id": 1, "version": 1,
             "order_day": "2026-02-01", "gross_cents": 12000, "status": "completed", "currency": "EUR"},
            {"row_id": 302, "order_id": 2, "customer_id": 2, "version": 1,
             "order_day": "2026-02-01", "gross_cents": 5000, "status": "completed", "currency": "EUR"},
            {"row_id": 303, "order_id": 3, "customer_id": 1, "version": 1,
             "order_day": "2026-02-02", "gross_cents": 7000, "status": "cancelled", "currency": "EUR"},
            {"row_id": 304, "order_id": 4, "customer_id": 3, "version": 1,
             "order_day": "2026-02-02", "gross_cents": 3000, "status": "completed", "currency": "EUR"},
        ],
        "payments": [
            {"row_id": 201, "payment_id": 1, "order_id": 1, "version": 1,
             "kind": "capture", "amount_cents": 12000},
            {"row_id": 202, "payment_id": 2, "order_id": 2, "version": 1,
             "kind": "capture", "amount_cents": 5000},
            {"row_id": 203, "payment_id": 3, "order_id": 4, "version": 1,
             "kind": "capture", "amount_cents": 3000},
            {"row_id": 204, "payment_id": 4, "order_id": 1, "version": 1,
             "kind": "refund", "amount_cents": 2000},
        ],
    }

def inject_source(fault: str) -> dict[str, list[dict[str, Any]]]:
    if fault not in SOURCE_FAULTS:
        raise ValueError("unknown source fault")
    data = deepcopy(baseline())
    customers, orders, payments = (data[key] for key in TABLES)
    if fault == "duplicate_customer":
        row = deepcopy(customers[0]); row["row_id"] = 105; customers.append(row)
    elif fault == "duplicate_payment":
        row = deepcopy(payments[0]); row["row_id"] = 205; payments.append(row)
    elif fault == "duplicate_order":
        row = deepcopy(orders[0]); row["row_id"] = 305; orders.append(row)
    elif fault == "orphan_customer":
        orders[-1]["customer_id"] = 999
    elif fault == "null_payment":
        payments[2]["amount_cents"] = None
    elif fault == "negative_payment":
        payments[2]["amount_cents"] = -3000
    elif fault == "usd_order":
        orders[-1]["currency"] = "USD"
    elif fault == "cancelled_with_payment":
        payments.append({"row_id": 206, "payment_id": 5, "order_id": 3,
                         "version": 1, "kind": "capture", "amount_cents": 7000})
    elif fault == "customer_version_change":
        customers.append({"row_id": 106, "customer_id": 1, "version": 2, "segment": "business"})
    elif fault == "missing_refund":
        payments[:] = [p for p in payments if p["payment_id"] != 4]
    elif fault == "split_capture":
        payments[:] = [p for p in payments if p["payment_id"] != 1]
        payments.extend([
            {"row_id": 207, "payment_id": 6, "order_id": 1, "version": 1,
             "kind": "capture", "amount_cents": 6000},
            {"row_id": 208, "payment_id": 7, "order_id": 1, "version": 1,
             "kind": "capture", "amount_cents": 6000},
        ])
    elif fault == "invalid_order_status":
        orders[-1]["status"] = "complete"
    elif fault == "null_order_gross":
        orders[-1]["gross_cents"] = None
    return data

def _latest(rows: list[dict], key: str) -> dict[int, dict]:
    """Independent source contract; no SQL AST / dbt model reuse."""
    grouped = defaultdict(list)
    for row in rows:
        grouped[row[key]].append(row)
    return {k: sorted(items, key=lambda v: (v["version"], v["row_id"]))[-1]
            for k, items in grouped.items()}

def oracle(data: dict[str, list[dict]]) -> dict[tuple[str, str], int]:
    customers = _latest(data["customers"], "customer_id")
    orders = _latest(data["orders"], "order_id")
    payments = _latest(data["payments"], "payment_id")
    net = defaultdict(int)
    for p in payments.values():
        value = p["amount_cents"]
        if type(value) is not int or value < 0 or p["kind"] not in ("capture", "refund"):
            continue  # Contract says quarantine invalid payment values.
        net[p["order_id"]] += value if p["kind"] == "capture" else -value
    totals = defaultdict(int)
    for order in orders.values():
        if (order["status"] != "completed" or order["currency"] != "EUR"
                or type(order["gross_cents"]) is not int or order["gross_cents"] <= 0):
            continue
        customer = customers.get(order["customer_id"])
        if not customer or not customer["segment"]:
            continue
        totals[(order["order_day"], customer["segment"])] += net[order["order_id"]]
    return dict(sorted((k, v) for k, v in totals.items() if v != 0))

def source_contract_alerts(data: dict[str, list[dict]]) -> list[str]:
    """Independent expectations for source-validation tests, not gold truth."""
    alerts = []
    for kind, key in (("customers", "customer_id"), ("orders", "order_id"),
                      ("payments", "payment_id")):
        counts = Counter((row[key], row["version"]) for row in data[kind])
        if any(n > 1 for n in counts.values()):
            alerts.append("duplicate_" + kind)
    customer_keys = {v["customer_id"] for v in data["customers"]}
    if any(o["customer_id"] not in customer_keys or o["currency"] != "EUR"
           or o["status"] not in ("completed", "cancelled")
           or type(o["gross_cents"]) is not int or o["gross_cents"] <= 0
           for o in data["orders"]):
        alerts.append("invalid_orders")
    if any(type(p["amount_cents"]) is not int or p["amount_cents"] < 0
           or p["kind"] not in ("capture", "refund")
           for p in data["payments"]):
        alerts.append("invalid_payments")
    return sorted(alerts)

def difference(expected: dict, actual: dict) -> dict:
    keys = expected.keys() | actual.keys()
    return {f"{key[0]}|{key[1]}": {"expected": expected.get(key),
                                  "actual": actual.get(key)}
            for key in sorted(keys) if expected.get(key) != actual.get(key)}

def classify(expected: dict, actual: dict, source_alerts: list[str],
             output_alerts: list[str], execution_error: str | None = None) -> str:
    """Output alerts must actually guard results; source alerts are not proof of output detection."""
    if execution_error:
        return "execution_failure"
    if expected != actual:
        return "detected_failure" if output_alerts else "silent_corruption"
    if source_alerts:
        return "contained"
    return "correct"

def assess(case: CommerceCase, observed: dict, source_alerts: list[str],
           output_alerts: list[str], execution_error: str | None = None) -> dict:
    data = inject_source(case.source_fault)
    expected = oracle(data)
    original = oracle(baseline())
    return {
        "case": case.name, "origin": case.origin, "source_fault": case.source_fault,
        "logic_fault": case.logic_fault, "contract": "commerce-v1",
        "expected": {f"{k[0]}|{k[1]}": v for k,v in expected.items()},
        "observed": {f"{k[0]}|{k[1]}": v for k,v in observed.items()},
        "contract_difference": difference(expected, observed),
        "source_baseline_difference": difference(original, expected),
        "source_alerts": source_alerts,
        "output_alerts": output_alerts,
        "classification": classify(expected, observed, source_alerts, output_alerts, execution_error),
        "execution_error": execution_error,
        "source_loss_not_self_verifiable": case.source_fault == "missing_refund",
        "notable": "All counts and amounts are synthetic; source inputs may legitimately change contract truth."
    }

def summarize(results: list[dict]) -> dict:
    counts = Counter(item["classification"] for item in results)
    per_origin: dict[str, Counter] = defaultdict(Counter)
    for item in results:
        per_origin[item["origin"]][item["classification"]] += 1
    errors = counts["execution_failure"]
    evaluable = len(results) - errors
    return {
        "schema_version": 1, "evidence_level": "executed_dbt_duckdb",
        "workload": "three-source-order-customer-payment", "contract": "commerce-v1",
        "outcomes": dict(sorted(counts.items())),
        "per_origin": {key: dict(sorted(value.items())) for key,value in sorted(per_origin.items())},
        "evaluated": evaluable, "execution_errors": errors,
        "cases": len(results), "silent_failures": counts["silent_corruption"],
        "correct_or_contained": counts["correct"] + counts["contained"],
        "interpretation": "Synthetic case outcomes only; not production reliability estimates."
    }
