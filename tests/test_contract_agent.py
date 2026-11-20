"""Matched contract-aware agents, actual SQL quality, publication and gate tests."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dbt_chaos.contract_agent import (
    CautiousControl, ScriptedCalibration, FORMAT, POLICIES,
    candidate_source, guard_action, make_tickets, parse_proposal,
    run_experiment, score_one_decision, summarize,
)
from dbt_chaos.contract_sql import run_quality_checks_on_sources
from dbt_chaos.process_contract import (
    delivered_source_oracle, event_business_oracle, project_source,
    run_sqlite_reference, simulate_process, validate_contract,
)

CONTRACTS = (Path("contracts/procurement.json"), Path("contracts/grants.json"))


class ContractAgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = []
        for path in CONTRACTS:
            c=validate_contract(json.loads(path.read_text()))
            events=simulate_process(c,20261119)
            clean=project_source(c,events)
            cls.data.append((c,events,clean))

    def test_six_reproducible_source_only_ticket_types_in_both_domains(self):
        for c,events,clean in self.data:
            with self.subTest(domain=c["name"]):
                tickets=make_tickets(c,clean,20261119,6)
                self.assertEqual([t["kind"] for t in tickets], [
                    "credit_reconciliation","party_category_sync",
                    "document_duplicate_review","delivery_retry",
                    "document_status_review","record_integrity_audit"])
                self.assertEqual(tickets,make_tickets(c,clean,20261119,6))
                self.assertNotEqual(tickets,make_tickets(c,clean,20261120,6))
                for t in tickets:
                    self.assertIn(t["target_table"],clean)
                    self.assertFalse(t["independent_evidence_attached"])
                    self.assertIn(
                        t["target_row_id"],
                        [row["row_id"]
                         for row in t["observed_source_rows"][t["target_table"]]])
                    self.assertNotIn("expected_business",json.dumps(t))
                    self.assertNotIn("process_events",json.dumps(t))

    def test_strict_no_arbitrary_code_in_proposals_and_typed_mutations(self):
        c,events,clean=self.data[0]
        ticket=make_tickets(c,clean,20261119,6)[0]
        samples=[
            '{"operation":"keep","note":"insufficient evidence"}',
            '{"operation":"drop_entity_versions","table":"invoices","row_id":20001,"note":"review"}',
        ]
        for raw in samples:
            self.assertTrue(parse_proposal(raw)[1])
        malicious=[
            '{"operation":"shell","note":"rm -rf /"}',
            '{"operation":"edit_cell","table":"settlements","row_id":30001,"field":"amount","value":99,"python":"run()","note":"hi"}',
            '{"operation":"edit_cell","table":"settlements","row_id":"30001","field":"amount","value":5,"note":"hi"}',
            '{"operation":"drop_row","table":"invoices","row_id":20001,"note":[]}',
            "not json",
        ]
        for raw in malicious:
            with self.subTest(raw=raw):
                proposal,valid=parse_proposal(raw)
                self.assertFalse(valid)
                self.assertEqual("keep",proposal["operation"])
        bad={"operation":"edit_cell","table":ticket["target_table"],
             "row_id":ticket["target_row_id"],"field":"row_id","value":1,"note":"change key"}
        changed,effect=candidate_source(c,clean,ticket,bad)
        self.assertEqual("rejected_immutable_or_unsupported_field",effect)
        self.assertEqual(clean,changed)

    def test_no_op_controls_no_corruption_no_blocking(self):
        for c,events,clean in self.data:
            with self.subTest(domain=c["name"]):
                report=run_experiment(contract=c,worker=CautiousControl(),seed=20261119)
                summary=summarize(report)
                self.assertEqual(6,summary["steps"])
                self.assertEqual(6,summary["valid_proposals"])
                self.assertEqual(0,summary["actual_source_changes"])
                self.assertEqual(0,summary["material_business_errors"])
                self.assertEqual(0,summary["gate_review_count"])
                for name in POLICIES:
                    scored=summary["policy_results"][name]
                    self.assertEqual(0,scored["cases_with_wrong_publication"])
                    self.assertEqual(0,scored["cases_with_all_held"])
                    self.assertEqual(1.0,scored["total_correct_value_fraction"])

    def test_scripted_realistic_calibration_is_never_mislabeled_as_llm(self):
        for c,events,clean in self.data:
            with self.subTest(domain=c["name"]):
                report=run_experiment(contract=c,worker=ScriptedCalibration(),seed=20261119)
                self.assertFalse(report["methodology"]["genuine_weak_llm"])
                self.assertFalse(report["methodology"]["injected_faults"])
                summary=summarize(report)
                self.assertEqual("scripted_plausible_mistakes_not_llm",summary["worker"])
                self.assertEqual(6,summary["steps"])
                self.assertEqual(6,summary["valid_proposals"])
                self.assertEqual(5,summary["actual_source_changes"])
                self.assertEqual(4,summary["material_business_errors"])
                raw=summary["policy_results"]["raw"]
                self.assertEqual(4,raw["cases_with_wrong_publication"])
                self.assertGreater(raw["total_wrong_publication_l1_cents"],0)
                self.assertEqual(4,summary["gate_review_count"])
                for tier in ("evidence_gate","attested_gate"):
                    result=summary["policy_results"][tier]
                    self.assertEqual(0,result["cases_with_wrong_publication"])
                    self.assertEqual(0,result["cases_with_all_held"])
                    self.assertEqual(1.0,result["total_correct_value_fraction"])
                self.assertEqual(1,summary["policy_results"]
                                 ["block_on_detection"]["cases_with_all_held"])
                self.assertGreater(
                    summary["policy_results"]["block_on_detection"]
                    ["cases_with_wrong_publication"],0)
                self.assertEqual("source_entity_versions_deleted",
                                 report["decisions"][2]["candidate_effect"])

    def test_credit_value_is_source_plausible_but_historically_false(self):
        for c,events,clean in self.data:
            ticket=make_tickets(c,clean,20261119)[0]
            proposal=json.loads(ScriptedCalibration().decide(ticket,{}))
            changed,effect=candidate_source(c,clean,ticket,proposal)
            self.assertEqual("source_cell_rewritten",effect)
            self.assertEqual(2000,sum(abs(
                event_business_oracle(c,events).get(key,0)
                - delivered_source_oracle(c,changed).get(key,0))
                for key in (set(event_business_oracle(c,events))
                            |set(delivered_source_oracle(c,changed)))))
            self.assertEqual([], [x for x in run_quality_checks_on_sources(c,changed)
                                  if x["severity"]=="block"])
            result=score_one_decision(c,events,clean,ticket,json.dumps(proposal))
            self.assertEqual(2000,result["source_l1_cents"])
            self.assertEqual(2000,result["policies"]["raw"]
                             ["publication"]["false_published_l1_cents"])
            self.assertEqual(2000,result["policies"]["monitor"]
                             ["publication"]["false_published_l1_cents"])
            self.assertEqual(2000,result["policies"]["block_on_detection"]
                             ["publication"]["false_published_l1_cents"])
            self.assertEqual("review_required",result["guard_decisions"]
                             ["evidence_gate"]["decision"])
            self.assertEqual(0,result["policies"]["evidence_gate"]
                             ["publication"]["false_published_l1_cents"])

    def test_document_deletion_is_detected_but_monitor_still_exposes_it(self):
        for c,events,clean in self.data:
            ticket=make_tickets(c,clean,20261119)[2]
            proposal=json.loads(ScriptedCalibration().decide(ticket,{}))
            changed,effect=candidate_source(c,clean,ticket,proposal)
            self.assertEqual("source_entity_versions_deleted",effect)
            source_alerts=run_quality_checks_on_sources(c,changed)
            self.assertIn("orphan_movement",
                          {s["check_name"] for s in source_alerts})
            result=score_one_decision(c,events,clean,ticket,json.dumps(proposal))
            self.assertEqual("silently_wrong",result["policies"]["monitor"]
                             ["publication"]["status"])
            self.assertGreater(
                result["policies"]["monitor"]["quality"]["blocking"],0)
            self.assertEqual("withheld_all",result["policies"]
                             ["block_on_detection"]["disposition"])
            self.assertEqual(0.0,result["policies"]["block_on_detection"]
                             ["publication"]["fraction_of_correct_business_value_published"])
            self.assertEqual("correctly_published",result["policies"]["evidence_gate"]
                             ["publication"]["status"])

    def test_safe_retry_does_not_cost_availability_in_source_gate(self):
        for c,events,clean in self.data:
            ticket=make_tickets(c,clean,20261119)[3]
            proposal=json.loads(ScriptedCalibration().decide(ticket,{}))
            changed,effect=candidate_source(c,clean,ticket,proposal)
            self.assertEqual("source_delivery_replayed",effect)
            self.assertEqual(
                run_sqlite_reference(c,clean),run_sqlite_reference(c,changed))
            result=score_one_decision(c,events,clean,ticket,json.dumps(proposal))
            self.assertEqual("accepted",result["guard_decisions"]
                             ["evidence_gate"]["decision"])
            self.assertEqual("idempotent_replay",result["guard_decisions"]
                             ["evidence_gate"]["reason"])
            self.assertEqual("correctly_published",result["policies"]
                             ["evidence_gate"]["publication"]["status"])
            self.assertEqual("published",result["policies"]
                             ["block_on_detection"]["disposition"])
            self.assertEqual(0,result["policies"]
                             ["block_on_detection"]["quality"]["blocking"])

    def test_attestation_only_accepts_correction_matching_private_source_exactly(self):
        c,events,clean=self.data[0]
        ticket=make_tickets(c,clean,20261119)[0]
        fault=json.loads(ScriptedCalibration().decide(ticket,{}))
        dirty,_=candidate_source(c,clean,ticket,fault)
        repair={**fault,"value":next(row[fault["field"]] for row in clean[fault["table"]]
                                    if row["row_id"]==fault["row_id"])}
        repaired,effect=candidate_source(c,dirty,ticket,repair)
        self.assertEqual(clean,repaired)
        source=guard_action(c,dirty,repaired,ticket,repair,tier="source_only")
        trusted=guard_action(c,dirty,repaired,ticket,repair,tier="attested",
                             attested=project_source(c,events))
        self.assertEqual("review_required",source["decision"])
        self.assertEqual("accepted",trusted["decision"])
        self.assertEqual("exact_event_attestation",trusted["reason"])
        assert not (run_sqlite_reference(c,dirty) == event_business_oracle(c,events))
        self.assertEqual(run_sqlite_reference(c,repaired),
                         event_business_oracle(c,events))
        wrong=guard_action(c,clean,dirty,ticket,fault,tier="attested",
                           attested=project_source(c,events))
        self.assertEqual("review_required",wrong["decision"])
        with self.assertRaisesRegex(ValueError, "mismatched"):
            guard_action(c,dirty,repaired,ticket,repair,tier="source_only",
                         attested=clean)

    def test_worker_not_given_private_ledger_or_oracle(self):
        class Spy(CautiousControl):
            def __init__(self):
                self.seen=[]
            def decide(self,ticket,context):
                self.seen.append((deepcopy(ticket),deepcopy(context)))
                return super().decide(ticket,context)
        c,events,clean=self.data[0]
        spy=Spy()
        run_experiment(contract=c,worker=spy,seed=20261119,steps=6)
        self.assertEqual(6,len(spy.seen))
        for ticket,context in spy.seen:
            self.assertNotIn("business_gold",json.dumps([ticket,context]))
            self.assertNotIn("process_events",json.dumps([ticket,context]))
            self.assertNotIn("ledger",json.dumps([ticket,context]))
            self.assertIn("process_contract",context)

    def test_public_export_hides_truth_and_full_tables_replayable(self):
        c,events,clean=self.data[0]
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            pub,pri=root/"public",root/"private"
            report=run_experiment(contract=c,worker=ScriptedCalibration(),
                                  seed=20261119,steps=6,
                                  public_dir=pub,private_dir=pri)
            self.assertTrue((pub/"manifest.json").exists())
            self.assertFalse((pub/"original_process_events.jsonl").exists())
            self.assertFalse((pub/"business_gold.json").exists())
            self.assertFalse((pub/"assessment.json").exists())
            self.assertTrue((pri/"original_process_events.jsonl").exists())
            self.assertTrue((pri/"business_gold.json").exists())
            self.assertEqual(6,len(list((pub/"steps").glob("*"))))
            manifest=json.loads((pub/"manifest.json").read_text())
            from hashlib import sha256
            for filename,digest in manifest["file_sha256"].items():
                self.assertEqual(digest,sha256((pub/filename).read_bytes()).hexdigest())
            self.assertTrue((pub/"steps/01/clean/invoices.csv").exists())
            self.assertTrue((pub/"steps/01/raw_proposed/settlements.csv").exists())
            self.assertEqual(FORMAT,report["experiment"])

    def test_no_automatic_llm_inference_on_calibrations(self):
        for obj in (CautiousControl(),ScriptedCalibration()):
            self.assertIsNone(obj.model_sha256)
            self.assertNotIn("genuine_",obj.name)


if __name__=="__main__":
    unittest.main()
