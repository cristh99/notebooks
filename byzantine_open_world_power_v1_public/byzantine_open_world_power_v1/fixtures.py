from __future__ import annotations

def o(domain,suffix,root,dep,value="VALID",epoch=1,**kw):
    return {"id":f"{domain}-{suffix}","root":root,"dep":dep,"value":value,"epoch":epoch,**kw}
def c(domain,suffix,root,dep,gain,reliability,exposure,cost):
    return {"id":f"candidate-{domain}-{suffix}","root":root,"dep":dep,"gain":gain,"reliability":reliability,"exposure":exposure,"cost":cost}
def base(domain,archetype,n=4,f=1,q=3):
    return {"scenario_id":f"{domain}::{archetype}","domain":domain,"archetype":archetype,"n":n,"f":f,"q":q,"epoch":1,"authorized_roots":{"r1","r2","r3","rbad","captured-evaluator"},"observations":[],"candidates":[]}
def build(domain,a):
    s=base(domain,a)
    good=[o(domain,f"good-{i}",f"r{i}",f"d{i}") for i in range(1,4)]
    if a=="honest_distinct_root_quorum": s["observations"]=good
    elif a=="sybil_aliases_one_root": s["observations"]=[o(domain,f"sybil-{i}","r1",f"d{i}") for i in range(1,4)]
    elif a=="root_equivocation": s["observations"]=good+[o(domain,"eq-a","rbad","db","VALID"),o(domain,"eq-b","rbad","db","INVALID")]
    elif a=="stale_signed_replay": s["observations"]=good+[o(domain,"stale","rbad","db",epoch=0)]
    elif a=="correlated_mirror_inflation": s["observations"]=[o(domain,f"mirror-{i}",f"r{i}","shared") for i in range(1,4)]
    elif a=="byzantine_minority_tolerated": s["observations"]=good+[o(domain,"minority","rbad","db","INVALID")]
    elif a=="fault_budget_exceeds_envelope": s.update(n=4,f=2,q=3)
    elif a=="poisoned_derivation_cascade":
        s["observations"]=[o(domain,"poison-base","r1","d1",poisoned=True),o(domain,"poison-derived-1","r2","d2",lineage=f"{domain}-poison-base"),o(domain,"poison-derived-2","r3","d3",lineage=f"{domain}-poison-derived-1")]
        s["candidates"]=[c(domain,"independent","r4","d4",4,.9,.1,1)]; s["authorized_roots"].add("r4")
    elif a=="revocation_deterministic_recompute":
        s["observations"]=[o(domain,"revoke-old","rbad","db",revoked=True),o(domain,"revoke-derived","rbad","dc",lineage=f"{domain}-revoke-old")]+good
    elif a=="evaluator_compromise": s["observations"]=[o(domain,f"eval-{i}","captured-evaluator",f"d{i}",evaluator=False) for i in range(1,4)]
    elif a=="adaptive_next_source_under_dependence":
        s["observations"]=[o(domain,"seen","r1","d1")]
        s["candidates"]=[c(domain,"correlated","r1","d1",100,1,0,1),c(domain,"independent","r4","d4",4,.9,.1,1)]; s["authorized_roots"].add("r4")
    elif a=="indistinguishable_worlds_impossible": s["indistinguishable"]=True
    else: raise KeyError(a)
    return s

def matrix(contract): return [build(d,a) for d in contract["domains"] for a in contract["archetypes"]]
