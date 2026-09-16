from __future__ import annotations

import math
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Sequence

from .genome import DigitalCellGenome
from .types import DevelopmentalAction, DevelopmentalExperience, ResourceCost
from .safety import require_safe_action


def _clip(value: float, low: float = -1., high: float = 1.) -> float:
    return max(low, min(high, value))


def _mul(matrix: Sequence[Sequence[float]], vector: Sequence[float]) -> list[float]:
    return [sum(weight * value for weight, value in zip(row, vector)) for row in matrix]


class CellInterface(ABC):
    @abstractmethod
    def sense(self, values: Sequence[float]) -> None: ...
    @abstractmethod
    def step(self, neighbor_message: Sequence[float], morphogens: Sequence[float]) -> tuple[float, ...]: ...
    @abstractmethod
    def emit(self) -> tuple[float, ...]: ...
    @abstractmethod
    def snapshot(self) -> dict[str, object]: ...
    @abstractmethod
    def resource_cost(self) -> ResourceCost: ...


@dataclass(slots=True)
class DigitalCell(CellInterface):
    genome: DigitalCellGenome
    lineage: str
    seed: int
    parent_id: str | None = None
    generation: int = 0
    mutation_lineage: tuple[str, ...] = ()
    birth_step: int = 0
    state: list[float] = field(init=False)
    epigenome: list[float] = field(init=False)
    message: tuple[float, ...] = field(init=False)
    predictor: list[float] = field(init=False)
    competence: list[float] = field(init=False)
    phenotype_channel: int = 0
    sleeping: bool = False
    experiences: list[DevelopmentalExperience] = field(default_factory=list)
    _input: list[float] = field(init=False)
    _compute: int = 0
    _communication: int = 0

    def __post_init__(self) -> None:
        rng = random.Random(self.seed)
        self.state = [rng.uniform(-.05, .05) for _ in range(self.genome.state_dim)]
        self.epigenome = [rng.random() for _ in range(self.genome.epigenome_dim)]
        self.message = (0.,) * self.genome.message_dim
        self.predictor = list(self.genome.predictor)
        self.competence = [0.] * self.genome.epigenome_dim
        self._input = [0.] * self.genome.state_dim

    def sense(self, values: Sequence[float]) -> None:
        if len(values) > self.genome.state_dim: raise ValueError("sensory input exceeds fixed dimension")
        self._input = [float(value) for value in values] + [0.] * (self.genome.state_dim-len(values))

    def step(self, neighbor_message: Sequence[float], morphogens: Sequence[float]) -> tuple[float, ...]:
        if len(neighbor_message) != self.genome.message_dim or len(morphogens) != self.genome.field_dim:
            raise ValueError("fixed numeric schema mismatch")
        if self.sleeping: return (0.,)*self.genome.message_dim
        terms = [_mul(self.genome.w_self, self.state), _mul(self.genome.w_msg, neighbor_message),
                 _mul(self.genome.w_morph, morphogens), _mul(self.genome.w_epi, self.epigenome),
                 _mul(self.genome.w_input, self._input)]
        rho = _clip(self.genome.state_rate, 0., 1.)
        self.state = [_clip((1-rho)*old + rho*math.tanh(sum(term[index] for term in terms)))
                      for index, old in enumerate(self.state)]
        emitted_state, emitted_epi = _mul(self.genome.w_emit, self.state), _mul(self.genome.w_emit_epi, self.epigenome)
        self.message = tuple(math.tanh(a+b) for a, b in zip(emitted_state, emitted_epi))
        prediction = sum(a*b for a, b in zip(self.predictor, self.state)) / len(self.state)
        target = sum(neighbor_message) / max(1, len(neighbor_message)); error = _clip(target-prediction)
        eta = _clip(self.genome.prediction_learning_rate, 0., .1)
        self.predictor = [_clip(weight + eta*error*value) for weight, value in zip(self.predictor, self.state)]
        self._compute += (self.genome.state_dim * (self.genome.state_dim+self.genome.message_dim+
                          self.genome.field_dim+self.genome.epigenome_dim+self.genome.state_dim))
        self._communication += len(self.message)
        return self.message

    def emit(self) -> tuple[float, ...]:
        return (0.,)*self.genome.message_dim if self.sleeping else self.message
    def snapshot(self) -> dict[str, object]:
        return {"genome_id": self.genome.genome_id, "lineage": self.lineage,
                "state": tuple(self.state), "epigenome": tuple(self.epigenome),
                "message": self.message, "phenotype_channel": self.phenotype_channel,
                "generation": self.generation, "mutation_lineage": self.mutation_lineage,
                "birth_step": self.birth_step}
    def resource_cost(self) -> ResourceCost:
        return ResourceCost(self._compute, self._communication, self._compute/10_000)

    def phenotype_distribution(self, needs: Sequence[float], neighbor_density: Sequence[float],
                               temperature: float = .5) -> tuple[float, ...]:
        if len(needs) != len(self.competence) or len(neighbor_density) != len(self.competence):
            raise ValueError("latent channel schema mismatch")
        scores = [(needs[i]*(self.competence[i]+.1)+self.genome.differentiation_tendencies[i]
                   - self.genome.inhibition_strength*neighbor_density[i])/max(.05, temperature)
                  for i in range(len(needs))]
        offset = max(scores); values = [math.exp(value-offset) for value in scores]; total = sum(values)
        return tuple(value/total for value in values)

    def record_experience(self, experience: DevelopmentalExperience) -> None:
        self.experiences.append(experience)
        if experience.outcome_verified and experience.action is DevelopmentalAction.DIFFERENTIATE:
            self.competence[self.phenotype_channel] = _clip(
                self.competence[self.phenotype_channel] + .05*experience.colony_metric_delta, 0., 1.)

    def propose(self, potentials: dict[DevelopmentalAction, float]) -> DevelopmentalAction:
        for action in potentials: require_safe_action(action)
        return max(sorted(potentials), key=lambda action: potentials[action])


@dataclass(slots=True)
class Organoid(CellInterface):
    units: list[CellInterface]
    _input: tuple[float, ...] = ()

    def sense(self, values: Sequence[float]) -> None:
        self._input = tuple(values)
        for unit in self.units: unit.sense(values)
    def step(self, neighbor_message: Sequence[float], morphogens: Sequence[float]) -> tuple[float, ...]:
        outputs = [unit.step(neighbor_message, morphogens) for unit in self.units]
        return tuple(sum(values)/len(values) for values in zip(*outputs)) if outputs else ()
    def emit(self) -> tuple[float, ...]:
        outputs = [unit.emit() for unit in self.units]
        return tuple(sum(values)/len(values) for values in zip(*outputs)) if outputs else ()
    def snapshot(self) -> dict[str, object]: return {"units": tuple(unit.snapshot() for unit in self.units)}
    def resource_cost(self) -> ResourceCost:
        costs = [unit.resource_cost() for unit in self.units]
        return ResourceCost(sum(x.compute_operations for x in costs),
                            sum(x.communication_values for x in costs), sum(x.energy for x in costs))
