"""Cryptographic proof is not an LLM note or an independent full ledger leak."""
from copy import deepcopy
import json
from pathlib import Path
import secrets
import unittest

from dbt_chaos.contract_agent import candidate_source
from dbt_chaos.contract_review import make_review_cases
from dbt_chaos.contract_receipt import (
    FORMAT, demonstrate_receipt_gate,
    issue_simulated_receipt, verify_scoped_correction,
)
from dbt_chaos.process_contract import project_source, validate_contract


class SignedReceiptTests(unittest.TestCase):
    def setUp(self):
        self.contracts=[
            validate_contract(json.loads(Path("contracts/procurement.json").read_text())),
            validate_contract(json.loads(Path("contracts/grants.json").read_text())),
        ]

    def _case(self,c):
        events,cases=make_review_cases(c,20261119)
        case=cases[4]
        dirty=case["initial"]
        proposed,reason=candidate_source(c,dirty,case["ticket"],case["candidate"])
        self.assertEqual("source_cell_rewritten",reason)
        auth=project_source(c,events)
        row=next(r for r in auth[case["candidate"]["table"]]
                 if r["row_id"]==case["candidate"]["row_id"])
        key=secrets.token_bytes(32)
        receipt=issue_simulated_receipt(c,row,key)
        return events,case,dirty,proposed,key,receipt

    def test_one_exact_receipt_allows_real_repair_without_full_ledger(self):
        for c in self.contracts:
            events,case,dirty,proposed,key,receipt=self._case(c)
            accepted=verify_scoped_correction(
                c,dirty,proposed,case["candidate"],receipt,key)
            self.assertEqual("accepted",accepted["decision"])
            self.assertEqual("authentic_scoped_provider_receipt",accepted["reason"])
            self.assertTrue(accepted["applied"])
            self.assertNotIn("business_gold",json.dumps(receipt))
            self.assertEqual(FORMAT,receipt["payload"]["format"])
            result=demonstrate_receipt_gate(
                c,events,dirty,proposed,case["candidate"])
            self.assertEqual("accepted",result["gate"]["decision"])
            self.assertFalse(result["full_private_ledger_given_to_gate"])
            self.assertFalse(result["model_authored_evidence"])
            self.assertFalse(result["real_external_provider_connected"])
            self.assertFalse(result["signing_key_exported"])
            self.assertGreater(result["before"]["false_published_l1_cents"],0)
            self.assertEqual("correctly_published",result["after"]["status"])

    def test_forged_or_misbound_receipts_cannot_authorize_edit(self):
        for c in self.contracts:
            events,case,dirty,proposed,key,receipt=self._case(c)
            options=[]
            tampered=deepcopy(receipt)
            tampered["payload"]["authentic_amount_cents"]+=20
            options.append(tampered)
            tampered=deepcopy(receipt)
            tampered["payload"]["row_id"]+=1
            options.append(tampered)
            tampered=deepcopy(receipt)
            tampered["payload"]["contract"]="another_contract"
            options.append(tampered)
            tampered=deepcopy(receipt)
            tampered["hmac_sha256"]="0"*64
            options.append(tampered)
            for idx,bad in enumerate(options):
                with self.subTest(domain=c["name"],variant=idx):
                    decision=verify_scoped_correction(
                        c,dirty,proposed,case["candidate"],bad,key)
                    self.assertEqual("review_required",decision["decision"])
                    self.assertFalse(decision["applied"])
            wrong_key=secrets.token_bytes(32)
            self.assertEqual("receipt_signature_invalid",
                verify_scoped_correction(
                    c,dirty,proposed,case["candidate"],
                    receipt,wrong_key)["reason"])

    def test_no_scope_escalation_to_other_source_rows_or_fields(self):
        c=self.contracts[0]
        events,case,dirty,proposed,key,receipt=self._case(c)
        malicious=deepcopy(proposed)
        party_table=c["roles"]["party"]["table"]
        field=c["roles"]["party"]["dimension"]
        replacement=next(x for x in c["semantics"]["dimensions"]
                         if x!=malicious[party_table][0][field])
        malicious[party_table][0][field]=replacement
        self.assertEqual("proposal_changes_outside_scoped_receipt",
            verify_scoped_correction(
                c,dirty,malicious,case["candidate"],receipt,key)["reason"])
        action=deepcopy(case["candidate"])
        action["operation"]="drop_row"
        self.assertEqual("proposal_not_a_scoped_amount_edit",
            verify_scoped_correction(
                c,dirty,proposed,action,receipt,key)["reason"])

    def test_invalid_signer_key_is_not_a_witness(self):
        c=self.contracts[0]
        events,case,dirty,proposed,key,receipt=self._case(c)
        with self.assertRaisesRegex(ValueError,"256-bit"):
            issue_simulated_receipt(c,proposed[case["candidate"]["table"]][0],b"x")
        decision=verify_scoped_correction(
            c,dirty,proposed,case["candidate"],receipt,b"wrong")
        self.assertEqual("verifier_key_missing",decision["reason"])

    def test_receipt_is_issued_only_for_authoritative_financial_rows(self):
        c=self.contracts[0]
        events,case,dirty,proposed,key,receipt=self._case(c)
        malformed=deepcopy(receipt["payload"])
        malformed["authentic_amount_cents"]=-1
        raw=next(r for r in project_source(c,events)[c["roles"]["movement"]["table"]]
                 if r["row_id"]==receipt["payload"]["row_id"])
        bad=dict(raw)
        bad[c["roles"]["movement"]["amount"]]=-1
        with self.assertRaisesRegex(ValueError,"amount"):
            issue_simulated_receipt(c,bad,key)
        other=dict(raw)
        other["sql"]='DROP TABLE settlements'
        with self.assertRaisesRegex(ValueError,"complete"):
            issue_simulated_receipt(c,other,key)


if __name__=="__main__":
    unittest.main()
