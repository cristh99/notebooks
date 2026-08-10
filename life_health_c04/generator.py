#!/usr/bin/env python3
from __future__ import annotations
import csv, json, random
from pathlib import Path

def clamp(x, lo, hi): return min(hi, max(lo, x))

def oxygen_content_ml_L(hb_g_dL, saturation_fraction, po2_mmHg, binding=1.34, dissolved=0.003):
    if hb_g_dL < 0: raise ValueError("hb_g_dL must be nonnegative")
    if not 0 <= saturation_fraction <= 1: raise ValueError("saturation_fraction must be in [0,1]")
    if po2_mmHg < 0: raise ValueError("po2_mmHg must be nonnegative")
    return 10.0 * (binding * hb_g_dL * saturation_fraction + dissolved * po2_mmHg)

def fick_vo2_ml_min(q_L_min, ca_ml_L, cv_ml_L):
    if q_L_min < 0: raise ValueError("q_L_min must be nonnegative")
    return q_L_min * (ca_ml_L - cv_ml_L)

def sample_normal(rng, mean_sd, lo=None, hi=None):
    mean, sd = mean_sd
    value = rng.gauss(mean, sd)
    return clamp(value, -float("inf") if lo is None else lo, float("inf") if hi is None else hi) if (lo is not None or hi is not None) else value

def generate(config):
    # Synthetic test fixtures only; values are engineering test constants, not clinical reference ranges.
    fixtures = {
        "baseline": {"q": [5.0, 0.5], "hb": [14.0, 1.0], "sao2": [0.98, 0.004], "svo2": [0.75, 0.025], "pao2": [95, 5], "pvo2": [40, 4], "active_mass": [50, 6], "blood_volume": [5.0, 0.5]},
        "high_flow": {"q": [15.0, 2.0], "hb": [14.2, 1.0], "sao2": [0.97, 0.006], "svo2": [0.45, 0.035], "pao2": [92, 6], "pvo2": [30, 4], "active_mass": [50, 6], "blood_volume": [5.2, 0.5]},
        "low_binding_capacity": {"q": [6.5, 0.8], "hb": [9.5, 0.7], "sao2": [0.98, 0.005], "svo2": [0.62, 0.035], "pao2": [95, 5], "pvo2": [36, 4], "active_mass": [50, 6], "blood_volume": [5.0, 0.5]},
        "low_oxygen_partial_pressure": {"q": [6.0, 0.8], "hb": [16.0, 1.0], "sao2": [0.90, 0.015], "svo2": [0.60, 0.04], "pao2": [60, 6], "pvo2": [30, 4], "active_mass": [50, 6], "blood_volume": [5.1, 0.5]}
    }
    rng = random.Random(int(config["seed"])); rows=[]; idx=0
    for scenario, p in fixtures.items():
        for j in range(int(config["n_per_fixture"])):
            idx += 1; sex = "F" if j % 2 == 0 else "M"
            q=sample_normal(rng,p["q"],0.5,None); hb=sample_normal(rng,p["hb"],3.0,22.0)
            sao2=sample_normal(rng,p["sao2"],0.5,1.0); svo2=sample_normal(rng,p["svo2"],0.2,0.95)
            if svo2 > sao2-0.02: svo2=sao2-0.02
            pao2=sample_normal(rng,p["pao2"],15.0,150.0); pvo2=sample_normal(rng,p["pvo2"],10.0,80.0)
            active_mass=sample_normal(rng,p["active_mass"],20.0,90.0); blood_volume=sample_normal(rng,p["blood_volume"],2.0,8.0)
            ca=oxygen_content_ml_L(hb,sao2,pao2); cv=oxygen_content_ml_L(hb,svo2,pvo2)
            true_vo2=fick_vo2_ml_min(q,ca,cv); measured=true_vo2*(1+rng.gauss(0,float(config["measurement_noise_fraction_sd"])))
            rows.append({"subject_id":f"S{idx:04d}","scenario":scenario,"split":"train" if j<int(config["train_per_fixture"]) else "test","sex_observed":sex,
              "cardiac_output_L_min":round(q,6),"hb_g_dL":round(hb,6),"sao2_fraction":round(sao2,6),"svo2_fraction":round(svo2,6),"pao2_mmHg":round(pao2,6),"pvo2_mmHg":round(pvo2,6),
              "active_mass_kg":round(active_mass,6),"blood_volume_L":round(blood_volume,6),"true_caO2_ml_L":round(ca,6),"true_cvO2_ml_L":round(cv,6),"true_vo2_ml_min":round(true_vo2,6),"observed_vo2_ml_min":round(measured,6)})
    return rows

def main():
    import argparse
    ap=argparse.ArgumentParser(); ap.add_argument("--config",default="config.json"); ap.add_argument("--out",default="output/c04_synthetic.csv"); a=ap.parse_args()
    cfg=json.loads(Path(a.config).read_text()); rows=generate(cfg); out=Path(a.out); out.parent.mkdir(parents=True,exist_ok=True)
    with out.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator="\n"); w.writeheader(); w.writerows(rows)
    print(json.dumps({"rows":len(rows),"output":str(out),"schema":cfg["schema"]},sort_keys=True))
if __name__=="__main__": main()
