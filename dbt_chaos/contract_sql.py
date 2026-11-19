"""Portable, read-only SQL generated from validated process contracts.

These queries are optional model/quality examples, not proof of warehouse
enforcement. In particular, they cannot see hidden business-event truth,
so plausible but historically wrong amounts/classifications still pass.
No arbitrary SQL fragments can appear in a JSON contract.
"""
from __future__ import annotations

from pathlib import Path
import csv
import json
import sqlite3
from typing import Any

from .process_contract import (
    ROLES, columns_for, validate_contract,
)


def _literal(value: str) -> str:
    """Safe SQL quoted string; contract data is NEVER executable code."""
    return "'" + value.replace("'", "''") + "'"


def build_sql_pack(contract: dict) -> dict[str, str]:
    c = validate_contract(contract)
    party, document, movement = (c["roles"][r] for r in ROLES)
    signs = c["semantics"]["signs"]
    plus = next(k for k, v in signs.items() if v == 1)
    minus = next(k for k, v in signs.items() if v == -1)

    # Table and column names are validated by validate_contract (alphanumeric
    # identifiers, no quoting or free-form SQL from user input). All text
    # literal values are single-quote-escaped.
    stages = f"""WITH p AS (
  SELECT *, ROW_NUMBER() OVER (
    PARTITION BY {party['id']} ORDER BY version DESC, row_id DESC
  ) AS _rn FROM {party['table']}
), d AS (
  SELECT *, ROW_NUMBER() OVER (
    PARTITION BY {document['id']} ORDER BY version DESC, row_id DESC
  ) AS _rn FROM {document['table']}
), m AS (
  SELECT *, ROW_NUMBER() OVER (
    PARTITION BY {movement['id']} ORDER BY version DESC, row_id DESC
  ) AS _rn FROM {movement['table']}
)
"""
    sign = (f"CASE m.{movement['kind']} "
            f"WHEN {_literal(plus)} THEN 1 "
            f"WHEN {_literal(minus)} THEN -1 ELSE 0 END")
    amount = f"m.{movement['amount']} * ({sign})"
    query = stages + f"""
SELECT d.{document['date']} AS period,
       p.{party['dimension']} AS group_label,
       SUM({amount}) AS amount_cents
FROM d
JOIN p ON d.{document['party_fk']} = p.{party['id']} AND p._rn=1
JOIN m ON m.{movement['document_fk']} = d.{document['id']} AND m._rn=1
WHERE d._rn=1
  AND d.{document['status']}={_literal(c['semantics']['included_status'])}
  AND d.{document['currency']}={_literal(c['semantics']['currency'])}
GROUP BY d.{document['date']},p.{party['dimension']}
HAVING SUM({amount}) <> 0
ORDER BY period,group_label;
"""
    checks = stages + f"""
SELECT 'orphan_movement' AS check_name, 'block' AS severity,
       m.{movement['id']} AS entity_id,
       m.{movement['document_fk']} AS related_id
FROM m LEFT JOIN d ON m.{movement['document_fk']}=d.{document['id']}
  AND d._rn=1
WHERE m._rn=1 AND d.{document['id']} IS NULL
UNION ALL
SELECT 'orphan_document_party', 'block',
       d.{document['id']},d.{document['party_fk']}
FROM d LEFT JOIN p ON d.{document['party_fk']}=p.{party['id']}
  AND p._rn=1
WHERE d._rn=1 AND p.{party['id']} IS NULL
UNION ALL
SELECT 'invalid_movement_kind', 'block',
       m.{movement['id']},m.{movement['document_fk']}
FROM m WHERE m._rn=1 AND
  m.{movement['kind']} NOT IN ({_literal(plus)},{_literal(minus)})
UNION ALL
SELECT 'negative_movement_amount', 'block',
       m.{movement['id']},m.{movement['document_fk']}
FROM m WHERE m._rn=1 AND (m.{movement['amount']} < 0 OR m.{movement['amount']} IS NULL)
UNION ALL
SELECT 'credit_exceeds_settlement', 'block',
       m.{movement['document_fk']},m.{movement['document_fk']}
FROM m WHERE m._rn=1
GROUP BY m.{movement['document_fk']}
HAVING SUM(CASE WHEN m.{movement['kind']}={_literal(minus)}
           THEN m.{movement['amount']} ELSE 0 END)
     > SUM(CASE WHEN m.{movement['kind']}={_literal(plus)}
           THEN m.{movement['amount']} ELSE 0 END)
UNION ALL
SELECT 'conflicting_movement_version', 'block',
       {movement['id']},MIN({movement['document_fk']})
FROM {movement['table']}
GROUP BY {movement['id']},version
HAVING MIN({movement['document_fk']})<>MAX({movement['document_fk']})
    OR MIN({movement['kind']})<>MAX({movement['kind']})
    OR MIN({movement['amount']})<>MAX({movement['amount']})
UNION ALL
SELECT 'benign_delivery_retry', 'info',
       {movement['id']},MIN({movement['document_fk']})
FROM {movement['table']}
GROUP BY {movement['id']},version,{movement['document_fk']},
         {movement['kind']},{movement['amount']}
HAVING COUNT(*) > 1
ORDER BY check_name,entity_id;
"""
    return {
        "reference_query.sql": (
            "-- Optional source-only reference query (portable SQL).\n"
            "-- Output: period,group_label,amount_cents; rename group_label "
            "to group when exporting the challenge result.\n"
            "-- Historical truth must be assessed via PRIVATE process events.\n"
            + query),
        "quality_checks.sql": (
            "-- Observable source-quality probes; NOT installed native dbt tests.\n"
            "-- check_name,severity,entity_id,related_id. A warning is NOT "
            "quarantine and source-only checks cannot infer missing genuine events.\n"
            + checks),
    }


