from dataclasses import asdict

from tmco.ontogeny import (DevelopmentalAction, DigitalCell, DigitalColony,
    Epigenome, HYPOTHESES, OperationAccount, ResourceBudgetViolation,
    best_isolated_cell, body_deficit, deficit_sources, evaluate_frozen,
    independent_ensemble, multi_stage_episode, parity_episode, run_hypothesis,
    temporal_memory_episode, tournament)


def test_receptor_causally_gates_field() -> None:
    normal=DigitalCell("a",HYPOTHETIC_GENOME); blocked=DigitalCell("b",type(HYPOTHETIC_GENOME)((0.,1.,1.,1.),HYPOTHETIC_GENOME.emitters,.2,.35))
    assert normal.perceive((1.,0.,0.,0.),OperationAccount(100))[0]>0
    assert blocked.perceive((1.,0.,0.,0.),OperationAccount(100))[0]==0


from tmco.ontogeny import CellGenome
HYPOTHETIC_GENOME=CellGenome()


def test_body_deficit_drives_muf_development_and_experience() -> None:
    colony=DigitalColony(2,HYPOTHESES["H1"]);before=dict(colony.fields)
    deficit=body_deficit({"goal":0.,"damage":1.,"novelty":0.,"scarcity":.5},{"goal":1.,"damage":1.,"novelty":1.,"scarcity":.5})
    assert deficit_sources(deficit,sorted(colony.cells))["c0"][0]==1
    experiences=colony.develop({"goal":0.,"damage":1.,"novelty":0.,"scarcity":.5},{"goal":1.,"damage":1.,"novelty":1.,"scarcity":.5})
    assert colony.fields!=before and experiences and all(e.verified for e in experiences)


def test_muf_prediction_and_history_have_causal_effects() -> None:
    full=DigitalColony(3,HYPOTHESES["H1"]); no_muf=DigitalColony(3,HYPOTHESES["H1-no-MUF"])
    for colony in (full,no_muf):
        for cell in colony.cells.values():cell.prediction_error=.9
    context={"goal":0.,"damage":.5,"novelty":0.,"scarcity":.5};target={"goal":1.,"damage":1.,"novelty":1.,"scarcity":.5}
    full.develop(context,target);no_muf.develop(context,target)
    assert full.fields!=no_muf.fields
    assert asdict(full.cells["c0"].epigenome)!=asdict(no_muf.cells["c0"].epigenome)
    no_prediction=DigitalColony(3,HYPOTHESES["H1-no-prediction-coupling"])
    for c in no_prediction.cells.values():c.prediction_error=.9
    no_prediction.develop(context,target)
    assert asdict(full.cells["c0"].epigenome)!=asdict(no_prediction.cells["c0"].epigenome)


def test_every_developmental_action_executes_under_governor() -> None:
    colony=DigitalColony(4,HYPOTHESES["H1"]);colony.governor.limits=type(colony.governor.limits)(20,40,10,20);colony.governor.begin()
    assert colony._execute("c0",DevelopmentalAction.STAY)
    assert colony._execute("c0",DevelopmentalAction.DIFFERENTIATE)
    assert colony._execute("c0",DevelopmentalAction.SLEEP) and colony.cells["c0"].sleeping
    assert colony._execute("c0",DevelopmentalAction.WAKE) and not colony.cells["c0"].sleeping
    assert colony._execute("c0",DevelopmentalAction.REWIRE_ADD)
    assert colony._execute("c0",DevelopmentalAction.REWIRE_DROP)
    size=len(colony.cells);assert colony._execute("c0",DevelopmentalAction.CLONE_REQUEST) and len(colony.cells)==size+1
    clone=next(i for i,c in colony.cells.items() if c.parent_id=="c0");assert clone!="c0"
    assert colony._execute(clone,DevelopmentalAction.PRUNE_REQUEST) and clone not in colony.cells


def test_tasks_are_temporal_distributed_and_do_not_reveal_answers() -> None:
    ids=["c0","c1","c2"]
    memory=temporal_memory_episode(1,4,ids);multi=multi_stage_episode(1,0,ids);parity=parity_episode([1,-1,1],ids,3)
    assert len(memory.observations)==5 and not memory.metadata["answer_present_at_query"] and all(v==0 for v in memory.observations[-1].values())
    assert multi.metadata["stages_separated"] and len(multi.observations)==3
    assert set(parity.observations[0])==set(ids) and all(len(stage)==len(ids) for stage in parity.observations)


def test_frozen_and_real_digitalcell_comparators() -> None:
    colony=DigitalColony(5,HYPOTHESES["H1"]);episodes=[temporal_memory_episode(1,2,sorted(colony.cells))]
    before=[c.predictor for c in colony.cells.values()]
    assert 0<=evaluate_frozen(colony,episodes)<=1 and before==[c.predictor for c in colony.cells.values()]
    assert 0<=best_isolated_cell(colony,episodes)<=1
    assert 0<=independent_ensemble(colony,episodes)<=1


def test_budget_violation_disqualifies_and_costs_are_visible() -> None:
    result=run_hypothesis("H1",8,budget=2)
    assert result["status"]=="DISQUALIFIED" and result["violation"]=="RESOURCE_BUDGET_VIOLATION"
    result=run_hypothesis("H1",8,budget=100_000)
    assert {"muf_diffusion","developmental_features","potential_ranking","readout"}<set(result["compute_categories"])


def test_protocol_is_reproducible_distinct_and_reports_ablations() -> None:
    one=tournament([11],episodes=2);two=tournament([11],episodes=2);other=tournament([12],episodes=2)
    def logical(report):return report["aggregate"],[(x["hypothesis"],x.get("quality"),x["status"]) for x in report["raw"]]
    assert logical(one)==logical(two) and logical(one)!=logical(other)
    assert set(HYPOTHESES)<=set(one["aggregate"])
    assert set(one["controlled_h1_ablations"])=={"H1-no-MUF","H1-fixed-topology","H1-no-differentiation","H1-no-prediction-coupling"}
    damage=next(x for x in one["raw"] if x["hypothesis"]=="H1")["damage"]
    assert damage["victims_remained_absent"]
