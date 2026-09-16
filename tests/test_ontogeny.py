import math

import pytest

from tmco.ontogeny.cell import CellInterface, DigitalCell, Organoid
from tmco.ontogeny.colony import ResourceGovernor
from tmco.ontogeny.fields import MorphogenFields
from tmco.ontogeny.genome import DigitalCellGenome
from tmco.ontogeny.graph import AdaptiveGraph
from tmco.ontogeny.safety import FORBIDDEN_INTERFACES
from tmco.ontogeny.types import (DevelopmentalAction, DevelopmentalExperience,
                                 DevelopmentalFeatures, MechanismEvidence, ResourceBudget)


def test_cell_transition_is_deterministic_bounded_numeric_and_safe():
    genome = DigitalCellGenome.create(7); first = DigitalCell(genome, "Saphira-A", 11)
    second = DigitalCell(genome, "Saphira-A", 11)
    for cell in (first, second):
        cell.sense((1., -1.)); cell.step((0.,)*8, (0.,)*11)
    assert first.snapshot() == second.snapshot()
    assert len(first.emit()) == 8 and all(-1 <= value <= 1 and math.isfinite(value) for value in first.state)
    assert not FORBIDDEN_INTERFACES.intersection(dir(first))
    assert not hasattr(first, "emergency") and not hasattr(first, "owner")
    assert not FORBIDDEN_INTERFACES.intersection(DigitalCellGenome.__dataclass_fields__)
    assert not FORBIDDEN_INTERFACES.intersection(DigitalCellGenome.create(7).mutate(8).__dataclass_fields__)
    with pytest.raises((PermissionError, AttributeError, TypeError)):
        first.propose({"SHELL": 999})


def test_morphogen_source_diffusion_decay_and_graph_limits():
    budget = ResourceBudget(max_cells=4, max_edges=4, max_degree=1, max_topology_mutations_per_step=4)
    graph = AdaptiveGraph(3, budget); graph.add(0, 1); graph.add(1, 2)
    fields = MorphogenFields.zero(3)
    fields.step(graph, {"goal": [1., 0., 0.]}); assert fields.values["goal"][0] > 0
    fields.step(graph, {}); assert fields.values["goal"][1] > 0
    prior = sum(abs(x) for x in fields.values["goal"])
    for _ in range(80): fields.step(graph, {}, decay=.5)
    assert sum(abs(x) for x in fields.values["goal"]) < prior
    assert all(-1 <= x <= 1 for values in fields.values.values() for x in values)
    with pytest.raises(ValueError): graph.add(0, 0)
    with pytest.raises(ValueError): graph.add(0, 2)


def test_lateral_inhibition_verified_learning_and_recursive_composition():
    genome = DigitalCellGenome.create(4); cell = DigitalCell(genome, "Saphira-A", 1)
    sparse = cell.phenotype_distribution([1.]*4, [0.]*4)
    dense = cell.phenotype_distribution([1.]*4, [1.,0.,0.,0.])
    assert dense[0] < sparse[0]
    before = tuple(cell.competence)
    cell.record_experience(DevelopmentalExperience((0.,), (0.,), DevelopmentalAction.DIFFERENTIATE,
                                                    1., 1., 0., False))
    assert tuple(cell.competence) == before
    cell.record_experience(DevelopmentalExperience((0.,), (0.,), DevelopmentalAction.DIFFERENTIATE,
                                                    1., 1., 0., True))
    assert cell.competence[0] > before[0]
    organoid = Organoid([DigitalCell(genome, "Saphira-A", 1), DigitalCell(genome, "Saphira-B", 2)])
    assert isinstance(cell, CellInterface) and isinstance(organoid, CellInterface)
    organoid.sense((.5,)); first = organoid.step((0.,)*8, (0.,)*11)
    clone = Organoid([DigitalCell(genome, "Saphira-A", 1), DigitalCell(genome, "Saphira-B", 2)])
    clone.sense((.5,)); assert first == clone.step((0.,)*8, (0.,)*11)


def test_governor_and_lineages_are_separate_and_evidence_is_compact():
    budget = ResourceBudget(max_cells=2, mutation_opportunities=1); governor = ResourceGovernor(budget)
    assert governor.approve_population(DevelopmentalAction.CLONE_REQUEST, 1)
    assert not governor.approve_population(DevelopmentalAction.CLONE_REQUEST, 1)
    with pytest.raises(RuntimeError): governor.account(budget.compute_operations+1, 0)
    genome = DigitalCellGenome.create(2)
    a, b = DigitalCell(genome, "Saphira-A", 10), DigitalCell(genome, "Saphira-B", 11)
    assert a.genome == b.genome and a.state != b.state and a.experiences is not b.experiences
    evidence = MechanismEvidence("hash", "rewire", "parity", .1, 0., .1, (), "Saphira-A")
    assert evidence.source_lineage == "Saphira-A"
    # Evidence can be examined; applying it still requires an independent B evaluation.
    assert not hasattr(evidence, "learned_state") and b.experiences == []
    b_graph = AdaptiveGraph(1, ResourceBudget(max_cells=1)); from tmco.ontogeny.colony import CellColony
    assert CellColony([b], b_graph, ResourceBudget(max_cells=1)).cross_test(evidence, .11)


def test_developmental_potential_is_bounded_configuration_not_safety():
    features = DevelopmentalFeatures(1, 1, 1, 1, 1, 1, .1, .1, .1, .1)
    assert features.potential((1,)*10) == pytest.approx(5.6)
    with pytest.raises(ValueError): features.potential((99,)*10)
