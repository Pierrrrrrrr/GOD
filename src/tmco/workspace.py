from __future__ import annotations

from dataclasses import dataclass, field

from .types import WorkspaceItem


@dataclass(slots=True)
class GlobalWorkspace:
    salience_threshold: float = .7
    capacity: int = 8
    items: list[WorkspaceItem] = field(default_factory=list)

    def publish(self, item: WorkspaceItem) -> bool:
        if item.salience < self.salience_threshold:
            return False
        self.items.append(item)
        self.items.sort(key=lambda entry: entry.salience, reverse=True)
        del self.items[self.capacity:]
        return True

    def read_for(self, colony_id: str) -> tuple[WorkspaceItem, ...]:
        return tuple(item for item in self.items if item.source_colony != colony_id)

