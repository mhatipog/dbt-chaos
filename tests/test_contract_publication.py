"""Platform release plans: protect affected groups without inventing repairs."""
import json
from copy import deepcopy
from pathlib import Path
import unittest

from dbt_chaos.contract_agent import (
    ScriptedCalibration, candidate_source, make_tickets, score_one_decision,
)
from dbt_chaos.contract_publication import plan_publication
from dbt_chaos.contract_sql import run_quality_checks_on_sources
from dbt_chaos.process_contract import (
    event_business_oracle, project_source, run_sqlite_reference,
    simulate_process, validate_contract,
)
from dbt_chaos.relay_platform_replay import score_publication

CONTRACTS=(Path("contracts/procurement.json"),Path("contracts/grants.json"))


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.cases=[]
        for path in CONTRACTS:
            c=validate_contract(json.loads(path.read_text()))
            e=simulate_process(c,20261119)
            src=project_source(c,e)
            self.cases.append((c,e,src))

    def test_clean_and_harmless_retry_publish_full_valid_business_value(self):
        for c,events,source in self.cases:
            for scenario in ("clean", "retry"):
                with self.subTest(domain=c["name"],scenario=scenario):
                    state=deepcopy(source)
                    if scenario=="retry":
                        ticket=make_tickets(c,source,20261119)[3]
                        proposal=json.loads(ScriptedCalibration().decide(ticket,{}))
                        state,effect=candidate_source(c,state,ticket,proposal)
                        self.assertEqual("source_delivery_replayed",effect)
                    issues=run_quality_checks_on_sources(c,state)
                    plan=plan_publication(c,state,issues)
                    self.assertEqual("published",plan["status"])
                    self.assertFalse(plan["global_hold"])
                    self.assertEqual([],plan["known_held_groups"])
                    self.assertEqual(0,plan["quarantined_physical_rows"])
                    self.assertEqual(run_sqlite_reference(c,source),plan["released"])
                    report=score_publication(event_business_oracle(c,events),
                                              plan["released"],set())
                    self.assertEqual("correctly_published",report["status"])
                    self.assertEqual(1.0,report["fraction_of_correct_business_value_published"])

    def test_plausible_credit_is_still_unobservable_and_published_wrong(self):
        for c,events,source in self.cases:
            ticket=make_tickets(c,source,20261119)[0]
            proposal=json.loads(ScriptedCalibration().decide(ticket,{}))
            state,_=candidate_source(c,source,ticket,proposal)
            issues=run_quality_checks_on_sources(c,state)
            plan=plan_publication(c,state,issues)
            self.assertEqual("published",plan["status"])
            self.assertEqual([],plan["known_held_groups"])
            error=score_publication(event_business_oracle(c,events),
                                    plan["released"],set())
            self.assertEqual("silently_wrong",error["status"])
            self.assertEqual(2000,error["false_published_l1_cents"])
            self.assertFalse(plan["global_hold"])

    def test_negative_amount_only_holds_derived_reporting_group(self):
        for c,events,source in self.cases:
            with self.subTest(domain=c["name"]):
                ticket=make_tickets(c,source,20261119)[0]
                table=c["roles"]["movement"]["table"]
                amount=c["roles"]["movement"]["amount"]
                state=deepcopy(source)
                row=next(x for x in state[table]
                         if x["row_id"]==ticket["target_row_id"])
                row[amount]=-1
                issues=run_quality_checks_on_sources(c,state)
                self.assertTrue(any(x["check_name"]=="negative_movement_amount"
                                    and x["severity"]=="block" for x in issues))
                plan=plan_publication(c,state,issues)
                self.assertEqual("partially_held",plan["status"])
                self.assertFalse(plan["global_hold"])
                self.assertGreater(len(plan["known_held_groups"]),0)
                self.assertLess(len(plan["known_held_groups"]),
                                len(event_business_oracle(c,events)))
                self.assertGreater(len(plan["released"]),0)
                held={tuple(key.split("|",1)) for key in plan["known_held_groups"]}
                report=score_publication(event_business_oracle(c,events),
                                          plan["released"],held)
                self.assertEqual("partially_held",report["status"])
                self.assertEqual([],report["false_published_groups"])
                self.assertEqual([],report["silent_missing_groups"])
                self.assertLess(report["fraction_of_correct_business_value_published"],1)
                self.assertGreater(report["fraction_of_correct_business_value_published"],0)
                self.assertEqual(0,plan["quarantined_physical_rows"])

    def test_orphaned_document_global_hold_instead_of_unknown_group(self):
        for c,events,source in self.cases:
            ticket=make_tickets(c,source,20261119)[2]
            proposal=json.loads(ScriptedCalibration().decide(ticket,{}))
            state,effect=candidate_source(c,source,ticket,proposal)
            self.assertEqual("source_entity_versions_deleted",effect)
            issues=run_quality_checks_on_sources(c,state)
            self.assertIn("orphan_movement",{x["check_name"] for x in issues})
            plan=plan_publication(c,state,issues)
            self.assertEqual("withheld_all",plan["status"])
            self.assertTrue(plan["global_hold"])
            self.assertEqual({},plan["released"])
            self.assertEqual("delivered_source_and_observable_sql_checks_only",
                             plan["basis"])
            self.assertEqual(0,plan["quarantined_physical_rows"])

    def test_unsupported_rule_or_unknown_ancestor_fails_closed(self):
        c,events,source=self.cases[0]
        broken=deepcopy(source)
        movement=c["roles"]["movement"]
        row=broken[movement["table"]][0]
        row[movement["document_fk"]]=999999999
        issues=[{"severity":"block","check_name":"negative_movement_amount",
                 "entity_id":row[movement["id"]],
                 "related_id":row[movement["document_fk"]]}]
        plan=plan_publication(c,broken,issues)
        self.assertEqual("withheld_all",plan["status"])
        self.assertEqual("ancestor_unavailable",plan["reasons"][0]["reason"])
        changed=plan_publication(c,source,[
            {"severity":"block","check_name":"unmapped_detector"}])
        self.assertEqual("withheld_all",changed["status"])
        weird=plan_publication(c,source,[
            {"severity":"warning","check_name":"unknown_severity"}])
        self.assertEqual("withheld_all",weird["status"])

    def test_gates_are_reported_as_release_not_quarantine(self):
        c,events,source=self.cases[0]
        ticket=make_tickets(c,source,20261119)[2]
        raw=ScriptedCalibration().decide(ticket,{})
        result=score_one_decision(c,events,source,ticket,raw)
        self.assertIn("targeted_hold",result["policies"])
        targeted=result["policies"]["targeted_hold"]
        self.assertEqual("withheld_all",targeted["disposition"])
        self.assertEqual(0,targeted["physical_source_quarantines"])
        self.assertEqual("withheld_all",result["policies"]
                         ["block_on_detection"]["disposition"])


if __name__=="__main__":
    unittest.main()
