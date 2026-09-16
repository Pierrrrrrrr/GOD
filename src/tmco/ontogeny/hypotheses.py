from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Hypothesis:
    id: str; name: str; muf: bool; adaptive_topology: bool; differentiation: bool
    prediction: bool; stigmergy: bool


HYPOTHESES = (
    Hypothesis("H0", "fixed simple graph baseline", False, False, False, False, False),
    Hypothesis("H1", "APGC + developmental genome + MUF", True, True, True, True, False),
    Hypothesis("H2", "neural-cellular-automata-like", False, False, False, True, False),
    Hypothesis("H3", "evolving-topology / NEAT-like", False, True, False, False, False),
    Hypothesis("H4", "stigmergic developmental cells", True, False, True, False, True),
    Hypothesis("H5", "active-inference-like predictive cells", False, False, True, True, False),
)
