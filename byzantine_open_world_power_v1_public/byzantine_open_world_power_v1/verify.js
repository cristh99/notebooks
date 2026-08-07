#!/usr/bin/env node
const fs=require('fs'),path=require('path'),crypto=require('crypto');
const R=path.resolve(__dirname,'..'), P=path.join(R,'reports');
const read=p=>JSON.parse(fs.readFileSync(p,'utf8'));
const canon=v=>Array.isArray(v)?`[${v.map(canon).join(',')}]`:v&&typeof v==='object'?`{${Object.keys(v).sort().map(k=>`${JSON.stringify(k)}:${canon(v[k])}`).join(',')}}`:JSON.stringify(v);
const dig=v=>crypto.createHash('sha256').update(canon(v)).digest('hex');
const fsha=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
function req(x,m){if(!x)throw Error(m)}
try{
 const c=read(path.join(R,'contract.json')), rows=read(path.join(P,'rows.json')), s=read(path.join(P,'summary.json')), rec=read(path.join(P,'receipt.json'));
 req(rec.schema==='byzantine-open-world-power-v1/public-receipt/1','receipt schema');
 req(dig(rec.payload)===rec.sha256,'receipt self-hash'); req(rows.length===c.scenario_count&&rows.length===72,'row count'); req(rows.every(r=>r.pass===true),'row pass');
 req(s.status==='PASS'&&s.scenario_count===72&&s.pass_count===72,'summary'); req(dig(rows)===rec.payload.rows_sha256,'rows hash'); req(dig(s)===rec.payload.summary_sha256,'summary hash');
 req(fsha(path.join(R,'contract.json'))===rec.payload.contract_sha256,'contract hash');
 for(const [n,h] of Object.entries(rec.payload.source_sha256)) req(fsha(path.join(R,n))===h,`source ${n}`);
 const expectedIds=new Set(c.domains.flatMap(d=>c.archetypes.map(a=>`${d}::${a}`))), ids=new Set();
 const counts={};
 for(const r of rows){
   req(!ids.has(r.scenario_id),'duplicate'); ids.add(r.scenario_id); counts[r.terminal]=(counts[r.terminal]||0)+1;
   req(r.terminal===c.expected_terminal[r.archetype],`terminal ${r.scenario_id}`); req(r.decision.terminal===r.terminal,`decision terminal ${r.scenario_id}`);
   const d={...r.decision}; delete d.sha256; req(dig(d)===r.decision.sha256,`decision hash ${r.scenario_id}`);
 }
 req(ids.size===expectedIds.size&&[...expectedIds].every(id=>ids.has(id)),'scenario matrix completeness');
 const ordered=Object.fromEntries(Object.entries(counts).sort(([a],[b])=>a.localeCompare(b)));
 req(canon(ordered)===canon(c.expected_terminal_counts),'row terminal counts'); req(canon(s.terminal_counts)===canon(ordered),'summary terminal counts'); req(canon(rec.payload.expected_terminal_counts)===canon(ordered),'receipt terminal counts');
 console.log(JSON.stringify({status:'PASS',receipt_sha256:rec.sha256,scenarios:rows.length}));
}catch(e){console.error(`REJECTED: ${e.message}`);process.exit(2)}
