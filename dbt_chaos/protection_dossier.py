"""Export auditable, full source/quarantine/publication dossiers for each policy.

This consumes a completed real-dbt JSON matrix and DOES NOT run an LLM or
evaluate an oracle inside the policy. The original event ledger is a separate
research evidence tier; no 'raw' policy may see it when making decisions.
"""
from __future__ import annotations

import argparse
import csv
import io
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from .commerce_runner import COLUMNS
from .protection import POLICIES, detect_and_quarantine, recorded_qwen_source_cases


def _csv(columns: tuple[str, ...], rows: list[dict]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def export_policy_dossier(matrix: dict, root: Path) -> dict:
    if root.exists() and any(root.iterdir()):
        raise ValueError("dossier folder must be empty to avoid stale evidence")
    if matrix.get("experiment") != "protection_replay_20261119_v1":
        raise ValueError("unexpected or unverified matrix version")
    root.mkdir(parents=True, exist_ok=True)
    truth, cases = recorded_qwen_source_cases()
    case_map = {entry["name"]: entry for entry in cases}
    files: dict[str, dict[str, Any]] = {}

    def write(relative: str, raw: bytes, *, rows: int | None = None):
        file = root / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(raw)
        files[relative] = {"sha256": sha256(raw).hexdigest(),
                           "bytes": len(raw)}
        if rows is not None:
            files[relative]["rows"] = rows

    # This is an independently attested RESEARCH ledger, separate from the
    # delivered data visible to baseline, monitor and quarantine policies.
    for table in ("customers", "orders", "payments"):
        rows = truth[table]
        write(f"trusted_reference/{table}.csv", _csv(COLUMNS[table], rows),
              rows=len(rows))
    emitted = set()
    for entry in matrix["evaluations"]:
        case, policy = entry["scenario"], entry["policy"]
        if case not in case_map or policy not in POLICIES:
            raise ValueError("unknown scenario or policy")
        if (case, policy) in emitted:
            raise ValueError("duplicate evaluation in matrix")
        emitted.add((case, policy))
        original = case_map[case]["delivered"]
        plan = detect_and_quarantine(original)
        if policy == "quarantine":
            accepted = plan.accepted
        elif policy == "attested_replay":
            accepted = truth
        else:
            accepted = original
        base = f"cases/{case}/{policy}"

        # If the policy withheld publication before running dbt, these are
        # *candidate* tables, not evidence that the SQL was executed.
        input_label = ("dbt_input" if entry["dbt_executed"] or
                       entry["dbt_result_reused"] else "unexecuted_candidate_input")
        for table in ("customers", "orders", "payments"):
            rows = accepted[table]
            write(f"{base}/{input_label}/{table}.csv",
                  _csv(COLUMNS[table], rows), rows=len(rows))

        quarantines = []
        if policy == "quarantine":
            for incident in entry["quarantine_manifest"]:
                table, row_id = incident["table"], incident["row_id"]
                source_row = next((r for r in original[table]
                                   if r["row_id"] == row_id), None)
                if source_row is None:
                    raise ValueError("quarantine manifest references missing original")
                quarantines.append({
                    "table": table, "row_id": row_id,
                    "reason": incident["reason"],
                    "disposition": incident["disposition"],
                    "source_row_json": json.dumps(source_row, sort_keys=True),
                })
        write(f"{base}/quarantined_rows.csv",
              _csv(("table", "row_id", "reason", "disposition",
                    "source_row_json"), quarantines), rows=len(quarantines))

        detected = [
            {"table": issue["table"], "row_id": issue["row_id"],
             "reason": issue["reason"], "disposition": issue["disposition"]}
            for issue in entry["candidate_detector_findings"]
        ]
        write(f"{base}/detector_findings.csv",
              _csv(("table", "row_id", "reason", "disposition"), detected),
              rows=len(detected))

        publication = [
            {"order_day": d, "segment": seg, "revenue_cents": value}
            for k, value in sorted(entry["observed"].items())
            for d, seg in [k.split("|", 1)]
        ]
        write(f"{base}/published_revenue.csv",
              _csv(("order_day", "segment", "revenue_cents"), publication),
              rows=len(publication))

        held = [
            {"order_day": d, "segment": seg, "reason": "risk_not_localizable"
             if len(entry["held_groups"]) == entry["truth_group_count"]
             else "quarantined_ancestor"}
            for k in entry["held_groups"] for d, seg in [k.split("|", 1)]
        ]
        write(f"{base}/held_reporting_groups.csv",
              _csv(("order_day", "segment", "reason"), held), rows=len(held))

        corrections = [
            {"table": change["table"], "row_id": change["row_id"],
             "operation": change["operation"], "evidence": change["evidence"]}
            for change in entry["evidence_manifest"]
        ]
        write(f"{base}/attested_corrections.csv",
              _csv(("table", "row_id", "operation", "evidence"),
                   corrections), rows=len(corrections))
        decision = {k: v for k, v in entry.items() if k not in
                    ("quarantine_manifest", "candidate_detector_findings",
                     "evidence_manifest", "observed")}
        write(f"{base}/publication_decision.json",
              (json.dumps(decision, indent=2, sort_keys=True) + "\n").encode())

    if len(emitted) != len(matrix["evaluations"]):
        raise ValueError("missing or duplicate evaluations")
    metadata = {
        "schema_version": 1, "experiment": matrix["experiment"],
        "provenance": matrix["provenance"], "cases": [
            {"scenario": case["name"], "model_authored_accepted_edit":
             case["recorded_model_edit"]}
            for case in cases
        ],
        "evaluations": len(emitted),
        "unique_real_dbt_executions": matrix["unique_real_dbt_executions"],
        "evidence_policy": ("attested_replay uses trusted_reference; other "
                            "policies must not use this reference to decide"),
        "files": files,
    }
    (root / "manifest.json").write_text(json.dumps(metadata, indent=2,
                                                    sort_keys=True) + "\n")
    return metadata


def audit_policy_dossier(root: Path) -> dict:
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest["schema_version"] != 1:
        raise ValueError("unsupported dossier manifest")
    if len(manifest["files"]) < manifest["evaluations"]:
        raise ValueError("missing dossier evidence")
    from pathlib import PurePosixPath
    for name, fields in manifest["files"].items():
        if (PurePosixPath(name).is_absolute() or
                ".." in PurePosixPath(name).parts):
            raise ValueError("path traversal in dossier manifest")
        raw = (root / name).read_bytes()
        if sha256(raw).hexdigest() != fields["sha256"]:
            raise ValueError(f"changed dossier evidence: {name}")
        if len(raw) != fields["bytes"]:
            raise ValueError(f"incorrect dossier file size: {name}")
        if "rows" in fields and raw.count(b"\n") - 1 != fields["rows"]:
            raise ValueError(f"incorrect dossier row count: {name}")
    return {"verified": True, "files": len(manifest["files"]),
            "evaluations": manifest["evaluations"],
            "unique_real_dbt_executions": manifest["unique_real_dbt_executions"]}


def main():
    ap = argparse.ArgumentParser(description="Export full quarantine/publication files")
    ap.add_argument("--matrix", type=Path, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    args = ap.parse_args()
    matrix = json.loads(args.matrix.read_text())
    manifest = export_policy_dossier(matrix, args.output_dir)
    print(json.dumps(audit_policy_dossier(args.output_dir), indent=2))
    print("Model edit provenance:", manifest["provenance"])


if __name__ == "__main__":
    main()
