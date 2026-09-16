"""Bounded, deterministic Digital Ontogeny laboratory (never a production organ).

The field equation is ``M[i,k] = clamp(diffuse(M)[i,k] + source[i,k] +
emitter[i,k])``.  A cell perceives ``M_eff[i,k] = receptor[i,k] * M[i,k]``;
therefore a zero receptor causally removes that channel.  Nothing in this module
has a bus, filesystem, credential, Root, model, network, or execution reference.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import random
import statistics
import time
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Iterable


CHANNELS = ("goal", "damage", "novelty", "scarcity")


class DevelopmentalAction(StrEnum):
    STAY="STAY"; REWIRE_ADD="REWIRE_ADD"; REWIRE_DROP="REWIRE_DROP"
    DIFFERENTIATE="DIFFERENTIATE"; CLONE_REQUEST="CLONE_REQUEST"
    SLEEP="SLEEP"; WAKE="WAKE"; PRUNE_REQUEST="PRUNE_REQUEST"


@dataclass(slots=True)
class OperationAccount:
    budget: int
    used: int = 0
    categories: dict[str, int] = field(default_factory=dict)
    def charge(self, category: str, amount: int = 1) -> None:
        self.used += max(0, amount); self.categories[category] = self.categories.get(category, 0)+max(0, amount)
        if self.used > self.budget: raise ResourceBudgetViolation(f"{self.used}>{self.budget}")


class ResourceBudgetViolation(RuntimeError): pass


@dataclass(frozen=True, slots=True)
class CellGenome:
    receptors: tuple[float, ...] = (1., 1., 1., 1.)
    emitters: tuple[float, ...] = (.05, .02, .04, .01)
    plasticity: float = .2
    threshold: float = .35


@dataclass(slots=True)
class Epigenome:
    sensitivity: float = 1.
    plasticity: float = 1.
    threshold_bias: float = 0.
    message_gain: float = 1.
    def bounded(self) -> None:
        self.sensitivity=min(2.,max(.1,self.sensitivity)); self.plasticity=min(2.,max(.1,self.plasticity))
        self.threshold_bias=min(.4,max(-.4,self.threshold_bias)); self.message_gain=min(2.,max(0.,self.message_gain))


@dataclass(slots=True)
class DigitalCell:
    id: str
    genome: CellGenome
    epigenome: Epigenome = field(default_factory=Epigenome)
    phenotype: str = "pluripotent"
    state: float = 0.
    memory: float = 0.
    predictor: float = 0.
    prediction_error: float = 0.
    sleeping: bool = False
    parent_id: str | None = None
    competence: float = 0.

    def perceive(self, fields: tuple[float, ...], account: OperationAccount) -> tuple[float, ...]:
        account.charge("receptor", len(CHANNELS))
        return tuple(max(0., min(1., m*r*self.epigenome.sensitivity))
                     for m,r in zip(fields,self.genome.receptors))

    def step(self, local_observation: float, messages: Iterable[float], fields: tuple[float, ...],
             account: OperationAccount, *, learn: bool, prediction_coupling: bool) -> float:
        if self.sleeping: return 0.
        perceived=self.perceive(fields,account); incoming=list(messages)
        account.charge("cell_update", 8+len(incoming))
        surprise=abs(local_observation-self.predictor)
        if learn:
            self.prediction_error=surprise
            self.predictor += self.genome.plasticity*.25*(local_observation-self.predictor)
            account.charge("prediction_update",3)
        coupling=surprise if prediction_coupling else 0.
        signal=local_observation+(sum(incoming)/len(incoming) if incoming else 0.)
        signal += .25*perceived[0]-.2*perceived[1]+.15*perceived[2]+.1*coupling
        self.memory=.75*self.memory+.25*signal
        self.state=math.tanh(signal+.4*self.memory)
        return self.state*self.epigenome.message_gain

    def adapt_epigenome(self, perceived: tuple[float, ...], prediction_coupling: bool) -> None:
        rate=self.genome.plasticity*.1*self.epigenome.plasticity
        self.epigenome.sensitivity += rate*(perceived[2]-perceived[3])
        if prediction_coupling: self.epigenome.plasticity += rate*(self.prediction_error-.25)
        self.epigenome.threshold_bias += rate*(perceived[1]-perceived[0])
        self.epigenome.message_gain += rate*(perceived[0]-perceived[1])
        self.epigenome.bounded()


@dataclass(slots=True)
class ColonyGraph:
    edges: set[tuple[str,str]] = field(default_factory=set)
    def neighbors(self, identity: str) -> list[str]:
        return sorted(b if a==identity else a for a,b in self.edges if a==identity or b==identity)
    def add(self,a:str,b:str)->bool:
        edge=tuple(sorted((a,b)))
        if a==b or edge in self.edges:return False
        self.edges.add(edge); return True
    def drop(self,a:str,b:str)->bool:
        edge=tuple(sorted((a,b)))
        if edge not in self.edges:return False
        self.edges.remove(edge); return True
    def remove(self,identity:str)->None:self.edges={e for e in self.edges if identity not in e}


@dataclass(frozen=True, slots=True)
class ResourceLimits:
    max_cells:int=12; max_edges:int=24; max_degree:int=5; mutations_per_step:int=2


class ResourceGovernor:
    def __init__(self,limits:ResourceLimits):self.limits=limits;self.mutations=0
    def begin(self)->None:self.mutations=0
    def structural(self,colony:"DigitalColony",action:DevelopmentalAction,cell_id:str,target:str|None=None)->bool:
        if self.mutations>=self.limits.mutations_per_step:return False
        if action==DevelopmentalAction.CLONE_REQUEST and len(colony.cells)>=self.limits.max_cells:return False
        if action==DevelopmentalAction.PRUNE_REQUEST and len(colony.cells)<=1:return False
        if action==DevelopmentalAction.REWIRE_ADD:
            if target is None or len(colony.graph.edges)>=self.limits.max_edges:return False
            if len(colony.graph.neighbors(cell_id))>=self.limits.max_degree or len(colony.graph.neighbors(target))>=self.limits.max_degree:return False
        self.mutations+=1;return True


@dataclass(frozen=True, slots=True)
class DevelopmentalFeatures:
    cell_id:str; action:DevelopmentalAction; goal:float; damage:float; novelty:float
    scarcity:float; prediction_error:float; degree:int


def developmental_potential(f:DevelopmentalFeatures)->float:
    weights={DevelopmentalAction.STAY:.05,DevelopmentalAction.REWIRE_ADD:.35,
      DevelopmentalAction.REWIRE_DROP:.12,DevelopmentalAction.DIFFERENTIATE:.3,
      DevelopmentalAction.CLONE_REQUEST:.22,DevelopmentalAction.SLEEP:.08,
      DevelopmentalAction.WAKE:.25,DevelopmentalAction.PRUNE_REQUEST:.1}
    score=weights[f.action]
    if f.action in {DevelopmentalAction.REWIRE_ADD,DevelopmentalAction.DIFFERENTIATE}:score += .35*f.goal+.3*f.novelty
    if f.action in {DevelopmentalAction.REWIRE_ADD,DevelopmentalAction.CLONE_REQUEST}:score += .45*f.damage
    if f.action in {DevelopmentalAction.REWIRE_ADD,DevelopmentalAction.DIFFERENTIATE}:score += .3*f.prediction_error
    if f.action in {DevelopmentalAction.SLEEP,DevelopmentalAction.PRUNE_REQUEST}:score += .35*f.scarcity
    if f.action==DevelopmentalAction.REWIRE_ADD:score += .08*(2-f.degree)
    if f.action==DevelopmentalAction.CLONE_REQUEST:score -= .2*f.scarcity
    if f.action==DevelopmentalAction.SLEEP:score += .4*f.scarcity
    return score


@dataclass(frozen=True, slots=True)
class DevelopmentalExperience:
    cell_id:str; prior_summary:str; field_context:tuple[float,...]; action:str
    local_delta:float; colony_delta:float; resource_delta:int; verified:bool


def body_deficit(observed:dict[str,float],target:dict[str,float])->dict[str,float]:
    return {k:max(-1.,min(1.,target.get(k,0.)-observed.get(k,0.))) for k in CHANNELS}


def deficit_sources(deficit:dict[str,float],cell_ids:list[str])->dict[str,tuple[float,...]]:
    # Same governed mapping for every context; positive homeostatic deficits source MUF.
    return {identity:tuple(max(0.,deficit[k]) for k in CHANNELS) for identity in cell_ids}


@dataclass(slots=True)
class Hypothesis:
    name:str; muf:bool=False; adaptive_topology:bool=False; differentiation:bool=False
    prediction_coupling:bool=False; nca:bool=False; stigmergy:bool=False; evolving:bool=False


HYPOTHESES={
 "H0":Hypothesis("H0-fixed-graph-control"),
 "H1":Hypothesis("H1-APGC-developmental-genome-MUF",True,True,True,True),
 "H2":Hypothesis("H2-NCA-like",nca=True),
 "H3":Hypothesis("H3-evolving-topology",adaptive_topology=True,evolving=True),
 "H4":Hypothesis("H4-stigmergic",stigmergy=True),
 "H5":Hypothesis("H5-active-inference-like",prediction_coupling=True),
 "H1-no-MUF":Hypothesis("H1-no-MUF",False,True,True,True),
 "H1-fixed-topology":Hypothesis("H1-fixed-topology",True,False,True,True),
 "H1-no-differentiation":Hypothesis("H1-no-differentiation",True,True,False,True),
 "H1-no-prediction-coupling":Hypothesis("H1-no-prediction-coupling",True,True,True,False),
}


class DigitalColony:
    def __init__(self,seed:int,hypothesis:Hypothesis,cell_count:int=6,compute_budget:int=100_000):
        self.rng=random.Random(seed);self.hypothesis=hypothesis;self.account=OperationAccount(compute_budget)
        self.cells={f"c{i}":DigitalCell(f"c{i}",CellGenome()) for i in range(cell_count)}
        self.graph=ColonyGraph(); ids=list(self.cells)
        for i in range(len(ids)-1):self.graph.add(ids[i],ids[i+1])
        self.governor=ResourceGovernor(ResourceLimits(max_cells=max(8,cell_count+2)))
        self.fields={i:(0.,0.,0.,0.) for i in ids};self.experiences:list[DevelopmentalExperience]=[]
        self.trace=0.;self.dead:set[str]=set();self.last_actions:list[str]=[]

    def snapshot(self)->"DigitalColony":return copy.deepcopy(self)
    def _diffuse(self,sources:dict[str,tuple[float,...]])->None:
        old=self.fields.copy(); updated={}
        for identity,cell in self.cells.items():
            neighbors=self.graph.neighbors(identity); values=[]
            for k in range(len(CHANNELS)):
                nearby=sum(old.get(n,(0.,)*4)[k] for n in neighbors)/(len(neighbors) or 1)
                endogenous=cell.genome.emitters[k]*max(0.,cell.state)
                source=sources.get(identity,(0.,)*4)[k]
                values.append(max(0.,min(1.,.55*old.get(identity,(0.,)*4)[k]+.25*nearby+source+endogenous)))
                self.account.charge("muf_diffusion",5)
            updated[identity]=tuple(values)
        self.fields=updated

    def _safe_actions(self,cell:DigitalCell)->list[DevelopmentalAction]:
        actions=[DevelopmentalAction.STAY,DevelopmentalAction.SLEEP if not cell.sleeping else DevelopmentalAction.WAKE]
        if self.hypothesis.adaptive_topology:actions += [DevelopmentalAction.REWIRE_ADD,DevelopmentalAction.REWIRE_DROP]
        if self.hypothesis.differentiation:actions += [DevelopmentalAction.DIFFERENTIATE,DevelopmentalAction.CLONE_REQUEST,DevelopmentalAction.PRUNE_REQUEST]
        return actions

    def _execute(self,cell_id:str,action:DevelopmentalAction)->bool:
        cell=self.cells[cell_id]; ids=sorted(self.cells); candidates=[i for i in ids if i!=cell_id]
        if action==DevelopmentalAction.STAY:return True
        if action==DevelopmentalAction.SLEEP:cell.sleeping=True;return True
        if action==DevelopmentalAction.WAKE:cell.sleeping=False;return True
        if action==DevelopmentalAction.DIFFERENTIATE:
            cell.phenotype=("relay" if cell.phenotype!="relay" else "memory");cell.epigenome.message_gain=min(2.,cell.epigenome.message_gain+.1);self.account.charge("differentiate",5);return True
        if action==DevelopmentalAction.REWIRE_ADD and candidates:
            target=min(candidates,key=lambda x:(x in self.graph.neighbors(cell_id),abs(self.cells[x].prediction_error-cell.prediction_error),x))
            if self.governor.structural(self,action,cell_id,target):self.account.charge("topology",5);return self.graph.add(cell_id,target)
        if action==DevelopmentalAction.REWIRE_DROP:
            neighbors=self.graph.neighbors(cell_id)
            if neighbors and self.governor.structural(self,action,cell_id,neighbors[-1]):self.account.charge("topology",4);return self.graph.drop(cell_id,neighbors[-1])
        if action==DevelopmentalAction.CLONE_REQUEST and self.governor.structural(self,action,cell_id):
            identity=f"{cell_id}.clone{len(self.cells)}"; receptors=list(cell.genome.receptors)
            channel=self.rng.randrange(4)
            receptors[channel]=min(1.,max(0.,receptors[channel]+self.rng.uniform(-.05,.05)))
            self.cells[identity]=DigitalCell(identity,CellGenome(tuple(receptors),cell.genome.emitters,cell.genome.plasticity,cell.genome.threshold),copy.deepcopy(cell.epigenome),cell.phenotype,parent_id=cell_id)
            self.fields[identity]=(0.,)*4;self.graph.add(cell_id,identity);self.account.charge("clone",12);return True
        if action==DevelopmentalAction.PRUNE_REQUEST and self.governor.structural(self,action,cell_id):
            self.graph.remove(cell_id);del self.cells[cell_id];self.fields.pop(cell_id,None);self.account.charge("prune",8);return True
        return False

    def develop(self,observed:dict[str,float],target:dict[str,float])->list[DevelopmentalExperience]:
        """One complete body→deficit→MUF→proposal→effect→verified-learning cycle."""
        if not (self.hypothesis.muf or self.hypothesis.adaptive_topology
                or self.hypothesis.differentiation or self.hypothesis.prediction_coupling):
            return []
        before=sum(abs(c.state) for c in self.cells.values())/(len(self.cells) or 1); start=self.account.used
        deficit=body_deficit(observed,target);self.account.charge("deficit_source",len(CHANNELS)*2)
        sources=deficit_sources(deficit,sorted(self.cells)) if self.hypothesis.muf else {i:(0.,)*4 for i in self.cells}
        if self.hypothesis.muf:self._diffuse(sources)
        self.governor.begin(); records=[]; self.last_actions=[]
        for identity in list(sorted(self.cells)):
            if identity not in self.cells:continue
            cell=self.cells[identity]; perceived=cell.perceive(self.fields.get(identity,(0.,)*4),self.account)
            safe=self._safe_actions(cell) # exclusion precedes ranking
            coupled_error=cell.prediction_error if self.hypothesis.prediction_coupling else 0.
            features=[DevelopmentalFeatures(identity,a,*perceived,coupled_error,len(self.graph.neighbors(identity))) for a in safe]
            self.account.charge("developmental_features",len(features)*8)
            ranked=sorted(features,key=lambda f:(developmental_potential(f),f.action.value),reverse=True)
            self.account.charge("potential_ranking",len(features)*2)
            prior=f"{cell.phenotype}:{cell.state:.4f}:{cell.epigenome.sensitivity:.4f}"
            prior_state=cell.state; graph_before=set(self.graph.edges)
            action,applied=DevelopmentalAction.STAY,False
            for candidate in ranked:
                action=candidate.action;applied=self._execute(identity,action)
                if applied:break
            # H3's topology mutations are selected by a measured local error/degree
            # proxy, never by task index and never by MUF.
            if self.hypothesis.evolving and action in {DevelopmentalAction.REWIRE_ADD,DevelopmentalAction.REWIRE_DROP}:
                before_proxy=-abs(sum(identity in e for e in graph_before)-2)-cell.prediction_error
                after_proxy=-abs(len(self.graph.neighbors(identity))-2)-cell.prediction_error
                self.account.charge("topology_evaluation",4)
                if after_proxy < before_proxy:
                    self.graph.edges=graph_before;applied=False;action=DevelopmentalAction.STAY
            if identity in self.cells:
                self.cells[identity].adapt_epigenome(perceived,self.hypothesis.prediction_coupling)
                local=abs(self.cells[identity].state)-abs(prior_state)
            else:local=-abs(prior_state)
            self.last_actions.append(action.value if applied else DevelopmentalAction.STAY.value)
            records.append((identity,prior,perceived,action if applied else DevelopmentalAction.STAY,local))
        after=sum(abs(c.state) for c in self.cells.values())/(len(self.cells) or 1); delta=after-before
        experiences=[]
        for identity,prior,perceived,action,local in records:
            exp=DevelopmentalExperience(identity,prior,perceived,action.value,local,delta,self.account.used-start,True)
            experiences.append(exp)
            if identity in self.cells:self.cells[identity].competence=max(-1.,min(1.,self.cells[identity].competence+.05*delta))
        self.experiences.extend(experiences);return experiences

    def tick(self,observations:dict[str,float],*,learn:bool=True,corrupt:set[str]|None=None)->float:
        prior={i:c.state*c.epigenome.message_gain for i,c in self.cells.items()}; outputs={}
        for identity,cell in sorted(self.cells.items()):
            messages=[(-prior[n] if corrupt and n in corrupt else prior[n]) for n in self.graph.neighbors(identity) if n not in self.dead]
            outputs[identity]=cell.step(observations.get(identity,0.),messages,self.fields.get(identity,(0.,)*4),self.account,learn=learn,prediction_coupling=self.hypothesis.prediction_coupling)
        if self.hypothesis.stigmergy:
            self.trace=.8*self.trace+.2*(sum(outputs.values())/(len(outputs) or 1));self.account.charge("stigmergy",len(outputs)+2)
            for c in self.cells.values():c.state=math.tanh(c.state+.2*self.trace)
        self.account.charge("readout",len(outputs));return sum(outputs.values())/(len(outputs) or 1)

    def damage(self,fraction:float)->set[str]:
        count=max(1,int(len(self.cells)*fraction)); victims=set(sorted(self.cells)[-count:]);self.dead|=victims
        for v in victims:self.cells[v].sleeping=True;self.graph.remove(v)
        return victims


@dataclass(frozen=True, slots=True)
class Episode:
    observations:tuple[dict[str,float],...]; target:int; kind:str
    metadata:dict[str,object]=field(default_factory=dict)


def temporal_memory_episode(bit:int,delay:int,ids:list[str])->Episode:
    stages=[{ids[0]:float(bit)}]+[{i:(-1.)**(t+j) *.1 for j,i in enumerate(ids)} for t in range(delay-1)]+[{i:0. for i in ids}]
    return Episode(tuple(stages),1 if bit else -1,"temporal-memory",{"delay":delay,"answer_present_at_query":False})


def multi_stage_episode(a:int,b:int,ids:list[str])->Episode:
    return Episode(({ids[0]:float(a)},{ids[-1]:float(b)},{i:0. for i in ids}),1 if bool(a)^bool(b) else -1,"multi-stage",{"stages_separated":True})


def parity_episode(bits:list[int],ids:list[str],ticks:int)->Episode:
    first={identity:float(bits[i]) for i,identity in enumerate(ids)}
    return Episode(tuple([first]+[{i:0. for i in ids} for _ in range(max(ticks-1,0))]),1 if sum(b>0 for b in bits)%2 else -1,"distributed-parity")


def evaluate_frozen(colony:DigitalColony,episodes:list[Episode])->float:
    frozen=colony.snapshot(); signature=json.dumps([(c.predictor,asdict(c.epigenome),c.phenotype) for c in frozen.cells.values()],sort_keys=True)
    correct=0
    for episode in episodes:
        out=0.
        for stage in episode.observations:out=frozen.tick(stage,learn=False)
        correct += (1 if out>=0 else -1)==episode.target
    after=json.dumps([(c.predictor,asdict(c.epigenome),c.phenotype) for c in frozen.cells.values()],sort_keys=True)
    if signature!=after:raise AssertionError("held-out learning was not frozen")
    return correct/(len(episodes) or 1)


def best_isolated_cell(colony:DigitalColony,episodes:list[Episode])->float:
    scores=[]
    for original in colony.cells.values():
        single=DigitalColony(0,colony.hypothesis,1,colony.account.budget);single.cells={original.id:copy.deepcopy(original)};single.graph=ColonyGraph();single.fields={original.id:(0.,)*4}
        scores.append(evaluate_frozen(single,episodes))
    return max(scores,default=0.)


def independent_ensemble(colony:DigitalColony,episodes:list[Episode])->float:
    independent=[]
    for c in colony.cells.values():
        unit=DigitalColony(0,colony.hypothesis,1,colony.account.budget);unit.cells={c.id:copy.deepcopy(c)};unit.graph=ColonyGraph();unit.fields={c.id:(0.,)*4};independent.append(unit)
    correct=0
    for ep in episodes:
        votes=[]
        for unit in independent:
            out=0.; identity=next(iter(unit.cells))
            for stage in ep.observations:out=unit.tick({identity:stage.get(identity,0.)},learn=False)
            votes.append(out)
        correct += (1 if sum(votes)>=0 else -1)==ep.target
    return correct/(len(episodes) or 1)


def functional_specialization(colony:DigitalColony,episodes:list[Episode])->dict[str,object]:
    base=evaluate_frozen(colony,episodes); groups={c.phenotype for c in colony.cells.values()};losses={}
    for group in sorted(groups):
        ablated=colony.snapshot()
        for c in ablated.cells.values():
            if c.phenotype==group:c.sleeping=True
        losses[group]=base-evaluate_frozen(ablated,episodes)
    values=list(losses.values()); functional=(max(values)-min(values) if len(values)>1 else 0.)
    return {"phenotype_diversity":len(groups),"ablation_losses":losses,"functional_specialization":functional}


def rule_shift_curve(colony:DigitalColony,ids:list[str],episodes:int=8,threshold:float=.8)->dict[str,object]:
    # Mapping changes silently; observations have no shift flag.
    curve=[]
    for index in range(episodes):
        value=1. if index%2 else -1.;target=(-1 if value>0 else 1)
        out=colony.tick({ids[0]:value},learn=True);curve.append(1. if (1 if out>=0 else -1)==target else 0.)
    attainable=max(.01,sum(curve[-3:])/3);wanted=threshold*attainable;latency=next((i+1 for i in range(len(curve)) if sum(curve[i:i+3])/len(curve[i:i+3])>=wanted),len(curve))
    return {"curve":curve,"threshold_fraction":threshold,"latency":latency,"shift_revealed":False}


def _episodes(seed:int,ids:list[str],count:int)->list[Episode]:
    rng=random.Random(seed);episodes=[]
    for i in range(count):
        if i%3==0:episodes.append(temporal_memory_episode(rng.randrange(2),2+(i%3),ids))
        elif i%3==1:episodes.append(multi_stage_episode(rng.randrange(2),rng.randrange(2),ids))
        else:episodes.append(parity_episode([rng.choice((-1,1)) for _ in ids],ids,len(ids)))
    return episodes


def run_hypothesis(key:str,seed:int,*,episodes:int=8,budget:int=100_000)->dict[str,object]:
    colony=DigitalColony(seed,HYPOTHESES[key],compute_budget=budget); ids=sorted(colony.cells)
    train=_episodes(seed,ids,episodes);held=_episodes(seed+10_000,ids,episodes)
    try:
        for episode in train:
            for stage in episode.observations:colony.tick(stage,learn=True)
            observed={"goal":abs(colony.tick({},learn=True)),"damage":1-len(colony.dead)/len(colony.cells),"novelty":1-statistics.fmean(c.prediction_error for c in colony.cells.values()),"scarcity":1-len(colony.cells)/colony.governor.limits.max_cells}
            colony.develop(observed,{"goal":.8,"damage":1.,"novelty":.8,"scarcity":.5})
        quality=evaluate_frozen(colony,held); single=best_isolated_cell(colony,held); ensemble=independent_ensemble(colony,held)
        damage=colony.snapshot();victims=damage.damage(.2);damaged=evaluate_frozen(damage,held)
        for _ in range(2):damage.develop({"goal":damaged,"damage":1-len(victims)/len(damage.cells),"novelty":.2,"scarcity":.3},{"goal":.8,"damage":1.,"novelty":.8,"scarcity":.5})
        recovery=evaluate_frozen(damage,held)
        spec=functional_specialization(colony,held);shift=rule_shift_curve(colony.snapshot(),ids)
        delta_compute=max(0,colony.account.used-episodes*len(ids)*10); advantage=quality-max(single,ensemble)
        synergy=advantage-1e-6*delta_compute-1e-4*len(colony.graph.edges)-.1*max(0.,quality-recovery)
        return {"hypothesis":key,"status":"ELIGIBLE","quality":quality,"best_isolated_cell":single,
          "independent_ensemble":ensemble,"collective_advantage":advantage,"synergy":synergy,
          "compute":colony.account.used,"compute_categories":colony.account.categories,"delta_compute":delta_compute,
          "communication":len(colony.graph.edges),"cells":len(colony.cells),"parameters":len(colony.cells)*14,
          "damage":{"victims":sorted(victims),"victims_remained_absent":all(damage.cells[v].sleeping for v in victims if v in damage.cells),"damaged":damaged,"recovered":recovery},
          "specialization":spec,"rule_shift":shift,"experiences":len(colony.experiences)}
    except ResourceBudgetViolation as error:
        return {"hypothesis":key,"status":"DISQUALIFIED","violation":"RESOURCE_BUDGET_VIOLATION","evidence":str(error),"compute":colony.account.used,"compute_categories":colony.account.categories}


def tournament(seeds:list[int],*,episodes:int=8,budget:int=100_000,git_sha:str="UNKNOWN",main_sha:str="UNKNOWN")->dict[str,object]:
    started=time.monotonic(); keys=list(HYPOTHESES);raw=[run_hypothesis(k,s,episodes=episodes,budget=budget) for s in seeds for k in keys]
    aggregate={}
    for key in keys:
        values=[float(r["quality"]) for r in raw if r["hypothesis"]==key and r["status"]=="ELIGIBLE"]
        if values:
            mean=statistics.fmean(values);sd=statistics.stdev(values) if len(values)>1 else 0.;margin=1.96*sd/math.sqrt(len(values)) if len(values)>1 else 0.
            aggregate[key]={"mean":mean,"standard_deviation":sd,"median":statistics.median(values),"confidence_interval_95":[mean-margin,mean+margin]}
        else:aggregate[key]={"status":"DISQUALIFIED"}
    config={"seeds":seeds,"episodes":episodes,"budget":budget,"cell_count":6,"ticks":"task-declared","learning_freeze":"held-out frozen","readout_rule":"sign(mean cell output)","damage_schedule":[.2],"accounting":"deterministic primitive operation approximation"}
    manifest={"git_sha":git_sha,"true_main_ancestor_sha":main_sha,"config_hash":hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest(),"hypothesis_versions":{k:"m0-1-v1" for k in keys},"task_versions":{"temporal-memory":"v2","multi-stage":"v2","distributed-parity":"v2","rule-shift":"v2","damage":"v2"},**config,"wallclock_seconds":time.monotonic()-started,"operation_counts":{k:sum(int(r.get("compute",0)) for r in raw if r["hypothesis"]==k) for k in keys}}
    eligible={k:v["mean"] for k,v in aggregate.items() if "mean" in v}; best=max(eligible.values(),default=0.)
    leaders=[k for k,v in eligible.items() if v==best]
    conclusion="NO_CLEAR_WINNER" if len(leaders)!=1 else leaders[0]+" leads (descriptive; causal claims require paired ablation)"
    return {"manifest":manifest,"aggregate":aggregate,"raw":raw,"conclusion":conclusion,
      "controlled_h1_ablations":{name:aggregate.get(name) for name in HYPOTHESES if name.startswith("H1-")}}
