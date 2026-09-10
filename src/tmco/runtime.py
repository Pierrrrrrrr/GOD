from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from .types import AssemblyPurpose, ComputeBudget, DigitalNeuron, Neuromodulators, Synapse


@dataclass(slots=True)
class Assembly:
    id: str
    purpose: AssemblyPurpose
    neuron_ids: tuple[str, ...]


@dataclass(slots=True)
class Colony:
    id: str
    neurons: dict[str, DigitalNeuron]
    synapses: dict[str, Synapse] = field(default_factory=dict)
    assemblies: dict[str, Assembly] = field(default_factory=dict)
    lineage: list[str] = field(default_factory=list)
    modulators: Neuromodulators = field(default_factory=Neuromodulators)
    memories: list[str] = field(default_factory=list)

    @classmethod
    def create(cls, name: str, population: int = 6) -> "Colony":
        identity = f"{name}-{uuid4().hex[:12]}"
        neurons = {}
        for index in range(population):
            neuron_id = f"{identity}:n{index}"
            neurons[neuron_id] = DigitalNeuron(neuron_id, (identity, neuron_id),
                                               receptors={"goal", "observation"})
        colony = cls(identity, neurons, lineage=[identity])
        ids = list(neurons)
        for source, target in zip(ids, ids[1:]):
            colony.connect(source, target, .4)
        return colony

    def connect(self, source: str, target: str, weight: float, temporary: bool = False) -> str:
        if source not in self.neurons or target not in self.neurons:
            raise KeyError("synapses cannot cross colony boundaries")
        key = f"{source}->{target}"
        if temporary and key in self.synapses:
            return key
        self.synapses[key] = Synapse(source, target, weight, temporary)
        return key

    def disconnect(self, source: str, target: str) -> None:
        self.synapses.pop(f"{source}->{target}", None)

    def adapt_weight(self, source: str, target: str, verified: bool) -> float:
        synapse = self.synapses[f"{source}->{target}"]
        synapse.weight = min(1.0, max(0.0, synapse.weight + (.1 if verified else -.1)))
        return synapse.weight

    def form_assembly(self, purpose: AssemblyPurpose, neuron_ids: tuple[str, ...],
                      budget: ComputeBudget) -> Assembly:
        if not neuron_ids or any(n not in self.neurons for n in neuron_ids):
            raise ValueError("assembly membership must belong to this colony")
        for neuron_id in neuron_ids:
            self.neurons[neuron_id].activate(budget)
        assembly = Assembly(uuid4().hex, purpose, neuron_ids)
        self.assemblies[assembly.id] = assembly
        for source, target in zip(neuron_ids, neuron_ids[1:]):
            self.connect(source, target, .5, temporary=True)
        return assembly

    def dissolve_assembly(self, assembly_id: str) -> None:
        assembly = self.assemblies.pop(assembly_id)
        members = set(assembly.neuron_ids)
        for neuron_id in members:
            self.neurons[neuron_id].deactivate()
        for key, edge in list(self.synapses.items()):
            if edge.temporary and edge.source in members and edge.target in members:
                del self.synapses[key]

    def graph(self) -> list[tuple[str, str, float]]:
        return sorted((s.source, s.target, s.weight) for s in self.synapses.values())
