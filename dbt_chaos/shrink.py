"""Bounded failure-preserving reduction: remove actions then individual event deliveries."""
from dataclasses import replace
from .core import screen

def reduce_plan(plan,strategy="strict",limit=250):
    def sig(p):
        result=screen(p,strategy)
        return (result["silent_corruption"],any(bool(c["alerts"]) for c in result["checkpoints"]))
    target=sig(plan)
    if not any(target): return {"plan":plan,"attempts":0,"changed":False}
    current=plan
    attempts=0
    changed=True
    while changed and attempts<limit:
        changed=False
        # Never remove the initial baseline delivery and run, nor the final assertion.
        for i in range(2,len(current.steps)-1):
            try: candidate=replace(current,steps=current.steps[:i]+current.steps[i+1:])
            except ValueError:continue
            attempts+=1
            if sig(candidate)==target:
                current=candidate
                changed=True
                break
            if attempts>=limit:break
        if changed or attempts>=limit:continue
        for i,step in enumerate(current.steps):
            if step.kind!="deliver":continue
            for j in range(len(step.events)):
                try:
                    slim=replace(step,events=step.events[:j]+step.events[j+1:])
                    candidate=replace(current,steps=current.steps[:i]+(slim,)+current.steps[i+1:])
                except ValueError:continue
                attempts+=1
                if sig(candidate)==target:
                    current=candidate
                    changed=True
                    break
                if attempts>=limit:break
            if changed or attempts>=limit:break
    return {"plan":current,"attempts":attempts,"changed":current.steps!=plan.steps}
