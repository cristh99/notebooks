from __future__ import annotations
from collections import Counter
from pathlib import Path
import hashlib,json
from .engine import canonical,digest,evaluate
from .fixtures import matrix
ROOT=Path(__file__).resolve().parents[1]; REPORTS=ROOT/"reports"
def load(p): return json.loads(Path(p).read_text())
def file_sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,v): Path(p).write_text(json.dumps(v,sort_keys=True,indent=2)+"\n")
def run():
    contract=load(ROOT/"contract.json"); rows=[]
    for s in matrix(contract):
        decision=evaluate(s); expected=contract["expected_terminal"][s["archetype"]]
        rows.append({"scenario_id":s["scenario_id"],"domain":s["domain"],"archetype":s["archetype"],"terminal":decision["terminal"],"pass":decision["terminal"]==expected,"decision":decision})
    rows.sort(key=lambda r:r["scenario_id"]); counts=dict(sorted(Counter(r["terminal"] for r in rows).items()))
    summary={"schema":"byzantine-open-world-power-v1/public-summary/1","status":"PASS" if all(r["pass"] for r in rows) else "FAIL","scenario_count":len(rows),"pass_count":sum(r["pass"] for r in rows),"terminal_counts":counts,"claim_boundary":contract["claim_boundary"]}
    source_names=["contract.json","byzantine_open_world_power_v1/engine.py","byzantine_open_world_power_v1/fixtures.py","byzantine_open_world_power_v1/replay.py","byzantine_open_world_power_v1/verify.py","byzantine_open_world_power_v1/verify.js","tests/test_replay.py"]
    payload={"schema":"byzantine-open-world-power-v1/public-receipt-payload/1","contract_sha256":file_sha(ROOT/"contract.json"),"rows_sha256":digest(rows),"summary_sha256":digest(summary),"source_sha256":{n:file_sha(ROOT/n) for n in source_names},"expected_terminal_counts":contract["expected_terminal_counts"]}
    receipt={"schema":"byzantine-open-world-power-v1/public-receipt/1","payload":payload,"sha256":digest(payload)}
    REPORTS.mkdir(exist_ok=True); write(REPORTS/"rows.json",rows); write(REPORTS/"summary.json",summary); write(REPORTS/"receipt.json",receipt)
    if summary["status"]!="PASS" or counts!=contract["expected_terminal_counts"]: raise SystemExit("FAIL")
    print(json.dumps({"status":"PASS","scenarios":len(rows),"receipt_sha256":receipt["sha256"]},sort_keys=True)); return receipt
if __name__=="__main__": run()
