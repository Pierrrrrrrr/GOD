from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .buses import ModelBus


@dataclass(slots=True)
class CognitiveDemand:
    task_type: str
    difficulty: float
    importance: float
    privacy: str = "standard"


@dataclass(slots=True)
class GoalInterpretation:
    desired_outcome: str
    success_evidence: list[str]
    constraints: list[str]
    unknowns: list[str]
    subgoals: list[str]
    risks: list[str]
    next_useful_step: str
    confidence: float
    hypothesis: str


@dataclass(slots=True)
class Subgoal:
    description: str
    status: str = "pending"


@dataclass(slots=True)
class Hypothesis:
    statement: str
    confidence: float
    uncertainties: list[str] = field(default_factory=list)


@dataclass(slots=True)
class VerificationAssessment:
    verified: bool
    confidence: float
    evidence: list[str]
    remaining_unknowns: list[str] = field(default_factory=list)


@dataclass(slots=True)
class HumanApprovalRequest:
    reason: str
    requested_permission: str
    scope: str
    risk: str
    estimated_monetary_cost: float
    reversible: bool
    expires_at: str
    status: str = "pending"
    id: str = field(default_factory=lambda: uuid4().hex)


class RuntimeStore:
    """SQLite WAL store for Phase 2 data; Phase 1 JSON recovery remains untouched."""

    TABLES = ("messages", "goals", "subgoals", "model_registry", "model_calls",
              "colony_interpretations", "assemblies", "approvals", "learning_observations")

    def __init__(self, path: Path):
        path.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path / "runtime.sqlite3", check_same_thread=False)
        self._lock = threading.RLock()
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        for table in self.TABLES:
            self.connection.execute(f"CREATE TABLE IF NOT EXISTS {table} (id TEXT PRIMARY KEY, created REAL NOT NULL, data TEXT NOT NULL)")
        self.connection.commit()

    def put(self, table: str, data: dict[str, Any], identifier: str | None = None) -> str:
        if table not in self.TABLES:
            raise ValueError("unknown runtime table")
        identifier = identifier or uuid4().hex
        with self._lock:
            self.connection.execute(f"INSERT OR REPLACE INTO {table} VALUES (?, ?, ?)",
                                    (identifier, time.time(), json.dumps(data, sort_keys=True)))
            self.connection.commit()
        return identifier

    def all(self, table: str) -> list[dict[str, Any]]:
        if table not in self.TABLES:
            raise ValueError("unknown runtime table")
        with self._lock:
            rows = self.connection.execute(f"SELECT * FROM {table} ORDER BY created").fetchall()
        return [json.loads(row["data"]) | {"id": row["id"]} for row in rows]


class ModelCapabilityRegistry:
    def __init__(self, store: RuntimeStore):
        self.store = store

    def register(self, provider: str, model_id: str, **metadata: Any) -> str:
        identifier = f"{provider}:{model_id}"
        current = next((x for x in self.store.all("model_registry") if x["id"] == identifier), {})
        entry = {"provider": provider, "model_id": model_id, "availability": True,
                 "context_capability": metadata.get("context_capability"),
                 "tool_capability": metadata.get("tool_capability"),
                 "input_modalities": metadata.get("input_modalities", ["text"]),
                 "output_modalities": metadata.get("output_modalities", ["text"]),
                 "estimated_cost": metadata.get("estimated_cost", 0.0),
                 "base_url": metadata.get("base_url", current.get("base_url", "")),
                 "latency_observations": current.get("latency_observations", []),
                 "success_count": current.get("success_count", 0),
                 "failure_count": current.get("failure_count", 0),
                 "task_family_performance": current.get("task_family_performance", {}),
                 "calibration": current.get("calibration", 0.5),
                 "last_tested": current.get("last_tested")}
        self.store.put("model_registry", entry, identifier)
        return identifier

    def route(self, demand: CognitiveDemand, *, exclude: set[str] | None = None) -> dict[str, Any]:
        entries = [entry for entry in self.store.all("model_registry")
                   if entry["availability"] and entry["id"] not in (exclude or set())]
        if not entries:
            raise RuntimeError("no model is available")
        def score(item: dict[str, Any]) -> float:
            quality = item["task_family_performance"].get(demand.task_type, item["calibration"])
            failures = item["failure_count"] / max(1, item["success_count"] + item["failure_count"])
            latency = sum(item["latency_observations"][-5:]) / max(1, len(item["latency_observations"][-5:]))
            privacy_penalty = 10 if demand.privacy == "local" and item["provider"] != "local" else 0
            return quality * (1 + demand.difficulty) - item["estimated_cost"] - latency / 10000 - failures - privacy_penalty
        return max(entries, key=score)

    def observe(self, identifier: str, task_type: str, success: bool, latency_ms: float) -> None:
        entry = next(item for item in self.store.all("model_registry") if item["id"] == identifier)
        entry.pop("id")
        entry["success_count" if success else "failure_count"] += 1
        entry["latency_observations"] = (entry["latency_observations"] + [latency_ms])[-20:]
        total = entry["success_count"] + entry["failure_count"]
        entry["calibration"] = entry["success_count"] / total
        entry["task_family_performance"][task_type] = entry["calibration"]
        entry["last_tested"] = datetime.now(UTC).isoformat()
        self.store.put("model_registry", entry, identifier)


class ModelBackedCognition:
    def __init__(self, bus: ModelBus, registry: ModelCapabilityRegistry, store: RuntimeStore):
        self.bus, self.registry, self.store = bus, registry, store

    def interpret(self, text: str, colony: str, demand: CognitiveDemand,
                  *, exclude: set[str] | None = None) -> tuple[GoalInterpretation, str]:
        model = self.registry.route(demand, exclude=exclude)
        prompt = ("Return JSON only with desired_outcome, success_evidence, constraints, unknowns, "
                  "subgoals, risks, next_useful_step, confidence, hypothesis. Independently interpret "
                  f"this goal as {colony}: {text}")
        started = time.perf_counter()
        success = False
        error = None
        response: dict[str, Any] = {}
        for attempt in range(2):
            try:
                response = self.bus.request(model["provider"], {"model": model["model_id"],
                    "messages": [{"role": "user", "content": prompt}],
                    "response_format": {"type": "json_object"}})
                raw = response["choices"][0]["message"]["content"]
                value = json.loads(raw) if isinstance(raw, str) else raw
                interpretation = GoalInterpretation(**value)
                success = True
                break
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as caught:
                error = str(caught)
                prompt += " Your prior response was invalid; include every required field."
        latency = (time.perf_counter() - started) * 1000
        self.registry.observe(model["id"], demand.task_type, success, latency)
        self.store.put("model_calls", {"provider": model["provider"], "model": model["model_id"],
            "purpose": f"interpret:{colony}", "latency_ms": latency, "token_usage": response.get("usage", {}),
            "estimated_cost": model["estimated_cost"], "success": success, "failure": error})
        if not success:
            raise ValueError(f"model did not produce a valid interpretation: {error}")
        return interpretation, model["id"]
