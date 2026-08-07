from __future__ import annotations
import copy, json, tempfile, unittest
from pathlib import Path
import verify_canonical_subject as v

S=json.loads((Path(__file__).resolve().parent/"LANE_E_CANONICAL_SUBJECT.json").read_text())
class T(unittest.TestCase):
    def bad(self,f,msg):
        x=copy.deepcopy(S); f(x)
        with self.assertRaisesRegex(v.VerificationError,msg): v.validate(x)
    def test_01_baseline(self): v.validate(copy.deepcopy(S))
    def test_02_load(self): self.assertEqual(v.load(),S)
    def test_03_schema(self): self.bad(lambda x:x.__setitem__("schema","x"),"schema")
    def test_04_lane(self): self.bad(lambda x:x.__setitem__("lane","M"),"lane")
    def test_05_canonical_pr(self): self.bad(lambda x:x.__setitem__("canonical_pr",145),"lane/PR")
    def test_06_arbiter_pr(self): self.bad(lambda x:x.__setitem__("arbiter_pr",137),"lane/PR")
    def test_07_source_pr(self): self.bad(lambda x:x.__setitem__("source_lane_pr",141),"lane/PR")
    def test_08_events(self): self.bad(lambda x:x["event_ids"].reverse(),"event IDs")
    def test_09_receipt_file(self): self.bad(lambda x:x["receipt_binding"].__setitem__("canonical_receipt_file_sha256","0"*64),"receipt file")
    def test_10_receipt_self(self): self.bad(lambda x:x["receipt_binding"].__setitem__("canonical_receipt_self_hash_sha256","0"*64),"receipt self")
    def test_11_universe(self): self.bad(lambda x:x["receipt_binding"].__setitem__("event_universe_sha256","0"*64),"event universe")
    def test_12_review(self): self.bad(lambda x:x["receipt_binding"].__setitem__("review_item_commitment_sha256","0"*64),"review item")
    def test_13_buyer(self): self.bad(lambda x:x["identity_commitments"].__setitem__("buyer_commitment_sha256","0"*64),"identity")
    def test_14_supplier_id(self): self.bad(lambda x:x["identity_commitments"].__setitem__("supplier_identifier_commitment_sha256","0"*64),"identity")
    def test_15_supplier_name(self): self.bad(lambda x:x["identity_commitments"].__setitem__("supplier_name_commitment_sha256","0"*64),"identity")
    def test_16_identity_export(self): self.bad(lambda x:x["identity_commitments"].__setitem__("raw_identity_exported",True),"raw identity")
    def test_17_exact_check(self): self.bad(lambda x:x["identity_commitments"]["exact_checks"].__setitem__("supplier_identifier_exact",False),"exact checks")
    def test_18_source(self): self.bad(lambda x:x["source_commitments"].__setitem__("sefin_raw_artifact_sha256","0"*64),"source commitments")
    def test_19_method(self): self.bad(lambda x:x["operational_context"].__setitem__("procurement_method","direct"),"method")
    def test_20_bid_count(self): self.bad(lambda x:x["operational_context"].__setitem__("bid_count",0),"bid count")
    def test_21_sefin_doc(self): self.bad(lambda x:x["operational_context"].__setitem__("sefin_source_document_status","PRESENT"),"SEFIN")
    def test_22_relationship(self): self.bad(lambda x:x["semantic_guards"].__setitem__("relationship_state","MATCH_VALIDATED"),"relationship")
    def test_23_stage08(self): self.bad(lambda x:x["governance"].__setitem__("stage08_unblocked",True),"governance boolean")
    def test_24_cost(self): self.bad(lambda x:x["governance"].__setitem__("external_cost_usd",.01),"governance numeric")
    def test_25_sensitive_key(self): self.bad(lambda x:x["governance"].__setitem__("private"+"_key","x"),"credential-like")
    def test_26_noncanonical(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"s.json"; p.write_text(json.dumps(S,indent=2)+"\n")
            with self.assertRaisesRegex(v.VerificationError,"canonical"): v.load(p)
if __name__=="__main__": unittest.main(verbosity=2)
