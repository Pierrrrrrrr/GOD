from __future__ import annotations

from dataclasses import dataclass

from .types import ResourceBudget


@dataclass(slots=True)
class Edge:
    source: int; target: int; weight: float
    reliability: float = .5; communication_cost: float = 1.; age: int = 0
    verified_usefulness: float = 0.


class AdaptiveGraph:
    def __init__(self, node_count: int, budget: ResourceBudget):
        if node_count < 1 or node_count > budget.max_cells: raise ValueError("cell budget exceeded")
        self.node_count, self.budget = node_count, budget
        self.edges: dict[tuple[int, int], Edge] = {}; self._mutations = 0

    def reset_step(self) -> None: self._mutations = 0
    def add(self, source: int, target: int, weight: float = .5) -> None:
        if source == target or not 0 <= source < self.node_count or not 0 <= target < self.node_count:
            raise ValueError("invalid graph transition")
        if len(self.edges) >= self.budget.max_edges or self.degree(source) >= self.budget.max_degree:
            raise ValueError("topology resource limit exceeded")
        if self._mutations >= self.budget.max_topology_mutations_per_step:
            raise ValueError("topology mutation limit exceeded")
        self.edges[(source, target)] = Edge(source, target, max(-1., min(1., weight))); self._mutations += 1

    def drop(self, source: int, target: int) -> None:
        if self._mutations >= self.budget.max_topology_mutations_per_step:
            raise ValueError("topology mutation limit exceeded")
        if (source, target) not in self.edges: raise ValueError("unknown edge")
        del self.edges[(source, target)]; self._mutations += 1

    def degree(self, node: int) -> int: return sum(source == node for source, _ in self.edges)
    def neighbors(self, node: int) -> tuple[Edge, ...]:
        return tuple(self.edges[key] for key in sorted(self.edges) if key[1] == node)
    def adapt(self, edge: Edge, predictive_utility: float, verified_contribution: float,
              redundancy: float) -> None:
        delta = .02*(predictive_utility+verified_contribution-.1*edge.communication_cost-.1*redundancy)
        edge.weight = max(-1., min(1., edge.weight+delta)); edge.age += 1

    def ring(self) -> None:
        for node in range(self.node_count):
            self.add(node, (node+1) % self.node_count)
            if self._mutations >= self.budget.max_topology_mutations_per_step: self.reset_step()
