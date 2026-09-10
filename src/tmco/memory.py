from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class MemoryKernel:
    working: dict[str, Any] = field(default_factory=dict)
    episodic: list[dict[str, Any]] = field(default_factory=list)
    semantic: dict[str, Any] = field(default_factory=dict)
    procedural_index: dict[str, str] = field(default_factory=dict)
    self_model: dict[str, Any] = field(default_factory=dict)
    world_model: dict[str, Any] = field(default_factory=dict)

    def relevant(self, terms: set[str], limit: int = 5) -> list[dict[str, Any]]:
        scored = []
        for episode in self.episodic:
            text = str(episode).lower()
            score = sum(term.lower() in text for term in terms)
            if score:
                scored.append((score, episode))
        return [episode for _, episode in sorted(scored, key=lambda x: x[0], reverse=True)[:limit]]

