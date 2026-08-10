#!/usr/bin/env python3
import json,subprocess,sys,tempfile
from pathlib import Path
from generator import oxygen_content_ml_L,fick_vo2_ml_min,generate
ROOT=Path(__file__).resolve().parent; CFG=json.loads((ROOT/'config.json').read_text())
def test_units():
    ca=oxygen_content_ml_L(15,.98,95); assert ca>0; assert fick_vo2_ml_min(5,ca,ca)==0
def test_invalid():
    for a in [(-1,.98,95),(15,1.1,95),(15,.98,-1)]:
        try: oxygen_content_ml_L(*a)
        except ValueError: pass
        else: raise AssertionError(a)
def test_repro():
    a=generate(CFG); b=generate(CFG); assert a==b and len(a)==256 and sum(r['split']=='test' for r in a)==64
def test_scenarios():
    rows=generate(CFG); by={}
    for r in rows: by.setdefault(r['scenario'],[]).append(r['true_vo2_ml_min'])
    m={k:sum(v)/len(v) for k,v in by.items()}; assert m['high_flow']>m['baseline']; assert all(x>0 for x in m.values())
def test_runner():
    with tempfile.TemporaryDirectory() as td:
        d=Path(td)/'d.csv'; r=Path(td)/'r.json'; subprocess.check_call([sys.executable,str(ROOT/'generator.py'),'--config',str(ROOT/'config.json'),'--out',str(d)]); subprocess.check_call([sys.executable,str(ROOT/'run.py'),'--config',str(ROOT/'config.json'),'--data',str(d),'--receipt',str(r)]); x=json.loads(r.read_text()); assert x['rows']==256 and x['test_rows']==64 and x['limits']['synthetic_only']; assert x['models']['common_fick']['rmse']<x['models']['size_only']['rmse']
def main():
    ts=[test_units,test_invalid,test_repro,test_scenarios,test_runner]
    for t in ts:t()
    print(json.dumps({'status':'PASS','tests':len(ts)},sort_keys=True))
if __name__=='__main__':main()
