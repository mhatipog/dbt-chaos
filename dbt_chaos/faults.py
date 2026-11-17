"""Reproducible realistic fault recipes; unsupported catalogue entries are not executable."""
from random import Random
from .core import Event,Step,Plan,DOMAINS

BASE=(Event("base-A",1,1,10,1000),Event("base-B",2,1,20,2000))
def d(*events):return Step("deliver",tuple(events))
def r():return Step("run")
def c(name):return Step("check",label=name)

def fault_steps(fault:str,prefix:str,rng:Random)->list[Step]:
    def e(s,k,v,t,cents,op="upsert"):
        return Event(prefix+"-"+s,k,v,t,cents,op)
    third=e("third",3,1,30,3000+rng.randrange(100))
    if fault=="normal":return [d(third),r(),c(fault)]
    if fault=="late":return [d(e("late",3,1,15,3000)),r(),c(fault)]
    if fault=="same_time":return [d(e("same",3,1,20,3000)),r(),c(fault)]
    if fault=="future_poison":return [d(e("future",3,1,999,3000)),r(),d(e("normal",4,1,40,4000)),r(),c(fault)]
    if fault=="historical_update":return [d(e("past",1,2,15,1100)),r(),c(fault)]
    if fault=="fresh_update":return [d(e("new",1,2,30,1100)),r(),c(fault)]
    if fault=="duplicate":return [d(third),r(),d(third),r(),c(fault)]
    if fault=="out_of_order":return [d(e("high",4,1,40,4000)),r(),d(e("low",3,1,30,3000)),r(),c(fault)]
    if fault=="stale_replay":return [d(e("new",1,2,30,1100)),r(),d(BASE[0]),r(),c(fault)]
    if fault=="split_batch":return [d(third),r(),d(e("other",4,1,31,4000)),r(),c(fault)]
    if fault=="empty_batch":return [d(),r(),c(fault)]
    if fault=="skipped_run":return [d(e("old",3,1,15,3000)),d(e("later",4,1,40,4000)),r(),c(fault)]
    if fault=="tombstone":return [d(e("delete",1,2,15,None,"delete")),r(),c(fault)]
    if fault=="replay_after_delete":return [d(e("delete",1,2,25,None,"delete")),r(),d(BASE[0]),r(),c(fault)]
    if fault=="reinsert":return [d(e("delete",1,2,25,None,"delete")),r(),d(e("revive",1,3,30,1200)),r(),c(fault)]
    if fault=="reverse_version":return [d(e("v3",1,3,30,1300)),r(),d(e("v2",1,2,40,1200)),r(),c(fault)]
    if fault=="negative_amount":return [d(e("negative",3,1,30,-100)),r(),c(fault)]
    if fault=="null_amount":return [d(e("null",3,1,30,None)),r(),c(fault)]
    if fault=="hot_key":return [d(*(e("hot"+str(i),1,i+2,30+i,1200+i) for i in range(12))),r(),c(fault)]
    if fault=="version_collision":return [d(e("a",1,2,30,1100),e("z",1,2,29,1150)),r(),c(fault)]
    raise ValueError("unknown or not yet implemented fault: "+fault)

def generate(seed:int=42,count:int=100,max_faults:int=3)->list[Plan]:
    if type(seed) is not int or not 0<=seed<2**63:raise ValueError("invalid seed")
    if not 1<=count<=10_000 or not 1<=max_faults<=3:raise ValueError("invalid campaign bounds")
    rng=Random(seed)
    names=list(DOMAINS)
    result=[]
    for i in range(count):
        group=(names[i],) if i<len(names) else tuple(rng.sample(names,rng.randint(1,max_faults)))
        steps=[d(*BASE),r(),c("baseline")]
        for j,fault in enumerate(group):
            steps.extend(fault_steps(fault,str(i)+"-"+str(j),rng))
        result.append(Plan(f"case-{i:04d}-"+"-".join(group),seed,group,tuple(steps)))
    return result
