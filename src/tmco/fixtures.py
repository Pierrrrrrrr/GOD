"""Deterministic cognition fixtures for tests and local demonstration only."""
from __future__ import annotations

import json
from typing import Any

from .executive import ActionResult, Observation
from .types import ActionCandidate, Goal


class DeterministicCognitionFixture:
    def decompose(self, goal: Goal) -> list[str]:
        return [f"establish evidence for: {criterion}" for criterion in goal.success_criteria]

    def candidates(self, goal: Goal) -> list[ActionCandidate]:
        subject = goal.description[:48]
        return [
            ActionCandidate(f"inspect evidence relevant to {subject}", .7, .5, .1, .2, .1, .0),
            ActionCandidate(f"record a reversible trial for {subject}", .8, .3, .2, .1, .1, .0),
        ]

    def verify(self, goal: Goal, observation: str) -> bool:
        return bool(observation.strip()) and bool(goal.success_criteria)


class DeterministicExecutorFixture:
    def __init__(self) -> None:
        self.results: dict[str, ActionResult] = {}
        self.effect_count = 0

    def execute(self, action: str, action_id: str) -> ActionResult:
        if action_id not in self.results:
            self.effect_count += 1
            self.results[action_id] = ActionResult(action_id, {"action": action, "result": "fixture-success"})
        return self.results[action_id]


class DeterministicObservationFixture:
    def observe(self, result: ActionResult) -> Observation:
        return Observation(result.action_id, f"fixture evidence: {result.output['result']}",
                           "deterministic-test-fixture")


class FakeProvider:
    """Scriptable model provider which ModelBus rejects in production mode."""

    test_only = True

    def __init__(self, *, confidence: float = .7, hypothesis: str = "inspect evidence"):
        self.confidence = confidence
        self.hypothesis = hypothesis
        self.calls: list[dict[str, Any]] = []

    def infer(self, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(request)
        prompt = request["messages"][-1]["content"]
        colony = "Saphira-B" if "Saphira-B" in prompt else "Saphira-A"
        value = {"desired_outcome": "achieve the requested outcome",
                 "success_evidence": ["observable evidence"], "constraints": [],
                 "unknowns": ["current conditions"], "subgoals": ["gather evidence"],
                 "risks": ["insufficient evidence"],
                 "next_useful_step": f"{colony} gathers targeted evidence",
                 "confidence": self.confidence,
                 "hypothesis": f"{self.hypothesis} from {colony}"}
        return {"choices": [{"message": {"content": json.dumps(value)}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20}}

    def models(self) -> list[dict[str, Any]]:
        return [{"id": "fake-model"}]
