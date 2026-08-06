from __future__ import annotations
from collections import defaultdict
import hashlib, json

TERMINALS={"ACCEPTED","QUARANTINED","BLOCKED_INSUFFICIENT_ROOTS","IMPOSSIBLE_UNDER_FAULT_MODEL","REVOKED_RECOMPUTED","ABSTAIN"}

def canonical(v): return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False)
def digest(v): return hashlib.sha256(canonical(v).encode()).hexdigest()
def envelope(n,f,q): return n>=3*f+1 and q>=2*f+1 and q<=n and 2*q>n+f

def matching(observations):
    edges=defaultdict(set)
    for o in observations: edges[o["root"]].add(o["dep"])
    paired={}
    def augment(root,seen):
        for dep in sorted(edges[root]):
            if dep in seen: continue
            seen.add(dep)
            if dep not in paired or augment(paired[dep],seen):
                paired[dep]=root; return True
        return False
    return sum(augment(root,set()) for root in sorted(edges))

def choose_candidate(candidates,seen_roots,seen_deps,bad_roots):
    ranked=[]
    for c in candidates:
        score=0.0 if c["root"] in seen_roots|bad_roots or c["dep"] in seen_deps else c["gain"]*c["reliability"]*(1-c["exposure"])/c["cost"]
        ranked.append((score,c["id"]))
    ranked.sort(key=lambda x:(-x[0],x[1]))
    return ranked[0][1] if ranked and ranked[0][0]>0 else None

def _lineage_bad(observations):
    by_id={o["id"]:o for o in observations}; bad=set()
    for o in observations:
        stack=[]; cur=o
        while cur.get("lineage"):
            parent=cur["lineage"]
            if parent not in by_id or parent in stack: bad.add(o["id"]); break
            stack.append(parent); cur=by_id[parent]
    changed=True
    while changed:
        changed=False
        for o in observations:
            if o.get("poisoned") or o.get("revoked") or o.get("lineage") in bad:
                if o["id"] not in bad: bad.add(o["id"]); changed=True
    return bad

def evaluate(s):
    if s.get("indistinguishable") or not envelope(s["n"],s["f"],s["q"]):
        return result("IMPOSSIBLE_UNDER_FAULT_MODEL")
    obs=s["observations"]; by_root=defaultdict(list)
    for o in obs: by_root[o["root"]].append(o)
    bad_roots=set(); bad_ids=_lineage_bad(obs); revoked={o["id"] for o in obs if o.get("revoked") or o.get("lineage") in bad_ids}
    for root,items in by_root.items():
        current={o["value"] for o in items if o["epoch"]==s["epoch"] and o.get("sig",True)}
        if len(current)>1: bad_roots.add(root); bad_ids.update(o["id"] for o in items)
    for o in obs:
        if o["root"] not in s["authorized_roots"] or not o.get("sig",True) or not o.get("evaluator",True) or o["epoch"]!=s["epoch"] or o.get("poisoned") or o.get("revoked"):
            bad_ids.add(o["id"])
        if not o.get("evaluator",True): bad_roots.add(o["root"])
    changed=True
    while changed:
        changed=False
        for o in obs:
            if o.get("lineage") in bad_ids and o["id"] not in bad_ids:
                bad_ids.add(o["id"]); revoked.add(o["id"]); changed=True
    valid=[o for o in obs if o["id"] not in bad_ids and o["root"] not in bad_roots]
    values=defaultdict(list)
    for o in valid: values[o["value"]].append(o)
    ranked=sorted(((matching(v),k) for k,v in values.items()),key=lambda x:(-x[0],x[1]))
    accepted=[]
    if ranked and ranked[0][0]>=s["q"]: accepted=[{"claim_key":f'{s["domain"]}:asset|status',"value":ranked[0][1]}]
    next_id=choose_candidate(s.get("candidates",[]),{o["root"] for o in obs},{o["dep"] for o in obs},bad_roots)
    if accepted: terminal="REVOKED_RECOMPUTED" if revoked else "ACCEPTED"
    elif bad_ids or bad_roots: terminal="QUARANTINED"
    elif next_id: terminal="ABSTAIN"
    else: terminal="BLOCKED_INSUFFICIENT_ROOTS"
    return result(terminal,accepted,bad_roots,bad_ids,revoked,next_id)

def result(terminal,accepted=None,bad_roots=None,bad_ids=None,revoked=None,next_id=None):
    out={"terminal":terminal,"accepted":accepted or [],"quarantined_roots":sorted(bad_roots or []),"quarantined_statement_ids":sorted(bad_ids or []),"revoked_statement_ids":sorted(revoked or []),"next_source_id":next_id}
    assert terminal in TERMINALS
    out["sha256"]=digest(out); return out
