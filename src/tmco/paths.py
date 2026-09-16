from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ProductPaths:
    """The single path contract shared by the product and owner controls."""

    data_root: Path

    @classmethod
    def resolve(cls, data: Path) -> "ProductPaths":
        return cls(data.expanduser().resolve())

    @property
    def organism_root(self) -> Path: return self.data_root / "organism"
    @property
    def emergency_state(self) -> Path: return self.organism_root / "emergency-state.json"
    @property
    def emergency_verifier(self) -> Path: return self.organism_root / "emergency-verifier.json"
    @property
    def awakening_db(self) -> Path: return self.data_root / "awakening.sqlite3"
    @property
    def embodiment_db(self) -> Path: return self.data_root / "embodiment.sqlite3"
    @property
    def owner_capabilities_db(self) -> Path: return self.data_root / "owner_capabilities.sqlite3"
