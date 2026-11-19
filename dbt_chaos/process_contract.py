"""Constrained declarative process-contract chaos engine (no executable DSL).

The contract describes a versioned PARTY→DOCUMENT→MOVEMENT workflow.
It is interpreted in two independent ways:
  * an event-stream reducer determines authoritative business truth;
  * a relational extractor determines the report implied by delivered tables.

A good-faith *scripted calibration* mutates delivered source records only.
It is NOT labelled as an LLM-produced mistake. Full LLM support is a
separate experiment. The engine exports public clean/chaos data and a
separate private event ledger / answer key for any SQL data platform.

No SQL expressions, Python imports, UDFs, production connections or eval.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import csv
from datetime import date, timedelta
from hashlib import sha256
import io
import json
from pathlib import Path
import random
import re
import sqlite3
from typing import Any

from .external_challenge import _nonoverlap, _safe_alerts
from .relay_platform_replay import score_publication

FORMAT = "dbt_chaos_declarative_process_v1"
IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,39}$")
FAULTS = (
    "none", "rewrite_credit", "reclassify_party", "drop_document",
    "duplicate_delivery",
)
ROLES = ("party", "document", "movement")
TYPES = ("party_created", "party_reclassified", "document_opened",
         "document_state", "movement_recorded", "movement_corrected",
         "movement_redelivered")


def _check_fields(obj: Any, keys: set[str], where: str) -> dict:
    if not isinstance(obj, dict) or set(obj) != keys:
        raise ValueError(f"{where} requires exactly {sorted(keys)}")
    return obj


def validate_contract(raw: Any) -> dict:
    _check_fields(raw, {"format", "name", "roles", "semantics", "generation"},
                  "contract")
    if raw["format"] != FORMAT or not isinstance(raw["name"], str) or not IDENT.fullmatch(raw["name"]):
        raise ValueError("unsupported contract format/name")
    roles = _check_fields(raw["roles"], set(ROLES), "roles")
    required = {
        "party": {"table", "id", "dimension"},
        "document": {"table", "id", "party_fk", "date", "gross", "status", "currency"},
        "movement": {"table", "id", "document_fk", "kind", "amount"},
    }
    for role, keys in required.items():
        record = _check_fields(roles[role], keys, role)
        if any(not isinstance(x, str) or not IDENT.fullmatch(x)
               for x in record.values()):
            raise ValueError(f"unsafe SQL/CSV identifier in {role}")
        cols = columns_for(raw, role)
        if len(set(cols)) != len(cols):
            raise ValueError(f"ambiguous duplicate column in {role}")
    if len({roles[r]["table"] for r in ROLES}) != 3:
        raise ValueError("all three tables must be distinct")

    sem = _check_fields(raw["semantics"], {"included_status", "currency",
                        "signs", "dimensions"}, "semantics")
    if any(not isinstance(sem[f], str) or not 1 <= len(sem[f]) <= 25
           for f in ("included_status", "currency")):
        raise ValueError("included status and currency must be bounded strings")
    signs = sem["signs"]
    if (not isinstance(signs, dict) or len(signs) != 2 or
            set(signs.values()) != {1, -1} or
            any(not isinstance(x, str) or not IDENT.fullmatch(x)
                for x in signs) or
            any(type(v) is not int for v in signs.values())):
        raise ValueError("signs must map exactly two named movement kinds to +1 and -1")
    labels = sem["dimensions"]
    if (not isinstance(labels, list) or not 2 <= len(labels) <= 12
            or len(set(labels)) != len(labels) or
            any(not isinstance(x, str) or not x.strip() or len(x) > 32
                for x in labels)):
        raise ValueError("expected 2..12 distinct bounded dimension values")

    gen = _check_fields(raw["generation"], {
        "parties", "documents", "history_percent", "approved_percent",
        "movement_percent", "credit_percent", "retry_percent",
        "start_day", "day_span",
    }, "generation")
    for key, lo, hi in (
        ("parties", 10, 150), ("documents", 30, 1000),
        ("history_percent", 0, 80), ("approved_percent", 35, 95),
        ("movement_percent", 40, 100), ("credit_percent", 5, 75),
        ("retry_percent", 0, 20), ("day_span", 2, 120),
    ):
        if type(gen[key]) is not int or not lo <= gen[key] <= hi:
            raise ValueError(f"generation.{key} must be integer {lo}..{hi}")
    try:
        date.fromisoformat(gen["start_day"])
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid YYYY-MM-DD start_day") from exc
    return deepcopy(raw)


def columns_for(contract: dict, role: str) -> tuple[str, ...]:
    r = contract["roles"][role]
    if role == "party":
        return ("row_id", r["id"], "version", r["dimension"])
    if role == "document":
        return ("row_id", r["id"], r["party_fk"], "version",
                r["date"], r["gross"], r["status"], r["currency"])
    if role == "movement":
        return ("row_id", r["id"], r["document_fk"], "version",
                r["kind"], r["amount"])
    raise ValueError("unknown role")


def _emit(events: list[dict], event_type: str, **fields) -> None:
    events.append({"event_id": len(events)+1, "type": event_type, **fields})


def simulate_process(contract: dict, seed: int) -> list[dict]:
    """Randomized underlying BUSINESS process, before any source fault."""
    c = validate_contract(contract)
    if type(seed) is not int or not 0 <= seed <= 2**32-1:
        raise ValueError("invalid deterministic random seed")
    gen, sem = c["generation"], c["semantics"]
    rng = random.Random(seed)
    events: list[dict] = []
    parties: list[int] = []
    for i in range(gen["parties"]):
        pid = 1000+i
        parties.append(pid)
        _emit(events, "party_created", entity=pid,
              dimension=rng.choice(sem["dimensions"]))
    docs: list[int] = []
    approved: list[int] = []
    for i in range(gen["documents"]):
        doc = 5000+i
        docs.append(doc)
        _emit(events, "document_opened", entity=doc,
              party=rng.choice(parties),
              day=(date.fromisoformat(gen["start_day"]) +
                   timedelta(days=rng.randrange(gen["day_span"]))).isoformat(),
              gross_cents=rng.randint(4000, 150000),
              status="draft", currency=sem["currency"]
                       if rng.randrange(100) < 94 else "USD")
        status = (sem["included_status"] if rng.randrange(100) <
                  gen["approved_percent"] else "voided")
        _emit(events, "document_state", entity=doc, status=status)
        if status == sem["included_status"]:
            approved.append(doc)
    chosen_kind = {
        value: key for key, value in sem["signs"].items()
    }
    for i, doc in enumerate(approved):
        if rng.randrange(100) >= gen["movement_percent"]:
            continue
        amount = rng.randint(3500, 49000)
        _emit(events, "movement_recorded", entity=9000+i,
              document=doc, kind=chosen_kind[1],
              amount_cents=amount)
        if rng.randrange(100) < gen["credit_percent"]:
            # A genuine partial credit/reversal, not a chaos mutation.
            refund = rng.randint(2000, max(2000, amount-100))
            _emit(events, "movement_recorded", entity=19000+i,
                  document=doc, kind=chosen_kind[-1],
                  amount_cents=refund)
        if rng.randrange(100) < gen["retry_percent"]:
            # An operational redelivery is not a new financial event.
            _emit(events, "movement_redelivered", entity=9000+i)
    for p in parties:
        if rng.randrange(100) < gen["history_percent"]:
            _emit(events, "party_reclassified", entity=p,
                  dimension=rng.choice(sem["dimensions"]))
    for e in list(events):
        if (e["type"] == "movement_recorded"
                and e["kind"] == chosen_kind[1]
                and rng.randrange(100) < 9):
            _emit(events, "movement_corrected", entity=e["entity"],
                  amount_cents=e["amount_cents"]+rng.randint(10, 240))
    return events


def project_source(contract: dict, events: list[dict]) -> dict[str, list[dict]]:
    """ONE projection of events into genuine versioned relational CSVs."""
    c = validate_contract(contract)
    r = c["roles"]
    tables = {r[role]["table"]: [] for role in ROLES}
    latest: dict[tuple[str, int], dict] = {}
    row_ids = {"party": 10000, "document": 20000, "movement": 30000}
    for e in events:
        typ = e["type"]
        if typ not in TYPES:
            raise ValueError("unrecognized process event")
        role = ("party" if typ.startswith("party_") else
                "document" if typ.startswith("document_") else "movement")
        obj = r[role]
        if typ == "movement_redelivered":
            old = latest.get((role, e["entity"]))
            if old is None:
                raise ValueError("redelivery before movement record")
            row_ids[role] += 1
            tables[obj["table"]].append(dict(old, row_id=row_ids[role]))
            continue
        old = latest.get((role, e["entity"]))
        if typ in ("party_created", "document_opened", "movement_recorded"):
            if old is not None:
                raise ValueError("duplicate creation event")
            data = {"row_id": 0, obj["id"]: e["entity"], "version": 1}
            if role == "party":
                data[obj["dimension"]] = e["dimension"]
            elif role == "document":
                data.update({
                    obj["party_fk"]: e["party"], obj["date"]: e["day"],
                    obj["gross"]: e["gross_cents"], obj["status"]: e["status"],
                    obj["currency"]: e["currency"],
                })
            else:
                data.update({
                    obj["document_fk"]: e["document"],
                    obj["kind"]: e["kind"], obj["amount"]: e["amount_cents"],
                })
        else:
            if old is None:
                raise ValueError("update event before creation")
            data = dict(old, version=old["version"]+1)
            if typ == "party_reclassified":
                data[obj["dimension"]] = e["dimension"]
            elif typ == "document_state":
                data[obj["status"]] = e["status"]
            elif typ == "movement_corrected":
                data[obj["amount"]] = e["amount_cents"]
            else:
                raise ValueError("illegal event transition")
        row_ids[role] += 1
        data["row_id"] = row_ids[role]
        tables[obj["table"]].append(data)
        latest[(role, e["entity"])] = data
    return tables


def event_business_oracle(contract: dict, events: list[dict]) -> dict[tuple[str, str], int]:
    """Independent process-event accounting; NEVER calls source projection."""
    c = validate_contract(contract)
    parties: dict[int, str] = {}
    documents: dict[int, dict] = {}
    movements: dict[int, dict] = {}
    for e in events:
        typ = e["type"]
        if typ == "party_created" or typ == "party_reclassified":
            parties[e["entity"]] = e["dimension"]
        elif typ == "document_opened":
            documents[e["entity"]] = dict(e)
        elif typ == "document_state":
            documents[e["entity"]]["status"] = e["status"]
        elif typ == "movement_recorded":
            movements[e["entity"]] = dict(e)
        elif typ == "movement_corrected":
            movements[e["entity"]]["amount_cents"] = e["amount_cents"]
        elif typ == "movement_redelivered":
            pass  # A delivery retry does NOT change business facts.
        else:
            raise ValueError("unknown ledger event type")
    result: dict[tuple[str, str], int] = defaultdict(int)
    sem = c["semantics"]
    for movement in movements.values():
        doc = documents[movement["document"]]
        if doc["status"] != sem["included_status"] or doc["currency"] != sem["currency"]:
            continue
        key = (doc["day"], parties[doc["party"]])
        result[key] += sem["signs"][movement["kind"]] * movement["amount_cents"]
    return dict(sorted((key, value) for key, value in result.items() if value != 0))


def _latest(rows: list[dict], key: str) -> dict[int, dict]:
    latest: dict[int, dict] = {}
    for row in rows:
        prev = latest.get(row[key])
        if prev is None or (row["version"], row["row_id"]) > (
                prev["version"], prev["row_id"]):
            latest[row[key]] = row
    return latest


def delivered_source_oracle(contract: dict, tables: dict[str, list[dict]]) -> dict[tuple[str, str], int]:
    """Independent reading of DELIVERED tables, including source defects."""
    c = validate_contract(contract)
    pr, dr, mr = (c["roles"][key] for key in ROLES)
    parties = _latest(tables[pr["table"]], pr["id"])
    docs = _latest(tables[dr["table"]], dr["id"])
    moves = _latest(tables[mr["table"]], mr["id"])
    result: dict[tuple[str, str], int] = defaultdict(int)
    for movement in moves.values():
        doc = docs.get(movement[mr["document_fk"]])
        if doc is None:
            continue
        if (doc[dr["status"]] != c["semantics"]["included_status"] or
                doc[dr["currency"]] != c["semantics"]["currency"]):
            continue
        party = parties.get(doc[dr["party_fk"]])
        if party is None:
            continue
        key = (doc[dr["date"]], party[pr["dimension"]])
        sign = c["semantics"]["signs"].get(movement[mr["kind"]])
        if sign is None:
            continue
        result[key] += sign * movement[mr["amount"]]
    return dict(sorted((key, value) for key, value in result.items() if value != 0))


def apply_scripted_fault(contract: dict, clean: dict[str, list[dict]],
                         events: list[dict], fault: str) -> tuple[dict, dict]:
    """Predefined plausible human-like mistake; NOT an LLM decision."""
    c = validate_contract(contract)
    if fault not in FAULTS:
        raise ValueError("unknown fault; no arbitrary code is executed")
    altered = deepcopy(clean)
    pr, dr, mr = (c["roles"][r] for r in ROLES)
    report_before = delivered_source_oracle(c, altered)
    detail: dict[str, Any] = {
        "mechanism": fault, "actor": "scripted_good_faith_operator_calibration_not_llm",
        "explanation": "A well-intentioned operator is responding to an ambiguous maintenance ticket.",
        "applied": False,
    }
    if fault == "none":
        detail["business_source_l1_cents"] = 0
        return altered, detail
    if fault == "duplicate_delivery":
        old = altered[mr["table"]][0]
        new = dict(old, row_id=max(x["row_id"] for x in altered[mr["table"]])+1)
        altered[mr["table"]].append(new)
        detail.update(applied=True, ticket="Retry a potentially missing delivery",
                      edit={"table": mr["table"], "row_id": new["row_id"],
                            "action": "exact_delivery_retry"})
    elif fault == "rewrite_credit":
        kind = next(k for k, sign in c["semantics"]["signs"].items() if sign < 0)
        valid_docs = {
            doc[dr["id"]] for doc in _latest(
                altered[dr["table"]], dr["id"]).values()
            if doc[dr["status"]] == c["semantics"]["included_status"]
            and doc[dr["currency"]] == c["semantics"]["currency"]
        }
        candidates = [x for x in _latest(
                          altered[mr["table"]], mr["id"]).values()
                      if x[mr["kind"]] == kind
                      and x[mr["amount"]] > 3500
                      and x[mr["document_fk"]] in valid_docs]
        if not candidates:
            raise RuntimeError("cannot produce realistic credit rewrite")
        x = sorted(candidates, key=lambda row: (
            row[mr["amount"]], row["row_id"]), reverse=True)[0]
        # Edit only latest row for a movement; otherwise older versions have
        # no effect in a version-aware platform.
        related = [y for y in altered[mr["table"]]
                   if y[mr["id"]] == x[mr["id"]]]
        x = max(related, key=lambda r: (r["version"], r["row_id"]))
        old = x[mr["amount"]]
        x[mr["amount"]] = old-2000
        detail.update(applied=True,
                      ticket="Reconcile credit that may have been posted twice",
                      edit={"table": mr["table"], "row_id": x["row_id"],
                            "column": mr["amount"], "from": old,
                            "to": x[mr["amount"]]})
    elif fault == "reclassify_party":
        before = event_business_oracle(c, events)
        candidates = sorted(_latest(altered[pr["table"]], pr["id"]).values(),
                            key=lambda r: r[pr["id"]])
        chosen = None
        for row in candidates:
            for value in c["semantics"]["dimensions"]:
                if value == row[pr["dimension"]]:
                    continue
                candidate = deepcopy(altered)
                dest = next(x for x in candidate[pr["table"]]
                            if x["row_id"] == row["row_id"])
                dest[pr["dimension"]] = value
                if delivered_source_oracle(c, candidate) != before:
                    chosen = (row, value)
                    break
            if chosen is not None:
                break
        if chosen is None:
            raise RuntimeError("no business-relevant party recategorization")
        x, newval = chosen
        old = x[pr["dimension"]]
        x[pr["dimension"]] = newval
        detail.update(applied=True,
                      ticket="Align updated party category with latest support records",
                      edit={"table": pr["table"], "row_id": x["row_id"],
                            "column": pr["dimension"], "from": old, "to": newval})
    elif fault == "drop_document":
        # Choose an actually paid document with positive contribution, so
        # deleting it leaves a structurally orphaned movement and business error.
        latest_docs = _latest(altered[dr["table"]], dr["id"])
        move_ids = {x[mr["document_fk"]] for x in altered[mr["table"]]}
        eligible = [x for x in latest_docs.values()
                    if x[dr["id"]] in move_ids and
                    x[dr["status"]] == c["semantics"]["included_status"] and
                    x[dr["currency"]] == c["semantics"]["currency"]]
        if not eligible:
            raise RuntimeError("no document with real movement to drop")
        doc = sorted(eligible, key=lambda row: row[dr["id"]])[0]
        altered[dr["table"]] = [x for x in altered[dr["table"]]
                               if x[dr["id"]] != doc[dr["id"]]]
        detail.update(applied=True,
                      ticket="Deduplicate a suspected repeated document batch",
                      edit={"table": dr["table"], "entity": doc[dr["id"]],
                            "action": "drop_all_versions"})
    after = delivered_source_oracle(c, altered)
    detail["business_source_l1_cents"] = sum(abs(
        report_before.get(k, 0) - after.get(k, 0))
        for k in report_before.keys() | after.keys())
    if fault != "duplicate_delivery" and detail["business_source_l1_cents"] == 0:
        raise AssertionError("chosen scripted error has no measured business impact")
    if fault == "duplicate_delivery" and detail["business_source_l1_cents"] != 0:
        raise AssertionError("benign retry unexpectedly altered process meaning")
    return altered, detail


def _csv_bytes(columns: tuple[str, ...], rows: list[dict]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf8")


def _gold_strings(gold: dict[tuple[str, str], int]) -> dict[str, int]:
    return {f"{period}|{group}": value for (period, group), value in sorted(gold.items())}


def _gold_dict(encoded: dict[str, int]) -> dict[tuple[str, str], int]:
    if any("|" not in k or k.count("|") != 1 for k in encoded):
        raise ValueError("invalid period/group key")
    return {tuple(k.split("|", 1)): int(v) for k, v in encoded.items()}


def export_contract_challenge(*, contract_path: Path, seed: int, fault: str,
                              public_dir: Path, private_dir: Path) -> dict:
    _nonoverlap(public_dir, private_dir)
    if any(path.exists() and (not path.is_dir() or any(path.iterdir()))
           for path in (public_dir, private_dir)):
        raise ValueError("output directories must be empty")
    contract = validate_contract(json.loads(contract_path.read_text(encoding="utf8")))
    events = simulate_process(contract, seed)
    clean = project_source(contract, events)
    chaos, fault_detail = apply_scripted_fault(contract, clean, events, fault)
    truth = event_business_oracle(contract, events)
    from_source = delivered_source_oracle(contract, clean)
    if from_source != truth:
        raise AssertionError("independent process and source oracles diverge on clean data")
    corrupted = delivered_source_oracle(contract, chaos)
    files: dict[str, dict] = {}
    public_dir.mkdir(parents=True, exist_ok=True)
    private_dir.mkdir(parents=True, exist_ok=True)
    for scenario, sources in (("clean", clean), ("chaos", chaos)):
        for role in ROLES:
            table = contract["roles"][role]["table"]
            rel = f"inputs/{scenario}/{table}.csv"
            raw = _csv_bytes(columns_for(contract, role), sources[table])
            path = public_dir / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            files[rel] = {
                "sha256": sha256(raw).hexdigest(),
                "bytes": len(raw), "rows": len(sources[table]),
            }
    contract_bytes = (json.dumps(contract, indent=2, sort_keys=True)+"\n").encode()
    (public_dir / "contract.json").write_bytes(contract_bytes)
    # Give the user a human-inspectable SQL model and DQ probes, generated
    # strictly from allowed identifiers, not from arbitrary model-written SQL.
    from .contract_sql import build_sql_pack
    sql_dir = public_dir / "sql"
    sql_dir.mkdir()
    support_files = {}
    for file_name, sql_text in build_sql_pack(contract).items():
        relative = f"sql/{file_name}"
        data = sql_text.encode("utf8")
        (sql_dir / file_name).write_bytes(data)
        support_files[relative] = {"sha256": sha256(data).hexdigest(),
                                   "bytes": len(data)}
    fingerprint = sha256(json.dumps({
        "seed": seed, "fault": fault,
        "contract_sha256": sha256(contract_bytes).hexdigest(),
        "inputs": files,
    }, sort_keys=True).encode()).hexdigest()[:24]
    manifest = {
        "format": FORMAT, "challenge_id": fingerprint,
        "workload": contract["name"],
        "fault": fault, "seed": seed, "generator_type": "scripted_calibration_not_llm",
        "input_files": files,
        "support_files": support_files,
        "contract_sha256": sha256(contract_bytes).hexdigest(),
        "publication_columns": ["period", "group", "amount_cents"],
        "source_truth_exposed": False,
    }
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True)+"\n").encode()
    (public_dir / "manifest.json").write_bytes(manifest_bytes)
    desc = (f"# {contract['name']} — independent data-platform challenge\n\n"
            "Run **the same pipeline** on inputs/clean and inputs/chaos, "
            "without receiving the private answer key.\n\n"
            "The supplied contract.json declares table and column names, "
            "the party→document→movement relationships, latest-version "
            "semantics, status/currency conditions and positive/negative "
            "movement kinds. The optional sql/reference_query.sql is a "
            "reference implementation; sql/quality_checks.sql emits "
            "source-only issues. Neither query has access to hidden truth.\n\n"
            "Output one CSV per scenario named clean.csv and chaos.csv with "
            "the exact header: period,group,amount_cents. "
            "These are calendar day and the latest party dimension. "
            "Only actually PUBLISHED groups belong in the output. "
            "Optionally list intentionally held groups in held/clean.csv or "
            "held/chaos.csv with period,group.\n\n"
            "A source row rejected for quality must not silently disappear "
            "from a published incomplete group; report a hold.\n\n"
            "Fault provenance: scripted good-faith operator calibration "
            "(NOT a new LLM-generated action).\n\n"
            "Use dbt-chaos contract-score with the separate private answer key."
            "\n")
    (public_dir / "README.md").write_text(desc, encoding="utf8")
    ledger_bytes = "".join(json.dumps(e, sort_keys=True)+"\n" for e in events).encode()
    (private_dir / "process_events.jsonl").write_bytes(ledger_bytes)
    key = {
        "format": FORMAT, "challenge_id": fingerprint,
        "public_manifest_sha256": sha256(manifest_bytes).hexdigest(),
        "ledger_sha256": sha256(ledger_bytes).hexdigest(),
        "contract_name": contract["name"],
        "expected_business": _gold_strings(truth),
        "expected_given_source": {
            "clean": _gold_strings(from_source),
            "chaos": _gold_strings(corrupted),
        },
        "fault": fault_detail,
    }
    (private_dir / "answer_key.json").write_text(
        json.dumps(key, indent=2, sort_keys=True)+"\n", encoding="utf8")
    return {
        "challenge_id": fingerprint, "contract": contract["name"],
        "seed": seed, "fault": fault,
        "process_event_count": len(events),
        "input_rows": {scenario: {
            table: len(sources[table]) for table in sources
        } for scenario, sources in (("clean", clean), ("chaos", chaos))},
        "business_source_l1_cents": fault_detail["business_source_l1_cents"],
        "public_dir": str(public_dir), "private_dir": str(private_dir),
        "oracle_separated": True, "model_generated_fault": False,
    }


def _read_output(file: Path) -> dict[tuple[str, str], int]:
    if not file.is_file() or file.stat().st_size > 5_000_000:
        raise ValueError("expected bounded actual publication CSV")
    with file.open(newline="", encoding="utf8") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ["period", "group", "amount_cents"]:
            raise ValueError("expected period,group,amount_cents header")
        out = {}
        for row in reader:
            key = (row["period"], row["group"])
            if key in out or not all(key):
                raise ValueError("duplicate/blank published grouping key")
            try:
                amount = int(row["amount_cents"])
            except (TypeError, ValueError) as exc:
                raise ValueError("amount_cents must be signed integer") from exc
            out[key] = amount
        return out


def _read_held(file: Path) -> set[tuple[str, str]]:
    if not file.is_file():
        return set()
    if file.stat().st_size > 1_000_000:
        raise ValueError("held group file too large")
    with file.open(newline="", encoding="utf8") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ["period", "group"]:
            raise ValueError("expected period,group held header")
        result = set()
        for row in reader:
            key = (row["period"], row["group"])
            if key in result or not all(key):
                raise ValueError("duplicate/blank held group")
            result.add(key)
        return result


def score_contract_challenge(*, public_dir: Path, answer_key: Path,
                             published_dir: Path, held_dir: Path | None = None,
                             alerts_json: Path | None = None) -> dict:
    manifest_bytes = (public_dir / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    key = json.loads(answer_key.read_text(encoding="utf8"))
    contract_bytes = (public_dir / "contract.json").read_bytes()
    contract = validate_contract(json.loads(contract_bytes))
    if (manifest.get("format") != FORMAT or key.get("format") != FORMAT or
            manifest["challenge_id"] != key["challenge_id"] or
            manifest["contract_sha256"] != sha256(contract_bytes).hexdigest() or
            manifest["workload"] != contract["name"] or
            key["public_manifest_sha256"] != sha256(manifest_bytes).hexdigest()):
        raise ValueError("challenge/contract/private key mismatch")
    expected_files = {
        f"inputs/{scenario}/{contract['roles'][role]['table']}.csv"
        for scenario in ("clean", "chaos") for role in ROLES
    }
    if set(manifest["input_files"]) != expected_files:
        raise ValueError("manifest has missing or unrecognized input files")
    for rel, spec in manifest.get("support_files", {}).items():
        if rel not in ("sql/reference_query.sql", "sql/quality_checks.sql"):
            raise ValueError("unrecognized SQL support file")
        support = (public_dir / rel).read_bytes()
        if (sha256(support).hexdigest() != spec["sha256"]
                or len(support) != spec["bytes"]):
            raise ValueError(f"SQL support changed: {rel}")
    for rel, spec in manifest["input_files"].items():
        bytes_ = (public_dir / rel).read_bytes()
        if (sha256(bytes_).hexdigest() != spec["sha256"]
                or len(bytes_) != spec["bytes"] or
                bytes_.count(b"\n")-1 != spec["rows"]):
            raise ValueError(f"input changed: {rel}")
    truth = _gold_dict(key["expected_business"])
    alerts = _safe_alerts(alerts_json)
    results = {}
    for scenario in ("clean", "chaos"):
        published = _read_output(published_dir / f"{scenario}.csv")
        held = _read_held(held_dir / f"{scenario}.csv") if held_dir else set()
        if held - (set(truth) | set(published)):
            raise ValueError("held group is not part of business workload")
        scored = score_publication(truth, published, held)
        expected_input = _gold_dict(key["expected_given_source"][scenario])
        relevant = (set(truth) | set(expected_input) | set(published)) - held
        transform_l1 = sum(abs(published.get(x, 0) -
                               expected_input.get(x, 0)) for x in relevant)
        source_l1 = sum(abs(truth.get(x, 0)-expected_input.get(x, 0))
                        for x in set(truth) | set(expected_input))
        if scored["status"] == "held":
            verdict = "all_withheld"
        elif scored["status"] == "partially_held":
            verdict = "safe_partial_hold"
        elif scored["status"] == "correctly_published":
            verdict = ("business_correct" if source_l1 == 0 else
                       "correct_output_recovery_not_verified")
        elif alerts[scenario]:
            verdict = "detected_but_exposed"
        elif transform_l1 == 0 and source_l1:
            verdict = "garbage_passed_through"
        elif transform_l1:
            verdict = "transformation_or_unexplained_output_error"
        else:
            verdict = "silent_business_corruption"
        results[scenario] = {
            "verdict": verdict, "published": scored,
            "observable_alerts": alerts[scenario],
            "source_to_business_l1_cents": source_l1,
            "published_vs_delivered_source_l1_cents": transform_l1,
            "held_groups": len(held),
        }
    return {
        "format": FORMAT, "challenge_id": manifest["challenge_id"],
        "contract": contract["name"], "fault": key["fault"]["mechanism"],
        "scored_against_independent_business_events": True,
        "results": results,
        "limitations": [
            "Fault is scripted human-like calibration, NOT an LLM output.",
            "A report with correct figures does not prove a verified repair.",
            "Source-only validation cannot reconstruct missing real events.",
            "Declarative DSL v1 covers party-document-money movement processes only.",
        ],
    }


def run_sqlite_reference(contract: dict, sources: dict[str, list[dict]]) -> dict[tuple[str, str], int]:
    """Independent SQL execution reference, with validated identifiers only.

    This is a baseline platform implementing the public business contract,
    not the secret process oracle. Its clean/chaos score is useful to
    calibrate whether garbage was merely packaged and passed onward.
    """
    c = validate_contract(contract)
    pr, dr, mr = [c["roles"][r] for r in ROLES]
    with sqlite3.connect(":memory:") as db:
        for role in ROLES:
            obj = c["roles"][role]
            table = obj["table"]
            cols = columns_for(c, role)
            intcols = {"row_id", "version", obj["id"]}
            if role == "document":
                intcols |= {obj["party_fk"], obj["gross"]}
            elif role == "movement":
                intcols |= {obj["document_fk"], obj["amount"]}
            ddl = ", ".join(
                f'"{name}" {"INTEGER" if name in intcols else "TEXT"}'
                for name in cols)
            db.execute(f'CREATE TABLE "{table}" ({ddl})')
            placeholders = ", ".join("?" for _ in cols)
            inserts = [tuple(row[col] for col in cols)
                       for row in sources[table]]
            if inserts:
                db.executemany(f'INSERT INTO "{table}" VALUES ({placeholders})', inserts)
        sql = f'''
        WITH p AS (
          SELECT *, ROW_NUMBER() OVER (
            PARTITION BY "{pr["id"]}" ORDER BY version DESC,row_id DESC
          ) AS rn FROM "{pr["table"]}"
        ), d AS (
          SELECT *, ROW_NUMBER() OVER (
            PARTITION BY "{dr["id"]}" ORDER BY version DESC,row_id DESC
          ) AS rn FROM "{dr["table"]}"
        ), m AS (
          SELECT *, ROW_NUMBER() OVER (
            PARTITION BY "{mr["id"]}" ORDER BY version DESC,row_id DESC
          ) AS rn FROM "{mr["table"]}"
        )
        SELECT d."{dr["date"]}" AS period,
               p."{pr["dimension"]}" AS group_name,
               SUM(m."{mr["amount"]}" * (
                 CASE m."{mr["kind"]}"
                    WHEN ? THEN 1 WHEN ? THEN -1 ELSE 0 END
               )) AS amount_cents
        FROM d
        INNER JOIN p ON d."{dr["party_fk"]}"=p."{pr["id"]}" AND p.rn=1
        INNER JOIN m ON m."{mr["document_fk"]}"=d."{dr["id"]}" AND m.rn=1
        WHERE d.rn=1 AND d."{dr["status"]}"=?
          AND d."{dr["currency"]}"=?
        GROUP BY 1,2
        HAVING amount_cents<>0
        ORDER BY 1,2
        '''
        signs = c["semantics"]["signs"]
        plus = next(k for k, v in signs.items() if v == 1)
        minus = next(k for k, v in signs.items() if v == -1)
        rows = db.execute(sql, (plus, minus,
                                c["semantics"]["included_status"],
                                c["semantics"]["currency"])).fetchall()
    return {(str(d), str(g)): int(value) for d, g, value in rows}


def run_reference_from_public(public_dir: Path, output_dir: Path) -> dict:
    if any(output_dir.resolve() == other.resolve() or
           output_dir.resolve() in other.resolve().parents
           for other in (public_dir,)):
        raise ValueError("reference output must be separate from input")
    contract = validate_contract(json.loads((public_dir / "contract.json").read_text()))
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError("output must be empty")
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = {}
    for scenario in ("clean", "chaos"):
        sources = {}
        for role in ROLES:
            table = contract["roles"][role]["table"]
            path = public_dir / "inputs" / scenario / (table+".csv")
            with path.open(newline="", encoding="utf8") as stream:
                reader = csv.DictReader(stream)
                if tuple(reader.fieldnames or []) != columns_for(contract, role):
                    raise ValueError("public CSV columns do not match contract")
                vals = []
                for row in reader:
                    parsed = {}
                    for col, val in row.items():
                        numeric = col in ("row_id", "version",
                                         contract["roles"][role]["id"])
                        if role == "document":
                            numeric |= col in (contract["roles"][role]["party_fk"],
                                               contract["roles"][role]["gross"])
                        elif role == "movement":
                            numeric |= col in (contract["roles"][role]["document_fk"],
                                               contract["roles"][role]["amount"])
                        parsed[col] = int(val) if numeric else val
                    vals.append(parsed)
            sources[table] = vals
        gold = run_sqlite_reference(contract, sources)
        raw = _csv_bytes(("period", "group", "amount_cents"), [
            {"period": day, "group": group, "amount_cents": amount}
            for (day, group), amount in sorted(gold.items())
        ])
        (output_dir / f"{scenario}.csv").write_bytes(raw)
        summary[scenario] = {"published_groups": len(gold)}
    return {"adapter": "sqlite3_reference", "outputs": summary,
            "model_input": "public_csv_only_no_hidden_oracle"}


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Declarative synthetic process chaos challenge")
    cmd = ap.add_subparsers(dest="command", required=True)
    gen = cmd.add_parser("generate")
    gen.add_argument("--contract", type=Path, required=True)
    gen.add_argument("--fault", choices=FAULTS, default="rewrite_credit")
    gen.add_argument("--seed", type=int, default=20261119)
    gen.add_argument("--public-dir", type=Path, required=True)
    gen.add_argument("--private-dir", type=Path, required=True)
    ref = cmd.add_parser("reference")
    ref.add_argument("--public-dir", type=Path, required=True)
    ref.add_argument("--output-dir", type=Path, required=True)
    score = cmd.add_parser("score")
    score.add_argument("--public-dir", type=Path, required=True)
    score.add_argument("--answer-key", type=Path, required=True)
    score.add_argument("--published-dir", type=Path, required=True)
    score.add_argument("--held-dir", type=Path)
    score.add_argument("--alerts-json", type=Path)
    score.add_argument("--out", type=Path, required=True)
    score.add_argument("--fail-on-silent", action="store_true")
    args = ap.parse_args()
    if args.command == "generate":
        report = export_contract_challenge(
            contract_path=args.contract, seed=args.seed, fault=args.fault,
            public_dir=args.public_dir, private_dir=args.private_dir)
    elif args.command == "reference":
        report = run_reference_from_public(args.public_dir, args.output_dir)
    else:
        report = score_contract_challenge(
            public_dir=args.public_dir, answer_key=args.answer_key,
            published_dir=args.published_dir, held_dir=args.held_dir,
            alerts_json=args.alerts_json)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, sort_keys=True, indent=2)+"\n")
    print(json.dumps(report, sort_keys=True, indent=2))
    if args.command == "score" and args.fail_on_silent and any(
            entry["published"]["status"] == "silently_wrong"
            for entry in report["results"].values()):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
