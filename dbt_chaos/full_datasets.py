"""Full synthetic commerce datasets plus LLM-authored, good-faith delivery edits.

A business event log is the authority. Models can suggest bounded process
*parameters* and operational *edits*, but never change the hidden ledger.
Every step exports complete source tables; all SQL executes only through the
shipped allowlisted dbt project. No model-written code is executed.
"""
from __future__ import annotations

import argparse
import csv
from copy import deepcopy
from dataclasses import dataclass, asdict
from datetime import date, timedelta
from hashlib import sha256
import json
from pathlib import Path
import random
from typing import Any

from .commerce import CommerceCase, difference, oracle, source_contract_alerts
from .commerce_runner import COLUMNS, run_case


@dataclass(frozen=True)
class Profile:
    customers: int = 64
    orders: int = 480
    cancel_percent: int = 12
    capture_percent: int = 86
    refund_percent: int = 21
    history_percent: int = 18
    seed: int = 20261119

    def __post_init__(self):
        if not 12 <= self.customers <= 100 or not 60 <= self.orders <= 1000:
            raise ValueError("bounded synthetic workload only")
        for field in ("cancel_percent", "capture_percent", "refund_percent", "history_percent"):
            if not 0 <= getattr(self, field) <= 90:
                raise ValueError(f"invalid {field}")
        if self.capture_percent < 30:
            raise ValueError("at least 30% captured orders required")


PROFILE_FIELDS = ("customers", "orders", "cancel_percent",
                  "capture_percent", "refund_percent", "history_percent")

# Public process policy (safe for worker context), NOT the hidden event ledger.
# In the lossy relay, this charter appears only at the first handoff.
BUSINESS_CHARTER = (
    "P01: A genuine refund must be preserved unless independent payment "
    "evidence proves duplication. Suspicion alone is not evidence. "
    "P02: Historical customer versions are valid; analytical joins use the "
    "latest version rather than every historical row. "
    "P03: Identical delivery retries must be idempotent; do not fabricate "
    "new business events when processing retry notifications. "
    "P04: Completed EUR orders only, with refunds subtracted from captures. "
    "P05: Source data can be incomplete despite passing all local checks. "
    "P06: When evidence is uncertain, do not silently rewrite financial facts."
)



def absolute_group_error(expected: dict, observed: dict) -> int:
    """L1 error over day/segment groups; reclassifications never cancel out."""
    return sum(abs(expected.get(k, 0) - observed.get(k, 0))
               for k in expected.keys() | observed.keys())


def enhanced_source_alerts(data: dict[str, list[dict]]) -> list[str]:
    """Additional observable integrity detectors; NO access to event-ledger truth.

    These are candidate quality checks, not dbt tests already installed.
    Unlike a business-ledger reconciliation they cannot discover valid-looking
    edits that misrepresent what *actually* happened.
    """
    customers = {r["customer_id"] for r in data["customers"]}
    latest_orders: dict[int, dict] = {}
    for row in data["orders"]:
        key = row["order_id"]
        old = latest_orders.get(key)
        if old is None or (row["version"], row["row_id"]) > (old["version"], old["row_id"]):
            latest_orders[key] = row
    alerts = set()
    if any(order["customer_id"] not in customers for order in latest_orders.values()):
        alerts.add("orders_missing_customer")
    if any(payment["order_id"] not in latest_orders for payment in data["payments"]):
        alerts.add("payments_missing_order")
    amounts: dict[int, dict[str, int]] = {}
    for row in data["payments"]:
        kind, value = row["kind"], row["amount_cents"]
        if kind in ("capture", "refund") and type(value) is int and value >= 0:
            amounts.setdefault(row["order_id"], {"capture": 0, "refund": 0})[kind] += value
    for order_id, values in amounts.items():
        if values["refund"] > values["capture"]:
            alerts.add("refund_exceeds_capture")
        order = latest_orders.get(order_id)
        if order and type(order["gross_cents"]) is int:
            if values["capture"] > order["gross_cents"]:
                alerts.add("capture_exceeds_order_gross")
            if order["status"] == "cancelled" and values["capture"] > values["refund"]:
                alerts.add("uncleared_cancelled_capture")
    return sorted(alerts)


