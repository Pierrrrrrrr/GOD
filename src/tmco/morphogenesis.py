from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .runtime import Colony
from .types import AssemblyPurpose, ComputeBudget, DigitalNeuron, Goal


@dataclass(frozen=True, slots=True)
class FormationDecision:
    colony_name: str
    purpose: AssemblyPurpose
    neuron_ids: tuple[str, ...]
    assembly_id: str


class AssemblyFormationPolicy:
    """Deterministic state-sensitive allocation, not a fixed role assignment."""

    def requirements(self, goal: Goal) -> tuple[AssemblyPurpose, ...]:
        explicit = goal.constraints.get("required_functions")
        if explicit:
            return tuple(AssemblyPurpose(value) for value in explicit)
        text = goal.description.lower()
        functions = [AssemblyPurpose.DECOMPOSITION, AssemblyPurpose.PLANNING,
                     AssemblyPurpose.VERIFICATION]
        if any(word in text for word in ("unknown", "discover", "explore", "unfamiliar")):
            functions.insert(1, AssemblyPurpose.EXPLORATION)
        return tuple(functions)

    def form(self, colonies: dict[str, Colony], goal: Goal,
             budgets: dict[str, ComputeBudget]) -> list[FormationDecision]:
        decisions = []
        used: set[str] = set()
        for purpose in self.requirements(goal):
            ranked_colonies = sorted(colonies.items(), key=lambda item: (
                -self._colony_score(item[0], item[1], goal, purpose), item[0]))
            name, colony = ranked_colonies[0]
            affordable = max(1, min(3, int((budgets[name].available - budgets[name].consumed))))
            ranked = sorted(colony.neurons.values(), key=lambda neuron: (
                -self._neuron_score(colony, neuron, goal, purpose, used), neuron.id))
            members = tuple(neuron.id for neuron in ranked[:affordable])
            assembly = colony.form_assembly(purpose, members, budgets[name])
            used.update(members)
            decisions.append(FormationDecision(name, purpose, members, assembly.id))
        return decisions

    def _colony_score(self, name: str, colony: Colony, goal: Goal,
                      purpose: AssemblyPurpose) -> float:
        competence = sum((n.verified_contribution + n.confidence)
                         * (2.0 if n.specialization == purpose.value else .1)
                         for n in colony.neurons.values())
        novelty = self._stable(f"{goal.description}|{purpose}|{name}")
        modulation = (colony.modulators.exploration if purpose == AssemblyPurpose.EXPLORATION
                      else colony.modulators.caution if purpose == AssemblyPurpose.VERIFICATION
                      else colony.modulators.curiosity)
        return competence / max(1, len(colony.neurons)) + modulation + novelty

    def _neuron_score(self, colony: Colony, neuron: DigitalNeuron, goal: Goal,
                      purpose: AssemblyPurpose, used: set[str]) -> float:
        specialization = 1.5 if neuron.specialization == purpose.value else 0.2 if neuron.specialization == "generalist" else 0.0
        affinity = max((edge.weight for edge in colony.synapses.values()
                        if edge.source == neuron.id or edge.target == neuron.id), default=0.0)
        diversity = .7 if neuron.id not in used else -.4
        stable_cell_name = neuron.id.rsplit(":", 1)[-1]
        novelty = self._stable(f"{goal.description}|{purpose}|{stable_cell_name}")
        return specialization + neuron.verified_contribution + neuron.confidence + affinity + diversity + novelty

    @staticmethod
    def _stable(value: str) -> float:
        return int.from_bytes(hashlib.sha256(value.encode()).digest()[:4], "big") / 2**32
