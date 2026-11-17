"""Portable, deterministic fault plans, independent oracle and pipeline simulators.

Pure Python screening is never presented as confirmation by dbt itself.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict, replace
from collections import defaultdict
from random import Random
import json
from typing import Any

STRATEGIES = ("strict", "inclusive", "lookback", "offset", "cdc", "full")
DOMAINS = {
    "normal": "control", "late": "time", "same_time": "time",
    "future_poison": "time", "historical_update": "history", "fresh_update": "control",
    "duplicate": "delivery", "out_of_order": "delivery", "stale_replay": "delivery",
    "split_batch": "delivery", "empty_batch": "delivery", "skipped_run": "execution",
    "tombstone": "cdc", "replay_after_delete": "cdc", "reinsert": "cdc",
    "reverse_version": "cdc", "negative_amount": "validation", "null_amount": "validation",
    "hot_key": "scale", "version_collision": "cdc",
}
# Exposed in the catalogue but explicitly NOT offered as executable faults yet.
PLANNED = {
    "schema_rename": "schema", "type_narrowing": "schema",
    "missing_dimension": "relationship", "join_fanout": "relationship",
    "scd2_overlap": "history", "missing_delivery_deadline": "delivery",
    "transaction_crash": "execution", "concurrent_writes": "execution",
    "currency_shift": "semantics", "precision_loss": "semantics",
    "large_scale": "scale", "cross_platform_parity": "execution",
}

@dataclass(frozen=True)
class Event:
    event_id: str
    key: int
    version: int
    time: int
    cents: int | None
    op: str = "upsert"

    def __post_init__(self):
        if not isinstance(self.event_id,str) or not 1 <= len(self.event_id) <= 80 or not self.event_id.isascii() or any(c.isspace() for c in self.event_id):
            raise ValueError("bad event id")
        if type(self.key) is not int or not 0 <= self.key <= 1_000_000:
            raise ValueError("bad key")
        if type(self.version) is not int or not 1 <= self.version <= 1_000_000:
            raise ValueError("bad source version")
        if type(self.time) is not int or not -1_000_000 <= self.time <= 1_000_000:
            raise ValueError("bad time")
        if self.cents is not None and (type(self.cents) is not int or abs(self.cents) > 1_000_000_000):
            raise ValueError("bad cents")
        if self.op not in ("upsert","delete") or (self.op=="delete" and self.cents is not None):
            raise ValueError("bad operation")

@dataclass(frozen=True)
class Step:
    kind: str
    events: tuple[Event,...] = ()
    label: str = ""

    def __post_init__(self):
        if self.kind not in ("deliver","run","check"):
            raise ValueError("unknown step")
        if self.kind!="deliver" and self.events:
            raise ValueError("only deliver can carry events")
        if not isinstance(self.label,str) or len(self.label)>80:
            raise ValueError("invalid label")

@dataclass(frozen=True)
class Plan:
    name: str
    seed: int
    faults: tuple[str,...]
    steps: tuple[Step,...]
    schema_version: int = 1

    def __post_init__(self):
        if self.schema_version!=1 or not isinstance(self.name,str) or not 1<=len(self.name)<=150:
            raise ValueError("unsupported plan")
        if type(self.seed) is not int or not 0 <= self.seed < 2**63:
            raise ValueError("invalid seed")
        if not self.faults or any(f not in DOMAINS for f in self.faults):
            raise ValueError("unknown or unsupported fault")
        if not 3 <= len(self.steps) <= 128 or sum(len(s.events) for s in self.steps)>512:
            raise ValueError("too many actions/events")
        if self.steps[-1].kind!="check" or self.steps[0].kind!="deliver":
            raise ValueError("plan must begin with a delivery and end with a check")
        ran=False
        for s in self.steps:
            if s.kind=="run": ran=True
            if s.kind=="check" and not ran: raise ValueError("check before first run")

    def to_dict(self):
        return asdict(self)

    def dumps(self):
        return json.dumps(self.to_dict(),sort_keys=True,indent=2)+"\n"

    @classmethod
    def from_dict(cls,data:dict[str,Any]):
        if not isinstance(data,dict) or set(data)!={"name","seed","faults","steps","schema_version"}:
            raise ValueError("unexpected plan fields")
        steps=[]
        if not isinstance(data["steps"],list) or not isinstance(data["faults"],list):
            raise ValueError("expected plan arrays")
        for item in data["steps"]:
            if not isinstance(item,dict) or set(item)!={"kind","events","label"} or not isinstance(item["events"],list):
                raise ValueError("unexpected step fields")
            events=[]
            for e in item["events"]:
                if not isinstance(e,dict) or set(e)!={"event_id","key","version","time","cents","op"}:
                    raise ValueError("unexpected event fields")
                events.append(Event(**e))
            steps.append(Step(item["kind"],tuple(events),item["label"]))
        return cls(data["name"],data["seed"],tuple(data["faults"]),tuple(steps),data["schema_version"])

def read_plan(path):
    from pathlib import Path
    p=Path(path)
    if p.stat().st_size>1_000_000: raise ValueError("plan file too large")
    return Plan.from_dict(json.loads(p.read_text(encoding="utf8")))

def oracle(events:list[Event])->dict[int,Event]:
    """Independently compute latest-by-source-version using grouped sorted immutable events."""
    unique={}
    for e in events:
        old=unique.setdefault(e.event_id,e)
        if old!=e: raise ValueError("conflicting delivery for immutable event ID")
    grouped=defaultdict(list)
    for e in unique.values(): grouped[e.key].append(e)
    return {key:sorted(seq,key=lambda x:(x.version,x.event_id))[-1]
            for key,seq in grouped.items()}

def live(state:dict[int,Event])->dict[int,tuple[int,int|None]]:
    return {k:(e.version,e.cents) for k,e in sorted(state.items()) if e.op!="delete"}

def delta(expected:dict[int,Event],actual:dict[int,Event])->dict:
    a,b=live(expected),live(actual)
    return {"missing":{k:a[k] for k in a.keys()-b.keys()},
            "extra":{k:b[k] for k in b.keys()-a.keys()},
            "changed":{k:{"expected":a[k],"actual":b[k]} for k in a.keys()&b.keys() if a[k]!=b[k]}}

class Pipeline:
    """Simplified semantic models, not a substitute for actual dbt SQL execution."""
    def __init__(self,strategy:str,lookback:int=10):
        if strategy not in STRATEGIES: raise ValueError("unknown strategy")
        if not 0<=lookback<=1_000_000: raise ValueError("invalid lookback")
        self.strategy,self.lookback=strategy,lookback
        self.state:dict[int,Event]={}
        self.cursor=0
        self.reads=0
        self.runs=0

    def run(self,arrivals:list[Event]):
        self.runs+=1
        boundary=max((e.time for e in self.state.values()),default=-1_000_001)
        if self.strategy=="full":
            self.reads+=len(arrivals)
            latest={}
            for e in arrivals:
                old=latest.get(e.key)
                if old is None or (e.version,e.event_id)>=(old.version,old.event_id):
                    latest[e.key]=e
            self.state=latest
            self.cursor=len(arrivals)
            return
        if self.strategy=="offset":
            candidates=arrivals[self.cursor:]
            self.cursor=len(arrivals)
            self.reads+=len(candidates)
        elif self.strategy=="cdc":
            candidates=arrivals
            self.reads+=len(arrivals)
        else:
            latest={}
            for e in arrivals:
                old=latest.get(e.key)
                if old is None or (e.version,e.event_id)>=(old.version,old.event_id):
                    latest[e.key]=e
            candidates=list(latest.values())
            self.reads+=len(arrivals)
            if self.strategy=="strict":
                candidates=[e for e in candidates if e.time>boundary]
            elif self.strategy=="inclusive":
                candidates=[e for e in candidates if e.time>=boundary]
            else:
                candidates=[e for e in candidates if e.time>=boundary-self.lookback]
        for e in candidates:
            old=self.state.get(e.key)
            if old is None or (e.version,e.event_id)>=(old.version,old.event_id):
                self.state[e.key]=e

def basic_alerts(state:dict[int,Event]):
    return sorted([
        name for name,condition in {
            "not_null_amount":any(e.op=="upsert" and e.cents is None for e in state.values()),
            "nonnegative_amount":any(e.op=="upsert" and e.cents is not None and e.cents<0 for e in state.values())
        }.items() if condition
    ])

def screen(plan:Plan,strategy:str,lookback:int=10)->dict:
    engine=Pipeline(strategy,lookback)
    arrivals=[]
    checkpoints=[]
    for idx,step in enumerate(plan.steps):
        if step.kind=="deliver":
            arrivals.extend(step.events)
        elif step.kind=="run":
            engine.run(arrivals)
        else:
            mismatch=delta(oracle(arrivals),engine.state)
            alerts=basic_alerts(engine.state)
            wrong=any(bool(v) for v in mismatch.values())
            checkpoints.append({"step":idx,"label":step.label,"mismatch":wrong,
                                "silent":bool(wrong and not alerts),"alerts":alerts,
                                "delta":mismatch})
    return {"evidence_level":"python_model_screen","plan":plan.name,
            "seed":plan.seed,"faults":list(plan.faults),"strategy":strategy,
            "checkpoints":checkpoints,"read_work_units":engine.reads,"run_count":engine.runs,
            "silent_corruption":any(p["silent"] for p in checkpoints),
            "final_correct":not checkpoints[-1]["mismatch"]}
