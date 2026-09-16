from __future__ import annotations

import random
from dataclasses import dataclass, replace


def _matrix(rng: random.Random, rows: int, columns: int, scale: float = .35) -> tuple[tuple[float, ...], ...]:
    return tuple(tuple(rng.uniform(-scale, scale) for _ in range(columns)) for _ in range(rows))


@dataclass(frozen=True, slots=True)
class DigitalCellGenome:
    genome_id: str
    state_dim: int
    message_dim: int
    epigenome_dim: int
    field_dim: int
    w_self: tuple[tuple[float, ...], ...]
    w_msg: tuple[tuple[float, ...], ...]
    w_morph: tuple[tuple[float, ...], ...]
    w_epi: tuple[tuple[float, ...], ...]
    w_input: tuple[tuple[float, ...], ...]
    w_emit: tuple[tuple[float, ...], ...]
    w_emit_epi: tuple[tuple[float, ...], ...]
    predictor: tuple[float, ...]
    receptors: tuple[float, ...]
    emitters: tuple[float, ...]
    differentiation_tendencies: tuple[float, ...]
    connection_preferences: tuple[float, ...]
    inhibition_strength: float = .4
    state_rate: float = .25
    prediction_learning_rate: float = .02
    topology_learning_rate: float = .02
    clone_threshold: float = .9
    dormancy_threshold: float = .05
    pruning_threshold: float = .02
    repair_response: float = .5
    topology_mutation_bound: float = .1
    state_mutation_bound: float = .05
    lineage_family: str = "APGC-v0"

    @classmethod
    def create(cls, seed: int, *, state_dim: int = 16, message_dim: int = 8,
               epigenome_dim: int = 4, field_dim: int = 11) -> "DigitalCellGenome":
        rng = random.Random(seed)
        return cls(f"apgc-{seed}", state_dim, message_dim, epigenome_dim, field_dim,
            _matrix(rng, state_dim, state_dim), _matrix(rng, state_dim, message_dim),
            _matrix(rng, state_dim, field_dim), _matrix(rng, state_dim, epigenome_dim),
            _matrix(rng, state_dim, state_dim), _matrix(rng, message_dim, state_dim),
            _matrix(rng, message_dim, epigenome_dim), tuple(rng.uniform(-.2, .2) for _ in range(state_dim)),
            tuple(rng.random() for _ in range(field_dim)), tuple(rng.random() for _ in range(field_dim)),
            tuple(rng.random() for _ in range(epigenome_dim)), tuple(rng.random() for _ in range(4)))

    def mutate(self, seed: int) -> "DigitalCellGenome":
        rng = random.Random(seed); bound = min(abs(self.state_mutation_bound), .1)
        predictor = tuple(max(-1., min(1., value + rng.uniform(-bound, bound))) for value in self.predictor)
        return replace(self, genome_id=f"{self.genome_id}.m{seed}", predictor=predictor)