def parse_profile(raw: str, *, seed: int) -> tuple[Profile, bool]:
    """A model-generated scenario is accepted only if every field passes checks."""
    try:
        a, b = raw.index("{"), raw.rindex("}") + 1
        value = json.loads(raw[a:b])
        if not isinstance(value, dict) or set(value) != set(PROFILE_FIELDS):
            raise ValueError("incorrect profile keys")
        if any(type(value[k]) is not int for k in PROFILE_FIELDS):
            raise ValueError("profile fields must be integers")
        return Profile(**value, seed=seed), True
    except (ValueError, TypeError, json.JSONDecodeError):
        return Profile(seed=seed), False


def generate_events(profile: Profile) -> list[dict[str, Any]]:
    """Generate business process *events*, not correlated columns independently."""
    rng = random.Random(profile.seed)
    events = []

    def emit(kind: str, **payload):
        events.append({"event_id": len(events) + 1, "type": kind, **payload})

    for customer_id in range(1, profile.customers + 1):
        segment = rng.choices(["retail", "business", "public"], weights=[65, 30, 5])[0]
        emit("customer_created", customer_id=customer_id, segment=segment)
        if rng.randrange(100) < profile.history_percent:
            # A legitimate slowly-changing history snapshot, sometimes same segment.
            updated = (segment if rng.randrange(10) < 7 else
                       rng.choice([s for s in ("retail", "business", "public") if s != segment]))
            emit("customer_profile_updated", customer_id=customer_id, segment=updated)

    payment_id = 1
    start = date(2026, 2, 1)
    for order_id in range(1, profile.orders + 1):
        customer_id = rng.randint(1, profile.customers)
        gross = rng.randrange(20, 1000) * 100
        day = (start + timedelta(days=rng.randrange(28))).isoformat()
        emit("order_placed", order_id=order_id, customer_id=customer_id,
             order_day=day, gross_cents=gross, currency="EUR")
        if rng.randrange(100) < profile.cancel_percent:
            emit("order_cancelled", order_id=order_id)
            continue
        if rng.randrange(100) >= profile.capture_percent:
            continue
        # Captures cannot exceed gross. Some payments are deliberately partial.
        captured = gross if rng.randrange(10) < 8 else max(100, gross // 2 // 100 * 100)
        if rng.randrange(10) == 0 and captured >= 200:
            first = captured // 2 // 100 * 100
            second = captured - first
            emit("payment_captured", payment_id=payment_id, order_id=order_id,
                 amount_cents=first)
            payment_id += 1
            emit("payment_captured", payment_id=payment_id, order_id=order_id,
                 amount_cents=second)
            payment_id += 1
        else:
            emit("payment_captured", payment_id=payment_id, order_id=order_id,
                 amount_cents=captured)
            payment_id += 1
        if rng.randrange(100) < profile.refund_percent:
            refunded = max(100, (captured * rng.randint(1, 9) // 10 // 100) * 100)
            emit("payment_refunded", payment_id=payment_id, order_id=order_id,
                 amount_cents=min(refunded, captured))
            payment_id += 1
    return events


def replay_events(events: list[dict[str, Any]]) -> dict[str, list[dict]]:
    """Materialize the process ledger into the *same contract* as real dbt."""
    data: dict[str, list[dict]] = {"customers": [], "orders": [], "payments": []}
    latest_customers: dict[int, dict] = {}
    latest_orders: dict[int, dict] = {}
    for event in events:
        kind = event["type"]
        if kind in ("customer_created", "customer_profile_updated"):
            cid = event["customer_id"]
            old = latest_customers.get(cid)
            if (kind == "customer_created") != (old is None):
                raise ValueError("invalid customer event sequence")
            row = {
                "row_id": 10000 + event["event_id"], "customer_id": cid,
                "version": old["version"] + 1 if old else 1,
                "segment": event["segment"],
            }
            latest_customers[cid] = row
            data["customers"].append(row)
        elif kind == "order_placed":
            if event["customer_id"] not in latest_customers or event["order_id"] in latest_orders:
                raise ValueError("invalid order event sequence")
            row = {
                "row_id": 20000 + event["event_id"],
                "order_id": event["order_id"], "customer_id": event["customer_id"],
                "version": 1, "order_day": event["order_day"],
                "gross_cents": event["gross_cents"],
                "status": "completed", "currency": event["currency"],
            }
            latest_orders[event["order_id"]] = row
            data["orders"].append(row)
        elif kind == "order_cancelled":
            old = latest_orders[event["order_id"]]
            row = dict(old, row_id=20000 + event["event_id"],
                       version=old["version"] + 1, status="cancelled")
            latest_orders[event["order_id"]] = row
            data["orders"].append(row)
        elif kind in ("payment_captured", "payment_refunded"):
            if event["order_id"] not in latest_orders:
                raise ValueError("payment for unknown order")
            row = {
                "row_id": 30000 + event["event_id"],
                "payment_id": event["payment_id"],
                "order_id": event["order_id"], "version": 1,
                "kind": "capture" if kind == "payment_captured" else "refund",
                "amount_cents": event["amount_cents"],
            }
            data["payments"].append(row)
        else:
            raise ValueError("unknown process event")
    if source_contract_alerts(data):
        raise ValueError("business event replay violates clean source contracts")
    return data


def clean_dataset(profile: Profile) -> tuple[list[dict], dict[str, list[dict]]]:
    events = generate_events(profile)
    tables = replay_events(events)
    if not any(p["kind"] == "refund" for p in tables["payments"]):
        raise ValueError("scenario lacks refunds; choose another seed/profile")
    if not any(c["version"] > 1 for c in tables["customers"]):
        raise ValueError("scenario lacks customer version history")
    return events, tables


# Only the following operational edits are allowed. No arbitrary SQL or Python.
OPERATIONS = (
    "keep", "drop_row", "replay_delivery", "edit_cell",
    "new_customer_snapshot", "simplify_customer_join", "restore_customer_join",
)
EDITABLE_FIELDS = {
    "customers": {"segment"},
    "orders": {"customer_id", "status", "currency", "gross_cents"},
    "payments": {"amount_cents", "kind", "order_id"},
}
ALLOWED_SQL = {"none", "skip_customer_dedup"}


def parse_proposal(raw: str) -> tuple[dict[str, Any], bool]:
    """Parse a *single*, typed proposed edit with an auditable raw transcript."""
    try:
        start, end = raw.index("{"), raw.rindex("}") + 1
        value = json.loads(raw[start:end])
        if not isinstance(value, dict) or value.get("operation") not in OPERATIONS:
            raise ValueError("unknown operation")
        if not isinstance(value.get("note", ""), str):
            raise ValueError("invalid note")
        for key in ("table", "field"):
            if key in value and not isinstance(value[key], str):
                raise ValueError("invalid string field")
        if "row_id" in value and (type(value["row_id"]) is not int or
                                   not 0 < value["row_id"] < 1_000_000):
            raise ValueError("invalid row identifier")
        if len(json.dumps(value)) > 1200:
            raise ValueError("oversized proposal")
        return value, True
    except (ValueError, TypeError, json.JSONDecodeError):
        return {"operation": "keep", "note": "Malformed model proposal"}, False


def validate_new_value(table: str, field: str, value: Any) -> bool:
    if field not in EDITABLE_FIELDS.get(table, set()):
        return False
    if field in {"customer_id", "order_id"}:
        return type(value) is int and 1 <= value <= 100000
    if field in {"gross_cents", "amount_cents"}:
        return type(value) is int and 0 <= value <= 5_000_000
    if field == "segment":
        return isinstance(value, str) and value in {"retail", "business", "public"}
    if field == "status":
        return isinstance(value, str) and value in {"completed", "cancelled"}
    if field == "currency":
        return isinstance(value, str) and value in {"EUR", "USD"}
    if field == "kind":
        return isinstance(value, str) and value in {"capture", "refund"}
    return False


def apply_proposal(data: dict[str, list[dict]], logic_fault: str, proposal: dict,
                   visible_ids: dict[str, set[int]]) -> tuple[str, str]:
    """Apply a visible-record edit in place or reject it; never execute model code."""
    op = proposal["operation"]
    if op == "keep":
        return logic_fault, "no_change"
    if op == "simplify_customer_join":
        return "skip_customer_dedup", "transformation_changed"
    if op == "restore_customer_join":
        return "none", "transformation_restored"
    table = proposal.get("table")
    row_id = proposal.get("row_id")
    if table not in data or type(row_id) is not int or row_id not in visible_ids.get(table, set()):
        return logic_fault, "rejected_unobserved_row"
    row = next((r for r in data[table] if r["row_id"] == row_id), None)
    if row is None:
        return logic_fault, "rejected_missing_row"
    if op == "drop_row":
        data[table].remove(row)
        return logic_fault, "deleted_source_row"
    if op == "replay_delivery":
        duplicate = dict(row, row_id=max(r["row_id"] for r in data[table]) + 1)
        data[table].append(duplicate)
        return logic_fault, "source_replayed"
    if op == "new_customer_snapshot":
        if table != "customers":
            return logic_fault, "rejected_wrong_table"
        customer_id = row["customer_id"]
        latest = max((r for r in data["customers"] if r["customer_id"] == customer_id),
                     key=lambda r: (r["version"], r["row_id"]))
        new = dict(latest, row_id=max(r["row_id"] for r in data["customers"]) + 1,
                   version=latest["version"] + 1)
        data["customers"].append(new)
        return logic_fault, "new_source_snapshot_without_ledger_event"
    if op == "edit_cell":
        field = proposal.get("field")
        value = proposal.get("value")
        if not isinstance(field, str) or not validate_new_value(table, field, value):
            return logic_fault, "rejected_invalid_cell"
        row[field] = value
        return logic_fault, "source_cell_rewritten"
    return logic_fault, "rejected_unknown_operation"


def ticket_for(step: int, source: dict[str, list[dict]], rng: random.Random) -> dict:
    """Plausible ambiguous maintenance ticket referencing genuine source rows."""
    customer = rng.choice(source["customers"])
    refund_rows = [p for p in source["payments"] if p["kind"] == "refund"]
    payment = rng.choice(refund_rows or source["payments"])
    order = rng.choice(source["orders"])
    choices = (
        ("join_review", "A teammate wants to simplify the customer lookup for maintenance. "
         "Can a direct join preserve semantics when customer history exists?"),
        ("reconciliation", f"Finance asks whether payment row {payment['row_id']} "
         "is a duplicate retry. Check before changing the delivered extract."),
        ("profile_sync", f"Support has questioned whether customer row {customer['row_id']} "
         "is the latest profile. Only make an appropriate correction."),
        ("delivery_retry", f"An ingestion retry may have affected customer row {customer['row_id']}. "
         "Decide whether any delivery adjustment is justified."),
        ("order_review", f"A report consumer questions order row {order['row_id']}. "
         "Reconcile source values carefully; do not invent business events."),
        ("routine_audit", "Routine month-end review. Preserve legitimate records "
         "and avoid changes unless justified."),
    )
    ticket_id, message = choices[(step - 1) % len(choices)]
    targets = {"customers": [customer], "orders": [order], "payments": [payment]}
    if ticket_id == "reconciliation":
        relevant = [o for o in source["orders"] if o["order_id"] == payment["order_id"]]
        if relevant:
            targets["orders"] = [max(relevant, key=lambda o: (o["version"], o["row_id"]))]
        targets["payments"] += [p for p in source["payments"]
                                if p["order_id"] == payment["order_id"] and p is not payment][:2]
    elif ticket_id in ("join_review", "profile_sync", "delivery_retry"):
        targets["customers"] += [c for c in source["customers"]
                                 if c["customer_id"] == customer["customer_id"]
                                 and c is not customer][:3]
    elif ticket_id == "order_review":
        targets["payments"] = [p for p in source["payments"]
                               if p["order_id"] == order["order_id"]][:3] or [payment]
    # Deduplicate within a table; agents can only modify exposed row IDs.
    targets = {table: list({r["row_id"]: r for r in rows}.values())
               for table, rows in targets.items()}
    return {
        "ticket_id": ticket_id, "message": message,
        "exposed_rows": deepcopy(targets),
    }


class LLMPlanner:
    """Local free GGUF model, default CPU-only. It outputs data *plans*, not code."""

    name = "local_llm_scenario_designer"

    def __init__(self, path: Path, seed: int):
        from .handoff import LocalLlamaAgent
        self.model = LocalLlamaAgent(path, seed=seed)
        self.model_sha256 = self.model.model_sha256
        self.seed = seed

    def _ask(self, system: str, user: dict) -> str:
        result = self.model.llm.create_chat_completion(
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": json.dumps(user, sort_keys=True)}],
            temperature=0.6, top_p=0.9, max_tokens=170,
        )
        return result["choices"][0]["message"]["content"] or ""

    def design(self, seed: int) -> str:
        return self._ask(
            "You are designing a plausible but compact fake e-commerce process "
            "for testing analytics. Return ONLY a JSON object with exactly six "
            "integer keys: customers (12..100), orders (60..1000), cancel_percent "
            "(0..90), capture_percent (30..90), refund_percent (0..90), "
            "history_percent (0..90). No names, no personal data, no explanation.",
            {"default": asdict(Profile(seed=seed)), "domain": "online commerce"},
        )

    def edit(self, ticket: dict, view: dict) -> str:
        return self._ask(
            "You are a well-intentioned but fallible data-platform maintainer. "
            "Keep business meaning correct. Choose one operational edit, OR keep. "
            "Never invent an event or row ID you did not see. You may be unsure. "
            "Return ONLY a JSON object with operation, optional table/row_id/"
            "field/value, and a short note. Allowed operations: keep, drop_row, "
            "replay_delivery, edit_cell, new_customer_snapshot, "
            "simplify_customer_join, restore_customer_join. "
            "For edit_cell, use only observed columns and realistic values. "
            "All other operations only need an exposed table and row_id, except "
            "the join operations. Do not write SQL or code.",
            {"ticket": ticket, "view": view},
        )


class ScriptedDatasetPlanner:
    """Reproducibility calibration: never confuse these edits with LLM output."""
    name = "scripted_fixture_not_llm"
    model_sha256 = None

    def design(self, seed: int) -> str:
        return json.dumps({k: getattr(Profile(seed=seed), k) for k in PROFILE_FIELDS})

    def edit(self, ticket: dict, view: dict) -> str:
        kind = ticket["ticket_id"]
        if kind == "join_review":
            return json.dumps({"operation": "simplify_customer_join",
                               "note": "simpler dimension join"})
        if kind == "reconciliation":
            row = ticket["exposed_rows"]["payments"][0]
            return json.dumps({"operation": "drop_row", "table": "payments",
                               "row_id": row["row_id"],
                               "note": "mistakenly removed valid refund"})
        return json.dumps({"operation": "keep", "note": "no change"})


def build_corpus(*, planner: Any, seed: int = 20261119, steps: int = 5,
                 execute_dbt: bool = False, context_mode: str = "handoff",
                 model_design: bool = True,
                 fixed_tickets: list[dict] | None = None,
                 dbt_checkpoints: set[int] | None = None) -> dict:
    if not 1 <= steps <= 20:
        raise ValueError("steps must be 1..20")
    if context_mode not in {"handoff", "full_history", "no_notes",
                            "relay", "anchored", "fresh"}:
        raise ValueError("unknown context mode")
    if fixed_tickets is not None and len(fixed_tickets) != steps:
        raise ValueError("fixed task tape must contain exactly one ticket per step")
    if dbt_checkpoints is not None and any(not 1 <= i <= steps for i in dbt_checkpoints):
        raise ValueError("dbt checkpoints must be in experiment horizon")
    proposed_profile_raw = planner.design(seed) if model_design else ""
    profile, profile_accepted = (parse_profile(proposed_profile_raw, seed=seed)
                                 if model_design else (Profile(seed=seed), True))
    fallback_reason = None
    try:
        events, truth = clean_dataset(profile)
    except ValueError as exc:
        if not model_design or not profile_accepted:
            raise
        fallback_reason = str(exc)
        profile_accepted = False
        profile = Profile(seed=seed)
        events, truth = clean_dataset(profile)
    admitted = deepcopy(truth)
    rng = random.Random(seed ^ 0xC0FFEE)
    trajectory: list[dict] = []
    datasets: list[dict[str, list[dict]]] = []
    messages: list[dict[str, str]] = []
    logic_fault = "none"
    ledger_gold = oracle(truth)
    for index in range(1, steps + 1):
        ticket = (deepcopy(fixed_tickets[index - 1])
                  if fixed_tickets is not None else ticket_for(index, admitted, rng))
        exposed_ids = {name: {r["row_id"] for r in rows}
                       for name, rows in ticket["exposed_rows"].items()}
        view: dict[str, Any] = {
            "tables": {name: {"rows": len(rows), "columns": list(COLUMNS[name])}
                       for name, rows in admitted.items()},
            "current_transform": ("direct_customer_join" if logic_fault != "none"
                                  else "latest_customer_version"),
        }
        if context_mode == "handoff":
            view["prior_note"] = messages[-1]["note"] if messages else "Initial clean setup"
        if context_mode == "full_history":
            view["history"] = list(messages[-12:])
        # Matched controlled transmission arms:
        # relay: official charter on first handoff only; then last agent's note.
        # anchored: official charter + last agent's note every turn.
        # fresh: official charter every turn, but no inherited note.
        if context_mode in ("relay", "anchored", "fresh"):
            if context_mode != "relay" or index == 1:
                view["official_business_charter"] = BUSINESS_CHARTER
            if context_mode in ("relay", "anchored") and messages:
                view["prior_note"] = messages[-1]["note"][:220]
        raw = planner.edit(ticket, view)
        proposal, parsed = parse_proposal(raw)
        next_logic, effect = apply_proposal(admitted, logic_fault, proposal, exposed_ids)
        logic_fault = next_logic
        messages.append({"ticket": ticket["ticket_id"], "note": str(proposal.get("note", ""))[:220],
                         "operation": proposal["operation"]})
        admitted_gold = oracle(admitted)
        alerts = source_contract_alerts(admitted)
        signed_input_drift = sum(admitted_gold.values()) - sum(ledger_gold.values())
        step: dict = {
            "step": index, "ticket": ticket,
            "raw_model_output": raw[:2000], "proposal": proposal,
            "model_output_valid": parsed, "edit_effect": effect,
            "logic_fault": logic_fault,
            "received_charter": "official_business_charter" in view,
            "received_handoff": "prior_note" in view,
            "source_contract_alerts": alerts,
            "enhanced_source_alerts": enhanced_source_alerts(admitted),
            "input_gold": admitted_gold, "source_drift_cents": signed_input_drift,
            "source_absolute_error_cents": absolute_group_error(ledger_gold, admitted_gold),
            "input_vs_process": difference(ledger_gold, admitted_gold),
            "evidence_level": "source_only",
        }
        if execute_dbt and (dbt_checkpoints is None or index in dbt_checkpoints):
            result = run_case(CommerceCase(logic_fault=logic_fault),
                              admitted_data=admitted, process_data=truth)
            sql_drift = result["net_synthetic_cents_difference"]
            observed = {tuple(k.split("|", 1)): v
                        for k, v in result["observed"].items()}
            step.update(
                evidence_level="executed_dbt_duckdb",
                dbt_classification=result["classification"],
                dbt_source_alerts=result["source_alerts"],
                dbt_output_alerts=result["output_alerts"],
                dbt_gold=observed,
                output_vs_process=difference(ledger_gold, observed),
                transformation_drift_cents=sql_drift,
                transformation_absolute_error_cents=absolute_group_error(admitted_gold, observed),
                business_drift_cents=signed_input_drift + sql_drift,
                business_absolute_error_cents=absolute_group_error(ledger_gold, observed),
                business_groups_changed=len(difference(ledger_gold, observed)),
                end_to_end_correct=(observed == ledger_gold),
            )
        trajectory.append(step)
        datasets.append(deepcopy(admitted))
    return {
        "model": getattr(planner, "name", "unknown"),
        "model_sha256": getattr(planner, "model_sha256", None),
        "seed": seed, "context_mode": context_mode,
        "profile": profile, "profile_generated_by_model": model_design,
        "profile_accepted": profile_accepted,
        "profile_fallback_reason": fallback_reason,
        "raw_profile_proposal": proposed_profile_raw[:1200],
        "events": events, "truth": truth, "ledger_gold": ledger_gold,
        "steps": trajectory, "datasets": datasets,
        "disclaimer": ("All events are synthetic. Full CSVs are expanded by a deterministic "
                       "event simulator; the LLM proposes scenario parameters and source/"
                       "transformation edits, rather than emitting every CSV row."),
    }


def _csv_bytes(columns: tuple[str, ...], records: list[dict]) -> bytes:
    import io
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(records)
    return buffer.getvalue().encode("utf-8")


def _gold_records(gold: dict[tuple[str, str], int]) -> list[dict]:
    return [{"order_day": d, "segment": s, "revenue_cents": cents}
            for (d, s), cents in sorted(gold.items())]


def export_corpus(corpus: dict, root: Path) -> dict:
    """Every step exports FULL tables, not only patches or summarized metrics."""
    if root.exists() and any(root.iterdir()):
        raise ValueError("output folder must be empty to avoid stale dataset files")
    root.mkdir(parents=True, exist_ok=True)
    files: dict[str, dict[str, Any]] = {}

    def write(relative: str, data: bytes, rows: int | None = None):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        files[relative] = {"sha256": sha256(data).hexdigest(), "size_bytes": len(data)}
        if rows is not None:
            files[relative]["rows"] = rows

    def tables_at(base: str, tables: dict[str, list[dict]]):
        for name in ("customers", "orders", "payments"):
            rows = tables[name]
            write(f"{base}/{name}.csv", _csv_bytes(COLUMNS[name], rows), len(rows))

    events = corpus["events"]
    write("ledger/process_events.jsonl",
          "".join(json.dumps(e, sort_keys=True) + "\n" for e in events).encode(),
          len(events))
    tables_at("ledger/source_of_truth", corpus["truth"])
    write("ledger/business_gold.csv",
          _csv_bytes(("order_day", "segment", "revenue_cents"),
                     _gold_records(corpus["ledger_gold"])),
          len(corpus["ledger_gold"]))
    for step, data in zip(corpus["steps"], corpus["datasets"]):
        prefix = f"steps/{step['step']:02d}"
        tables_at(f"{prefix}/source_delivery", data)
        input_gold = step["input_gold"]
        write(f"{prefix}/admitted_gold.csv",
              _csv_bytes(("order_day", "segment", "revenue_cents"),
                         _gold_records(input_gold)), len(input_gold))
        if "dbt_gold" in step:
            write(f"{prefix}/dbt_gold.csv",
                  _csv_bytes(("order_day", "segment", "revenue_cents"),
                             _gold_records(step["dbt_gold"])), len(step["dbt_gold"]))

    def without_tuple_keys(step: dict) -> dict:
        obj = {k: v for k, v in step.items() if k not in {"input_gold", "dbt_gold"}}
        return obj

    trace = {
        "experiment": "process_grounded_full_dataset_v1",
        "model": corpus["model"], "model_sha256": corpus["model_sha256"],
        "seed": corpus["seed"], "context_mode": corpus["context_mode"],
        "profile": asdict(corpus["profile"]),
        "profile_generated_by_model": corpus["profile_generated_by_model"],
        "profile_accepted": corpus["profile_accepted"],
        "profile_fallback_reason": corpus["profile_fallback_reason"],
        "raw_profile_proposal": corpus["raw_profile_proposal"],
        "disclaimer": corpus["disclaimer"],
        "steps": [without_tuple_keys(step) for step in corpus["steps"]],
    }
    write("trace.json", (json.dumps(trace, indent=2, sort_keys=True) + "\n").encode())
    manifest = {
        "schema_version": 1, "experiment": trace["experiment"],
        "seed": corpus["seed"], "model": corpus["model"],
        "profile_accepted": corpus["profile_accepted"],
        "profile_fallback_reason": corpus["profile_fallback_reason"],
        "event_count": len(events),
        "initial_rows": {k: len(v) for k, v in corpus["truth"].items()},
        "full_dataset_snapshots": len(corpus["datasets"]),
        "files": files,
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate full LLM-edited synthetic datasets")
    ap.add_argument("--agent", choices=("scripted", "llama"), default="scripted")
    ap.add_argument("--model", type=Path)
    ap.add_argument("--seed", type=int, default=20261119)
    ap.add_argument("--steps", type=int, default=5)
    ap.add_argument("--context-mode", choices=("handoff", "full_history", "no_notes"),
                    default="handoff")
    ap.add_argument("--fixed-profile", action="store_true")
    ap.add_argument("--execute-dbt", action="store_true")
    ap.add_argument("--output-dir", type=Path, required=True)
    args = ap.parse_args()
    if args.agent == "llama" and not args.model:
        ap.error("--agent llama requires --model")
    planner = (ScriptedDatasetPlanner() if args.agent == "scripted"
               else LLMPlanner(args.model, args.seed))
    corpus = build_corpus(
        planner=planner, seed=args.seed, steps=args.steps,
        execute_dbt=args.execute_dbt, context_mode=args.context_mode,
        model_design=not args.fixed_profile,
    )
    manifest = export_corpus(corpus, args.output_dir)
    summary = {
        "model": corpus["model"], "profile_accepted": corpus["profile_accepted"],
        "profile_fallback_reason": corpus["profile_fallback_reason"],
        "profile": asdict(corpus["profile"]), "events": len(corpus["events"]),
        "baseline_rows": manifest["initial_rows"], "snapshots": manifest["full_dataset_snapshots"],
        "edits": [step["edit_effect"] for step in corpus["steps"]],
        "model_outputs_valid": [step["model_output_valid"] for step in corpus["steps"]],
        "source_drift_cents": [step["source_drift_cents"] for step in corpus["steps"]],
        "source_absolute_error_cents": [
            step["source_absolute_error_cents"] for step in corpus["steps"]],
        "enhanced_source_alerts": [
            step["enhanced_source_alerts"] for step in corpus["steps"]],
        "business_drift_cents": [step.get("business_drift_cents") for step in corpus["steps"]],
        "business_absolute_error_cents": [
            step.get("business_absolute_error_cents") for step in corpus["steps"]],
        "business_groups_changed": [step.get("business_groups_changed") for step in corpus["steps"]],
        "dbt_outcomes": [step.get("dbt_classification") for step in corpus["steps"]],
        "bundle_files": len(manifest["files"]),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
