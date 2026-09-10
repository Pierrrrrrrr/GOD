from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


@dataclass(slots=True)
class EvolutionCandidate:
    id: str
    parent: str
    architecture: dict[str, Any]
    status: str = "pending_benchmark"
    benchmark: dict[str, float] | None = None
    sister_audit: str | None = None


@dataclass(slots=True)
class EvolutionArchive:
    champion_id: str
    champion_architecture: dict[str, Any]
    candidates: dict[str, EvolutionCandidate] = field(default_factory=dict)

    def branch(self, mutation: dict[str, Any]) -> EvolutionCandidate:
        architecture = deepcopy(self.champion_architecture)
        architecture.update(mutation)
        candidate = EvolutionCandidate(uuid4().hex, self.champion_id, architecture)
        self.candidates[candidate.id] = candidate
        return candidate

    def decide(self, candidate_id: str, benchmark: dict[str, float], sister_audit: str,
               promote: bool) -> None:
        candidate = self.candidates[candidate_id]
        candidate.benchmark, candidate.sister_audit = benchmark, sister_audit
        candidate.status = "promoted" if promote else "rejected"
        if promote:
            self.champion_id = candidate.id
            self.champion_architecture = deepcopy(candidate.architecture)

