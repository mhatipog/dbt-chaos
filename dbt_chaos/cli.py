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
    m.add_argument("--confirm-dbt",action="store_true",help="Confirm original and shrunk failures against actual isolated dbt")
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
    rp=cmd.add_parser("report",help="Render a local, self-contained HTML evidence report")
    rp.add_argument("file",type=Path)
    rp.add_argument("--out",type=Path,required=True)
    merge=cmd.add_parser("merge-dbt",help="Aggregate validated real dbt evidence shards")
    merge.add_argument("files",type=Path,nargs="+")
    merge.add_argument("--out",type=Path,required=True)
    commerce=cmd.add_parser("commerce",help="Execute source/SQL faults in real dbt on isolated DuckDB")
    commerce.add_argument("--source",default="none")
    commerce.add_argument("--sql",default="none")
    commerce.add_argument("--out",type=Path)
    cm=cmd.add_parser("commerce-bench",help="Run bounded source/SQL fault matrix in real dbt")
    cm.add_argument("--selection",choices=("representative","source","logic","combined"),default="representative")
    cm.add_argument("--max-cases",type=int,default=30)
    cm.add_argument("--out",type=Path,required=True)
    cr=cmd.add_parser("commerce-report",help="Render local HTML from real commerce evidence")
    cr.add_argument("file",type=Path)
    cr.add_argument("--out",type=Path,required=True)
    demo=cmd.add_parser("evidence-demo",help="One-command real-dbt demo of recorded weak-LLM refund error and evidence gate")
    demo.add_argument("--out",type=Path,required=True)
    demo.add_argument("--markdown-out",type=Path)
    demo.add_argument("--no-native",action="store_true",help="Skip native quality-table comparison")
    demo.add_argument("--fail-on-silent",action="store_true",help="Exit nonzero when guarded publication has incorrect groups")
    replay_gate=cmd.add_parser("evaluate-chain",help="Replay full archived LLM chain with an independent evidence gate; real dbt")
    replay_gate.add_argument("corpus",type=Path,help="Exported full-dataset corpus arm (e.g. /tmp/relay/relay)")
    replay_gate.add_argument("--tier",choices=("source_only","attested"),default="source_only")
    replay_gate.add_argument("--out",type=Path,required=True)
    replay_gate.add_argument("--markdown-out",type=Path)
    replay_gate.add_argument("--no-native",action="store_true")
    replay_gate.add_argument("--fail-on-silent",action="store_true")
    args=parser.parse_args(argv)
    if args.command in ("evidence-demo", "evaluate-chain"):
        from .evidence_gate import replay_recorded_refund_demo, replay_frozen_chain, to_markdown
        if args.command=="evidence-demo":
            result=replay_recorded_refund_demo(quality_enabled=not args.no_native)
            scored=result["results"]["source_only"]["real_dbt"]
        else:
            result=replay_frozen_chain(args.corpus,tier=args.tier,
                                       quality_enabled=not args.no_native)
            scored=result["guarded_dbt_publication"]
        args.out.parent.mkdir(parents=True,exist_ok=True)
        args.out.write_text(json.dumps(result,indent=2,sort_keys=True)+"\\n",encoding="utf8")
        report=to_markdown(result)
        if args.markdown_out:
            args.markdown_out.parent.mkdir(parents=True,exist_ok=True)
            args.markdown_out.write_text(report,encoding="utf8")
        print(report)
        return 2 if args.fail_on_silent and (
            scored["false_published_groups"] or scored["silent_missing_groups"]) else 0
    if args.command=="commerce-report":
        from .commerce_report import render_file
        args.out.write_text(render_file(args.file),encoding="utf8")
        print("Wrote standalone report:",args.out)
        return 0
    if args.command=="commerce":
        from .commerce import CommerceCase,SOURCE_FAULTS,LOGIC_FAULTS
        from .commerce_runner import run_case
        if args.source not in SOURCE_FAULTS or args.sql not in LOGIC_FAULTS:
            parser.error("unsupported source/SQL fault; inspect the catalogue")
        result=run_case(CommerceCase(args.source,args.sql))
        output=json.dumps(result,indent=2,sort_keys=True)+"\n"
        if args.out: args.out.write_text(output,encoding="utf8")
        else: print(output)
        return 0
    if args.command=="commerce-bench":
        from .commerce import cases
        from .commerce_runner import run_matrix
        selected=cases()
        if args.selection=="source":
            selected=[x for x in selected if x.origin in ("source","control")]
        elif args.selection=="logic":
            selected=[x for x in selected if x.origin in ("transformation","control")]
        elif args.selection=="combined":
            selected=[x for x in selected if x.origin in ("combined","control")]
        report=run_matrix(selected,args.max_cases)
        args.out.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf8")
        print("Cases",report["cases"],"Outcomes",report["outcomes"])
        return int(report["execution_errors"]>0)
    if args.command=="merge-dbt":
        from .real_score import merge_reports
        shards=[]
        for file in args.files:
            if file.stat().st_size>10_000_000:parser.error("shard file too large")
            shards.append(json.loads(file.read_text(encoding="utf8")))
        report=merge_reports(shards)
        args.out.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf8")
        print("Merged",len(shards),"executed dbt score shards into",args.out)
        return int(any(s["execution_errors"] for s in report["strategies"].values()))
    if args.command=="report":
        from .report import load_and_render
        args.out.write_text(load_and_render(args.file),encoding="utf8")
        print("Wrote standalone report:",args.out)
        return 0
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
        if args.confirm_dbt:
            from .dbt_runner import run_real
            original=run_real(plan,args.strategy)
            minimized=run_real(result["plan"],args.strategy)
            def signature(item):
                return (item["silent_corruption"],
                        any(bool(point["alerts"]) for point in item["checkpoints"]))
            if signature(original)!=signature(minimized) or not any(signature(original)):
                raise RuntimeError("counterexample minimization did not preserve the real dbt failure signature")
            evidence=args.out.with_suffix(".evidence.json")
            evidence.write_text(json.dumps({"evidence_level":"executed_dbt_duckdb",
                "original":original,"minimized":minimized},indent=2,sort_keys=True)+"\n",encoding="utf8")
            print("Verified minimized failure twice in actual isolated dbt; evidence:",evidence)
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
