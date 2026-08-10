#!/usr/bin/env node
import fs from 'fs';
const text=fs.readFileSync(process.argv[2] ?? 'output/c04_synthetic.csv','utf8').trimEnd(); const lines=text.split(/\r?\n/); const h=lines[0].split(','); let maxAbs=0,n=0;
for(const line of lines.slice(1)){const v=line.split(','); const r=Object.fromEntries(h.map((x,i)=>[x,v[i]])); const hb=+r.hb_g_dL,sao=+r.sao2_fraction,svo=+r.svo2_fraction,pa=+r.pao2_mmHg,pv=+r.pvo2_mmHg,q=+r.cardiac_output_L_min; const ca=10*(1.34*hb*sao+0.003*pa),cv=10*(1.34*hb*svo+0.003*pv); const pred=q*(ca-cv),truth=+r.true_vo2_ml_min; maxAbs=Math.max(maxAbs,Math.abs(pred-truth)); n++;}
const tolerance=0.005; if(maxAbs>tolerance){console.error(JSON.stringify({status:'FAIL',n,max_abs_diff:maxAbs,tolerance}));process.exit(2);} console.log(JSON.stringify({status:'PASS',n,max_abs_diff:maxAbs,tolerance,independence:'Node.js formula reimplementation; same serialized synthetic CSV; no Python imports'}));
