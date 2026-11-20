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
    external=cmd.add_parser("export-challenge",help="Export clean and weak-agent-chaotic CSVs for any data platform; keep answer key separate")
    external.add_argument("corpus",type=Path,nargs="?",help="Existing full agent corpus; omit with --starter")
    external.add_argument("--starter",action="store_true",help="Replay one archived real Qwen refund edit; no model or dbt required")
    external.add_argument("--public-dir",type=Path,required=True)
    external.add_argument("--private-dir",type=Path,required=True)
    external.add_argument("--step",type=int)
    external_score=cmd.add_parser("score-challenge",help="Score externally published CSV results against hidden process truth")
    external_score.add_argument("--public-dir",type=Path,required=True)
    external_score.add_argument("--answer-key",type=Path,required=True)
    external_score.add_argument("--published-dir",type=Path,required=True)
    external_score.add_argument("--held-dir",type=Path)
    external_score.add_argument("--alerts-json",type=Path)
    external_score.add_argument("--out",type=Path,required=True)
    external_score.add_argument("--fail-on-silent",action="store_true")
    rec_demo=cmd.add_parser("reconcile-demo",help="Run real native dbt with provider, correlated GL and bank reconciliation")
    rec_demo.add_argument("--scenario",default="qwen_refund_source_only")
    rec_demo.add_argument("--out",type=Path,required=True)
    rec_demo.add_argument("--fail-on-silent",action="store_true")
    rec_export=cmd.add_parser("export-reconciliation",help="Generate six synthetic evidence tables for any isolated data platform")
    rec_export.add_argument("--scenario",default="qwen_refund_source_only")
    rec_export.add_argument("--public-dir",type=Path,required=True)
    rec_export.add_argument("--private-dir",type=Path,required=True)
    rec_score=cmd.add_parser("score-reconciliation",help="Evaluate an external platform's actually published revenue against private business events")
    rec_score.add_argument("--public-dir",type=Path,required=True)
    rec_score.add_argument("--answer-key",type=Path,required=True)
    rec_score.add_argument("--published",type=Path,required=True)
    rec_score.add_argument("--held",type=Path)
    rec_score.add_argument("--out",type=Path,required=True)
    rec_score.add_argument("--fail-on-silent",action="store_true")
    contract=cmd.add_parser("contract-generate",help="Generate independent process-ledger chaos from a safe declarative contract")
    contract.add_argument("--contract",type=Path,required=True)
    contract.add_argument("--seed",type=int,default=20261119)
    contract.add_argument("--fault",choices=("none","rewrite_credit","reclassify_party","drop_document","duplicate_delivery"),default="rewrite_credit")
    contract.add_argument("--public-dir",type=Path,required=True)
    contract.add_argument("--private-dir",type=Path,required=True)
    cref=cmd.add_parser("contract-reference",help="Run independently executed SQLite reference on public synthetic inputs (no private truth)")
    cref.add_argument("--public-dir",type=Path,required=True)
    cref.add_argument("--output-dir",type=Path,required=True)
    cprobe=cmd.add_parser("contract-probe",help="Run optional source-only SQL DQ checks from a contract")
    cprobe.add_argument("--public-dir",type=Path,required=True)
    cprobe.add_argument("--out",type=Path,required=True)
    cs=cmd.add_parser("contract-score",help="Grade platform-published results against private event-ledger truth")
    cs.add_argument("--public-dir",type=Path,required=True)
    cs.add_argument("--answer-key",type=Path,required=True)
    cs.add_argument("--published-dir",type=Path,required=True)
    cs.add_argument("--held-dir",type=Path)
    cs.add_argument("--alerts-json",type=Path)
    cs.add_argument("--out",type=Path,required=True)
    cs.add_argument("--fail-on-silent",action="store_true")
    ca=cmd.add_parser("contract-agent",help="Replay good-faith maintenance proposals through independent SQL and safety policies")
    ca.add_argument("--contract",type=Path,required=True)
    ca.add_argument("--agent",choices=("scripted","cautious","llama"),default="cautious")
    ca.add_argument("--model",type=Path)
    ca.add_argument("--seed",type=int,default=20261119)
    ca.add_argument("--steps",type=int,default=6)
    ca.add_argument("--public-dir",type=Path,required=True)
    ca.add_argument("--private-dir",type=Path,required=True)
    ca.add_argument("--out",type=Path)
    cv=cmd.add_parser("contract-review",help="Balanced approve/keep/escalate decisions over harmful and beneficial edits")
    cv.add_argument("--contract",type=Path,required=True)
    cv.add_argument("--agent",choices=("always_apply","always_keep","llama"),
                    default="always_keep")
    cv.add_argument("--model",type=Path)
    cv.add_argument("--seed",type=int,default=20261119)
    cv.add_argument("--public-dir",type=Path,required=True)
    cv.add_argument("--private-dir",type=Path,required=True)
    cv.add_argument("--out",type=Path)
    cw=cmd.add_parser("contract-casework",help="Demonstrate incorrect publication, targeted pending hold and signed receipt recovery")
    cw.add_argument("--contract",type=Path,required=True)
    cw.add_argument("--seed",type=int,default=20261119)
    cw.add_argument("--out",type=Path,required=True)
    cw.add_argument("--fail-on-incorrect-final",action="store_true")
    assess=cmd.add_parser("assess-demo",help="Run two-domain executed-SQL resilience assessment, emit JSON/Markdown/HTML")
    assess.add_argument("--seed",type=int,default=20261119)
    assess.add_argument("--out-dir",type=Path,required=True)
    assess.add_argument("--fail-on-unsafe",action="store_true")
    foreign=cmd.add_parser(
        "external-dbt",
        help="Execute real dbt/DuckDB mutations against an unfamiliar seed-backed local project",
    )
    foreign.add_argument("--project-dir",type=Path,required=True)
    foreign.add_argument("--model",required=True)
    foreign.add_argument("--seed-table",required=True)
    foreign.add_argument("--column",required=True)
    foreign.add_argument("--match-column",required=True)
    foreign.add_argument("--match-value",required=True)
    foreign.add_argument("--delta",type=int,default=2000)
    foreign.add_argument("--faults",default="amount_shift,duplicate_row,drop_row")
    foreign.add_argument("--independent-expected",type=Path)
    foreign.add_argument("--out",type=Path,required=True)
    foreign.add_argument("--timeout",type=int,default=90)
    foreign.add_argument("--acknowledge-project-code-execution",action="store_true")
    foreign.add_argument("--fail-on-silent",action="store_true")
    args=parser.parse_args(argv)
    if args.command=="external-dbt":
        from .external_dbt import run_external_campaign, write_external_report
        report=run_external_campaign(
            project_dir=args.project_dir,
            model=args.model,seed_table=args.seed_table,
            column=args.column,match_column=args.match_column,
            match_value=args.match_value,delta=args.delta,
            faults=tuple(args.faults.split(",")),
            independent_expected=args.independent_expected,
            acknowledge_code_execution=args.acknowledge_project_code_execution,
            timeout=args.timeout)
        write_external_report(report,args.out)
        print(json.dumps({
            "project":report["project"],
            "actual_engine":report["engine"],
            "independent_gold_supplied":report["independent_gold_supplied"],
            "cases":[{"fault":c["fault"],"outcome":c["outcome"]}
                     for c in report["cases"]],
            "evidence_path":str(args.out),
        },indent=2,sort_keys=True))
        return (2 if args.fail_on_silent and
                report["silent_business_mismatches"] else 0)
    if args.command=="assess-demo":
        from .resilience_assessment import run_assessment, write_assessment
        report=run_assessment(args.seed)
        result=write_assessment(report,args.out_dir)
        print(json.dumps(result,indent=2,sort_keys=True))
        return 2 if args.fail_on_unsafe and not report["controls_passed"] else 0
    if args.command=="contract-casework":
        from .contract_review import make_review_cases
        from .contract_casework import demonstrate_contract_casework
        contract_data=json.loads(args.contract.read_text(encoding="utf8"))
        events,cases=make_review_cases(contract_data,args.seed)
        result=demonstrate_contract_casework(contract_data,events,cases[4])
        args.out.parent.mkdir(parents=True,exist_ok=True)
        args.out.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf8")
        for step in result["stages"]:
            print(step["stage"],step["publication_status"],
                  "wrong published cents:",
                  step["score"]["false_published_l1_cents"],
                  "correct business value:",
                  step["score"]["fraction_of_correct_business_value_published"])
        return (2 if args.fail_on_incorrect_final and
                result["stages"][-1]["score"]["status"]!="correctly_published"
                else 0)
    if args.command in ("contract-agent","contract-review"):
        from .process_contract import validate_contract
        contract_data=validate_contract(json.loads(args.contract.read_text(encoding="utf8")))
        if args.agent=="llama" and args.model is None:
            parser.error("--agent llama requires --model PATH_TO_GGUF")
        if args.command=="contract-agent":
            from .contract_agent import (
                LocalContractWorker,CautiousControl,ScriptedCalibration,
                run_experiment,summarize)
            worker=(LocalContractWorker(args.model,args.seed) if args.agent=="llama"
                    else ScriptedCalibration() if args.agent=="scripted"
                    else CautiousControl())
            data=run_experiment(contract=contract_data,worker=worker,seed=args.seed,
                                steps=args.steps,public_dir=args.public_dir,
                                private_dir=args.private_dir)
        else:
            from .contract_review import (
                LocalLLMReviewer,AlwaysApplyReviewer,AlwaysKeepReviewer,
                run_review_experiment,summarize)
            worker=(LocalLLMReviewer(args.model,args.seed) if args.agent=="llama"
                    else AlwaysApplyReviewer() if args.agent=="always_apply"
                    else AlwaysKeepReviewer())
            data=run_review_experiment(contract=contract_data,reviewer=worker,
                                       seed=args.seed,public_dir=args.public_dir,
                                       private_dir=args.private_dir)
        result=summarize(data)
        if args.out:
            args.out.parent.mkdir(parents=True,exist_ok=True)
            args.out.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf8")
        print(json.dumps(result,indent=2,sort_keys=True))
        return 0
    if args.command in ("contract-generate","contract-reference","contract-score","contract-probe"):
        from .process_contract import (
            export_contract_challenge,run_reference_from_public,
            score_contract_challenge)
        if args.command=="contract-probe":
            from .contract_sql import evaluate_public_quality
            result=evaluate_public_quality(args.public_dir)
            args.out.parent.mkdir(parents=True,exist_ok=True)
            args.out.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf8")
            print(json.dumps({scenario:{"block":results["block_count"],
                "info":results["informational_count"]}
                for scenario,results in result["results"].items()},indent=2))
            return 0
        if args.command=="contract-generate":
            result=export_contract_challenge(
                contract_path=args.contract,seed=args.seed,fault=args.fault,
                public_dir=args.public_dir,private_dir=args.private_dir)
        elif args.command=="contract-reference":
            result=run_reference_from_public(args.public_dir,args.output_dir)
        else:
            result=score_contract_challenge(
                public_dir=args.public_dir,answer_key=args.answer_key,
                published_dir=args.published_dir,held_dir=args.held_dir,
                alerts_json=args.alerts_json)
            args.out.parent.mkdir(parents=True,exist_ok=True)
            args.out.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf8")
        print(json.dumps(result,indent=2,sort_keys=True))
        return (2 if args.command=="contract-score" and args.fail_on_silent and any(
                r["published"]["status"]=="silently_wrong"
                for r in result["results"].values()) else 0)
    if args.command in ("reconcile-demo","export-reconciliation",
                          "score-reconciliation"):
        from .reconciliation_lab import (
            run_native_demo, export_scenario, score_scenario)
        if args.command=="reconcile-demo":
            result=run_native_demo(args.scenario)
            grade=result["native_published_business_score"]
            printed={
                "scenario":result["case"],
                "raw_business_score":result["baseline_publication"]["status"],
                "reconciled_publication_score":grade["status"],
                "wrong_amount_cents":grade["false_published_l1_cents"],
                "withheld_groups":len(grade["held_groups"]),
                "observed_disputes":result["native_dbt_reconciliation"]["dispute_count"],
            }
        elif args.command=="export-reconciliation":
            result=export_scenario(
                args.scenario,public_dir=args.public_dir,
                private_dir=args.private_dir)
            printed=result
        else:
            result=score_scenario(
                public_dir=args.public_dir,answer_key=args.answer_key,
                published=args.published,held=args.held)
            grade=result["business_score"]
            printed={
                "scenario":result["scenario"],
                "publication_status":grade["status"],
                "wrong_published_groups":len(grade["false_published_groups"]),
                "wrong_amount_cents":grade["false_published_l1_cents"],
                "correct_business_value_fraction":
                    grade["fraction_of_correct_business_value_published"],
            }
        if args.command!="export-reconciliation":
            args.out.parent.mkdir(parents=True,exist_ok=True)
            args.out.write_text(
                json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf8")
        print(json.dumps(printed,indent=2,sort_keys=True))
        return (2 if getattr(args,"fail_on_silent",False) and
                result.get("native_published_business_score",
                           result.get("business_score",{})).get("status")
                    == "silently_wrong" else 0)
    if args.command=="export-challenge":
        from .external_challenge import (export_external_challenge,
                                         export_recorded_qwen_starter_challenge)
        if args.starter == bool(args.corpus):
            parser.error("choose exactly one: an existing corpus OR --starter")
        if args.starter and args.step is not None:
            parser.error("--step applies only to existing corpora, not --starter")
        result=(export_recorded_qwen_starter_challenge(
                    public_dir=args.public_dir,private_dir=args.private_dir)
                if args.starter else
                export_external_challenge(
                    corpus=args.corpus,public_dir=args.public_dir,
                    private_dir=args.private_dir,step=args.step))
        print(json.dumps(result,indent=2,sort_keys=True))
        return 0
    if args.command=="score-challenge":
        from .external_challenge import score_external_challenge
        result=score_external_challenge(
            public_dir=args.public_dir,answer_key=args.answer_key,
            published_dir=args.published_dir,held_dir=args.held_dir,
            alerts_json=args.alerts_json)
        args.out.parent.mkdir(parents=True,exist_ok=True)
        args.out.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf8")
        for case,value in result["results"].items():
            print(f"{case}: {value['verdict']}; "
                  f"wrong published groups={len(value['published']['false_published_groups'])}; "
                  f"correct value fraction={value['published']['fraction_of_correct_business_value_published']}")
        return (2 if args.fail_on_silent and any(
            value["published"]["status"]=="silently_wrong"
            for value in result["results"].values()) else 0)
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
        args.out.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf8")
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
