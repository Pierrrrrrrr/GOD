"""Usable, idle-by-default awakening runtime built around replaceable model organs."""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import uuid4

from .buses import ModelBus, ModelProvider
from .executive import Cognition
from .models import ModelRecord, ModelRouter
from .morphogenesis import AssemblyFormationPolicy
from .system import TMCOSystem
from .types import ActionCandidate, ComputeBudget, Goal, GoalStatus


class AwakeningStore:
    def __init__(self, path: Path):
        self.connection = sqlite3.connect(path)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS goals(id TEXT PRIMARY KEY, description TEXT, status TEXT, state TEXT);
        CREATE TABLE IF NOT EXISTS chat(id INTEGER PRIMARY KEY, role TEXT, content TEXT, created REAL);
        CREATE TABLE IF NOT EXISTS episodes(id TEXT PRIMARY KEY, goal_id TEXT, state TEXT, created REAL);
        CREATE TABLE IF NOT EXISTS models(key TEXT PRIMARY KEY, state TEXT);
        """)
        self.connection.commit()

    def put(self, table: str, key: str, value: dict[str, Any]) -> None:
        if table == "goals":
            self.connection.execute("INSERT OR REPLACE INTO goals VALUES(?,?,?,?)",
                                    (key, value["description"], value["status"], json.dumps(value)))
        elif table == "episodes":
            self.connection.execute("INSERT OR REPLACE INTO episodes VALUES(?,?,?,?)",
                                    (key, value["goal_id"], json.dumps(value), time.time()))
        elif table == "models":
            self.connection.execute("INSERT OR REPLACE INTO models VALUES(?,?)", (key, json.dumps(value)))
        self.connection.commit()

    def chat(self, role: str, content: str) -> None:
        self.connection.execute("INSERT INTO chat(role,content,created) VALUES(?,?,?)",
                                (role, content, time.time()))
        self.connection.commit()

    def rows(self, query: str, parameters: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        self.connection.row_factory = sqlite3.Row
        return list(self.connection.execute(query, parameters))

    def close(self) -> None:
        self.connection.commit()
        self.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.connection.close()


class ModelBackedCognition(Cognition):
    """Cognitive schema adapter. Identity and learning remain outside the model."""
    def __init__(self, bus: ModelBus, provider: str):
        self.bus, self.provider = bus, provider

    def ask(self, demand: str, context: dict[str, Any]) -> dict[str, Any]:
        result = self.bus.request(self.provider, {"prompt": demand + "\nJSON context:\n" + json.dumps(context)})
        if not isinstance(result, dict):
            raise ValueError("model cognition must return a JSON object")
        return result

    def decompose(self, goal: Goal) -> list[str]:
        result = self.ask("Infer a short receding-horizon goal interpretation. Return subgoals.",
                          {"goal": goal.description, "success": goal.success_criteria})
        return list(result.get("subgoals", []))

    def candidates(self, goal: Goal) -> list[ActionCandidate]:
        result = self.ask("Return the single next useful reversible action as next_action.",
                          {"goal": goal.description, "subgoals": goal.subgoals})
        return [ActionCandidate(str(result["next_action"]), .8, .5, .2, .2, .1, 0)]

    def verify(self, goal: Goal, observation: str) -> bool:
        return bool(self.ask("Assess evidence and return verified boolean.",
                             {"goal": goal.description, "evidence": observation}).get("verified"))


class GodRuntime:
    """Phase 2 runtime. Calls only ModelBackedCognition through a production ModelBus."""
    def __init__(self, directory: Path, providers: dict[str, ModelProvider],
                 records: list[ModelRecord], *, formation_policy: AssemblyFormationPolicy | None = None,
                 secret: bytes | str | None = None):
        self.directory = directory
        self.bus = ModelBus(providers, production=True)
        self.router = ModelRouter()
        self.records = {record.key: record for record in records}
        if not self.records:
            raise RuntimeError("at least one model record is required")
        initial = self.router.choose(list(self.records.values()), "conversation")
        self.cognition = ModelBackedCognition(self.bus, initial.provider)
        self.policy = formation_policy or AssemblyFormationPolicy()
        # Existing Phase 1 state format remains the authority for organism identity/neural state.
        self.organism = TMCOSystem(directory / "organism", self.cognition, secret=secret,
                                   formation_policy=self.policy)
        self.store = AwakeningStore(directory / "awakening.sqlite3")
        self._restore_models()

    def _restore_models(self) -> None:
        for row in self.store.rows("SELECT state FROM models"):
            data = json.loads(row["state"])
            record = ModelRecord(**data)
            if record.key in self.records:
                self.records[record.key] = record

    def submit_goal(self, text: str, *, important: bool = True) -> dict[str, Any]:
        if not text.strip():
            raise ValueError("a natural-language goal is required")
        goal_id = uuid4().hex
        goal = Goal(goal_id, text, ("credible evidence of progress",))
        decisions = self.policy.form(self.organism.colonies, goal,
                                     {name: ComputeBudget(8) for name in self.organism.colonies})
        interpretations: dict[str, dict[str, Any]] = {}
        used: set[str] = set()
        colonies = list(self.organism.colonies.items()) if important else [self._best_colony(decisions)]
        for name, colony in colonies:
            record = self.router.choose(list(self.records.values()), "goal_reasoning", exclude=used)
            used.add(record.key)
            started = time.monotonic()
            cognition = ModelBackedCognition(self.bus, record.provider)
            try:
                answer = cognition.ask(
                    "Reason independently as this persistent colony. Infer desired_outcome, success_evidence, "
                    "constraints, unknowns, risks, subgoals, hypotheses, and next_useful_action. Do not assume "
                    "the other colony's view.", {"colony": name, "identity": colony.id, "goal": text})
                self.router.learn(record, "goal_reasoning", True, (time.monotonic() - started) * 1000)
            except Exception:
                self.router.learn(record, "goal_reasoning", False, (time.monotonic() - started) * 1000)
                self._save_models(); raise
            interpretations[name] = {"model": record.key, "argument": answer}
        disagreement = self._disagree(interpretations)
        audit = None
        if disagreement:
            record = self.router.choose(list(self.records.values()), "sister_audit")
            started = time.monotonic()
            audit = ModelBackedCognition(self.bus, record.provider).ask(
                "Act as a separate sister-audit demand. Identify material disagreements, assess each argument "
                "against the goal, and return disagreements, synthesis, selected_next_action, and rationale.",
                {"goal": text, "independent_arguments": interpretations})
            self.router.learn(record, "sister_audit", True, (time.monotonic() - started) * 1000)
        episode = {"id": uuid4().hex, "goal_id": goal_id, "goal": text,
                   "interpretations": interpretations, "material_disagreement": disagreement,
                   "audit": audit, "assemblies": [{"colony": d.colony_name, "purpose": d.purpose.value,
                                                    "neurons": list(d.neuron_ids)} for d in decisions]}
        state = {"id": goal_id, "description": text, "status": GoalStatus.ACTIVE.value,
                 "next_action": (audit or next(iter(interpretations.values()))["argument"]).get(
                     "selected_next_action", next(iter(interpretations.values()))["argument"].get("next_useful_action")),
                 "episode_id": episode["id"]}
        self.store.put("goals", goal_id, state)
        self.store.put("episodes", episode["id"], episode)
        self._learn_neurons(decisions, text)
        self._save_models()
        self.organism._commit_state("awakening_episode")
        self._dissolve()
        return episode

    def _best_colony(self, decisions: list[Any]) -> tuple[str, Any]:
        name = decisions[0].colony_name
        return name, self.organism.colonies[name]

    @staticmethod
    def _disagree(arguments: dict[str, dict[str, Any]]) -> bool:
        if len(arguments) < 2:
            return False
        normalized = [json.dumps(v["argument"], sort_keys=True) for v in arguments.values()]
        return len(set(normalized)) > 1

    def _learn_neurons(self, decisions: list[Any], stimulus: str) -> None:
        for decision in decisions:
            colony = self.organism.colonies[decision.colony_name]
            for neuron_id in decision.neuron_ids:
                neuron = colony.neurons[neuron_id]
                neuron.specialize(decision.purpose.value, stimulus)
                neuron.verified_contribution += .25
                neuron.confidence = min(1, neuron.confidence + .02)
            if len(decision.neuron_ids) > 1:
                colony.adapt_weight(*decision.neuron_ids[:2], verified=True)
            colony.memories.append(decision.purpose.value)

    def _dissolve(self) -> None:
        for colony in self.organism.colonies.values():
            for assembly_id in tuple(colony.assemblies):
                colony.dissolve_assembly(assembly_id)

    def _save_models(self) -> None:
        for record in self.records.values(): self.store.put("models", record.key, asdict(record))

    def chat(self, message: str) -> str:
        self.store.chat("user", message)
        lower = message.lower().strip()
        active = self.store.rows("SELECT state FROM goals WHERE status='active' ORDER BY rowid DESC LIMIT 1")
        if lower == "stop this goal." or lower == "stop this goal":
            if active:
                state = json.loads(active[0]["state"]); state["status"] = "stopped"
                self.store.put("goals", state["id"], state); answer = "Stopped the active goal."
            else: answer = "There is no active goal to stop."
        elif any(lower.startswith(prefix) for prefix in ("find a way to ", "find a realistic way to ")):
            episode = self.submit_goal(message, important=True)
            answer = (episode.get("audit") or next(iter(episode["interpretations"].values()))["argument"]).get(
                "synthesis", "I have started the goal and recorded the next evidence-seeking action.")
        elif lower in {"what are you doing?", "why?", "what have you learned?",
                       "what does saphira-a think?", "what does saphira-b think?"}:
            answer = self._state_answer(lower, active)
        else:
            record = self.router.choose(list(self.records.values()), "conversation")
            persisted = json.loads(active[0]["state"]) if active else None
            result = ModelBackedCognition(self.bus, record.provider).ask(
                "Reply naturally and truthfully. Do not invent activity; use only supplied persisted state.",
                {"message": message, "active_goal": persisted})
            answer = str(result.get("answer", result.get("response", "I do not have an answer.")))
        self.store.chat("assistant", answer)
        return answer

    def _state_answer(self, question: str, active: list[sqlite3.Row]) -> str:
        if not active: return "I have no active goal."
        state = json.loads(active[0]["state"])
        episodes = self.store.rows("SELECT state FROM episodes WHERE id=?", (state["episode_id"],))
        episode = json.loads(episodes[0]["state"])
        if "saphira-a" in question or "saphira-b" in question:
            name = "Saphira-A" if "saphira-a" in question else "Saphira-B"
            view = episode["interpretations"].get(name)
            return json.dumps(view["argument"], sort_keys=True) if view else f"{name} was not recruited."
        if question == "why?":
            return str((episode.get("audit") or {}).get("rationale", "The next action follows the recorded reasoning."))
        if "learned" in question:
            return f"Recorded {len(episode['assemblies'])} assemblies and their verified contributions."
        return f"Working on {state['description']}. Next action: {state['next_action']}"

    def close(self) -> None:
        self.organism.checkpoint()
        self.store.close()

    def __enter__(self) -> "GodRuntime": return self
    def __exit__(self, *_: Any) -> None: self.close()
