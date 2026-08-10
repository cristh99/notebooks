#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,hashlib,json,math,statistics
from pathlib import Path
from generator import oxygen_content_ml_L,fick_vo2_ml_min

def sha256(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for c in iter(lambda:f.read(1<<20),b""): h.update(c)
    return h.hexdigest()

def predict_fick(r):
    ca=oxygen_content_ml_L(float(r["hb_g_dL"]),float(r["sao2_fraction"]),float(r["pao2_mmHg"])); cv=oxygen_content_ml_L(float(r["hb_g_dL"]),float(r["svo2_fraction"]),float(r["pvo2_mmHg"]))
    return fick_vo2_ml_min(float(r["cardiac_output_L_min"]),ca,cv)

def metrics(y,p):
    e=[a-b for a,b in zip(y,p)]; return {"n":len(y),"mae":sum(abs(x) for x in e)/len(e),"rmse":math.sqrt(sum(x*x for x in e)/len(e)),"bias":sum(b-a for a,b in zip(y,p))/len(e)}

def slope(xs,ys):
    d=sum(x*x for x in xs); return sum(x*y for x,y in zip(xs,ys))/d if d else 0

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--data",default="output/c04_synthetic.csv"); ap.add_argument("--config",default="config.json"); ap.add_argument("--receipt",default="output/receipt.json"); a=ap.parse_args()
    rows=list(csv.DictReader(Path(a.data).open(encoding="utf-8"))); tr=[r for r in rows if r["split"]=="train"]; te=[r for r in rows if r["split"]=="test"]
    ytr=[float(r["observed_vo2_ml_min"]) for r in tr]; y=[float(r["observed_vo2_ml_min"]) for r in te]
    ftr=[predict_fick(r) for r in tr]; fte=[predict_fick(r) for r in te]; gb=statistics.mean(a-b for a,b in zip(ytr,ftr)); common=[p+gb for p in fte]
    beta=slope([float(r["active_mass_kg"]) for r in tr],ytr); size=[beta*float(r["active_mass_kg"]) for r in te]
    sb={s:statistics.mean(float(r["observed_vo2_ml_min"])-predict_fick(r) for r in tr if r["sex_observed"]==s) for s in ("F","M")}; sex=[predict_fick(r)+sb[r["sex_observed"]] for r in te]
    m={"common_fick":metrics(y,common),"size_only":metrics(y,size),"fick_plus_sex_residual":metrics(y,sex)}
    resid=[float(r["observed_vo2_ml_min"])-predict_fick(r)-gb for r in tr]; sd=statistics.stdev(resid); m["common_fick"]["calibration_ratio_mean_pred_over_obs"]=statistics.mean(common)/statistics.mean(y); m["common_fick"]["train_residual_sd"]=sd; m["common_fick"]["test_95pct_residual_coverage"]=sum(abs(a-b)<=1.96*sd for a,b in zip(y,common))/len(y)
    base=[predict_fick(r) for r in te]
    def pert(r,qm=1,hm=1): rr=dict(r); rr["cardiac_output_L_min"]=str(float(rr["cardiac_output_L_min"])*qm); rr["hb_g_dL"]=str(float(rr["hb_g_dL"])*hm); return predict_fick(rr)
    sens={name:statistics.mean((pert(r,qm,hm)-b)/b for r,b in zip(te,base)) for name,qm,hm in [("Q_plus5",1.05,1),("Q_minus5",0.95,1),("Hb_plus5",1,1.05),("Hb_minus5",1,0.95)]}
    rec={"schema":"C04_RECEIPT_v1","rows":len(rows),"train_rows":len(tr),"test_rows":len(te),"scenarios":sorted({r["scenario"] for r in rows}),"models":m,"sex_residual_bias_ml_min":sb,"size_only_beta_ml_min_per_kg":beta,"sensitivity_fractional_mean":sens,"data_sha256":sha256(a.data),"config_sha256":sha256(a.config),"limits":{"synthetic_only":True,"clinical_use":False,"causal_claim":False,"external_validation":False,"sex_category_not_causal":True}}
    out=Path(a.receipt); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(rec,sort_keys=True,indent=2)+"\n"); print(json.dumps(rec,sort_keys=True))
if __name__=="__main__": main()
