"""Escaped, standalone human-readable report for the source × SQL chaos matrix."""
from __future__ import annotations
import html
import json
from pathlib import Path

VALID={"correct","contained","detected_failure","silent_corruption","execution_failure"}

def render(report:dict)->str:
    if report.get("schema_version")!=1 or report.get("workload")!="three-source-order-customer-payment":
        raise ValueError("Expected commerce contract v1 evidence")
    cases=report.get("results")
    if not isinstance(cases,list) or len(cases)>100:
        raise ValueError("Bad commerce case count")
    esc=lambda x:html.escape(str(x),quote=True)
    rows=[]
    for case in cases:
        outcome=case.get("classification")
        if outcome not in VALID:raise ValueError("Unsupported result classification")
        columns=[
            case.get("source_fault","?"),case.get("logic_fault","?"),
            case.get("origin","?"),outcome,
            ", ".join(case.get("source_alerts",[])),
            ", ".join(case.get("output_alerts",[])),
            ", ".join(case.get("contract_difference",{}).keys()),
        ]
        rows.append("<tr class='"+esc(outcome)+"'>"+
                    "".join("<td>"+esc(v)+"</td>" for v in columns)+"</tr>")
    totals=report.get("outcomes",{})
    counts=" · ".join(esc(x)+": "+esc(totals.get(x,0)) for x in
                      ("correct","contained","detected_failure","silent_corruption","execution_failure"))
    return """<!doctype html><html lang="en"><meta charset="utf-8">
<title>dbt-chaos: Source and SQL chaos</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{font:15px/1.6 system-ui,sans-serif;max-width:1250px;margin:35px auto;padding:0 15px}
table{width:100%;border-collapse:collapse}td,th{padding:8px;border-bottom:1px solid #ddd;text-align:left}
th{background:#f2f2f2}.silent_corruption{background:#fff1ee}
.contained{background:#eff8ff}.execution_failure{background:#ffdfdf}
small{color:#555}</style>
<h1>dbt-chaos · Source × SQL</h1><p>""" + counts + """</p>
<p><small>Results come from synthetic inputs and real dbt/DuckDB execution.
Source-quality alerts do not by themselves prove gold-output correctness.
Absence of an upstream event is not necessarily detectable without an external ledger.</small></p>
<table><thead><tr><th>Source chaos</th><th>SQL chaos</th><th>Origin</th>
<th>Outcome</th><th>Source alerts</th><th>Output alerts</th><th>Different gold keys</th>
</tr></thead><tbody>""" + "".join(rows) + "</tbody></table></html>\n"

def render_file(path:Path)->str:
    if path.stat().st_size>5_000_000:
        raise ValueError("Large/untrusted report file refused")
    return render(json.loads(path.read_text(encoding="utf8")))
