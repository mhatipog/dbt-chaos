"""One-command, offline evidence pack for the bounded business-truth benchmark.

Runs real SQLite (not an emulated model screen) over two process contracts.
The evaluator sees immutable synthetic business events; the release planner
and model-free policy gates do not. This is NOT a production platform test.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
from html import escape
import json
from pathlib import Path

from .contract_casework import demonstrate_contract_casework
from .contract_review import (
    AlwaysApplyReviewer, AlwaysKeepReviewer, make_review_cases,
    run_review_experiment, summarize,
)
from .process_contract import load_contract

DOMAINS = ("procurement", "grants")
FORMAT = "dbt_chaos_business_truth_assessment_v1"


def _absolute(score: dict) -> int:
    return score["false_published_l1_cents"] + score["unannounced_missing_l1_cents"]


def _stage(step: dict) -> dict:
    score = step["score"]
    return {
        "stage": step["stage"],
        "publication_status": step["publication_status"],
        "business_status": score["status"],
        "wrong_published_cents": score["false_published_l1_cents"],
        "wrong_published_groups": len(score["false_published_groups"]),
        "correct_value_fraction": score["fraction_of_correct_business_value_published"],
        "held_reporting_groups": len(step.get("held_group_ids", [])),
    }


def run_assessment(seed: int = 20261119) -> dict:
    """Execute actual SQL and independent event-ledger checks, not mock scores."""
    if type(seed) is not int or not 0 <= seed <= 2**32 - 1:
        raise ValueError("seed must be a uint32")

    domains = []
    controls = []
    for name in DOMAINS:
        contract = load_contract(name)
        # SAME initial events, candidates and six tickets for both policies.
        applied = run_review_experiment(
            contract=contract, reviewer=AlwaysApplyReviewer(), seed=seed)
        kept = run_review_experiment(
            contract=contract, reviewer=AlwaysKeepReviewer(), seed=seed)
        applied_score, kept_score = summarize(applied), summarize(kept)

        events, cases = make_review_cases(contract, seed)
        lifecycle = demonstrate_contract_casework(contract, events, cases[4])
        stages = [_stage(step) for step in lifecycle["stages"]]

        cases_out = []
        no_new_source_harm = True
        for row in applied["cases"]:
            source = row["selected_gate_results"]["source_only"]
            signed = row["selected_gate_results"]["provider_receipt"]
            src_score = source["actual_business_publication"]
            no_new_source_harm &= _absolute(src_score) <= row["starting_source_error_l1_cents"]
            cases_out.append({
                "id": row["case_id"],
                "candidate_class": row["candidate_outcome_class"],
                "ungated_status": row["selected_ungated_publication"]["status"],
                "source_only_status": src_score["status"],
                "source_only_decision": source["gate_decision"]["decision"],
                "receipt_status": signed["actual_business_publication"]["status"],
                "receipt_decision": signed["gate_decision"]["decision"],
            })
        verdicts = {
            "source_only_never_increased_existing_business_error": bool(no_new_source_harm),
            "stronger_attested_reference_has_no_wrong_case":
                applied_score["policy_results"]["selected_attested_gate"]["wrong_case_count"] == 0,
            "pending_hold_published_no_wrong_cents":
                stages[1]["wrong_published_cents"] == 0,
            "pending_hold_retained_some_correct_value":
                0 < stages[1]["correct_value_fraction"] < 1,
            "signed_repair_released_correct_business_value":
                stages[2]["business_status"] == "correctly_published"
                and stages[2]["correct_value_fraction"] == 1,
        }
        controls.extend(verdicts.values())
        domains.append({
            "domain": name,
            "ticket_count": len(cases_out),
            "candidate_proposals_authored_by_llm": False,
            "real_sql_engine": "sqlite3",
            "policies": {
                "always_apply": applied_score["policy_results"]["always_apply_publication"],
                "always_keep": kept_score["policy_results"]["always_keep_publication"],
                "source_only_gate": applied_score["policy_results"]["selected_source_only_gate"],
                "attested_upper_bound": applied_score["policy_results"]["selected_attested_gate"],
                "scoped_provider_receipt": applied_score["policy_results"]["selected_provider_receipt_gate"],
            },
            "cases": cases_out,
            "correction_lifecycle": stages,
            "controls": verdicts,
        })
    report = {
        "format": FORMAT,
        "seed": seed,
        "evidence_level": "actual_sqlite_reference_execution_and_independent_synthetic_oracle",
        "not_real_dbt_or_production_adapter": True,
        "no_live_llm_called": True,
        "original_process_ledger_hidden_from_release_gate": True,
        "provider_receipt": "synthetic_hmac_not_an_external_issuer",
        "domain_count": len(domains),
        "ticket_count": sum(d["ticket_count"] for d in domains),
        "controls_passed": all(controls),
        "domains": domains,
        "limitations": [
            "Selected simulated business tasks; not representative incident frequencies",
            "Reference SQL in SQLite, not installed Fabric, Databricks or customer pipelines",
            "Candidates are scripted and always-apply/keep baselines are not LLM decisions",
            "Trusted event-attested recovery is a stronger evidence tier, not a source-only detector",
            "A plausible error cannot be detected if every independent evidence channel is wrong",
        ],
    }
    return report


def render_markdown(report: dict) -> str:
    lines = [
        "# Business Truth Resilience — offline assessment",
        "",
        "**Evidence:** actual SQLite SQL vs an independent synthetic process-event oracle.",
        "**Scope:** two bounded transactional contracts; no customer data, no live LLM or cloud.",
        "**Result:** " + ("controls passed" if report["controls_passed"] else "CONTROLS FAILED"),
        "",
        "| Domain | Tickets | Always apply wrong | Always keep wrong | Source gate wrong | Attested upper bound wrong |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for domain in report["domains"]:
        p = domain["policies"]
        lines.append(
            f'| {domain["domain"]} | {domain["ticket_count"]} | '
            f'{p["always_apply"]["wrong_case_count"]} | '
            f'{p["always_keep"]["wrong_case_count"]} | '
            f'{p["source_only_gate"]["wrong_case_count"]} | '
            f'{p["attested_upper_bound"]["wrong_case_count"]} |')
    lines.extend([
        "",
        "The source-only gate can leave an already wrong source uncorrected. A held",
        "reporting group is **not** a quarantined row or a successful repair.",
        "",
        "## Actually executed publication lifecycle",
        "",
        "| Domain | Stage | Published error (EUR) | Held groups | Correct value delivered |",
        "|---|---|---:|---:|---:|",
    ])
    for domain in report["domains"]:
        for stage in domain["correction_lifecycle"]:
            lines.append(
                f'| {domain["domain"]} | {stage["stage"]} | '
                f'{stage["wrong_published_cents"] / 100:.2f} | '
                f'{stage["held_reporting_groups"]} | '
                f'{100 * stage["correct_value_fraction"]:.2f}% |')
    lines.extend(["", "## Safety and interpretability", ""])
    for item in report["limitations"]:
        lines.append("- " + item)
    lines.extend([
        "",
        "All results use independently generated **synthetic** business truth.",
        "Never interpret green controls as proof of an arbitrary warehouse's reliability.",
        "",
    ])
    return "\n".join(lines)


def render_html(report: dict) -> str:
    """Render accessible, completely offline evidence tables (no JS or CDN)."""
    e = lambda obj: escape(str(obj), quote=True)
    out = [
        '<!doctype html><html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        '<meta http-equiv="Content-Security-Policy" ',
        'content="default-src &#39;none&#39;; style-src &#39;unsafe-inline&#39;">',
        '<title>dbt-chaos | Business Truth Resilience</title>',
        '<style>',
        ':root{color-scheme:light}*{box-sizing:border-box}',
        'body{margin:0;background:#f4f7fa;color:#1c3045;',
        'font:15px/1.6 system-ui,-apple-system,sans-serif}',
        'main{max-width:1080px;margin:0 auto;padding:48px 20px 70px}',
        'h1{font-size:2rem;line-height:1.2;margin:10px 0}',
        'h2{margin:32px 0 14px;font-size:1.25rem}',
        '.eyebrow{font-size:12px;text-transform:uppercase;letter-spacing:.1em;',
        'font-weight:700;color:#50748e}',
        '.muted{color:#597087}.intro{max-width:850px}',
        '.card{background:white;border:1px solid #dce5ee;border-radius:12px;',
        'padding:20px;margin:14px 0;box-shadow:0 3px 16px #233e5007}',
        '.facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(185px,1fr));gap:12px}',
        '.fact strong{font-size:1.75rem;display:block}',
        '.fact span{font-size:12px;color:#597087}',
        'table{width:100%;border-collapse:collapse;text-align:left;font-variant-numeric:tabular-nums}',
        'th,td{padding:10px 12px;border-bottom:1px solid #e6edf3;vertical-align:top}',
        'th{font-size:12px;color:#54728b;background:#f5f8fa;white-space:normal}',
        '.scroll{overflow-x:auto}.ok{color:#167352;font-weight:700}',
        '.alert{color:#a34627;font-weight:700}',
        '.pill{display:inline-block;border:1px solid #c5d7e1;',
        'border-radius:50px;padding:1px 10px;font-size:12px}',
        'ul{padding-left:22px}li{margin:4px 0}',
        '@media(max-width:700px){main{padding:25px 10px}',
        '.card{padding:14px}th,td{padding:8px;font-size:12px}}',
        '</style></head><body><main>',
        '<div class="eyebrow">dbt-chaos / synthetic research</div>',
        '<h1>Business Truth Resilience</h1>',
        '<p class="intro">Executed reference SQL assessed against an independent ',
        'synthetic process-event oracle. This is not a test of a connected ',
        'production warehouse, and policy comparisons are not incident rates.</p>',
        '<div class="facts">',
        '<div class="card fact"><strong>', e(report["domain_count"]),
        '</strong><span>Process contracts</span></div>',
        '<div class="card fact"><strong>', e(report["ticket_count"]),
        '</strong><span>Matched maintenance cases</span></div>',
        '<div class="card fact"><strong>',
        ('Passed' if report["controls_passed"] else 'FAILED'),
        '</strong><span>Calibrated safety controls</span></div>',
        '</div>',
    ]
    names = (
        ("always_apply", "Always apply"),
        ("always_keep", "Always keep"),
        ("source_only_gate", "Source-only gate"),
        ("attested_upper_bound", "Event-attested upper bound"),
        ("scoped_provider_receipt", "Scoped simulated receipt"),
    )
    for domain in report["domains"]:
        out.extend([
            '<section class="card"><div class="eyebrow">Domain</div><h2>',
            e(domain["domain"]), '</h2>',
            '<p class="muted">Six selected, individually reset synthetic ',
            'scenarios. Incorrect-case counts are not population estimates.</p>',
            '<div class="scroll"><table><thead><tr><th>Policy</th>',
            '<th>Incorrect cases</th><th>Absolute business error (EUR)</th>',
            '</tr></thead><tbody>',
        ])
        for key, label in names:
            p = domain["policies"][key]
            wrong = p["wrong_case_count"]
            out.extend([
                '<tr><td>', e(label), '</td><td class="',
                ('alert' if wrong else 'ok'), '">', e(wrong),
                ' / ', e(domain["ticket_count"]), '</td><td>',
                e(f'{p["wrong_l1_cents"] / 100:.2f}'), '</td></tr>',
            ])
        out.extend([
            '</tbody></table></div><h2>Actual publication lifecycle</h2>',
            '<div class="scroll"><table><thead><tr>',
            '<th>Stage</th><th>Published error</th><th>Held groups</th>',
            '<th>Correct value delivered</th></tr></thead><tbody>',
        ])
        for step in domain["correction_lifecycle"]:
            out.extend([
                '<tr><td>', e(step["stage"].replace("_", " ")),
                '</td><td>€', e(f'{step["wrong_published_cents"] / 100:.2f}'),
                '</td><td>', e(step["held_reporting_groups"]),
                '</td><td>', e(f'{step["correct_value_fraction"] * 100:.2f}%'),
                '</td></tr>',
            ])
        out.extend([
            '</tbody></table></div><h2>Safety-control assertions</h2><ul>',
        ])
        for key, okay in domain["controls"].items():
            out.extend([
                '<li><span class="', ('ok' if okay else 'alert'), '">',
                ('PASS ' if okay else 'FAIL '), '</span>',
                e(key.replace("_", " ")), '</li>',
            ])
        out.append('</ul></section>')
    out.extend([
        '<section class="card"><h2>Interpretation limits</h2><ul>',
    ])
    out.extend('<li>' + e(item) + '</li>' for item in report["limitations"])
    out.extend([
        '</ul><p class="muted">No private process ledger, cryptographic key, ',
        'customer records, or simulated raw provider receipt is embedded in ',
        'this report. SHA256SUMS verifies artifact integrity, not third-party ',
        'provenance.</p></section></main></body></html>',
    ])
    return "".join(out)


def write_assessment(report: dict, out_dir: Path) -> dict:
    """Never overwrite or mix previous evidence; JSON and HTML omit oracle data."""
    if out_dir.is_symlink() or (out_dir.exists() and (
            not out_dir.is_dir() or any(out_dir.iterdir()))):
        raise ValueError("assessment output directory must be new or empty")
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    (out_dir / "assessment.json").write_text(payload, encoding="utf8")
    (out_dir / "assessment.md").write_text(
        render_markdown(report), encoding="utf8")
    (out_dir / "assessment.html").write_text(
        render_html(report), encoding="utf8")
    names = ("assessment.json", "assessment.md", "assessment.html")
    sums = [(sha256((out_dir / name).read_bytes()).hexdigest(), name)
            for name in names]
    (out_dir / "SHA256SUMS").write_text(
        "".join(digest + "  " + name + "\n" for digest, name in sums),
        encoding="utf8")
    return {"directory": str(out_dir), "assessment_sha256": sums[0][0],
            "controls_passed": report["controls_passed"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20261119)
    parser.add_argument("--fail-on-unsafe", action="store_true")
    args = parser.parse_args(argv)
    report = run_assessment(args.seed)
    print(json.dumps(write_assessment(report, args.out_dir), sort_keys=True))
    return 2 if args.fail_on_unsafe and not report["controls_passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
