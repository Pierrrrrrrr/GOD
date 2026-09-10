from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .types import ActionCandidate, Goal


class Cognition(Protocol):
    def decompose(self, goal: Goal) -> list[str]: ...
    def candidates(self, goal: Goal) -> list[ActionCandidate]: ...
    def verify(self, goal: Goal, observation: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class ActionResult:
    action_id: str
    output: Any


@dataclass(frozen=True, slots=True)
class Observation:
    action_id: str
    evidence: str
    provenance: str


class ActionExecutor(Protocol):
    """External effects must honor action_id as an idempotency key."""
    def execute(self, action: str, action_id: str) -> ActionResult: ...


class ObservationProvider(Protocol):
    def observe(self, result: ActionResult) -> Observation: ...


@dataclass(slots=True)
class ExecutiveKernel:
    cognition: Cognition

    def prepare(self, goal: Goal) -> ActionCandidate:
        goal.subgoals = self.cognition.decompose(goal)
        options = self.cognition.candidates(goal)
        if not options:
            raise ValueError("cognition produced no actionable candidate")
        selected = max(options, key=lambda option: option.score)
        goal.plan = [selected.action]
        return selected

    def verify(self, goal: Goal, observation: str) -> bool:
        goal.observations.append(observation)
        return self.cognition.verify(goal, observation)
