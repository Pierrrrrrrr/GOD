from __future__ import annotations

from dataclasses import dataclass

from .cell import DigitalCell
from .fields import MorphogenFields
from .graph import AdaptiveGraph
from .types import DevelopmentalAction, MechanismEvidence, ResourceBudget


@dataclass(slots=True)
class ResourceGovernor:
    budget: ResourceBudget
    compute_used: int = 0
    communication_used: int = 0
    mutations_used: int = 0

    def account(self, compute: int, communication: int) -> None:
        if self.compute_used+compute > self.budget.compute_operations: raise RuntimeError("compute budget exceeded")
        if self.communication_used+communication > self.budget.communication_values: raise RuntimeError("communication budget exceeded")
        self.compute_used += compute; self.communication_used += communication

    def approve_population(self, action: DevelopmentalAction, cell_count: int) -> bool:
        if action not in {DevelopmentalAction.CLONE_REQUEST, DevelopmentalAction.PRUNE_REQUEST}: return False
        if self.mutations_used >= self.budget.mutation_opportunities: return False
        allowed = (action is DevelopmentalAction.CLONE_REQUEST and cell_count < self.budget.max_cells) or (
                   action is DevelopmentalAction.PRUNE_REQUEST and cell_count > 1)
        if allowed: self.mutations_used += 1
        return allowed


class CellColony:
    def __init__(self, cells: list[DigitalCell], graph: AdaptiveGraph, budget: ResourceBudget):
        if len(cells) != graph.node_count: raise ValueError("cell graph mismatch")
        self.cells, self.graph, self.fields = cells, graph, MorphogenFields.zero(len(cells))
        self.governor = ResourceGovernor(budget)

    def tick(self, sensory: list[tuple[float, ...]], sources: dict[str, list[float]] | None = None) -> tuple[float, ...]:
        prior_messages = [cell.emit() for cell in self.cells]
        self.fields.step(self.graph, sources or {})
        outputs = []
        for index, cell in enumerate(self.cells):
            cell.sense(sensory[index])
            incoming = self.graph.neighbors(index)
            aggregate = [0.]*cell.genome.message_dim
            for edge in incoming:
                for position, value in enumerate(prior_messages[edge.source]): aggregate[position] += edge.weight*value
            if incoming: aggregate = [value/len(incoming) for value in aggregate]
            before = cell.resource_cost(); outputs.append(cell.step(aggregate, self.fields.at(index)))
            after = cell.resource_cost(); self.governor.account(after.compute_operations-before.compute_operations,
                after.communication_values-before.communication_values)
        return tuple(sum(values)/len(values) for values in zip(*outputs))

    def cross_test(self, evidence: MechanismEvidence, measured_delta: float) -> bool:
        """Record no state transfer; accept only an independent receiving-lineage measurement."""
        lineages = {cell.lineage for cell in self.cells}
        if evidence.source_lineage in lineages:
            raise ValueError("source lineage cannot certify its own transferred mechanism")
        return measured_delta > 0 and measured_delta >= evidence.benchmark_delta
