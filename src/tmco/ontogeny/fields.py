from __future__ import annotations

from dataclasses import dataclass

from .graph import AdaptiveGraph

FIELD_NAMES = ("uncertainty", "memory", "verification", "prediction", "speed", "compute",
               "novelty", "damage", "conflict", "goal", "security")


@dataclass(slots=True)
class MorphogenFields:
    node_count: int
    values: dict[str, list[float]]

    @classmethod
    def zero(cls, node_count: int) -> "MorphogenFields":
        return cls(node_count, {name: [0.]*node_count for name in FIELD_NAMES})

    def step(self, graph: AdaptiveGraph, sources: dict[str, list[float]], *, diffusion: float = .2,
             decay: float = .1, dt: float = .25) -> None:
        for name in FIELD_NAMES:
            current = self.values[name]; source = sources.get(name, [0.]*self.node_count)
            updated = []
            for node, value in enumerate(current):
                flow = 0.
                incident = [edge for edge in graph.edges.values() if node in (edge.source, edge.target)]
                for edge in incident:
                    other = edge.target if edge.source == node else edge.source
                    flow += abs(edge.weight)*(current[other]-value)
                updated.append(max(-1., min(1., value+dt*(diffusion*flow+source[node]-decay*value))))
            self.values[name] = updated

    def at(self, node: int) -> tuple[float, ...]: return tuple(self.values[name][node] for name in FIELD_NAMES)


def body_deficit(observed: dict[str, float], context: dict[str, float]) -> dict[str, float]:
    base = {"performance": .8, "accuracy": .8, "robustness": .7, "adaptability": .6,
            "memory": .6, "verification": .6, "communication_efficiency": .6,
            "compute_efficiency": .6, "diversity": .5, "repair_capacity": .5, "security": 1.}
    if context.get("novelty", 0) > .5: base["adaptability"] = .9
    if context.get("damage", 0) > 0: base["repair_capacity"] = .9
    if context.get("scarcity", 0) > .5: base.update(communication_efficiency=.9, compute_efficiency=.9)
    if context.get("verification_sensitive", 0) > .5: base["verification"] = .95
    return {key: max(-1., min(1., target-observed.get(key, 0.))) for key, target in base.items()}


def deficit_sources(deficit: dict[str, float], node_count: int, context: dict[str, float]) -> dict[str, list[float]]:
    average = sum(deficit.values())/max(1, len(deficit))
    mapping = {name: [0.]*node_count for name in FIELD_NAMES}
    mapping["goal"][0] = average; mapping["damage"][0] = context.get("damage", 0)
    mapping["novelty"][0] = context.get("novelty", 0); mapping["security"][0] = deficit.get("security", 0)
    mapping["verification"][0] = deficit.get("verification", 0)
    return mapping
