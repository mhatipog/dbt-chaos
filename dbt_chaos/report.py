"""Self-contained, escaped HTML report for synthetic-model and real-dbt score JSON."""
from __future__ import annotations
from html import escape
from datetime import datetime,timezone
import json

def render(report:dict)->str:
    if not isinstance(report,dict) or report.get("evidence_level") not in ("python_model_screen","executed_dbt_duckdb"):
        raise ValueError("expected a dbt-chaos score document with known evidence level")
    models=report.get("strategies")
    if not isinstance(models,dict) or not models:
        raise ValueError("score document has no strategy results")
    source=report["evidence_level"]
    def label(value):return escape(str(value),quote=True)
    def number(value):
        if value is None:return "N/A"
        if not isinstance(value,(int,float)) or isinstance(value,bool):
            return "N/A"
        return label(value)
    def percent(value):
        return number(value)+("%" if isinstance(value,(float,int)) else "")
    rows=[]
    for name,item in sorted(models.items()):
        if not isinstance(item,dict):raise ValueError("malformed strategy")
        score=item.get("score_0_100")
        correct=item.get("correctness_pct")
        wrong=item.get("incorrect")
        silent=item.get("silent_corruption")
        checks=item.get("fault_checkpoints")
        if score is not None and not 0<=score<=100:raise ValueError("invalid score")
        rows.append("<tr><th scope='row'>"+label(name)+"</th><td>"+percent(correct)+
                    "</td><td>"+percent(score)+"</td><td>"+number(wrong)+
                    "</td><td>"+number(silent)+"</td><td>"+number(checks)+
                    "</td><td>"+number(item.get("execution_errors",0))+"</td></tr>")
    coverage=report.get("coverage") or {}
    cov=("<p>Generator coverage: "+number(coverage.get("executed_operator_kinds"))+
        " fault types, "+number(coverage.get("realized_distinct_pairs"))+
        " distinct pairs / "+number(coverage.get("possible_unordered_pairs"))+
        " possible.</p>") if coverage else ""
    warnings=report.get("limits",[])
    if not isinstance(warnings,list) or not all(isinstance(x,str) for x in warnings):
        warnings=["No validated limitation field supplied."]
    notes="<ul>"+"".join("<li>"+label(w)+"</li>" for w in warnings)+"</ul>"
    stamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return ("<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>dbt-chaos resilience experiment</title>"
            "<style>body{font:16px/1.5 system-ui,sans-serif;max-width:1000px;margin:3rem auto;padding:0 1rem;color:#17212a}"
            "table{border-collapse:collapse;width:100%;margin:1rem 0;overflow-x:auto}th,td{border-bottom:1px solid #ccd1d8;text-align:left;padding:.65rem}"
            "thead{background:#edf1f4}th{font-weight:600}.muted{color:#56636f}code{background:#edf1f4;padding:.15rem .4rem}"
            "@media(max-width:700px){table{font-size:.78rem}th,td{padding:.45rem}}</style></head><body>"
            "<h1>dbt-chaos · resilience benchmark</h1><p class='muted'>Evidence level: <code>"+
            label(source)+"</code> · Generated "+label(stamp)+"</p>"
            "<p>This report measures an explicitly bounded synthetic workload, not all real-world outages.</p>"+
            cov+"<table><thead><tr><th scope='col'>Strategy</th><th>Correct</th><th>Non-silent</th>"
            "<th>Wrong</th><th>Silent</th><th>Checkpoints</th><th>Run errors</th></tr></thead><tbody>"+
            "".join(rows)+"</tbody></table><h2>Interpretation and limitations</h2>"+notes+
            "<p class='muted'>Correct = independent truth matched. Non-silent = no mismatch escaped configured tests. "
            "These scores are deliberately distinct. Apache-2.0 · Vecture.</p></body></html>\n")

def load_and_render(path):
    from pathlib import Path
    file=Path(path)
    if file.stat().st_size>5_000_000:raise ValueError("report input is too large")
    return render(json.loads(file.read_text(encoding="utf8")))
