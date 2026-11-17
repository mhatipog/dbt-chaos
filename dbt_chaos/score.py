"""Transparent evidence-ranked scoring; do not interpret the synthetic score as a field probability."""
from collections import defaultdict
from .core import DOMAINS,STRATEGIES,screen
from .faults import coverage

def evaluate(plans,strategies=STRATEGIES,lookback=10):
    data=defaultdict(list)
    for plan in plans:
        for model in strategies:
            data[model].append(screen(plan,model,lookback))
    report={}
    for model,runs in sorted(data.items()):
        # Baseline checkpoints are controls, not injected-fault evidence.
        points=[p for run in runs for p in run["checkpoints"] if p["label"]!="baseline"]
        n=len(points)
        if not n:raise ValueError("no exercised fault checkpoints")
        silent=sum(int(p["silent"]) for p in points)
        wrong=sum(int(p["mismatch"]) for p in points)
        detected=sum(int(bool(p["alerts"])) for p in points)
        domains=defaultdict(lambda:[0,0])
        for run in runs:
            for tag in set(run["faults"]):
                domain=DOMAINS[tag]
                for p in run["checkpoints"]:
                    if p["label"]==tag:
                        domains[domain][0]+=1
                        domains[domain][1]+=int(p["silent"])
        report[model]={
            "cases":len(runs),"fault_checkpoints":n,
            "incorrect":wrong,"correct_checkpoints":n-wrong,
            "correctness_pct":round(100*(n-wrong)/n,2),
            "silent_corruption":silent,"detected_by_basic_tests":detected,
            "alerted_corruption":sum(int(p["mismatch"] and bool(p["alerts"])) for p in points),
            "undetected_wrong_pct":round(100*silent/wrong,2) if wrong else None,
            "score_0_100":round(100*(n-silent)/n,2),
            "read_work_units":sum(run["read_work_units"] for run in runs),
            "pipeline_runs":sum(run["run_count"] for run in runs),
            "by_domain":{k:{"checked":v[0],"silent":v[1]} for k,v in sorted(domains.items())}
        }
    return {"evidence_level":"python_model_screen","score_definition":"100 x (1 - silent_fault_checkpoints / fault_checkpoints)",
            "limits":["Synthetic workload; not real-world probability or an estimate of incidents.",
                      "Basic alerts only; not an arbitrary project's dbt tests.",
                      "Read work units approximate model work, not measured CPU hours or cost.",
                      "Unsupported fault domains are excluded and must not be claimed as tested."],
            "coverage":coverage(plans), "strategies":report}

def table(report):
    lines=["Strategy    Safe score  Silent  Checkpoints  Read units", "-"*55]
    for name,d in report["strategies"].items():
        lines.append(f'{name:<10} {d["score_0_100"]:>8.1f} {d["silent_corruption"]:>7} {d["fault_checkpoints"]:>12} {d["read_work_units"]:>11}')
    return "\n".join(lines)
