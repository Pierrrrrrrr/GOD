from __future__ import annotations

import hashlib
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import uuid4

from .buses import BodyBus, ModelBus, ProviderUnavailable
from .evolution import EvolutionArchive, EvolutionCandidate
from .executive import (ActionExecutor, ActionResult, Cognition, ExecutiveKernel,
                        Observation, ObservationProvider)
from .memory import MemoryKernel
from .morphogenesis import AssemblyFormationPolicy
from .persistence import EventStore
from .root import (AuthorizationError, InjectedRootSecretStore, RootGuard, RootKernel,
                   RootSecretStore, platform_root_secret_store)
from .runtime import Colony
from .types import (AssemblyPurpose, ComputeBudget, DigitalNeuron, Goal, GoalStatus,
                    Neuromodulators, Synapse, WorkspaceItem)
from .workspace import GlobalWorkspace


class TMCOSystem:
    def __init__(self, path: Path, cognition: Cognition, *, owner: str = "owner",
                 secret: str | bytes | None = None, executor: ActionExecutor | None = None,
                 observation_provider: ObservationProvider | None = None,
                 formation_policy: AssemblyFormationPolicy | None = None,
                 root_secret_store: RootSecretStore | None = None):
        self.store = EventStore(path)
        self.executive = ExecutiveKernel(cognition)
        self.executor, self.observation_provider = executor, observation_provider
        self.formation_policy = formation_policy or AssemblyFormationPolicy()
        self.model_bus, self.body_bus = ModelBus(), BodyBus()
        saved = self.store.recover_state()
        injected = secret.encode() if isinstance(secret, str) else secret
        if injected is not None and root_secret_store is not None:
            raise ValueError("choose either an injected test secret or a root secret store")
        secret_store = (InjectedRootSecretStore(injected) if injected is not None
                        else root_secret_store or platform_root_secret_store(path))
        root_guard = secret_store.open_guard(existing_organism=saved is not None)
        if saved:
            self._restore(saved, root_guard)
        else:
            self.root = RootKernel(owner, root_guard)
            self.root.record("root_initialized", {"owner": owner,
                                                   "key_fingerprint": self.root.key_fingerprint})
            self.colonies = {name: Colony.create(name) for name in ("Saphira-A", "Saphira-B")}
            self.workspace = GlobalWorkspace()
            self.memory = MemoryKernel()
            self.evolution = EvolutionArchive("champion-0", {"population": 6})
            self.goals: dict[str, Goal] = {}
            self.idle = True
            self.store.append("boot", {"colonies": list(self.colonies),
                                       "root_key_reference": self.root.key_reference})
            self._commit_state("initialization")

    def submit_goal(self, description: str, success_criteria: tuple[str, ...],
                    constraints: dict[str, Any] | None = None) -> Goal:
        if not description.strip():
            raise ValueError("goal description is required")
        goal = Goal(uuid4().hex, description, success_criteria, constraints or {})
        self.goals[goal.id] = goal
        self.idle = False
        self.store.append("goal_submitted", {"id": goal.id, "description": description})
        self._commit_state("goal_submitted")
        return goal

    def step(self, *, crash_after_commit: bool = False) -> bool:
        pending = next((goal for goal in self.goals.values()
                        if goal.status == GoalStatus.PENDING), None)
        if pending is None:
            self.idle = True
            return False
        if self.executor is None or self.observation_provider is None:
            raise ProviderUnavailable("execution requires explicit ActionExecutor and ObservationProvider")

        pending.status = GoalStatus.ACTIVE
        selected = self.executive.prepare(pending)
        pending.action_id = hashlib.sha256(f"{pending.id}:{selected.action}".encode()).hexdigest()
        budgets = {name: ComputeBudget(10) for name in self.colonies}
        decisions = self.formation_policy.form(self.colonies, pending, budgets)
        completed = self.store.completed_action(pending.action_id)
        if completed:
            observation = Observation(**completed["observation"])
        else:
            self.store.append("action_started", {"goal_id": pending.id,
                                                 "action_id": pending.action_id,
                                                 "action": selected.action})
            result = self.executor.execute(selected.action, pending.action_id)
            if result.action_id != pending.action_id:
                raise ValueError("executor returned evidence for a different action")
            observation = self.observation_provider.observe(result)
            if observation.action_id != pending.action_id:
                raise ValueError("observation provenance does not match action")
            self.store.append("action_completed", {"goal_id": pending.id,
                                                    "action_id": pending.action_id,
                                                    "result": asdict(result),
                                                    "observation": asdict(observation)})

        verified = self.executive.verify(pending, observation.evidence)
        contributors: list[str] = []
        for decision in decisions:
            colony = self.colonies[decision.colony_name]
            lead = colony.neurons[decision.neuron_ids[0]]
            lead.specialize(decision.purpose.value, pending.description)
            lead.verified_contribution += 1.0 if verified else 0.0
            contributors.append(lead.id)
            if len(decision.neuron_ids) > 1:
                source, target = decision.neuron_ids[:2]
                key = f"{source}->{target}"
                if key not in colony.synapses:
                    colony.connect(source, target, .4)
                colony.synapses[key].temporary = False
                colony.adapt_weight(source, target, verified)
        pending.status = GoalStatus.VERIFIED if verified else GoalStatus.FAILED
        if verified:
            publisher = self.colonies[decisions[0].colony_name].id
            self.workspace.publish(WorkspaceItem(publisher,
                                                 "verified-result", observation.evidence, .92))
        assembly_record = [{"colony": d.colony_name, "purpose": d.purpose.value,
                            "neurons": list(d.neuron_ids)} for d in decisions]
        episode = {"goal_id": pending.id, "description": pending.description,
                   "action_id": pending.action_id, "action": selected.action,
                   "observation": asdict(observation), "verified": verified,
                   "assemblies": assembly_record}
        self.memory.episodic.append(episode)
        self.memory.self_model.update({"last_contributors": contributors,
                                      "verified_goals": sum(g.status == GoalStatus.VERIFIED for g in self.goals.values())})
        self.memory.world_model["last_observation"] = asdict(observation)
        for decision in decisions:
            colony = self.colonies[decision.colony_name]
            colony.memories.append(pending.id)
        for colony in self.colonies.values():
            for assembly_id in tuple(colony.assemblies):
                colony.dissolve_assembly(assembly_id)
        self.idle = True
        self._commit_state("verified_action" if verified else "failed_action")
        if crash_after_commit:
            raise RuntimeError("simulated process death after durable commit")
        return True

    def checkpoint(self) -> None:
        self.store.checkpoint(self._state())

    def architectural_mutation(self, mutation: dict[str, Any]) -> EvolutionCandidate:
        candidate = self.evolution.branch(mutation)
        self.store.append("evolution_candidate", {"id": candidate.id, "parent": candidate.parent})
        self._commit_state("evolution_candidate")
        return candidate

    def _commit_state(self, reason: str) -> None:
        self.store.append("state_committed", {"reason": reason, "state": self._state()})

    def _state(self) -> dict[str, Any]:
        def colony_data(colony: Colony) -> dict[str, Any]:
            return {"id": colony.id, "lineage": colony.lineage, "memories": colony.memories,
                    "modulators": asdict(colony.modulators),
                    "neurons": {key: {**asdict(value), "receptors": sorted(value.receptors),
                                      "lineage": list(value.lineage)} for key, value in colony.neurons.items()},
                    "synapses": {key: asdict(value) for key, value in colony.synapses.items()}}
        return {"root": {"owner": self.root.owner, "key_reference": self.root.key_reference,
                          "key_fingerprint": self.root.key_fingerprint,
                          "constitution": list(self.root.constitution),
                          "permissions": {k: sorted(v) for k, v in self.root.permissions.items()},
                          "audit": self.root.audit},
                "colonies": {k: colony_data(v) for k, v in self.colonies.items()},
                "workspace": {"threshold": self.workspace.salience_threshold,
                              "capacity": self.workspace.capacity,
                              "items": [asdict(i) for i in self.workspace.items]},
                "memory": asdict(self.memory),
                "evolution": {"champion_id": self.evolution.champion_id,
                              "champion_architecture": self.evolution.champion_architecture,
                              "candidates": {k: asdict(v) for k, v in self.evolution.candidates.items()}},
                "goals": {k: {**asdict(v), "success_criteria": list(v.success_criteria),
                               "status": v.status.value} for k, v in self.goals.items()}, "idle": self.idle}

    def _restore(self, state: dict[str, Any], root_guard: RootGuard) -> None:
        root = state["root"]
        if root_guard.fingerprint != root["key_fingerprint"]:
            raise AuthorizationError("root key does not match checkpoint verification material")
        if root_guard.key_reference != root["key_reference"]:
            raise AuthorizationError("root secret store does not match checkpoint reference")
        self.root = RootKernel(root["owner"], root_guard)
        self.root.audit = root["audit"]
        if not self.root.verify_audit():
            raise AuthorizationError("root audit verification failed")
        initialized = next((entry for entry in self.root.audit
                            if entry["kind"] == "root_initialized"), None)
        if initialized is None or initialized["payload"]["owner"] != root["owner"]:
            raise AuthorizationError("checkpoint attempted to alter root ownership")
        if tuple(root["constitution"]) != self.root.constitution:
            raise AuthorizationError("checkpoint attempted to alter root constitution")
        derived: dict[str, set[str]] = {}
        for entry in self.root.audit:
            if entry["kind"] == "privilege_granted":
                payload = entry["payload"]
                derived.setdefault(payload["principal"], set()).add(payload["permission"])
        if derived != {k: set(v) for k, v in root["permissions"].items()}:
            raise AuthorizationError("checkpoint permissions are not authorized by signed audit")
        self.root.permissions = derived
        self.colonies = {}
        for name, data in state["colonies"].items():
            neurons = {key: DigitalNeuron(**{**value, "lineage": tuple(value["lineage"]),
                                             "receptors": set(value["receptors"])})
                       for key, value in data["neurons"].items()}
            colony = Colony(data["id"], neurons, lineage=data["lineage"], memories=data["memories"],
                            modulators=Neuromodulators(**data["modulators"]))
            colony.synapses = {key: Synapse(**value) for key, value in data["synapses"].items()}
            self.colonies[name] = colony
        ws = state["workspace"]
        self.workspace = GlobalWorkspace(ws["threshold"], ws["capacity"],
                                         [WorkspaceItem(**item) for item in ws["items"]])
        self.memory = MemoryKernel(**state["memory"])
        evo = state["evolution"]
        self.evolution = EvolutionArchive(evo["champion_id"], evo["champion_architecture"],
                                           {k: EvolutionCandidate(**v) for k, v in evo["candidates"].items()})
        self.goals = {key: Goal(**{**value, "success_criteria": tuple(value["success_criteria"]),
                                  "status": GoalStatus(value["status"])})
                      for key, value in state["goals"].items()}
        self.idle = state["idle"]
