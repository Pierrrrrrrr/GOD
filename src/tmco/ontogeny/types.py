from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class DevelopmentalAction(StrEnum):
    STAY = "STAY"; REWIRE_ADD = "REWIRE_ADD"; REWIRE_DROP = "REWIRE_DROP"
    DIFFERENTIATE = "DIFFERENTIATE"; CLONE_REQUEST = "CLONE_REQUEST"
    SLEEP = "SLEEP"; WAKE = "WAKE"; PRUNE_REQUEST = "PRUNE_REQUEST"


SAFE_ACTIONS = frozenset(DevelopmentalAction)


@dataclass(frozen=True, slots=True)
class ResourceBudget:
    max_cells: int = 32
    max_edges: int = 64
    max_degree: int = 4
    compute_operations: int = 100_000
    communication_values: int = 20_000
    mutation_opportunities: int = 32
    max_topology_mutations_per_step: int = 2


@dataclass(frozen=True, slots=True)
class ResourceCost:
    compute_operations: int
    communication_values: int
    energy: float


@dataclass(frozen=True, slots=True)
class MechanismEvidence:
    mechanism_hash: str
    mechanism_type: str
    task_class: str
    benchmark_delta: float
    resource_delta: float
    robustness_delta: float
    failure_modes: tuple[str, ...]
    source_lineage: str


@dataclass(frozen=True, slots=True)
class DevelopmentalExperience:
    previous_summary: tuple[float, ...]
    field_summary: tuple[float, ...]
    action: DevelopmentalAction
    local_metric_delta: float
    colony_metric_delta: float
    resource_delta: float
    outcome_verified: bool


@dataclass(frozen=True, slots=True)
class DevelopmentalFeatures:
    affinity: float; deficit_match: float; complementarity: float
    expected_information_gain: float; repair_urgency: float; goal_relevance: float
    energy_cost: float; communication_cost: float; redundancy: float
    reconfiguration_cost: float

    def potential(self, weights: tuple[float, ...]) -> float:
        if len(weights) != 10 or any(not 0 <= value <= 2 for value in weights):
            raise ValueError("developmental potential weights must be bounded and inspectable")
        positive = (self.affinity, self.deficit_match, self.complementarity,
                    self.expected_information_gain, self.repair_urgency, self.goal_relevance)
        negative = (self.energy_cost, self.communication_cost, self.redundancy,
                    self.reconfiguration_cost)
        return sum(a*b for a, b in zip(weights[:6], positive))-sum(
            a*b for a, b in zip(weights[6:], negative))
