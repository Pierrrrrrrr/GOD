from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class AssemblyPurpose(StrEnum):
    DECOMPOSITION = "decomposition"
    PLANNING = "planning"
    EXPLORATION = "exploration"
    VERIFICATION = "verification"


class GoalStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    VERIFIED = "verified"
    FAILED = "failed"


@dataclass(slots=True)
class Goal:
    id: str
    description: str
    success_criteria: tuple[str, ...]
    constraints: dict[str, Any] = field(default_factory=dict)
    status: GoalStatus = GoalStatus.PENDING
    subgoals: list[str] = field(default_factory=list)
    plan: list[str] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
    action_id: str | None = None


@dataclass(slots=True)
class ActionCandidate:
    action: str
    expected_goal_value: float
    expected_information_gain: float
    expected_capability_gain: float
    cost: float
    risk: float
    irreversibility: float

    @property
    def score(self) -> float:
        return (self.expected_goal_value + self.expected_information_gain
                + self.expected_capability_gain - self.cost - self.risk
                - self.irreversibility)


@dataclass(slots=True)
class Neuromodulators:
    curiosity: float = .5
    urgency: float = .5
    caution: float = .5
    exploration: float = .5
    economic_pressure: float = 0.0
    stagnation: float = 0.0
    consolidation_need: float = 0.0


@dataclass(slots=True)
class Synapse:
    source: str
    target: str
    weight: float
    temporary: bool = False


@dataclass(slots=True)
class DigitalNeuron:
    id: str
    lineage: tuple[str, ...]
    local_state: dict[str, Any] = field(default_factory=dict)
    receptors: set[str] = field(default_factory=set)
    active: bool = False
    specialization: str = "generalist"
    salience: float = 0.0
    confidence: float = 0.5
    metabolic_cost: float = 1.0
    verified_contribution: float = 0.0
    model_pointers: list[str] = field(default_factory=list)
    organ_pointers: list[str] = field(default_factory=list)
    epigenome: dict[str, Any] = field(default_factory=dict)
    genome: dict[str, Any] = field(default_factory=lambda: {"plasticity": .1})
    inbox: list[dict[str, Any]] = field(default_factory=list)

    def activate(self, budget: "ComputeBudget") -> bool:
        if budget.consume(self.metabolic_cost):
            self.active = True
            return True
        return False

    def deactivate(self) -> None:
        self.active = False

    def specialize(self, role: str, stimulus: str) -> None:
        self.specialization = role
        self.epigenome["specialization_trigger"] = stimulus

    def signal(self, receptor: str, payload: Any) -> bool:
        if receptor not in self.receptors:
            return False
        self.inbox.append({"receptor": receptor, "payload": payload})
        return True

    async def process_next(self, budget: "ComputeBudget") -> dict[str, Any] | None:
        """Cooperatively process one addressed message; idle cells do no work."""
        if not self.inbox or not self.activate(budget):
            return None
        await asyncio.sleep(0)
        message = self.inbox.pop(0)
        self.local_state["last_signal"] = message
        self.deactivate()
        return message

    def request_model(self, bus: Any, provider: str, request: dict[str, Any]) -> dict[str, Any]:
        return bus.request(provider, request)

    def request_capability(self, bus: Any, organ: str, operation: str,
                           arguments: dict[str, Any]) -> Any:
        return bus.request(organ, operation, arguments)

    def publish(self, workspace: Any, colony_id: str, topic: str, content: str) -> bool:
        return workspace.publish(WorkspaceItem(colony_id, topic, content, self.salience))


@dataclass(slots=True)
class ComputeBudget:
    available: float
    consumed: float = 0.0

    def consume(self, amount: float) -> bool:
        if amount > self.available - self.consumed:
            return False
        self.consumed += amount
        return True


@dataclass(slots=True)
class WorkspaceItem:
    source_colony: str
    topic: str
    content: str
    salience: float


def public_dict(value: Any) -> dict[str, Any]:
    return asdict(value)
