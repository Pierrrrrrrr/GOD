"""Usable, idle-by-default awakening runtime built around replaceable model organs."""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import uuid4

from .buses import BodyBus, ModelBus, ModelProvider, OrganManifest, ProviderUnavailable
from .capabilities import OwnerCapabilityAuthority
from .embodiment import (ActionLoop, CapabilityDemand, CapabilityResolver, EmbodimentStore,
                         DecisionProvenance, HumanApprovalRequest, ObservationEnvelope,
                         OrganRegistry, OutcomeEvaluation, OutcomeEvaluator, PermissionAuthority,
                         VerificationLevel, WebResearchOrgan,
                         WorkspaceFilesystemOrgan)
from .executive import Cognition
from .models import ModelRecord, ModelRouter
from .morphogenesis import AssemblyFormationPolicy
from .system import TMCOSystem
from .types import ActionCandidate, ComputeBudget, Goal, GoalStatus
from .sisters import (BriefResponse, DigestResponse, SisterBrief, SisterDevelopmentDigest,
                      SisterExchangePolicy, SisterView, WorkClass, classify_work)


class AwakeningStore:
    def __init__(self, path: Path):
        self.connection = sqlite3.connect(path)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS goals(id TEXT PRIMARY KEY, description TEXT, status TEXT, state TEXT);
        CREATE TABLE IF NOT EXISTS chat(id INTEGER PRIMARY KEY, role TEXT, content TEXT, created REAL);
        CREATE TABLE IF NOT EXISTS episodes(id TEXT PRIMARY KEY, goal_id TEXT, state TEXT, created REAL);
        CREATE TABLE IF NOT EXISTS models(key TEXT PRIMARY KEY, state TEXT);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS runtime_events(
          sequence INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
          summary TEXT NOT NULL, state TEXT NOT NULL, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS model_selections(
          id TEXT PRIMARY KEY, goal_id TEXT, episode_id TEXT, task_class TEXT,
          colony TEXT, provider TEXT, model_id TEXT, routing_policy TEXT,
          routing_reason TEXT, started_at REAL, finished_at REAL, latency_ms REAL,
          success INTEGER);
        CREATE TABLE IF NOT EXISTS sister_states(
          sequence INTEGER PRIMARY KEY AUTOINCREMENT,colony TEXT,goal_id TEXT,status TEXT,
          summary TEXT,confidence REAL,created REAL);
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

    def setting(self, key: str, default: str) -> str:
        row = self.connection.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return str(row[0]) if row else default

    def set_setting(self, key: str, value: str) -> None:
        self.connection.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (key, value))
        self.connection.commit()

    def runtime_event(self, kind: str, summary: str, state: dict[str, Any]) -> None:
        """Persist an event only when called by a completed runtime transition."""
        self.connection.execute("INSERT INTO runtime_events(kind,summary,state,created) VALUES(?,?,?,?)",
                                (kind, summary, json.dumps(state), time.time()))
        self.connection.commit()

    def model_selection(self, value: dict[str, Any]) -> None:
        columns = ("id","goal_id","episode_id","task_class","colony","provider","model_id",
                   "routing_policy","routing_reason","started_at","finished_at","latency_ms","success")
        self.connection.execute(f"INSERT OR REPLACE INTO model_selections VALUES({','.join('?' for _ in columns)})",
                                tuple(value.get(key) for key in columns)); self.connection.commit()

    def sister_state(self, colony: str, goal_id: str | None, status: str, summary: str,
                     confidence: float | None) -> None:
        self.connection.execute("INSERT INTO sister_states(colony,goal_id,status,summary,confidence,created) VALUES(?,?,?,?,?,?)",
                                (colony, goal_id, status, summary, confidence, time.time())); self.connection.commit()


class ModelBackedCognition(Cognition):
    """Cognitive schema adapter. Identity and learning remain outside the model."""
    def __init__(self, bus: ModelBus, record: ModelRecord):
        self.bus, self.record = bus, record

    def ask(self, demand: str, context: dict[str, Any]) -> dict[str, Any]:
        result = self.bus.request(self.record.provider, {
            "model_id": self.record.model_id,
            "prompt": demand + "\nJSON context:\n" + json.dumps(context),
        })
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


class DisconnectedCognition(Cognition):
    """Safe core boundary: Saphira exists, but no external reasoning is available."""

    @staticmethod
    def _unavailable() -> None:
        raise ProviderUnavailable("external intelligence is disconnected")

    def decompose(self, goal: Goal) -> list[str]:
        self._unavailable()

    def candidates(self, goal: Goal) -> list[ActionCandidate]:
        self._unavailable()

    def verify(self, goal: Goal, observation: str) -> bool:
        self._unavailable()


