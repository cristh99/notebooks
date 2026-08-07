from __future__ import annotations
import argparse, hashlib, json, re
from pathlib import Path

HERE=Path(__file__).resolve().parent
SUBJECT=HERE/"LANE_E_CANONICAL_SUBJECT.json"
EXPECTED_SHA="53b5112447a795fb7a902976cd9854c9ca2c6c46be16d05684e1975ed6b8f6b6"
SHA=re.compile(r"^[0-9a-f]{64}$")
SECRET=re.compile(r"(^|[_-])(secret|password|private[_-]?key|credential|api[_-]?key|access[_-]?token|auth[_-]?token)($|[_-])",re.I)
EVENTS=["lane-v17:contract:e49e3465608c7c4d86ed75f7fdbcdb4de0e0b06edb7d5700609b555dc4122053","lane-v17:payment:355f019de733e170c264b707778f850785572e36f8cd836b745f002ca5662eb3"]
SOURCE={"inspector_receipt_sha256":"7b18e89390fa93850155af058c5a951a1cfc395de0083f01d87e73f83385322e","oncae_compiled_release_sha256":"4e1b0aa5e69a065932273f187540bcef48fa01698750680d63358e039f693219","oncae_raw_artifact_sha256":"b31907dfa36e307136684d8fcd7849d4aa0d76181c4c79bdd1822151a50231e3","oncae_source_record_sha256":"6815273455df3694955fe2804cfb26831df40b064f89c9ba252a4f4ed330ef30","sefin_raw_artifact_sha256":"cbc4083d4b27c637f6d1daf21a0971450d0b4cb65309ba3d161ac59e58003405","sefin_source_record_sha256":"153aefc7095cee5d5225d3d81ae775d2daf3ec554b6e56a7b69cd9b890bc0eb4"}
IDENTITY={"buyer_commitment_sha256":"a1c010fa05e81556ca632334c045e395d9d841028a760e77cce659bc90afc40c","supplier_identifier_commitment_sha256":"4eec1bd6d600de3dd2bf9d04296e55669f3583e0bc79faf803009853b5072928","supplier_name_commitment_sha256":"138fce928095cfa3afcdc2f05eb3f26aedfe0cbf0d71e4ef18a699c68f82a2f9"}

class VerificationError(ValueError): pass
def req(x,m):
    if not x: raise VerificationError(m)
