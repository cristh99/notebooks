from __future__ import annotations
import copy, json, tempfile, unittest
from pathlib import Path
import verify_attachment as v
E=json.loads((Path(__file__).resolve().parent/"LANE_E_EXACT_RECEIPT_ATTACHMENT_ENVELOPE.json").read_text())
class T(unittest.TestCase):
    def bad(self,f,msg):
        x=copy.deepcopy(E); f(x)
        with self.assertRaisesRegex(v.VerificationError,msg): v.validate(x)
    def test_01_baseline(self): v.validate(copy.deepcopy(E))
    def test_02_load(self): self.assertEqual(v.load(),E)
    def test_03_schema(self): self.bad(lambda x:x.__setitem__("schema","x"),"schema")
    def test_04_coord(self): self.bad(lambda x:x.__setitem__("coordination_id","x"),"coordination")
    def test_05_pr(self): self.bad(lambda x:x.__setitem__("lane_e_pr",144),"PR")
    def test_06_subject(self): self.bad(lambda x:x["bindings"].__setitem__("canonical_subject_sha256","0"*64),"binding")
    def test_07_receipt_file(self): self.bad(lambda x:x["bindings"].__setitem__("canonical_receipt_file_sha256","0"*64),"binding")
    def test_08_receipt_self(self): self.bad(lambda x:x["bindings"].__setitem__("canonical_receipt_self_hash_sha256","0"*64),"binding")
    def test_09_receipt_bytes(self): self.bad(lambda x:x["bindings"].__setitem__("canonical_receipt_bytes",1399),"binding")
    def test_10_run(self): self.bad(lambda x:x["prior_canonical_signature"].__setitem__("github_run_id",1),"prior run")
    def test_11_artifact(self): self.bad(lambda x:x["prior_canonical_signature"].__setitem__("artifact_sha256","0"*64),"artifact hash")
    def test_12_bundle(self): self.bad(lambda x:x["prior_canonical_signature"].__setitem__("sigstore_bundle_sha256","0"*64),"bundle hash")
    def test_13_workflow(self): self.bad(lambda x:x["prior_canonical_signature"].__setitem__("workflow_path","x"),"workflow path")
    def test_14_subject_missing(self): self.bad(lambda x:x["governance"].__setitem__("exact_canonical_subject_bytes_present",False),"subject bytes")
    def test_15_receipt_missing(self): self.bad(lambda x:x["governance"].__setitem__("exact_operational_receipt_bytes_present",False),"receipt bytes")
    def test_16_lane_m(self): self.bad(lambda x:x["governance"].__setitem__("independent_lane_m_signature_present",True),"Lane M")
    def test_17_stage08(self): self.bad(lambda x:x["governance"].__setitem__("stage08_unblocked",True),"governance boolean")
    def test_18_noncanonical(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"e.json"; p.write_text(json.dumps(E,indent=2)+"\n")
            with self.assertRaisesRegex(v.VerificationError,"canonical"): v.load(p)
if __name__=="__main__": unittest.main(verbosity=2)
