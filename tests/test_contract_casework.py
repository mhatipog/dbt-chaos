"""Dispute triage, targeted publication holds and evidence-arrival recovery."""
from copy import deepcopy
import json
from pathlib import Path
import secrets
import unittest

from dbt_chaos.contract_agent import candidate_source
from dbt_chaos.contract_casework import (
    demonstrate_contract_casework, resolve_dispute_lineage,
    publish_pending_dispute, publish_verified_correction,
)
from dbt_chaos.contract_receipt import issue_simulated_receipt
from dbt_chaos.contract_review import make_review_cases
from dbt_chaos.process_contract import project_source, validate_contract
from dbt_chaos.relay_platform_replay import score_publication

CONTRACTS=(Path("contracts/procurement.json"),Path("contracts/grants.json"))


class ContractCaseworkTests(unittest.TestCase):
    def setUp(self):
        self.cases=[]
        for path in CONTRACTS:
            c=validate_contract(json.loads(path.read_text()))
            events,cases=make_review_cases(c,20261119)
            case=cases[4]
            self.cases.append((c,events,case))

    def test_three_real_sql_published_stages_and_zero_post_proof_error(self):
        for c,events,case in self.cases:
            with self.subTest(domain=c["name"]):
                timeline=demonstrate_contract_casework(c,events,case)
                self.assertEqual(3,len(timeline["stages"]))
                self.assertFalse(timeline["source_ledger_present_in_release_planner"])
                self.assertFalse(timeline["signing_key_exported"])
                self.assertTrue(timeline["synthetic_provider_receipt_not_real_connection"])
                initial,pending,final=timeline["stages"]
                self.assertEqual("unprotected_dirty_source",initial["stage"])
                self.assertGreater(initial["score"]["false_published_l1_cents"],0)
                self.assertEqual("silently_wrong",initial["score"]["status"])
                self.assertEqual("partially_held",pending["publication_status"])
                self.assertEqual(1,len(pending["held_group_ids"]))
                self.assertEqual(0,pending["quarantined_source_rows"])
                self.assertEqual("partially_held",pending["score"]["status"])
                self.assertEqual(0,pending["score"]["false_published_l1_cents"])
                self.assertEqual([],pending["score"]["silent_missing_groups"])
                self.assertGreater(pending["score"]
                                   ["fraction_of_correct_business_value_published"],0.5)
                self.assertLess(pending["score"]
                                  ["fraction_of_correct_business_value_published"],1.0)
                self.assertEqual("published",final["publication_status"])
                self.assertEqual("accepted",final["gate"]["decision"])
                self.assertEqual("authentic_scoped_provider_receipt",
                                 final["gate"]["reason"])
                self.assertEqual("correctly_published",final["score"]["status"])
                self.assertEqual(1.0,final["score"]
                                 ["fraction_of_correct_business_value_published"])

    def test_unverified_or_forged_receipt_stays_pending(self):
        for c,events,case in self.cases:
            with self.subTest(domain=c["name"]):
                original=case["initial"]
                proposed,_=candidate_source(c,original,case["ticket"],
                                             case["candidate"])
                row=next(r for r in project_source(c,events)[case["candidate"]["table"]]
                         if r["row_id"]==case["candidate"]["row_id"])
                key=secrets.token_bytes(32)
                receipt=issue_simulated_receipt(c,row,key)
                tampered=deepcopy(receipt)
                tampered["payload"]["authentic_amount_cents"]+=1
                hold=publish_verified_correction(
                    c,original,proposed,case["candidate"],
                    receipt=tampered,verifier_key=key)
                self.assertEqual("partially_held",hold["status"])
                self.assertFalse(hold["recovered"])
                self.assertEqual("review_required",hold["receipt_gate"]["decision"])
                self.assertEqual(1,len(hold["held_groups"]))
                self.assertFalse(hold["proposed_mutation_admitted"])

    def test_missing_parent_fails_closed_not_falsely_localized(self):
        c,events,case=self.cases[0]
        source=deepcopy(case["initial"])
        proposal=case["candidate"]
        m=c["roles"]["movement"]
        d=c["roles"]["document"]
        transaction=next(r for r in source[m["table"]]
                         if r["row_id"]==proposal["row_id"])
        related=transaction[m["document_fk"]]
        source[d["table"]]=[r for r in source[d["table"]]
                            if r[d["id"]]!=related]
        mapping=resolve_dispute_lineage(c,source,proposal)
        self.assertTrue(mapping["global_hold"])
        self.assertEqual("document_ancestor_not_found",mapping["reason"])
        hold=publish_pending_dispute(c,source,proposal)
        self.assertEqual("withheld_all",hold["status"])
        self.assertEqual({},hold["published"])

    def test_unsupported_proposal_fails_closed(self):
        c,events,case=self.cases[0]
        proposal={"operation":"drop_entity_versions","table":"invoices","row_id":20050}
        mapping=resolve_dispute_lineage(c,case["initial"],proposal)
        self.assertTrue(mapping["global_hold"])
        self.assertEqual("unsupported_dispute_scope",mapping["reason"])

    def test_lineage_inference_never_consults_hidden_ledger(self):
        c,events,case=self.cases[1]
        a=resolve_dispute_lineage(c,case["initial"],case["candidate"])
        b=resolve_dispute_lineage(c,deepcopy(case["initial"]),case["candidate"])
        self.assertEqual(a,b)
        self.assertFalse(a["global_hold"])
        self.assertIsInstance(a["group"],tuple)
        self.assertEqual(2,len(a["group"]))


if __name__=="__main__":
    unittest.main()
