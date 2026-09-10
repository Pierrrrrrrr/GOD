from __future__ import annotations

from dataclasses import asdict
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from .buses import ModelBus
from .fixtures import DeterministicCognitionFixture
from .phase2 import (CognitiveDemand, HumanApprovalRequest, ModelBackedCognition,
                     ModelCapabilityRegistry, RuntimeStore)
from .providers import GeminiProvider, OpenAICompatibleProvider, OpenRouterProvider
from .system import TMCOSystem
from .types import AssemblyPurpose, ComputeBudget
from .vault import CredentialVault


class GodRuntime:
    """Idle-on-demand Phase 2 coordinator over the compatible Phase 1 organism."""

    def __init__(self, path: Path, *, bus: ModelBus | None = None):
        self.path = path
        self.store = RuntimeStore(path)
        self.vault = CredentialVault(path)
        self.bus = bus or ModelBus()
        self.registry = ModelCapabilityRegistry(self.store)
        self.cognition = ModelBackedCognition(self.bus, self.registry, self.store)
        # Phase 1 recovery and colony identity remain authoritative. This cognition is
        # not used for production thought; it only satisfies the legacy kernel boundary.
        self.organism = TMCOSystem(path, DeterministicCognitionFixture())
        self._restore_connections()

    def _restore_connections(self) -> None:
        for entry in self.store.all("model_registry"):
            provider = entry["provider"]
            if provider in self.bus.providers or not self.vault.exists(provider):
                continue
            credential = self.vault.load(provider)
            if provider == "openrouter":
                adapter = OpenRouterProvider(entry["model_id"], credential)
            elif provider == "gemini":
                adapter = GeminiProvider(entry["model_id"], credential)
            elif provider == "openai-compatible" and entry.get("base_url"):
                adapter = OpenAICompatibleProvider(entry["base_url"], entry["model_id"], credential)
            else:
                continue
            self.bus.register(provider, adapter)

    def connect(self, provider: str, model: str, credential: str, base_url: str = "") -> None:
        if provider == "openrouter":
            adapter = OpenRouterProvider(model, credential)
        elif provider == "gemini":
            adapter = GeminiProvider(model, credential)
        elif provider == "openai-compatible" and base_url:
            adapter = OpenAICompatibleProvider(base_url, model, credential)
        else:
            raise ValueError("unsupported provider configuration")
        self.bus.register(provider, adapter)
        identifier = self.registry.register(provider, model, base_url=base_url)
        started = time.perf_counter()
        success = False
        usage: dict[str, Any] = {}
        try:
            response = self.bus.request(provider, {"model": model, "max_tokens": 8,
                "messages": [{"role": "user", "content": "Reply with JSON: {\"ok\":true}"}],
                "response_format": {"type": "json_object"}})
            usage = response.get("usage", {})
            success = True
        except Exception:
            entry = next(item for item in self.store.all("model_registry") if item["id"] == identifier)
            entry.pop("id")
            entry["availability"] = False
            self.store.put("model_registry", entry, identifier)
            self.bus.providers.pop(provider, None)
            raise
        finally:
            latency = (time.perf_counter() - started) * 1000
            self.registry.observe(identifier, "capability-probe", success, latency)
            self.store.put("model_calls", {"provider": provider, "model": model,
                "purpose": "capability-probe", "latency_ms": latency, "token_usage": usage,
                "estimated_cost": 0.0, "success": success, "failure": None if success else "probe failed"})
        self.vault.save(provider, credential)

    def submit_goal(self, text: str, *, importance: float = 0.7,
                    difficulty: float = 0.7) -> dict[str, Any]:
        if not text.strip():
            raise ValueError("goal text is required")
        identifier = uuid4().hex
        demand = CognitiveDemand("goal", difficulty, importance)
        a, model_a = self.cognition.interpret(text, "Saphira-A", demand)
        dual = importance >= 0.6 or difficulty >= 0.6 or a.confidence < 0.65
        b = None
        if dual:
            available = self.store.all("model_registry")
            exclude = {model_a} if len(available) > 1 else None
            b, _ = self.cognition.interpret(text, "Saphira-B", demand, exclude=exclude)
        interpretations = {"Saphira-A": asdict(a)}
        if b:
            interpretations["Saphira-B"] = asdict(b)
        for colony, interpretation in interpretations.items():
            self.store.put("colony_interpretations", {"goal_id": identifier, "colony": colony,
                                                       "interpretation": interpretation})
        disagreement = bool(b and (a.hypothesis != b.hypothesis or a.next_useful_step != b.next_useful_step))
        purposes = (AssemblyPurpose.DECOMPOSITION, AssemblyPurpose.PLANNING)
        assemblies = []
        for purpose, colony in zip(purposes, self.organism.colonies.values()):
            neuron = next(iter(colony.neurons))
            assembly = colony.form_assembly(purpose, (neuron,), ComputeBudget(10))
            interpretation = a if colony.id.startswith("Saphira-A") else (b or a)
            colony.neurons[neuron].confidence = (
                colony.neurons[neuron].confidence + interpretation.confidence) / 2
            record = {"goal_id": identifier, "colony": colony.id, "purpose": purpose.value,
                      "neurons": list(assembly.neuron_ids)}
            assemblies.append(record)
            self.store.put("assemblies", record)
            colony.dissolve_assembly(assembly.id)
        goal = {"text": text, "status": "thinking", "desired_outcome": a.desired_outcome,
                "success_evidence": a.success_evidence, "constraints": a.constraints,
                "unknowns": a.unknowns, "subgoals": a.subgoals, "risks": a.risks,
                "next_action": a.next_useful_step, "disagreement": disagreement,
                "selective_sister_audit": disagreement, "confidence": a.confidence}
        self.store.put("goals", goal, identifier)
        for subgoal in a.subgoals:
            self.store.put("subgoals", {"goal_id": identifier, "text": subgoal, "status": "pending"})
        self.store.put("learning_observations", {"goal_id": identifier, "prediction": a.hypothesis,
                                                  "outcome": "pending", "confidence": a.confidence})
        self.organism.memory.episodic.append({"goal_id": identifier, "description": text,
                                              "interpretations": interpretations,
                                              "assemblies": assemblies})
        self.organism.memory.world_model[identifier] = {"prediction": a.hypothesis, "outcome": "pending"}
        self.organism.checkpoint()
        return goal | {"id": identifier, "interpretations": interpretations}

    def chat(self, text: str) -> dict[str, Any]:
        normalized = text.lower().strip(" ?.!")
        goals = self.store.all("goals")
        current = goals[-1] if goals else None
        if normalized == "stop this goal" and current:
            current["status"] = "stopped"
            identifier = current.pop("id")
            self.store.put("goals", current, identifier)
            answer = "The current goal is stopped."
        elif "saphira-a" in normalized:
            answer = self._colony_position("Saphira-A", current)
        elif "saphira-b" in normalized:
            answer = self._colony_position("Saphira-B", current)
        elif any(phrase in normalized for phrase in ("what are you doing", "why did you choose", "what have you learned")):
            answer = self._state_answer(current)
        elif normalized.startswith(("find a way", "achieve ")):
            result = self.submit_goal(text)
            answer = f"I interpreted the goal and selected this next step: {result['next_action']}"
        else:
            demand = CognitiveDemand("conversation", 0.1, 0.1)
            result, _ = self.cognition.interpret(text, "G.O.D.", demand)
            answer = result.next_useful_step
        self.store.put("messages", {"role": "user", "content": text})
        self.store.put("messages", {"role": "assistant", "content": answer})
        return {"answer": answer, "detail": self.status()}

    def _colony_position(self, colony: str, goal: dict[str, Any] | None) -> str:
        if not goal:
            return f"{colony} has no active goal."
        entries = [x for x in self.store.all("colony_interpretations")
                   if x["goal_id"] == goal["id"] and x["colony"] == colony]
        if not entries:
            return f"{colony} was not invoked for this goal."
        value = entries[-1]["interpretation"]
        return f"{colony} hypothesis: {value['hypothesis']} Confidence: {value['confidence']:.2f}."

    def _state_answer(self, goal: dict[str, Any] | None) -> str:
        if not goal:
            return "I am idle. No goal has been submitted."
        return (f"Goal status is {goal['status']}. The persisted next action is: "
                f"{goal['next_action']}. Disagreement recorded: {goal['disagreement']}.")

    def request_approval(self, request: HumanApprovalRequest) -> str:
        return self.store.put("approvals", asdict(request), request.id)

    def decide_approval(self, identifier: str, approved: bool) -> None:
        request = next(item for item in self.store.all("approvals") if item["id"] == identifier)
        request["status"] = "approved" if approved else "denied"
        request.pop("id")
        self.store.put("approvals", request, identifier)

    def status(self) -> dict[str, Any]:
        calls = self.store.all("model_calls")
        cost = sum(float(call.get("estimated_cost") or 0) for call in calls)
        goals = self.store.all("goals")
        interpretations = self.store.all("colony_interpretations")
        return {"Saphira-A": "ONLINE", "Saphira-B": "ONLINE", "Root": "SECURE",
                "Memory": "ONLINE", "Intelligence": "CONNECTED" if self.bus.providers else "DISCONNECTED",
                "current_goal": goals[-1] if goals else None,
                "positions": interpretations[-2:], "approval_required": any(
                    item["status"] == "pending" for item in self.store.all("approvals")),
                "messages": self.store.all("messages"), "session_cost": cost, "day_cost": cost}
