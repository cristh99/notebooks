from __future__ import annotations
import argparse, hashlib, json, re
from pathlib import Path
HERE=Path(__file__).resolve().parent
ENVELOPE=HERE/"LANE_E_EXACT_RECEIPT_ATTACHMENT_ENVELOPE.json"
EXPECTED_SHA="0962b0fc14c2e96542192f33b2fe87f4370130ac559c7a5dc12af5e22b77f2c3"
SHA=re.compile(r"^[0-9a-f]{64}$")
class VerificationError(ValueError): pass
def req(x,m):
    if not x: raise VerificationError(m)
def canon(x): return (json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode()
def validate(e):
    req(e.get("schema")=="data-science-pipeline/lane-e-exact-receipt-attachment-envelope/1","schema mismatch")
    req(e.get("coordination_id")=="COORD-2026-08-06-PARALLEL-V2","coordination mismatch")
    req((e.get("canonical_pr"),e.get("lane_e_pr"))==(144,145),"PR mismatch")
    b=e.get("bindings",{})
    expected={"canonical_subject_sha256":"53b5112447a795fb7a902976cd9854c9ca2c6c46be16d05684e1975ed6b8f6b6","canonical_receipt_file_sha256":"b5b8f70ebc278b65816b78e0065ad7827f39902b13d271c7f101a65daf8b8883","canonical_receipt_self_hash_sha256":"c002dc08d8536b9ba2109543a668d46d30397da7fe0968e7f850087d42c55f5b","canonical_receipt_bytes":1398,"event_universe_sha256":"e53c65bd2c78979809f98051c25dd3f6239f7a4c5966578a30fcd8ecab1db88f","review_item_commitment_sha256":"39bd1c485c703ef371c2b57a68987f5781697197cc422c14aaa686bd9cc06f2d"}
    req(b==expected,"binding mismatch")
    p=e.get("prior_canonical_signature",{})
    req(p.get("github_run_id")==31139455920,"prior run mismatch")
    req(p.get("github_sha")=="96787111628e6c38ac0262a8a988a17f291a6f28","prior SHA mismatch")
    req(p.get("artifact_id")==8979257517,"artifact ID mismatch")
    for k in ("artifact_sha256","external_receipt_sha256","sigstore_bundle_sha256","cosign_verify_log_sha256","local_receipt_sha256"):
        req(bool(SHA.fullmatch(str(p.get(k,"")))),f"{k} invalid")
    req(p.get("artifact_sha256")=="e16252c0be9e3a854daa764e960011081c876659afe495be4bc6d64856c03e98","artifact hash mismatch")
    req(p.get("external_receipt_sha256")=="e4085c2daf1e431f2a6c7327af6421939bf3207c9fd7a08687fc14a18437fe21","external receipt hash mismatch")
    req(p.get("sigstore_bundle_sha256")=="324456fa4ce224e9bf7b77d475f89174a5a24a0b0ef32d323d7e27b4f2539753","bundle hash mismatch")
    req(p.get("cosign_verify_log_sha256")=="80a53f76c7ed6969dade3b6ee47cdb753162db7c00be625448999d08bae77ed8","verify hash mismatch")
    req(p.get("local_receipt_sha256")=="cbdb1087472e99777d6b11eecae40941c1734b108368bbde02bb51234434539e","local receipt hash mismatch")
    req(p.get("workflow_path")==".github/workflows/data-science-v17-lane-e-canonical-oidc.yml","workflow path mismatch")
    req(p.get("oidc_issuer")=="https://token.actions.githubusercontent.com" and p.get("event")=="push","OIDC contract mismatch")
    g=e.get("governance",{})
    req(g.get("exact_canonical_subject_bytes_present") is True,"subject bytes missing")
    req(g.get("exact_operational_receipt_bytes_present") is True,"receipt bytes missing")
    req(g.get("independent_lane_e_signature_present") is True,"Lane E signature missing")
    req(g.get("independent_lane_m_signature_present") is False,"Lane M must remain absent")
    req(g.get("external_cost_usd")==0.0 and g.get("scientific_promotion_credit")==0,"governance numeric mismatch")
    req(g.get("production_modified") is False and g.get("stage08_unblocked") is False,"governance boolean mismatch")
    c=e.get("claim_boundary",{})
    req(len(c.get("establishes_after_external_pass",[]))==4 and len(c.get("does_not_establish",[]))==8,"claim boundary mismatch")
def load(path=ENVELOPE):
    raw=path.read_bytes(); e=json.loads(raw)
    req(raw==canon(e),"envelope is not canonical JSON")
    req(hashlib.sha256(raw).hexdigest()==EXPECTED_SHA,"envelope SHA-256 mismatch")
    validate(e); return e
def receipt(e):
    return {"schema":"data-science-pipeline/lane-e-exact-receipt-attachment-local-receipt/1","verdict":"PASS_LANE_E_EXACT_RECEIPT_ATTACHMENT_SOFTWARE_ONLY","envelope_sha256":EXPECTED_SHA,"tests_expected":18,"canonical_subject_sha256":e["bindings"]["canonical_subject_sha256"],"canonical_receipt_file_sha256":e["bindings"]["canonical_receipt_file_sha256"],"canonical_receipt_self_hash_sha256":e["bindings"]["canonical_receipt_self_hash_sha256"],"prior_artifact_sha256":e["prior_canonical_signature"]["artifact_sha256"],"exact_operational_receipt_bytes_present":True,"prior_signature_independently_reverified":False,"external_cost_usd":0.0,"production_modified":False,"scientific_promotion_credit":0,"stage08_unblocked":False}
if __name__=="__main__":
    p=argparse.ArgumentParser(); p.add_argument("--output",type=Path,required=True); a=p.parse_args()
    r=receipt(load()); a.output.write_bytes(canon(r)); print(json.dumps(r,sort_keys=True))
