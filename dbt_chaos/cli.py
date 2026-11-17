"""Local synthetic-only CLI; production connection strings are never accepted."""
import argparse
import json
from pathlib import Path
from .core import STRATEGIES,DOMAINS,PLANNED,screen,read_plan
from .faults import generate
from .score import evaluate,table
from .shrink import reduce_plan

def main(argv=None):
    parser=argparse.ArgumentParser(prog="dbt-chaos",description=__doc__)
    cmd=parser.add_subparsers(dest="command",required=True)
    cmd.add_parser("faults",help="Show implemented and planned fault coverage")
    g=cmd.add_parser("generate",help="Generate portable replayable JSON plans")
    g.add_argument("--seed",type=int,default=42)
    g.add_argument("--count",type=int,default=100)
    g.add_argument("--out",type=Path,default=Path("campaign"))
    b=cmd.add_parser("bench",help="Compare candidate strategy models (not real dbt)")
    b.add_argument("--seed",type=int,default=42)
    b.add_argument("--count",type=int,default=100)
    b.add_argument("--max-faults",type=int,choices=(1,2,3),default=3)
    b.add_argument("--lookback",type=int,default=10)
    b.add_argument("--out",type=Path)
    r=cmd.add_parser("replay",help="Inspect one scenario using model screening")
    r.add_argument("file",type=Path)
    r.add_argument("--strategy",choices=STRATEGIES,default="strict")
    r.add_argument("--out",type=Path)
    m=cmd.add_parser("minimize",help="Shrink a screened failure without changing its signature")
    m.add_argument("file",type=Path)
    m.add_argument("--strategy",choices=STRATEGIES,default="strict")
    m.add_argument("--out",type=Path,required=True)
    real=cmd.add_parser("verify-dbt",help="Execute actual dbt on isolated synthetic DuckDB database")
    real.add_argument("file",type=Path)
    real.add_argument("--strategy",choices=STRATEGIES,default="strict")
    real.add_argument("--out",type=Path)
    rb=cmd.add_parser("bench-dbt",help="Run bounded actual dbt/DuckDB strategy comparison")
    rb.add_argument("--seed",type=int,default=42)
    rb.add_argument("--count",type=int,default=3)
    rb.add_argument("--start",type=int,default=0,help="Zero-based scenario index for CI sharding")
    rb.add_argument("--strategies",default="strict,offset,full")
    rb.add_argument("--max-executions",type=int,default=12)
    rb.add_argument("--time-budget",type=int,default=900)
    rb.add_argument("--out",type=Path,required=True)
    args=parser.parse_args(argv)
    if args.command=="bench-dbt":
        from .real_score import run_campaign
        choices=tuple(args.strategies.split(","))
        if not choices or any(s not in STRATEGIES for s in choices) or len(set(choices))!=len(choices):
            parser.error("strategies must be a distinct subset of "+",".join(STRATEGIES))
        if args.start<0 or args.start+args.count>10_000:
            parser.error("scenario slice outside supported range")
        plans=generate(args.seed,args.start+args.count)[args.start:]
        report=run_campaign(plans,choices,
                            args.max_executions,args.time_budget)
        args.out.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf8")
        for name,score in report["strategies"].items():
            print(f"{name}: score={score['score_0_100']}, silent={score['silent_corruption']}, errors={score['execution_errors']}")
        print("Wrote actual dbt evidence:",args.out)
        return int(any(score["execution_errors"] for score in report["strategies"].values()))
    if args.command=="faults":
        for name,domain in DOMAINS.items():
            print(f"{name:28} {domain:14} implemented")
        for name,domain in PLANNED.items():
            print(f"{name:28} {domain:14} PLANNED - not tested")
        return 0
    if args.command=="generate":
        args.out.mkdir(parents=True,exist_ok=True)
        plans=generate(args.seed,args.count)
        for i,plan in enumerate(plans):
            (args.out/f"{i:04d}.json").write_text(plan.dumps(),encoding="utf8")
        print(f"Wrote {len(plans)} scenarios to {args.out}")
        return 0
    if args.command=="bench":
        report=evaluate(generate(args.seed,args.count,args.max_faults),lookback=args.lookback)
        print(table(report))
        if args.out:args.out.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf8")
        return 0
    plan=read_plan(args.file)
    if args.command=="replay":
        result=screen(plan,args.strategy)
        content=json.dumps(result,indent=2,sort_keys=True)+"\n"
        if args.out:args.out.write_text(content,encoding="utf8")
        else:print(content)
        return 0
    if args.command=="minimize":
        result=reduce_plan(plan,args.strategy)
        args.out.write_text(result["plan"].dumps(),encoding="utf8")
        print(f"minimized={result['changed']}, attempts={result['attempts']}, saved={args.out}")
        return 0
    if args.command=="verify-dbt":
        from .dbt_runner import run_real
        result=run_real(plan,args.strategy)
        content=json.dumps(result,indent=2,sort_keys=True)+"\n"
        if args.out:args.out.write_text(content,encoding="utf8")
        else:print(content)
        return int(any(point.get("execution_error") for point in result["checkpoints"]))
    raise AssertionError("unknown command")

if __name__=="__main__":
    raise SystemExit(main())
