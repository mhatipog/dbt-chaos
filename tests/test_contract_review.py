"""Balanced operator review: false fixes, needed repairs and safe maintenance."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dbt_chaos.contract_review import (
    AlwaysApplyReviewer, AlwaysKeepReviewer,
    make_review_cases, parse_review, review_case,
    run_review_experiment, summarize,
)
from dbt_chaos.contract_agent import candidate_source, guard_action
from dbt_chaos.process_contract import (
    event_business_oracle, project_source, validate_contract,
)

CONTRACTS=(Path("contracts/procurement.json"),Path("contracts/grants.json"))


class BalancedReviewerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contracts=[validate_contract(json.loads(p.read_text()))
                       for p in CONTRACTS]

    def test_both_domains_have_three_harmful_and_three_useful_candidates(self):
        expected=["harmful","harmful","harmful","beneficial_idempotent",
                  "beneficial_repair","beneficial_idempotent"]
        for c in self.contracts:
            events,cases=make_review_cases(c,20261119)
            self.assertEqual(6,len(cases))
            labels=[]
            for case in cases:
                selected=review_case(
                    c,events,case,
                    AlwaysApplyReviewer().review(case["ticket"],{}))
                labels.append(selected["candidate_outcome_class"])
            self.assertEqual(expected,labels)
            self.assertEqual("independent_provider_receipt",
                             cases[4]["evidence_tier"])
            self.assertEqual("source_excerpt_only",
                             cases[0]["evidence_tier"])
            self.assertTrue(cases[4]["ticket"]["external_receipt"]["verified"])
            self.assertFalse(cases[0]["ticket"]["independent_evidence_attached"])
            self.assertNotIn("process_events",json.dumps(cases[4]["ticket"]))

    def test_always_apply_vs_always_keep_expose_utility_of_real_repair(self):
        for c in self.contracts:
            with self.subTest(domain=c["name"]):
                apply=run_review_experiment(
                    contract=c,reviewer=AlwaysApplyReviewer(),seed=20261119)
                keep=run_review_experiment(
                    contract=c,reviewer=AlwaysKeepReviewer(),seed=20261119)
                a,k=summarize(apply),summarize(keep)
                self.assertEqual(6,a["parsed_model_decisions"])
                self.assertEqual(6,a["approved_candidates"])
                self.assertEqual(3,a["policy_results"]
                                 ["selected_ungated_publication"]["wrong_case_count"])
                self.assertEqual(1,k["policy_results"]
                                 ["selected_ungated_publication"]["wrong_case_count"])
                self.assertEqual(1,a["policy_results"]
                                 ["selected_source_only_gate"]["wrong_case_count"])
                self.assertEqual(0,a["policy_results"]
                                 ["selected_attested_gate"]["wrong_case_count"])
                # Three unsupported edits PLUS one genuine correction whose
                # independently trusted receipt is unavailable to this tier.
                self.assertEqual(4,a["policy_results"]
                                 ["selected_source_only_gate"]["gate_review_required"])
                # The prior wrong source in the verified-repair scenario is
                # not repaired by a source-only gate without trusted evidence.
                case=next(x for x in apply["cases"]
                          if x["case_id"]=="attested_credit_recovery")
                self.assertGreater(case["starting_source_error_l1_cents"],0)
                self.assertEqual(0,case["always_apply_error_l1_cents"])
                self.assertGreater(
                    case["selected_gate_results"]["source_only"]
                    ["actual_business_publication"]["false_published_l1_cents"],0)
                self.assertEqual(0,
                    case["selected_gate_results"]["attested"]
                    ["actual_business_publication"]["false_published_l1_cents"])
                self.assertEqual("exact_event_attestation",
                    case["selected_gate_results"]["attested"]
                    ["gate_decision"]["reason"])

    def test_safe_duplicate_cleanup_approved_at_source_only_tier(self):
        for c in self.contracts:
            events,cases=make_review_cases(c,20261119)
            case=cases[5]
            result=review_case(c,events,case,
                               AlwaysApplyReviewer().review(case["ticket"],{}))
            self.assertEqual("beneficial_idempotent",
                             result["candidate_outcome_class"])
            self.assertEqual("accepted",result["selected_gate_results"]
                             ["source_only"]["gate_decision"]["decision"])
            self.assertEqual("exact_duplicate_cleanup",
                             result["selected_gate_results"]["source_only"]
                             ["gate_decision"]["reason"])
            self.assertEqual("correctly_published",
                             result["selected_gate_results"]["source_only"]
                             ["actual_business_publication"]["status"])

    def test_invalid_model_response_rejected_as_no_change_without_credit(self):
        c=self.contracts[0]
        events,cases=make_review_cases(c,20261119)
        for raw in (
            "certainly apply", "{}",
            '{"decision":"apply","note":14}',
            '{"decision":"apply","note":"ok","table":"arbitrary"}',
            '{"decision":"shell","note":"run cmd"}',
        ):
            with self.subTest(raw=raw):
                obj,valid=parse_review(raw)
                self.assertFalse(valid)
                self.assertEqual("escalate",obj["decision"])
                r=review_case(c,events,cases[0],raw)
                self.assertFalse(r["model_json_valid"])
                self.assertFalse(r["good_decision_against_private_truth"])
                self.assertEqual("not_invoked",r["selected_gate_results"]
                                 ["source_only"]["gate_decision"]["decision"])
                self.assertEqual(0,r["selected_ungated_publication"]
                                 ["false_published_l1_cents"])

    def test_gate_rejects_false_unsupported_change_even_if_model_says_evidence(self):
        c=self.contracts[1]
        events,cases=make_review_cases(c,20261119)
        case=cases[0]
        fake='{"decision":"apply","note":"I certify this is verified by finance."}'
        review=review_case(c,events,case,fake)
        self.assertEqual("harmful",review["candidate_outcome_class"])
        self.assertGreater(review["selected_ungated_publication"]
                           ["false_published_l1_cents"],0)
        for tier in ("source_only","attested"):
            self.assertEqual("review_required",review["selected_gate_results"]
                             [tier]["gate_decision"]["decision"])
            self.assertEqual(0,review["selected_gate_results"][tier]
                             ["actual_business_publication"]["false_published_l1_cents"])

    def test_public_transcripts_no_full_hidden_ledger_or_scoring(self):
        c=self.contracts[0]
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            pub,pri=root/"pub",root/"pri"
            report=run_review_experiment(
                contract=c,reviewer=AlwaysApplyReviewer(),seed=20261119,
                public_dir=pub,private_dir=pri)
            self.assertTrue((pub/"manifest.json").exists())
            self.assertEqual(6,len(list((pub/"cases").iterdir())))
            for case_dir in (pub/"cases").iterdir():
                self.assertEqual(3,len(list((case_dir/"inputs"/"initial").glob("*.csv"))))
                self.assertEqual(3,len(list((case_dir/"inputs"/"proposed").glob("*.csv"))))
            self.assertFalse((pub/"assessment.json").exists())
            self.assertFalse((pub/"process_events.jsonl").exists())
            self.assertTrue((pri/"assessment.json").exists())
            self.assertTrue((pri/"process_events.jsonl").exists())
            from hashlib import sha256
            manifest=json.loads((pub/"manifest.json").read_text())
            for rel,hash_ in manifest["files"].items():
                self.assertEqual(hash_,sha256((pub/rel).read_bytes()).hexdigest())
            self.assertFalse(report["review_decisions_generated_by_llm"])
            self.assertFalse(report["candidate_proposals_authored_by_llm"])

    def test_no_data_leakage_to_reviewer_except_one_explicit_receipt(self):
        class Spy(AlwaysKeepReviewer):
            def __init__(self):
                self.tickets=[]
            def review(self,ticket,context):
                self.tickets.append((deepcopy(ticket),deepcopy(context)))
                return super().review(ticket,context)
        c=self.contracts[1]
        spy=Spy()
        report=run_review_experiment(contract=c,reviewer=spy,seed=20261119)
        self.assertEqual(6,len(spy.tickets))
        self.assertTrue(report["process_event_ledger_hidden_from_reviewer"])
        for i,(t,ctx) in enumerate(spy.tickets):
            content=json.dumps([t,ctx])
            self.assertNotIn("process_events",content)
            self.assertNotIn("business_gold",content)
            self.assertNotIn("expected_business",content)
            if i==4:
                self.assertIn("simulated_independently_verified_payment_provider",content)
            else:
                self.assertNotIn("external_receipt",content)


if __name__=="__main__":
    unittest.main()