def canon(x): return (json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode()
def walk(x,p="$"):
    if isinstance(x,dict):
        for k,v in x.items():
            req(not SECRET.search(str(k)),f"credential-like key at {p}.{k}"); walk(v,f"{p}.{k}")
    elif isinstance(x,list):
        for i,v in enumerate(x): walk(v,f"{p}[{i}]")

def validate(s):
    walk(s)
    req(s.get("schema")=="data-science-pipeline/lane-e-independent-signature-subject/1","schema mismatch")
    req(s.get("coordination_id")=="COORD-2026-08-06-PARALLEL-V2","coordination mismatch")
    req((s.get("lane"),s.get("canonical_pr"),s.get("arbiter_pr"),s.get("source_lane_pr"))==("E",144,138,140),"lane/PR mismatch")
    req(s.get("event_ids")==EVENTS,"event IDs mismatch")
    r=s.get("receipt_binding",{})
    req(r.get("canonical_receipt_file_sha256")=="b5b8f70ebc278b65816b78e0065ad7827f39902b13d271c7f101a65daf8b8883","receipt file mismatch")
    req(r.get("canonical_receipt_self_hash_sha256")=="c002dc08d8536b9ba2109543a668d46d30397da7fe0968e7f850087d42c55f5b","receipt self mismatch")
    req(r.get("event_universe_sha256")=="e53c65bd2c78979809f98051c25dd3f6239f7a4c5966578a30fcd8ecab1db88f","event universe mismatch")
    req(r.get("review_item_commitment_sha256")=="39bd1c485c703ef371c2b57a68987f5781697197cc422c14aaa686bd9cc06f2d","review item mismatch")
    i=s.get("identity_commitments",{})
    req(all(i.get(k)==v for k,v in IDENTITY.items()),"identity commitment mismatch")
    req(i.get("raw_identity_exported") is False,"raw identity export forbidden")
    req(len(i.get("exact_checks",{}))==4 and all(v is True for v in i["exact_checks"].values()),"exact checks mismatch")
    req(s.get("source_commitments")==SOURCE and all(SHA.fullmatch(v) for v in SOURCE.values()),"source commitments mismatch")
    o=s.get("operational_context",{})
    req((o.get("procurement_method"),o.get("procurement_method_details"))==("open","Convenio Marco"),"method mismatch")
    req(o.get("bid_count") is None and o.get("bid_count_status")=="ABSTAIN_MISSING_EXPLICIT_FIELD","bid count mismatch")
    req(o.get("sefin_source_document_status")=="ABSTAIN_MISSING_EXPLICIT_DOCUMENT_REF","SEFIN document mismatch")
    g=s.get("semantic_guards",{})
    req(g.get("relationship_state")=="CANDIDATE_REVIEW","relationship state mismatch")
    req(all(g.get(k) is False for k in ("canonical_promotion","cross_source_relationship_asserted","identity_inference_beyond_exact_checks")),"semantic guard mismatch")
    gov=s.get("governance",{})
    req(gov.get("external_cost_usd")==0.0 and gov.get("scientific_promotion_credit")==0,"governance numeric mismatch")
    req(all(gov.get(k) is False for k in ("mass_processing_authorized","merge_authorized","production_modified","stage08_unblocked")),"governance boolean mismatch")
    b=s.get("claim_boundary",{})
    req(len(b.get("establishes_after_valid_signature",[]))==5 and len(b.get("does_not_establish",[]))==9,"claim boundary mismatch")
    req(all(x in b["does_not_establish"] for x in ("Stage 08 readiness","explicit bid count","SEFIN source document existence")),"claim exclusions missing")

def load(path=SUBJECT):
    raw=path.read_bytes(); s=json.loads(raw)
    req(raw==canon(s),"subject is not canonical JSON")
    req(hashlib.sha256(raw).hexdigest()==EXPECTED_SHA,"subject SHA-256 mismatch")
    validate(s); return s

def receipt(s):
    return {"schema":"data-science-pipeline/lane-e-canonical-subject-local-receipt/1","verdict":"PASS_LANE_E_CANONICAL_SUBJECT_SOFTWARE_ONLY","subject_sha256":EXPECTED_SHA,"tests_expected":26,"event_universe_sha256":s["receipt_binding"]["event_universe_sha256"],"lane_e_receipt_file_sha256":s["receipt_binding"]["canonical_receipt_file_sha256"],"lane_e_receipt_self_hash_sha256":s["receipt_binding"]["canonical_receipt_self_hash_sha256"],"review_item_commitment_sha256":s["receipt_binding"]["review_item_commitment_sha256"],"procurement_method":s["operational_context"]["procurement_method"],"procurement_method_details":s["operational_context"]["procurement_method_details"],"bid_count_status":s["operational_context"]["bid_count_status"],"sefin_source_document_status":s["operational_context"]["sefin_source_document_status"],"relationship_state":s["semantic_guards"]["relationship_state"],"exact_operational_receipt_bytes_present":False,"independent_signature_created":False,"external_cost_usd":0.0,"production_modified":False,"scientific_promotion_credit":0,"stage08_unblocked":False,"next_gate":"github_oidc_sigstore_signature_then_exact_operational_receipt_byte_attachment"}

if __name__=="__main__":
    p=argparse.ArgumentParser(); p.add_argument("--output",type=Path,required=True); a=p.parse_args()
    r=receipt(load()); a.output.write_bytes(canon(r)); print(json.dumps(r,sort_keys=True))