def evaluate_public_quality(public_dir: Path) -> dict[str, Any]:
    """Evaluate generated check SQL on public CSVs, no hidden oracle access."""
    c = validate_contract(json.loads(
        (public_dir / "contract.json").read_text(encoding="utf8")))
    query = build_sql_pack(c)["quality_checks.sql"]
    results = {}
    for scenario in ("clean", "chaos"):
        with sqlite3.connect(":memory:") as db:
            for role in ROLES:
                r = c["roles"][role]
                table = r["table"]
                cols = columns_for(c, role)
                ints = {"row_id", "version", r["id"]}
                if role == "document":
                    ints.update((r["party_fk"],r["gross"]))
                elif role == "movement":
                    ints.update((r["document_fk"],r["amount"]))
                ddl = ",".join(
                    f"{col} {'INTEGER' if col in ints else 'TEXT'}"
                    for col in cols)
                db.execute(f"CREATE TABLE {table}({ddl})")
                source = public_dir / "inputs" / scenario / f"{table}.csv"
                with source.open(newline="", encoding="utf8") as f:
                    reader = csv.DictReader(f)
                    if tuple(reader.fieldnames or []) != cols:
                        raise ValueError("public source columns differ from contract")
                    rows = [tuple(
                        int(row[col]) if col in ints else row[col]
                        for col in cols) for row in reader]
                if rows:
                    db.executemany(
                        f"INSERT INTO {table} VALUES({','.join('?' for _ in cols)})",
                        rows)
            issues = [
                dict(zip(("check_name","severity","entity_id","related_id"), row))
                for row in db.execute(query).fetchall()
            ]
        results[scenario] = {
            "issues": issues,
            "block_count": sum(x["severity"]=="block" for x in issues),
            "informational_count": sum(x["severity"]=="info" for x in issues),
        }
    return {
        "evidence_tier": "observable_delivered_csv_only",
        "generated_from_contract": c["name"],
        "native_warehouse_tests_installed": False,
        "results": results,
        "important": ("These are optional source-only probes. "
                      "An alert cannot prove safe quarantine or historically "
                      "correct business output."),
    }


def main() -> None:
    import argparse
    parser=argparse.ArgumentParser(description="Run generated SQL quality probes on public challenge CSVs")
    parser.add_argument("--public-dir",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args()
    report=evaluate_public_quality(args.public_dir)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps({
        "contract":report["generated_from_contract"],
        "clean_block_count":report["results"]["clean"]["block_count"],
        "chaos_block_count":report["results"]["chaos"]["block_count"],
        "note":"Source-only checks are not an independent business ledger.",
    },indent=2))


if __name__=="__main__":
    main()