class GodRuntime:
    """Phase 2 runtime. Calls only ModelBackedCognition through a production ModelBus."""
    def __init__(self, directory: Path, providers: dict[str, ModelProvider] | None = None,
                 records: list[ModelRecord] | None = None, *, formation_policy: AssemblyFormationPolicy | None = None,
                 secret: bytes | str | None = None, web_test_allow_hosts: set[str] | None = None):
        self.directory = directory
        self.bus = ModelBus(production=True)
        self.router = ModelRouter()
        self.records: dict[str, ModelRecord] = {}
        self.routing_policy = "AUTO"
        self.cognition: Cognition = DisconnectedCognition()
        self.policy = formation_policy or AssemblyFormationPolicy()
        # Existing Phase 1 state format remains the authority for organism identity/neural state.
        self.organism = TMCOSystem(directory / "organism", self.cognition, secret=secret,
                                   formation_policy=self.policy)
        self.store = AwakeningStore(directory / "awakening.sqlite3")
        self.routing_policy = self.store.setting("routing_policy", "AUTO")
        self.body_bus = BodyBus()
        self.embodiment_store = EmbodimentStore(directory / "embodiment.sqlite3")
        self.organ_registry = OrganRegistry(self.body_bus, self.embodiment_store)
        self.capability_resolver = CapabilityResolver(self.body_bus, self.embodiment_store)
        self.action_loop = ActionLoop(self.body_bus, self.embodiment_store, self._action_event)
        self.permission_authority = PermissionAuthority(self.embodiment_store)
        self.owner_capabilities = OwnerCapabilityAuthority(self.organism.root,
                                                           directory / "owner_capabilities.sqlite3")
        self.sister_exchange = SisterExchangePolicy()
        self._restore_exchange_rounds()
        self._register_builtin_organs(web_test_allow_hosts)
        self._event("BOOT", "Root and both sister lineages restored")
        for name in ("Saphira-A", "Saphira-B"):
            if not self.store.rows("SELECT 1 FROM sister_states WHERE colony=? LIMIT 1", (name,)):
                self._sister_transition(name, None, "IDLE", "Awake and idle")
        if providers or records:
            self.attach_intelligence(providers or {}, records or [])

    def _register_builtin_organs(self, test_hosts: set[str] | None) -> None:
        workspace = self.directory / "workspace"
        filesystem = WorkspaceFilesystemOrgan(workspace, (self.directory / "organism", self.directory / "credentials.vault"))
        fs_manifest = OrganManifest("workspace", "filesystem", "1", filesystem.OPERATIONS,
            description="runtime workspace", permissions={"workspace.access"}, side_effect_class="workspace",
            capability_tags={"filesystem"}, filesystem_scope=(str(workspace.resolve()),), verified_reliability=1)
        self.organ_registry.register(fs_manifest, {name: (lambda args, name=name: filesystem.handle(name, args)) for name in filesystem.OPERATIONS})
        web = WebResearchOrgan(test_allow_hosts=test_hosts)
        web_manifest = OrganManifest("web-research", "web", "1", {"GET":{"required":["url"]}, "HEAD":{"required":["url"]}},
            description="public read-only research", permissions={"public.read"}, side_effect_class="read",
            capability_tags={"web"}, network_scope=("public-http-test" if test_hosts else "public-https",), verified_reliability=.8)
        self.organ_registry.register(web_manifest, {method: (lambda args, method=method: web.request({**args, "method": method})) for method in ("GET", "HEAD")})

    def _action_event(self, kind: str, state: dict[str, Any]) -> None:
        summaries = {"APPROVAL_REQUIRED": "Pier approval required",
                     "PREDICTION_STORED": "Action prediction persisted",
                     "ORGAN_STARTED": "Body organ invocation started",
                     "OBSERVATION_RECEIVED": "Body observation persisted",
                     "VERIFICATION_CHANGED": "Observation verification changed",
                     "FAILED": "Body invocation failed"}
        self._event(kind, summaries[kind], state)

    def _restore_exchange_rounds(self) -> None:
        for event in self.embodiment_store.all("exchange"):
            self.sister_exchange.rounds[event["goal_id"]] = max(
                self.sister_exchange.rounds.get(event["goal_id"], 0), event["round"])

    @property
    def intelligence_connected(self) -> bool:
        return bool(self.bus.providers and self.records)

    def set_routing_policy(self, policy: str) -> None:
        if policy not in {"AUTO", "FREE_FIRST", "LOCAL_FIRST"}:
            raise ValueError("unknown routing policy")
        self.routing_policy = policy
        self.store.set_setting("routing_policy", policy)
        self._event("ROUTING", f"Routing policy changed to {policy}")

    def attach_intelligence(self, providers: dict[str, ModelProvider],
                            records: list[ModelRecord]) -> None:
        bus = ModelBus(providers, production=True)
        configured = {record.key: record for record in records}
        if not configured:
            raise ProviderUnavailable("at least one model record is required")
        self.bus, self.records = bus, configured
        self._restore_models()
        # Attachment follows a successful capability probe, so transient prior
        # unavailability must not prevent this newly confirmed connection.
        for key, record in configured.items():
            self.records[key].availability = record.availability
        initial = self.router.choose(list(self.records.values()), "conversation",
                                     policy=self.routing_policy)
        self.cognition = ModelBackedCognition(self.bus, initial)
        self.organism.executive.cognition = self.cognition
        self._save_models()
        self._event("INTELLIGENCE", f"Connected {len(configured)} discovered model(s)")

    def detach_intelligence(self) -> None:
        self.bus = ModelBus(production=True)
        self.records = {}
        self.cognition = DisconnectedCognition()
        self.organism.executive.cognition = self.cognition
        self._event("INTELLIGENCE", "External intelligence disconnected")

    def _restore_models(self) -> None:
        for row in self.store.rows("SELECT state FROM models"):
            data = json.loads(row["state"])
            if "quality_observations" not in data:
                # Pre-correction values conflated call success with quality and cannot be trusted.
                data["task_performance"], data["calibration"] = {}, .5
            record = ModelRecord(**data)
            if record.key in self.records:
                self.records[record.key] = record

    def _model_call(self, record: ModelRecord, goal_id: str | None, episode_id: str | None,
                    task: str, colony: str | None, demand: str, context: dict[str, Any]) -> dict[str, Any]:
        identity, started_wall, started = uuid4().hex, time.time(), time.monotonic()
        selection = {"id": identity, "goal_id": goal_id, "episode_id": episode_id,
                     "task_class": task, "colony": colony, "provider": record.provider,
                     "model_id": record.model_id, "routing_policy": self.routing_policy,
                     "routing_reason": self.router.reason(record, task, self.routing_policy),
                     "started_at": started_wall, "finished_at": None, "latency_ms": None,
                     "success": None}
        self.store.model_selection(selection)
        self._event("MODEL_SELECTED", f"{record.key} selected for {task}",
                    {key: selection[key] for key in ("id", "goal_id", "episode_id", "task_class", "colony",
                                                     "provider", "model_id", "routing_policy", "routing_reason")})
        try:
            result = ModelBackedCognition(self.bus, record).ask(demand, context); success = True
            return result
        except Exception:
            success = False; raise
        finally:
            latency = (time.monotonic() - started) * 1000
            selection.update(finished_at=time.time(), latency_ms=latency, success=int(success))
            self.store.model_selection(selection); self.router.observe_call(record, success, latency)

    def _sister_transition(self, colony: str, goal_id: str | None, status: str, summary: str) -> None:
        confidence = round(sum(n.confidence for n in self.organism.colonies[colony].neurons.values()) /
                           len(self.organism.colonies[colony].neurons), 3)
        self.store.sister_state(colony, goal_id, status, summary, confidence)

    def submit_goal(self, text: str, *, important: bool = True) -> dict[str, Any]:
        if not text.strip():
            raise ValueError("a natural-language goal is required")
        if not self.intelligence_connected:
            raise ProviderUnavailable("external intelligence is disconnected")
        goal_id, episode_id = uuid4().hex, uuid4().hex
        self._event("GOAL_ACCEPTED", "Owner goal accepted", {"goal_id": goal_id})
        goal = Goal(goal_id, text, ("credible evidence of progress",))
        work_class = classify_work(text)
        self._event("WORK_CLASS_SELECTED", f"Work classified as {work_class.value}", {"goal_id": goal_id})
        decisions = self.policy.form(self.organism.colonies, goal,
                                     {name: ComputeBudget(8) for name in self.organism.colonies})
        interpretations: dict[str, dict[str, Any]] = {}
        used: set[str] = set()
        colonies = (list(self.organism.colonies.items()) if work_class == WorkClass.DELIBERATIVE and important
                    else [self._dynamic_primary(text)])
        primary_colony = colonies[0][0]
        self._event("PRIMARY_COLONY_SELECTED", f"{primary_colony} selected as primary", {"goal_id": goal_id,
                    "colony": primary_colony})
        for name, colony in colonies:
            record = self.router.choose(list(self.records.values()), "goal_reasoning", exclude=used,
                                        policy=self.routing_policy)
            used.add(record.key)
            self._sister_transition(name, goal_id, "THINKING", "Independent goal interpretation started")
            self._event("SISTER_A_STARTED" if name == "Saphira-A" else "SISTER_B_STARTED",
                        f"{name} independent pass started", {"goal_id": goal_id, "colony": name})
            try:
                answer = self._model_call(record, goal_id, episode_id, "goal_reasoning", name,
                    "Reason independently as this persistent colony. Infer desired_outcome, success_evidence, "
                    "constraints, unknowns, risks, subgoals, hypotheses, and next_useful_action. Do not assume "
                    "the other colony's view. If external information or action is needed, return body_demands as "
                    "a JSON list whose every item contains required_capability, intent, inputs, expected_output, "
                    "expected_evidence, risk, side_effect_class, budget, reversibility, confidence, goal_value, "
                    "information_gain, capability_gain, uncertainty, network_need, and filesystem_need. Return an "
                    "empty body_demands list when no body capability is needed. Describe WHAT is required only; "
                    "never request shell or arbitrary code execution and never claim prose is an executed action.",
                    {"colony": name, "identity": colony.id, "goal": text})
            except Exception:
                self._sister_transition(name, goal_id, "BLOCKED", "Model call failed")
                self._event("FAILED", f"{name} model call failed", {"goal_id": goal_id, "colony": name})
                self._save_models(); raise
            interpretations[name] = {"model": record.key, "argument": answer}
            self._event("SISTER_RESULT_READY", f"{name} result ready", {"goal_id": goal_id, "colony": name})
            self._sister_transition(name, goal_id, "IDLE", "Independent result ready")
        candidate_disagreement = self._candidate_disagreement(interpretations)
        material_disagreement = False
        materiality_reasons: list[str] = []
        if candidate_disagreement:
            record = self.router.choose(list(self.records.values()), "disagreement_assessment",
                                        policy=self.routing_policy)
            assessment = self._model_call(record, goal_id, episode_id, "disagreement_assessment", None,
                "Assess only whether these core claims conflict enough to change the decision. Return a JSON "
                "boolean material_disagreement and a list of reasons. Cosmetic wording is not material.",
                {"goal": text, "core_claims": self._core_claims(interpretations)})
            decision = assessment.get("material_disagreement")
            if not isinstance(decision, bool):
                raise ValueError("disagreement assessment must return a boolean material_disagreement")
            material_disagreement = decision
            materiality_reasons = [str(reason) for reason in assessment.get("reasons", [])]
        audit = None
        if material_disagreement:
            record = self.router.choose(list(self.records.values()), "sister_audit",
                                        policy=self.routing_policy)
            audit = self._model_call(record, goal_id, episode_id, "sister_audit", None,
                "Act as a separate sister-audit demand. Identify material disagreements, assess each argument "
                "against the goal, and return disagreements, synthesis, selected_next_action, and rationale.",
                {"goal": text, "independent_arguments": interpretations})
        exchange = self._integrated_exchange(goal_id, episode_id, text, interpretations, material_disagreement)
        episode = {"id": episode_id, "goal_id": goal_id, "goal": text,
                   "interpretations": interpretations,
                   "candidate_disagreement": candidate_disagreement,
                   "material_disagreement": material_disagreement,
                   "materiality_reasons": materiality_reasons,
                   "audit": audit, "exchange": exchange, "work_class": work_class.value,
                   "assemblies": [{"colony": d.colony_name, "purpose": d.purpose.value,
                                                    "neurons": list(d.neuron_ids)} for d in decisions]}
        state = {"id": goal_id, "description": text, "status": GoalStatus.ACTIVE.value,
                 "next_action": (audit or next(iter(interpretations.values()))["argument"]).get(
                     "selected_next_action", next(iter(interpretations.values()))["argument"].get("next_useful_action")),
                 "episode_id": episode["id"], "work_class": work_class.value, "current_step": "reasoning",
                 "selected_colony": primary_colony,
                 "current_organ": None, "last_observation": None, "exchange_status": "completed" if exchange else "none"}
        self.store.put("goals", goal_id, state)
        self.store.put("episodes", episode["id"], episode)
        self._learn_neurons(decisions, text)
        self._save_models()
        self.organism._commit_state("awakening_episode")
        self._dissolve()
        demands = self._structured_demands(goal_id, episode["id"], text, interpretations, decisions)
        if demands:
            episode["body"] = self._run_body_plan(state, demands, interpretations)
            self.store.put("episodes", episode["id"], episode)
        if not demands or episode.get("body", {}).get("status") == "executed":
            self._event("FINAL_RESPONSE", "Synchronous goal response returned", {"goal_id": goal_id})
        return episode

    def _dynamic_primary(self, text: str) -> tuple[str, Any]:
        tokens = set(text.lower().split())
        def score(item: tuple[str, Any]) -> tuple[float, str]:
            name, colony = item; neurons = list(colony.neurons.values())
            relevance = sum(bool(tokens & set(n.specialization.lower().split())) for n in neurons)
            verified = sum(n.verified_contribution for n in neurons)
            confidence = sum(n.confidence for n in neurons)/len(neurons)
            cost = sum(n.metabolic_cost for n in neurons)/len(neurons)
            novelty = 1/(1+len(colony.memories))
            borrowed = sum(memory.startswith("borrowed-tested:") for memory in colony.memories)
            return (relevance*2 + verified + confidence + novelty + borrowed - cost*.1, name)
        return max(self.organism.colonies.items(), key=score)

    def _integrated_exchange(self, goal_id: str, episode_id: str, goal: str, interpretations: dict[str, dict[str, Any]], triggered: bool) -> dict[str, Any] | None:
        if not triggered or len(interpretations) < 2: return None
        names = list(interpretations); source, target = names[0], names[1]
        self._event("SISTER_EXCHANGE_STARTED", "Bounded sister exchange started", {"goal_id": goal_id})
        self._sister_transition(source, goal_id, "EXCHANGING", "Sharing bounded sister brief")
        self._sister_transition(target, goal_id, "EXCHANGING", "Reviewing bounded sister brief")
        argument = interpretations[source]["argument"]
        brief = SisterBrief(source, str(argument.get("hypotheses", [""])[0]), str(argument.get("next_useful_action", "")),
                            tuple(map(str, argument.get("evidence_refs", ()))), float(argument.get("confidence", .5)),
                            tuple(map(str, argument.get("critical_assumptions", argument.get("constraints", ())))),
                            tuple(map(str, argument.get("unknowns", ()))), tuple(map(str, argument.get("capability_gaps", ()))),
                            str(argument.get("prediction", "")))
        # This is a genuinely new post-brief turn. It contains the compact brief and
        # goal only—not the source interpretation, private memory, or topology.
        target_record = self.records[interpretations[target]["model"]]
        post = self._model_call(target_record, goal_id, episode_id, "sister_exchange", target,
            "Respond to this SisterBrief after your independent first pass. Return response as exactly ACCEPT, "
            "CHALLENGE, IGNORE, or COUNTERPROPOSE, plus reason, updated_confidence, optional counterproposal, "
            "and evidence_refs.", {"goal": goal, "sister_brief": asdict(brief)})
        response_name = str(post.get("response", "IGNORE")).upper()
        response = BriefResponse(response_name) if response_name in BriefResponse.__members__ else BriefResponse.CHALLENGE
        target_view = SisterView(target, {})
        if not self.sister_exchange.exchange(goal_id, SisterView(source, {}), target_view, brief, response,
                                             trigger="material_disagreement", counterproposal=str(post.get("counterproposal") or interpretations[target]["argument"].get("hypotheses", [""])[0])): return None
        event = {"goal_id": goal_id, "round": self.sister_exchange.rounds[goal_id], "source": source, "target": target,
                 "brief": asdict(brief), "response": response.value, "post_brief_response": post,
                 "minority_hypotheses": target_view.minority_hypotheses}
        self.embodiment_store.put("exchange", f"{goal_id}:{event['round']}", event)
        self._event("SISTER_EXCHANGE_RESULT", "Bounded sister exchange recorded", {"goal_id": goal_id})
        for name in (source, target): self._sister_transition(name, goal_id, "IDLE", "Exchange complete")
        return event

    def _structured_demands(self, goal_id: str, episode_id: str, task: str,
                            interpretations: dict[str, dict[str, Any]], decisions: list[Any]) -> list[tuple[float, CapabilityDemand, dict[str, Any]]]:
        candidates = []
        for source_colony, view in interpretations.items():
            plans = view["argument"].get("body_demands", [])
            if isinstance(view["argument"].get("body_demand"), dict): plans = [view["argument"]["body_demand"]]
            for data in plans:
                required = {"required_capability","intent","inputs","expected_output","expected_evidence","risk","side_effect_class","budget","reversibility","confidence","goal_value","information_gain","capability_gain","uncertainty","network_need","filesystem_need"}
                if not isinstance(data, dict) or not required <= set(data): raise ValueError("invalid structured body demand")
                if str(data["required_capability"]).lower() in {"shell", "code", "subprocess"}:
                    raise ValueError("arbitrary shell/code body demands are forbidden")
                demand = CapabilityDemand(goal_id, task, str(data["required_capability"]), str(data["intent"]), dict(data["inputs"]),
                    str(data["expected_output"]), float(data["risk"]), str(data["side_effect_class"]),
                    str(data.get("network_need", "none")), str(data.get("filesystem_need", "none")),
                    float(data.get("privacy", 1)), float(data["budget"]), bool(data["reversibility"]),
                    str(data["expected_evidence"]), float(data["confidence"]), float(data["goal_value"]),
                    float(data["information_gain"]), float(data["capability_gain"]), float(data["uncertainty"]))
                neuron_ids = tuple(n for decision in decisions if decision.colony_name == source_colony for n in decision.neuron_ids)
                assembly_ids = tuple(decision.assembly_id for decision in decisions if decision.colony_name == source_colony)
                provenance = DecisionProvenance(uuid4().hex, goal_id, episode_id, source_colony,
                    view["model"], assembly_ids, neuron_ids, demand.id, time.time())
                demand.decision_provenance_id = provenance.id
                self.embodiment_store.put("decision_provenance", provenance.id, provenance)
                self._event("CAPABILITY_DEMAND_CREATED", f"{source_colony} requested {demand.required_capability}",
                            {"goal_id": goal_id, "demand_id": demand.id, "colony": source_colony})
                utility = float(data.get("goal_value",1))+float(data.get("information_gain",.5))+float(data.get("capability_gain",0)) \
                    - float(data["budget"])-float(data["risk"])-(0 if data["reversibility"] else 1)-float(data.get("uncertainty",1-float(data["confidence"])))
                candidates.append((utility, demand, data))
        # Compare utilities within an inference stage, while cheap information-gathering
        # actions precede actions whose output depends on that evidence.
        return sorted(candidates, key=lambda x: (x[2]["side_effect_class"] not in {"none", "read"}, -x[0]))

    def _run_body_plan(self, state: dict[str, Any], candidates: list[tuple[float, CapabilityDemand, dict[str, Any]]], interpretations: dict[str, dict[str, Any]]) -> dict[str, Any]:
        observations = []; evidence = ""
        # Execute the best candidate per intent in utility order, permitting research then save.
        seen = set()
        for _, demand, raw in candidates:
            if demand.intent in seen: continue
            seen.add(demand.intent)
            provenance = next((item for item in self.embodiment_store.all("decision_provenance")
                               if item["id"] == demand.decision_provenance_id), {})
            acting_colony = provenance.get("source_colony")
            if evidence and isinstance(demand.inputs.get("content"), str): demand.inputs["content"] = demand.inputs["content"].replace("{evidence}", evidence[:8000])
            state.update(current_step="body_execution", current_organ=None); self.store.put("goals", state["id"], state)
            resolved = self.capability_resolver.resolve(demand)
            if resolved:
                state["current_organ"] = resolved[0].id; self.store.put("goals", state["id"], state)
                self._event("CAPABILITY_RESOLVED", f"Demand resolved to {resolved[0].id}",
                            {"goal_id": state["id"], "organ": resolved[0].id})
            result = self.action_loop.execute(demand)
            if isinstance(result, HumanApprovalRequest):
                state.update(current_step="pending_approval", pending_approval=result.id); self.store.put("goals",state["id"],state)
                if acting_colony: self._sister_transition(acting_colony, state["id"], "WAITING", "Waiting for Pier approval")
                return {"status":"pending_approval","request":asdict(result)}
            if not isinstance(result, ObservationEnvelope):
                state.update(current_step="capability_gap"); self.store.put("goals",state["id"],state)
                self._event("CAPABILITY_GAP", "No safe compatible organ", {"goal_id": state["id"], "demand_id": demand.id})
                return {"status":"gap"}
            if acting_colony: self._sister_transition(acting_colony, state["id"], "ACTING", "Body operation invoked")
            if acting_colony: self._sister_transition(acting_colony, state["id"], "VERIFYING", "Checking body observation")
            level = VerificationLevel.TRANSPORT_VERIFIED if demand.required_capability == "web" else VerificationLevel.ARTIFACT_VERIFIED
            verified = self.action_loop.verify(result, lambda obs: obs.success and bool(obs.content_hash), level)
            if not result.success:
                state.update(status="failed", current_step="FAILED", last_observation=result.action_id)
                self.store.put("goals", state["id"], state)
                if acting_colony: self._sister_transition(acting_colony, state["id"], "BLOCKED", "Body invocation failed")
                return {"status": "failed", "observations": [asdict(result)]}
            if verified:
                manifest = self.body_bus.manifests[result.organ]
                manifest.verified_reliability = min(1, manifest.verified_reliability + .01)
            observations.append(asdict(result)); state["last_observation"] = result.action_id
            if verified and demand.required_capability == "filesystem" and demand.intent in {"write", "append"}:
                for check in ("exists", "hash"):
                    verification = CapabilityDemand(demand.goal_id, demand.task, "filesystem", check,
                        {"path": demand.inputs["path"]}, f"written file {check}", risk=0,
                        filesystem_need="workspace", budget=demand.budget)
                    checked = self.action_loop.execute(verification)
                    if isinstance(checked, ObservationEnvelope):
                        self.action_loop.verify(checked, lambda obs: obs.success and bool(obs.result.get("exists", obs.result.get("sha256"))), VerificationLevel.ARTIFACT_VERIFIED)
                        observations.append(asdict(checked)); state["last_observation"] = checked.action_id
            if verified:
                evidence = result.result.get("text", json.dumps(result.result)) if isinstance(result.result, dict) else str(result.result)
            state["current_step"] = "verified" if verified else "replan"; self.store.put("goals",state["id"],state)
            if acting_colony: self._sister_transition(acting_colony, state["id"], "IDLE", "Body step complete")
        state["status"] = "awaiting_outcome"; state["current_step"] = "AWAITING_OUTCOME"; self.store.put("goals",state["id"],state)
        self._event("OUTCOME_AWAITING", "Body result awaits outcome evidence", {"goal_id": state["id"]})
        self.organism.memory.world_model["last_body_outcome"] = {"observations": observations,
            "verification_level": VerificationLevel.ARTIFACT_VERIFIED.value}
        self.organism._commit_state("observed_body_execution")
        return {"status":"executed", "observations":observations,
                "final_response":"Completed real body actions and verified their transport/artifacts; cognitive outcome remains unverified."}

    def evaluate_outcome(self, evaluation: OutcomeEvaluation, *, task: str = "goal_reasoning") -> bool:
        """External/evaluable outcome gate; transport success alone cannot call this."""
        if evaluation.evaluator not in OutcomeEvaluator.__members__:
            raise PermissionError("models and colonies are not trusted outcome evaluators")
        if not evaluation.evidence_refs: raise ValueError("outcome verification requires real evidence references")
        data = next(o for o in self.embodiment_store.all("observation") if o["action_id"] == evaluation.observation_id)
        observation = ObservationEnvelope(**{**data, "evidence_refs": tuple(data["evidence_refs"])})
        self.embodiment_store.put("outcome_evaluation", evaluation.observation_id, evaluation)
        if not evaluation.correct: return self.action_loop.verify(observation, lambda _: False, VerificationLevel.OUTCOME_VERIFIED)
        if not observation.decision_provenance_id: return False
        matches = [p for p in self.embodiment_store.all("decision_provenance") if p["id"] == observation.decision_provenance_id]
        if len(matches) != 1: return False
        provenance = matches[0]
        if not provenance.get("source_colony") or not provenance.get("source_model_key") or not provenance.get("source_neuron_ids"): return False
        self.action_loop.verify(observation, lambda _: True, VerificationLevel.OUTCOME_VERIFIED)
        colony = self.organism.colonies[provenance["source_colony"]]
        for neuron_id in provenance["source_neuron_ids"]: colony.neurons[neuron_id].verified_contribution += 1
        record = self.records.get(provenance["source_model_key"])
        if record is not None: self.router.observe_verified_outcome(record, task, True)
        digest = SisterDevelopmentDigest(provenance["source_colony"],(observation.operation,),(),None,None,
            "route by outcome evidence", "retain outcome-verified strategy", evaluation.evidence_refs, True)
        other = next(name for name in self.organism.colonies if name != provenance["source_colony"])
        self.embodiment_store.put("digest", evaluation.observation_id, {**asdict(digest),"observation_id":evaluation.observation_id,
            "target":other,"response":"PENDING"})
        goal_rows = self.store.rows("SELECT state FROM goals WHERE id=?", (observation.goal_id,))
        if goal_rows:
            goal = json.loads(goal_rows[0]["state"]); goal.update(status="outcome_verified", current_step="OUTCOME_VERIFIED")
            self.store.put("goals", observation.goal_id, goal)
        self._event("OUTCOME_VERIFIED", "External outcome evidence verified", {"goal_id": observation.goal_id})
        self.organism._commit_state("outcome_verified_learning"); self._save_models(); return True

    def respond_to_digest(self, observation_id: str, sister: str, response: DigestResponse) -> None:
        data = next(d for d in self.embodiment_store.all("digest") if d.get("observation_id") == observation_id
                    and d.get("target") == sister and d.get("response") == "PENDING")
        data["response"] = response.value
        if response == DigestResponse.ADOPT: self.organism.colonies[sister].memories.append("candidate-strategy:"+data["strategy_lesson"])
        elif response == DigestResponse.TEST_INDEPENDENTLY: self.embodiment_store.put("borrowed_hypothesis", observation_id,
            {"sister":sister,"lesson":data["strategy_lesson"],"verified":False})
        elif response == DigestResponse.PRESERVE_ALTERNATIVE: self.organism.colonies[sister].memories.append("alternative:"+data["strategy_lesson"])
        self.embodiment_store.put("digest", observation_id, data)

    def _best_colony(self, decisions: list[Any]) -> tuple[str, Any]:
        name = decisions[0].colony_name
        return name, self.organism.colonies[name]

    @staticmethod
    def _core_claims(arguments: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        return [{"colony": colony,
                 "hypotheses": view["argument"].get("hypotheses", []),
                 "next_action": view["argument"].get("next_useful_action"),
                 "critical_assumptions": view["argument"].get(
                     "critical_assumptions", view["argument"].get("constraints", []))}
                for colony, view in arguments.items()]

    @classmethod
    def _candidate_disagreement(cls, arguments: dict[str, dict[str, Any]]) -> bool:
        if len(arguments) < 2:
            return False
        normalized = [json.dumps({key: value for key, value in claim.items() if key != "colony"},
                                 sort_keys=True) for claim in cls._core_claims(arguments)]
        return len(set(normalized)) > 1

    def _learn_neurons(self, decisions: list[Any], stimulus: str) -> None:
        for decision in decisions:
            colony = self.organism.colonies[decision.colony_name]
            for neuron_id in decision.neuron_ids:
                neuron = colony.neurons[neuron_id]
                neuron.specialize(decision.purpose.value, stimulus)
                # Successful cognition is useful experience, not verified real-world evidence.
                neuron.confidence = min(1, neuron.confidence + .01)
            colony.memories.append(decision.purpose.value)

    def _dissolve(self) -> None:
        for colony in self.organism.colonies.values():
            for assembly_id in tuple(colony.assemblies):
                colony.dissolve_assembly(assembly_id)

    def _save_models(self) -> None:
        for record in self.records.values(): self.store.put("models", record.key, asdict(record))

    def _event(self, kind: str, summary: str, state: dict[str, Any] | None = None) -> None:
        # Deliberately accepts structured operational facts, never prompts, model
        # reasoning, secrets, memory contents, or private topology.
        self.store.runtime_event(kind, summary, state or {})

    def timeline(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.store.rows("SELECT sequence,kind,summary,state,created FROM runtime_events "
                               "ORDER BY sequence DESC LIMIT ?", (max(1, min(limit, 200)),))
        return [{"sequence": row["sequence"], "kind": row["kind"],
                 "summary": row["summary"], "state": json.loads(row["state"]),
                 "created": row["created"]} for row in reversed(rows)]

    def _sister_summary(self, name: str, goal: dict[str, Any], episode: dict[str, Any]) -> dict[str, Any]:
        row = self.store.rows("SELECT status,summary,confidence,created FROM sister_states WHERE colony=? "
                              "ORDER BY sequence DESC LIMIT 1", (name,))[0]
        view = episode.get("interpretations", {}).get(name, {}); argument = view.get("argument", {})
        selection = self.store.rows("SELECT model_id,provider,latency_ms FROM model_selections WHERE colony=? "
                                    "ORDER BY started_at DESC LIMIT 1", (name,))
        selected = selection[0] if selection else {}
        return {"status": row["status"], "public_summary": row["summary"],
                "hypothesis": next(iter(argument.get("hypotheses", [])), None), "confidence": row["confidence"],
                "evidence_count": len(argument.get("success_evidence", [])),
                "model": f'{selected["provider"]}:{selected["model_id"]}' if selected else None,
                "organ": goal.get("current_organ"), "latency_ms": selected["latency_ms"] if selected else None}

    def operational_status(self) -> dict[str, Any]:
        active = self.store.rows("SELECT state FROM goals ORDER BY rowid DESC LIMIT 1")
        goal = json.loads(active[0]["state"]) if active else {}
        episode = {}
        if goal.get("episode_id"):
            row = self.store.rows("SELECT state FROM episodes WHERE id=?", (goal["episode_id"],))
            episode = json.loads(row[0]["state"]) if row else {}
        observations = self.embodiment_store.all("observation"); approvals = self.embodiment_store.all("approval")
        predictions = self.embodiment_store.all("prediction")
        gaps = self.embodiment_store.all("gap"); exchanges = self.embodiment_store.all("exchange")
        confidences = {name: round(sum(n.confidence for n in colony.neurons.values())/len(colony.neurons),3)
                       for name,colony in self.organism.colonies.items()}
        last = observations[-1] if observations else None
        selected_rows = self.store.rows("SELECT * FROM model_selections ORDER BY started_at DESC LIMIT 1")
        selected = dict(selected_rows[0]) if selected_rows else None
        return {"current_goal": goal.get("description"), "work_class": goal.get("work_class"),
                "current_step": goal.get("current_step","idle"), "current_organ": goal.get("current_organ"),
                "selected_colony": goal.get("selected_colony") or (selected.get("colony") if selected else None),
                "selected_model": f'{selected["provider"]}:{selected["model_id"]}' if selected else None,
                "routing_reason": selected.get("routing_reason") if selected else None,
                "prediction": predictions[-1] if predictions else None,
                "observation": last, "verification": last.get("verification") if last else None,
                "approval": next((a for a in reversed(approvals) if a["status"] == "pending"), None),
                "last_observation": last, "pending_approval": next((a for a in reversed(approvals) if a["status"]=="pending"),None),
                "capability_gaps": gaps, "a_confidence": confidences["Saphira-A"], "b_confidence": confidences["Saphira-B"],
                "sister_exchange": exchanges[-1] if exchanges else None,
                "latest_latency": last.get("latency_ms") if last else None,
                "sisters": {name: self._sister_summary(name, goal, episode)
                            for name in ("Saphira-A", "Saphira-B")},
                "timeline": self.timeline()}

    def decide_approval(self, request_id: str, approve: bool) -> None:
        if not approve:
            self.permission_authority.deny(request_id, approver="Pier")
            request = next(a for a in self.embodiment_store.all("approval") if a["id"] == request_id)
            goal_rows = self.store.rows("SELECT state FROM goals WHERE id=?", (request["goal_id"],))
            if goal_rows:
                state = json.loads(goal_rows[0]["state"])
                state.update(status="blocked", current_step="DENIED", pending_approval=None)
                self.store.put("goals", state["id"], state)
            return
        lease = self.permission_authority.approve(request_id, approver="Pier")
        request = next(a for a in self.embodiment_store.all("approval") if a["id"] == request_id)
        pending = next(d for d in self.embodiment_store.all("pending_demand")
                       if d["approval_request_id"] == request_id)
        pending.pop("approval_request_id")
        demand = CapabilityDemand(**pending)
        manifest = self.body_bus.manifests[request["organ"]]
        goal_rows = self.store.rows("SELECT state FROM goals WHERE id=?", (request["goal_id"],))
        state = json.loads(goal_rows[0]["state"]) if goal_rows else {"id":request["goal_id"],"description":"approved task"}
        result = self.action_loop.execute(demand, lease=lease)
        if isinstance(result, ObservationEnvelope):
            level = VerificationLevel.TRANSPORT_VERIFIED if manifest.kind == "web" else VerificationLevel.ARTIFACT_VERIFIED
            self.action_loop.verify(result, lambda observation: observation.success and bool(observation.content_hash), level)
            state.update(status="awaiting_outcome", current_step="AWAITING_OUTCOME", current_organ=request["organ"],
                         last_observation=result.action_id, pending_approval=None)
            self.store.put("goals", state["id"], state)

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
            if not self.intelligence_connected:
                raise ProviderUnavailable("external intelligence is disconnected")
            record = self.router.choose(list(self.records.values()), "conversation",
                                        policy=self.routing_policy)
            persisted = json.loads(active[0]["state"]) if active else None
            result = self._model_call(record, persisted.get("id") if persisted else None,
                persisted.get("episode_id") if persisted else None, "conversation", None,
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
            return (f"Recruited {len(episode['assemblies'])} assemblies, updated cautious "
                    "specializations, and recorded routing reliability. No real-world outcome has been verified.")
        return f"Working on {state['description']}. Next action: {state['next_action']}"

    def close(self) -> None:
        self.organism.checkpoint()
        self.owner_capabilities.close()
        self.embodiment_store.close()
        self.store.close()

    def __enter__(self) -> "GodRuntime": return self
    def __exit__(self, *_: Any) -> None: self.close()
