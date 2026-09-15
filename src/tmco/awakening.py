"""Usable, idle-by-default awakening runtime built around replaceable model organs."""
from __future__ import annotations

import json
import sqlite3
import time
import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from .buses import BodyBus, ModelBus, ModelProvider, OrganManifest, ProviderUnavailable
from .capabilities import OwnerCapability, OwnerCapabilityAuthority
from .embodiment import (ActionLoop, CapabilityDemand, CapabilityResolver, EmbodimentStore,
                         DecisionProvenance, HumanApprovalRequest, ObservationEnvelope,
                         OrganRegistry, OutcomeEvaluation, OutcomeEvaluator, PermissionAuthority,
                         VerificationLevel, WebResearchOrgan,
                         WorkspaceFilesystemOrgan)
from .executive import Cognition
from .development import DevelopmentCandidate, DevelopmentEngine
from .data_policy import DataClass
from .models import ModelRecord, ModelRouter, ResponseMode
from .morphogenesis import AssemblyFormationPolicy
from .system import TMCOSystem
from .types import ActionCandidate, ComputeBudget, Goal, GoalStatus
from .sisters import (BriefResponse, DigestResponse, SisterBrief, SisterDevelopmentDigest,
                      SisterExchangePolicy, SisterView, WorkClass, classify_work)


@dataclass(frozen=True, slots=True)
class GoalSuccessVerification:
    goal_id: str
    evaluator: str
    success_criteria: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    verified: bool
    timestamp: float
    reason: str


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
        CREATE TABLE IF NOT EXISTS goal_success_verifications(
          id INTEGER PRIMARY KEY AUTOINCREMENT, goal_id TEXT NOT NULL,
          state TEXT NOT NULL, created REAL NOT NULL);
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

    def goal_verification(self, verification: GoalSuccessVerification) -> None:
        self.connection.execute("INSERT INTO goal_success_verifications(goal_id,state,created) VALUES(?,?,?)",
                                (verification.goal_id, json.dumps(asdict(verification)), verification.timestamp))
        self.connection.commit()


class ModelBackedCognition(Cognition):
    """Cognitive schema adapter. Identity and learning remain outside the model."""
    def __init__(self, bus: ModelBus, record: ModelRecord):
        self.bus, self.record = bus, record

    def ask(self, demand: str, context: dict[str, Any]) -> dict[str, Any]:
        result = self.bus.request(self.record.provider, {
            "model_id": self.record.model_id,
            "prompt": demand + "\nJSON context:\n" + json.dumps(context),
            "response_mode": ResponseMode.STRUCTURED.value,
            "data_classes": [DataClass.OWNER_TYPED.value, DataClass.OPERATIONAL_METADATA.value],
        })
        if not isinstance(result, dict):
            raise ValueError("model cognition must return a JSON object")
        return result

    def converse(self, message: str, context: dict[str, Any]) -> str:
        """Send owner-authored text plus compact, non-private operational context."""
        result = self.bus.request(self.record.provider, {
            "model_id": self.record.model_id,
            "prompt": "Reply naturally and truthfully. Do not invent activity.\n"
                      + "Owner message:\n" + message + "\nOperational context:\n"
                      + json.dumps(context),
            "response_mode": ResponseMode.TEXT.value,
            "data_classes": [DataClass.OWNER_TYPED.value, DataClass.OPERATIONAL_METADATA.value],
        })
        if not isinstance(result, str):
            raise ValueError("conversation model must return text")
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
        self.routing_policy = "ZERO_COST"
        self.monetary_budget = 0
        self.cognition: Cognition = DisconnectedCognition()
        # DigitalNeuron formation remains an opt-in legacy experiment. Live body
        # capability resolution and development do not depend on it.
        self.policy = formation_policy
        # Existing Phase 1 state format remains the authority for organism identity/neural state.
        self.organism = TMCOSystem(directory / "organism", self.cognition, secret=secret,
                                   formation_policy=self.policy)
        self.store = AwakeningStore(directory / "awakening.sqlite3")
        self.routing_policy = self.store.setting("routing_policy", "ZERO_COST")
        if self.routing_policy == "AUTO":
            self.routing_policy = "ZERO_COST"
            self.store.set_setting("routing_policy", self.routing_policy)
        self.body_bus = BodyBus()
        self.embodiment_store = EmbodimentStore(directory / "embodiment.sqlite3")
        self.organ_registry = OrganRegistry(self.body_bus, self.embodiment_store)
        self.capability_resolver = CapabilityResolver(self.body_bus, self.embodiment_store)
        self.action_loop = ActionLoop(self.body_bus, self.embodiment_store, self._action_event)
        self.permission_authority = PermissionAuthority(self.embodiment_store)
        self.owner_capabilities = OwnerCapabilityAuthority(self.organism.root,
                                                           directory / "owner_capabilities.sqlite3")
        self.bus.outbound_policy.authority = self.owner_capabilities
        self.sister_exchange = SisterExchangePolicy()
        self._restore_exchange_rounds()
        self._register_builtin_organs(web_test_allow_hosts)
        self.development = DevelopmentEngine(self.body_bus, self.embodiment_store,
                                             self.organ_registry, self._development_event)
        self.development.restore()
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

    def _development_event(self, kind: str, state: dict[str, Any]) -> None:
        self._event(kind, kind.replace("_", " ").title(), state)

    def _composable_catalog(self) -> list[dict[str, Any]]:
        catalog = []
        for manifest in sorted(self.body_bus.manifests.values(), key=lambda item: item.id):
            boundary = f"{manifest.id} {manifest.kind}".lower()
            if (not manifest.available or not manifest.trusted
                    or any(token in boundary for token in ("root", "credential", "vault", "shell"))):
                continue
            catalog.append({"organ": manifest.id, "kind": manifest.kind,
                            "operations": manifest.operations,
                            "permissions": sorted(manifest.permissions), "risk": manifest.risk,
                            "side_effect_class": manifest.side_effect_class,
                            "reversible": manifest.reversible, "cost": manifest.cost})
        return catalog

    @staticmethod
    def _objective_composite_score(_spec: Any, evidence: dict[str, Any]) -> float:
        steps = evidence.get("steps")
        if not isinstance(steps, dict) or not steps: return 0
        score = 1.0
        for result in steps.values():
            if not isinstance(result, dict) or not result: return 0
            score += sum(value not in (None, "", False) for value in result.values())
            if isinstance(result.get("sha256"), str) and len(result["sha256"]) == 64: score += 4
        return score

    @staticmethod
    def _compact_development_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
        compact: dict[str, Any] = {}
        for step, result in evidence.get("steps", {}).items():
            if isinstance(result, dict):
                compact[step] = {key: (value[:128] if isinstance(value, str) else value)
                                 for key, value in result.items() if key in {"path", "bytes", "size", "exists", "sha256"}}
        return compact

    def _develop_gap(self, demand: CapabilityDemand, interpretations: dict[str, dict[str, Any]]) -> DevelopmentCandidate | None:
        if (demand.network_need != "none" or demand.filesystem_need not in {"workspace", "none"}
                or not interpretations):
            return None
        catalog = self._composable_catalog()
        contract = {"id": "composite:<name>", "capability": demand.required_capability,
                    "operation": demand.intent, "required_inputs": sorted(demand.inputs),
                    "steps": [{"id": "unique-step", "organ": "catalog organ", "operation": "catalog operation",
                               "arguments": {"argument": "input.<name> or steps.<prior-step>.<field>"}}],
                    "description": "compact purpose", "version": "1"}
        proposals: dict[str, Any] = {}
        development_records: dict[str, ModelRecord] = {}
        used = {view["model"] for view in interpretations.values()}
        for lineage in ("Saphira-A", "Saphira-B"):
            if lineage in interpretations:
                record = self.records[interpretations[lineage]["model"]]
            else:
                record = self.router.choose(list(self.records.values()), "capability_development",
                                            exclude=used, policy=self.routing_policy)
                used.add(record.key)
            development_records[lineage] = record
            def propose(_demand: CapabilityDemand, *, lineage=lineage, record=record):
                response = self._model_call(record, demand.goal_id, None, "capability_development", lineage,
                    "Independently propose one declarative CompositeOrganSpec. Return only a JSON object under "
                    "composite_organ. Use only catalog operations and reference syntax from the contract. Do not "
                    "return reasoning, Python, shell, credentials, Root data, network targets, or executable code.",
                    {"demand": asdict(demand), "trusted_catalog": catalog,
                     "composite_organ_contract": contract,
                     "security": ["registered trusted operations only", "no recursion or cycles",
                                  "no Root, credentials, shell, code, privilege grants, or scope expansion"]})
                development_records[lineage] = self.records[self._last_model_key]
                proposal = response.get("composite_organ")
                if not isinstance(proposal, dict): raise ValueError("model did not return a composite_organ object")
                return proposal
            proposals[lineage] = propose

        def audit(auditor: str, origin: str, spec: Any, evidence: dict[str, Any]) -> bool:
            record = development_records[auditor]
            response = self._model_call(record, demand.goal_id, None, "capability_development_audit", auditor,
                "Audit this tested declarative candidate using only its compact spec and objective evidence. "
                "Return approved as a JSON boolean. Do not return private reasoning.",
                {"candidate_origin": origin, "candidate": asdict(spec),
                 "objective_evidence": self._compact_development_evidence(evidence)})
            return response.get("approved") is True
        return self.development.develop(demand, proposals, self._objective_composite_score, audit)

    def _restore_exchange_rounds(self) -> None:
        for event in self.embodiment_store.all("exchange"):
            self.sister_exchange.rounds[event["goal_id"]] = max(
                self.sister_exchange.rounds.get(event["goal_id"], 0), event["round"])

    @property
    def intelligence_connected(self) -> bool:
        return bool(self.bus.providers and any(record.availability and record.zero_cost_eligible
                                               and (record.privacy == "local" or record.corporate_safe)
                                               for record in self.records.values()))

    def set_routing_policy(self, policy: str) -> None:
        if policy not in {"ZERO_COST", "FREE_FIRST", "LOCAL_FIRST"}:
            raise ValueError("unknown routing policy")
        self.routing_policy = policy
        self.store.set_setting("routing_policy", policy)
        self._event("ROUTING", f"Routing policy changed to {policy}")

    def attach_intelligence(self, providers: dict[str, ModelProvider],
                            records: list[ModelRecord], *, configuration_changed: bool = False) -> None:
        bus = ModelBus(providers, production=True)
        bus.outbound_policy.authority = self.owner_capabilities
        configured = {record.key: record for record in records}
        if not configured:
            raise ProviderUnavailable("at least one model record is required")
        self.bus, self.records = bus, configured
        self._restore_models()
        # Attachment follows a successful capability probe, so transient prior
        # unavailability must not prevent this newly confirmed connection.
        for key, record in configured.items():
            self.records[key].availability = record.availability
            if configuration_changed:
                self.records[key].blocked = False
                self.records[key].consecutive_failures = 0
                self.records[key].last_failure_class = None
                self.records[key].cooldown_until = 0
        try:
            initial = self.router.choose(list(self.records.values()), "conversation",
                                         policy=self.routing_policy)
        except RuntimeError:
            self.cognition = DisconnectedCognition()
            self.organism.executive.cognition = self.cognition
            self._save_models()
            self._event("INTELLIGENCE", "NO_FREE_SAFE_INTELLIGENCE_AVAILABLE")
            return
        self.cognition = ModelBackedCognition(self.bus, initial)
        self.organism.executive.cognition = self.cognition
        self._save_models()
        self._event("INTELLIGENCE", f"Connected {len(configured)} discovered model(s)")

    def detach_intelligence(self) -> None:
        self.bus = ModelBus(production=True)
        self.bus.outbound_policy.authority = self.owner_capabilities
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

    def _model_attempt(self, record: ModelRecord, goal_id: str | None, episode_id: str | None,
                       task: str, colony: str | None, demand: str, context: dict[str, Any]) -> dict[str, Any]:
        identity, started_wall, started = uuid4().hex, time.time(), time.monotonic()
        selection = {"id": identity, "goal_id": goal_id, "episode_id": episode_id,
                     "task_class": task, "colony": colony, "provider": record.provider,
                     "model_id": record.model_id, "routing_policy": self.routing_policy,
                     "routing_reason": self.router.reason(record, task, self.routing_policy),
                     "started_at": started_wall, "finished_at": None, "latency_ms": None,
                     "success": None}
        self._event("MODEL_SELECTED", f"{record.key} selected for {task}",
                    {key: selection[key] for key in ("id", "goal_id", "episode_id", "task_class", "colony",
                                                     "provider", "model_id", "routing_policy", "routing_reason")})
        self.store.model_selection(selection)
        failure_class = None
        try:
            result = ModelBackedCognition(self.bus, record).ask(demand, context); success = True
            return result
        except Exception as error:
            success = False
            failure_class = getattr(error, "failure_class", None)
            raise
        finally:
            latency = (time.monotonic() - started) * 1000
            selection.update(finished_at=time.time(), latency_ms=latency, success=int(success))
            self.store.model_selection(selection)
            self.router.observe_call(record, success, latency, failure_class)

    def _model_call(self, record: ModelRecord, goal_id: str | None, episode_id: str | None,
                    task: str, colony: str | None, demand: str, context: dict[str, Any]) -> dict[str, Any]:
        attempted: set[str] = set()
        current = record
        last_error: Exception | None = None
        while len(attempted) < len(self.records):
            attempted.add(current.key)
            try:
                result = self._model_attempt(current, goal_id, episode_id, task, colony, demand, context)
                self._last_model_key = current.key
                self._save_models()
                return result
            except Exception as error:
                last_error = error
                self._save_models()
                self._event("MODEL_FAILOVER", f"{current.key} failed; seeking another safe free model",
                            {"goal_id": goal_id, "task": task})
                try:
                    current = self.router.choose(list(self.records.values()), task, exclude=attempted,
                                                 policy=self.routing_policy)
                except RuntimeError:
                    break
        raise ProviderUnavailable("NO_FREE_SAFE_INTELLIGENCE_AVAILABLE") from last_error

    def _conversation_call(self, message: str, state: dict[str, Any] | None) -> str:
        """Use TEXT mode with bounded failover and no private or workspace state."""
        attempted: set[str] = set()
        last_error: Exception | None = None
        while len(attempted) < len(self.records):
            try:
                record = self.router.choose(list(self.records.values()), "conversation",
                                            exclude=attempted, policy=self.routing_policy)
            except RuntimeError:
                break
            attempted.add(record.key)
            started = time.monotonic()
            try:
                compact = {key: state.get(key) for key in
                           ("status", "current_step", "work_class") if state is not None}
                answer = ModelBackedCognition(self.bus, record).converse(message, compact)
                self.router.observe_call(record, True, (time.monotonic() - started) * 1000)
                self._event("MODEL_RESPONSE", f"{record.key} returned conversation text")
                self._save_models()
                return answer
            except Exception as error:
                last_error = error
                self.router.observe_call(record, False, (time.monotonic() - started) * 1000,
                                         getattr(error, "failure_class", None))
                self._event("MODEL_FAILOVER", f"{record.key} failed; trying another available model")
        self._save_models()
        raise ProviderUnavailable("NO_FREE_SAFE_INTELLIGENCE_AVAILABLE") from last_error

    def _sister_transition(self, colony: str, goal_id: str | None, status: str, summary: str) -> None:
        confidence = round(sum(n.confidence for n in self.organism.colonies[colony].neurons.values()) /
                           len(self.organism.colonies[colony].neurons), 3)
        self.store.sister_state(colony, goal_id, status, summary, confidence)

    def submit_goal(self, text: str, *, important: bool = True) -> dict[str, Any]:
        if not text.strip():
            raise ValueError("a natural-language goal is required")
        if not self.intelligence_connected:
            raise ProviderUnavailable("NO_FREE_SAFE_INTELLIGENCE_AVAILABLE")
        goal_id, episode_id = uuid4().hex, uuid4().hex
        self._event("GOAL_ACCEPTED", "Owner goal accepted", {"goal_id": goal_id})
        goal = Goal(goal_id, text, ("credible evidence of progress",))
        work_class = classify_work(text)
        self._event("WORK_CLASS_SELECTED", f"Work classified as {work_class.value}", {"goal_id": goal_id})
        decisions = (self.policy.form(self.organism.colonies, goal,
                                      {name: ComputeBudget(8) for name in self.organism.colonies})
                     if self.policy is not None else [])
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
                    {"colony": name, "goal": text})
            except Exception:
                self._sister_transition(name, goal_id, "BLOCKED", "Model call failed")
                self._event("FAILED", f"{name} model call failed", {"goal_id": goal_id, "colony": name})
                self._save_models(); raise
            interpretations[name] = {"model": self._last_model_key, "argument": answer}
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
                 "current_organ": None, "last_observation": None, "exchange_status": "completed" if exchange else "none",
                 "step_count": 1, "action_ledger": {}, "stagnation_count": 0,
                 "blocker": None, "verified_evidence": [], "last_consumed_observation": None,
                 "success_criteria": list(goal.success_criteria)}
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

    def launch_goal(self, text: str) -> str:
        """Production entry point returning the durable identity of a launched goal."""
        return str(self.submit_goal(text, important=True)["goal_id"])

    @staticmethod
    def _blocker_for(state: dict[str, Any], body: dict[str, Any] | None = None) -> str | None:
        if state.get("pending_approval"): return "PERMISSION"
        if body and body.get("status") == "gap": return "CAPABILITY"
        if body and body.get("status") == "failed": return "EXECUTION"
        if state.get("stagnation_count", 0): return "STRATEGY"
        return None

    BLOCKER_CLASSES = {"INFORMATION", "CAPABILITY", "PERMISSION", "PROVIDER",
                       "STRATEGY", "OBJECTIVE", "EXECUTION"}
    ACTION_LEDGER_STATES = {"PROPOSED", "WAITING_APPROVAL", "EXECUTING", "OBSERVED",
                            "VERIFIED", "FAILED", "RETRYABLE", "SUPERSEDED"}
    GOAL_VERIFIERS = {"OWNER", "REGISTERED_VERIFIER", "OBJECTIVE_TEST"}

    def verify_goal_success(self, verification: GoalSuccessVerification,
                            capability: OwnerCapability) -> bool:
        rows = self.store.rows("SELECT state FROM goals WHERE id=?", (verification.goal_id,))
        if not rows: raise KeyError("unknown goal")
        state = json.loads(rows[0]["state"])
        if verification.evaluator not in self.GOAL_VERIFIERS:
            raise PermissionError("untrusted goal verifier")
        if tuple(state.get("success_criteria", ())) != verification.success_criteria:
            raise ValueError("goal verification criteria do not match the stable goal")
        if not verification.evidence_refs:
            raise ValueError("goal verification requires evidence references")
        request = capability.request
        verification_digest = hashlib.sha256(json.dumps(
            asdict(verification), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if (request.service != "goal-verification" or request.operation != verification.evaluator
                or request.account_id != verification.goal_id
                or request.allowed_submitted_data != verification.evidence_refs
                or request.workflow_id != verification_digest
                or request.executor_principal != "goal-success-gate" or request.maximum_cost != 0):
            raise PermissionError("goal verification capability scope mismatch")
        self.owner_capabilities.start(capability, request, executor_principal="goal-success-gate")
        self.store.goal_verification(verification)
        self._event("GOAL_SUCCESS_VERIFIED" if verification.verified else "GOAL_SUCCESS_REJECTED",
                    "Trusted goal-level verification recorded", {"goal_id": verification.goal_id,
                    "evaluator": verification.evaluator, "verified": verification.verified})
        return verification.verified

    @staticmethod
    def _action_identity(demand: CapabilityDemand) -> str:
        canonical = {"capability": demand.required_capability, "intent": demand.intent,
                     "inputs": demand.inputs, "expected_output": demand.expected_output,
                     "expected_evidence": demand.expected_evidence,
                     "side_effect_class": demand.side_effects,
                     "reversible": demand.reversible}
        return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def _twin_decision(self, candidates: list[tuple[float, CapabilityDemand, dict[str, Any]]],
                       interpretations: dict[str, dict[str, Any]]) -> tuple[str, list[tuple[float, CapabilityDemand, dict[str, Any]]]]:
        if len(interpretations) < 2:
            return "SINGLE", candidates
        by_fingerprint: dict[str, list[tuple[float, CapabilityDemand, dict[str, Any]]]] = {}
        for candidate in candidates:
            by_fingerprint.setdefault(self._action_identity(candidate[1]), []).append(candidate)
        if not by_fingerprint:
            return "AGREE", []
        if len(by_fingerprint) == 1:
            return "AGREE", [max(next(iter(by_fingerprint.values())), key=lambda item: item[0])]
        distinct = [max(group, key=lambda item: item[0]) for group in by_fingerprint.values()]
        compatible = (len({item[1].intent for item in distinct}) == len(distinct)
                      and all(item[1].reversible and item[1].risk <= .25 for item in distinct)
                      and sum(item[0] for item in distinct) > 0)
        if compatible:
            return "COMPLEMENTARY", sorted(distinct, key=lambda item: -item[0])
        # Conflict is arbitrated by explicit utility; do not execute both.
        return "CONFLICT", [max(distinct, key=lambda item: (item[0], self._action_identity(item[1])))]

    def advance_goal(self, goal_id: str) -> dict[str, Any]:
        """Advance one bounded, durable goal step without replaying verified actions."""
        rows = self.store.rows("SELECT state FROM goals WHERE id=?", (goal_id,))
        if not rows: raise KeyError("unknown goal")
        state = json.loads(rows[0]["state"])
        if state.get("status") in {"completed", "blocked"}:
            return state
        if state.get("status") == "budget_exhausted":
            state["status"] = "active"
        uncertain_actions = [entry for entry in state.get("action_ledger", {}).values()
                             if entry.get("status") == "EXECUTING"]
        if uncertain_actions:
            state.update(status="blocked", blocker="EXECUTION", current_step="BLOCKED")
            self.store.put("goals", goal_id, state)
            return state
        if state.get("pending_approval"):
            state.update(status="waiting_owner", blocker="PERMISSION")
            self.store.put("goals", goal_id, state); return state
        if not self.intelligence_connected:
            state.update(status="blocked", blocker="PROVIDER", current_step="BLOCKED")
            self.store.put("goals", goal_id, state); return state

        observations = [item for item in self.embodiment_store.all("observation")
                        if item.get("goal_id") == goal_id]
        evaluations = {item.get("observation_id"): item for item in
                       self.embodiment_store.all("outcome_evaluation")}
        positive = [item for item in observations if evaluations.get(item.get("action_id"), {}).get("correct")]
        negative = [item for item in observations if item.get("action_id") in evaluations
                    and not evaluations[item["action_id"]].get("correct")]
        goal_checks = [json.loads(row["state"]) for row in self.store.rows(
            "SELECT state FROM goal_success_verifications WHERE goal_id=? ORDER BY id", (goal_id,))]
        trusted_goal_checks = [check for check in goal_checks if check.get("verified")]
        goal_verified = bool(trusted_goal_checks)
        if goal_verified and state.get("completion_requested"):
            state.update(status="completed", current_step="COMPLETED", blocker=None,
                         verified_evidence=trusted_goal_checks[-1]["evidence_refs"])
            self.store.put("goals", goal_id, state)
            self._event("GOAL_COMPLETED", "Goal completed from downstream verified outcome", {"goal_id": goal_id})
            return state
        if negative:
            state.update(status="active", blocker="STRATEGY", current_step="REPLAN")

        compact_evidence = [{"action_id": item["action_id"], "operation": item["operation"],
                             "success": item["success"], "verification": item.get("verification_state"),
                             "content_hash": item.get("content_hash"),
                             "evidence_refs": item.get("evidence_refs", [])} for item in observations[-8:]]
        recruit_twins = bool(state.get("stagnation_count") or state.get("escalate_twin") or state.get("blocker") in
                             {"STRATEGY", "CAPABILITY", "EXECUTION", "OBJECTIVE"})
        lineages = ("Saphira-A", "Saphira-B") if recruit_twins else (self._dynamic_primary(state["description"])[0],)
        interpretations: dict[str, dict[str, Any]] = {}
        used: set[str] = set()
        for lineage in lineages:
            record = self.router.choose(list(self.records.values()), "goal_advance", exclude=used,
                                        policy=self.routing_policy)
            used.add(record.key)
            response = self._model_call(record, goal_id, state.get("episode_id"), "goal_advance", lineage,
                "Using this compact GoalBrief, return only next_useful_action, body_demands, completion_requested, "
                "uncertainty, risk, and blocker. Determine what is missing, which assumption matters, what evidence "
                "would reduce uncertainty, why the prior route failed, and what different safe experiment should run. "
                "Classify blocker as INFORMATION, CAPABILITY, PERMISSION, PROVIDER, STRATEGY, OBJECTIVE, or EXECUTION. "
                "Never claim completion from model judgment and do not return private reasoning.",
                {"owner_goal": state["description"], "step": state.get("step_count", 1),
                 "prior_action": state.get("next_action"), "blocker": state.get("blocker"),
                 "verified_operational_evidence": compact_evidence})
            interpretations[lineage] = {"model": self._last_model_key, "argument": response}

        chosen = next(iter(interpretations.values()))["argument"]
        demands = self._structured_demands(goal_id, state.get("episode_id") or uuid4().hex,
                                           state["description"], interpretations, [])
        twin_decision, selected_demands = self._twin_decision(demands, interpretations)
        state["twin_decision"] = twin_decision
        state["twin_decision_facts"] = {"relation": twin_decision,
            "lineages": sorted(interpretations), "proposal_count": len(demands),
            "selected_fingerprints": [self._action_identity(item[1]) for item in selected_demands]}
        ledger = state.setdefault("action_ledger", {})
        prior_evidence_count = len(observations)
        causal_step = state.get("step_count", 1) + 1
        unique = []
        for candidate in selected_demands:
            fingerprint = self._action_identity(candidate[1])
            prior = ledger.get(fingerprint)
            if prior and prior.get("step") != causal_step:
                meaningful_change = prior.get("evidence_count", 0) != prior_evidence_count
                if not meaningful_change:
                    state["stagnation_count"] = state.get("stagnation_count", 0) + 1
                else:
                    prior["evidence_count"] = prior_evidence_count
                continue
            unique.append(candidate)
        state["_current_causal_step"] = causal_step
        body = self._run_body_plan(state, unique, interpretations) if unique else None
        state.pop("_current_causal_step", None)
        state["step_count"] = causal_step
        state["next_action"] = chosen.get("next_useful_action")
        state["completion_requested"] = chosen.get("completion_requested") is True
        proposed_blocker = str(chosen.get("blocker") or "").upper()
        state["blocker"] = self._blocker_for(state, body) or (
            proposed_blocker if proposed_blocker in self.BLOCKER_CLASSES else None)
        state["escalate_twin"] = (float(chosen.get("uncertainty", 0)) >= .5
                                  or float(chosen.get("risk", 0)) >= .4
                                  or state["completion_requested"] and not goal_verified)
        state["current_step"] = ("METACOGNITION" if state.get("stagnation_count") else
                                 "CANDIDATE_FOR_COMPLETION" if state["completion_requested"] else
                                 state.get("current_step", "REPLAN"))
        if state.get("stagnation_count", 0) >= 3:
            state.update(status="blocked", current_step="BLOCKED", blocker="STRATEGY")
        elif body and body.get("status") == "pending_approval":
            state.update(status="waiting_owner", blocker="PERMISSION")
        else:
            state["status"] = "active"
        self.store.put("goals", goal_id, state)
        self._event("GOAL_ADVANCED", "Durable goal advanced one bounded step",
                    {"goal_id": goal_id, "step": state["step_count"], "blocker": state.get("blocker"),
                     "twin_recruited": len(lineages) == 2})
        return state

    def run_goal(self, goal_id: str, max_steps: int = 1) -> dict[str, Any]:
        if not 1 <= max_steps <= 50: raise ValueError("max_steps must be between 1 and 50")
        state: dict[str, Any] = {}
        for _ in range(max_steps):
            state = self.advance_goal(goal_id)
            if state.get("status") in {"completed", "waiting_owner", "blocked"}: return state
        if state.get("status") == "active":
            state["status"] = "budget_exhausted"; state["current_step"] = "BUDGET_EXHAUSTED"
            self.store.put("goals", goal_id, state)
        return state

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
                # Outcome attribution remains compatible with the persisted Phase-1
                # substrate without requiring heuristic assembly formation.
                if not neuron_ids:
                    neuron_ids = (next(iter(self.organism.colonies[source_colony].neurons)),)
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
        return sorted(candidates, key=lambda x: (
            x[2]["side_effect_class"] not in {"none", "read"}, -x[0],
            hashlib.sha256(json.dumps({"intent": x[1].intent, "inputs": x[1].inputs},
                                     sort_keys=True).encode()).hexdigest()))

    def _run_body_plan(self, state: dict[str, Any], candidates: list[tuple[float, CapabilityDemand, dict[str, Any]]], interpretations: dict[str, dict[str, Any]]) -> dict[str, Any]:
        observations = []; evidence = ""
        ledger = state.setdefault("action_ledger", {})
        # Execute the best candidate per intent in utility order, permitting research then save.
        seen = set()
        for _, demand, raw in candidates:
            if demand.intent in seen: continue
            seen.add(demand.intent)
            fingerprint = self._action_identity(demand)
            existing = ledger.get(fingerprint)
            if existing and existing.get("status") in {"OBSERVED", "VERIFIED", "FAILED", "EXECUTING", "WAITING_APPROVAL"}:
                # EXECUTING after a crash is deliberately not retried: the host
                # cannot prove the prior side effect did not occur.
                continue
            ledger[fingerprint] = {"fingerprint": fingerprint, "status": "PROPOSED",
                "step": state.get("_current_causal_step", state.get("step_count", 1)),
                "evidence_count": len(self.embodiment_store.all("observation")),
                "capability": demand.required_capability, "intent": demand.intent,
                "reversible": demand.reversible, "action_id": None}
            self.store.put("goals", state["id"], state)
            winner = None
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
            else:
                state.update(current_step="capability_gap"); self.store.put("goals", state["id"], state)
                self._event("CAPABILITY_GAP", "No safe compatible organ", {"goal_id": state["id"], "demand_id": demand.id})
                winner = self._develop_gap(demand, interpretations)
                resolved = self.capability_resolver.resolve(demand) if winner is not None else None
                if resolved is None:
                    ledger[fingerprint]["status"] = "RETRYABLE"
                    self.store.put("goals", state["id"], state)
                    return {"status":"gap"}
                state.update(current_step="body_execution", current_organ=resolved[0].id)
                self.store.put("goals", state["id"], state)
                self._event("CAPABILITY_RESOLVED", f"Developed demand resolved to {resolved[0].id}",
                            {"goal_id": state["id"], "organ": resolved[0].id, "demand_id": demand.id})
            ledger[fingerprint]["status"] = "EXECUTING"
            self.store.put("goals", state["id"], state)
            result = self.action_loop.execute(demand)
            if isinstance(result, HumanApprovalRequest):
                ledger[fingerprint].update(status="WAITING_APPROVAL", approval_request_id=result.id)
                state.update(current_step="pending_approval", pending_approval=result.id); self.store.put("goals",state["id"],state)
                if acting_colony: self._sister_transition(acting_colony, state["id"], "WAITING", "Waiting for Pier approval")
                return {"status":"pending_approval","request":asdict(result)}
            if not isinstance(result, ObservationEnvelope):
                ledger[fingerprint]["status"] = "FAILED"
                state.update(current_step="capability_gap"); self.store.put("goals",state["id"],state)
                return {"status":"gap"}
            ledger[fingerprint].update(status="OBSERVED", action_id=result.action_id)
            self.store.put("goals", state["id"], state)
            if acting_colony: self._sister_transition(acting_colony, state["id"], "ACTING", "Body operation invoked")
            if acting_colony: self._sister_transition(acting_colony, state["id"], "VERIFYING", "Checking body observation")
            level = VerificationLevel.TRANSPORT_VERIFIED if demand.required_capability == "web" else VerificationLevel.ARTIFACT_VERIFIED
            verified = self.action_loop.verify(result, lambda obs: obs.success and bool(obs.content_hash), level)
            if not result.success:
                ledger[fingerprint]["status"] = "FAILED"
                state.update(status="failed", current_step="FAILED", last_observation=result.action_id)
                self.store.put("goals", state["id"], state)
                if acting_colony: self._sister_transition(acting_colony, state["id"], "BLOCKED", "Body invocation failed")
                return {"status": "failed", "observations": [asdict(result)]}
            if verified:
                ledger[fingerprint]["status"] = "VERIFIED"
                manifest = self.body_bus.manifests[result.organ]
                manifest.verified_reliability = min(1, manifest.verified_reliability + .01)
                if winner is not None:
                    self.development.record_resumed(winner, demand, result.action_id)
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
        if not evaluation.correct:
            self.action_loop.verify(observation, lambda _: False, VerificationLevel.OUTCOME_VERIFIED)
            goal_rows = self.store.rows("SELECT state FROM goals WHERE id=?", (observation.goal_id,))
            if goal_rows:
                goal = json.loads(goal_rows[0]["state"])
                goal.update(status="active", current_step="REPLAN", blocker="STRATEGY")
                self.store.put("goals", observation.goal_id, goal)
            self._event("NEGATIVE_OUTCOME", "Verified negative outcome requires replanning",
                        {"goal_id": observation.goal_id})
            return False
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
        # A syntactically valid model response is not verified learning.
        # Attribution and competence updates occur only in evaluate_outcome().
        return

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
        selected_key = f'{selected["provider"]}:{selected["model_id"]}' if selected else None
        selected_record = self.records.get(selected_key) if selected_key else None
        resource_class = (selected_record.cost_classification if selected_record else
                          "NO FREE SAFE INTELLIGENCE AVAILABLE")
        return {"current_goal": goal.get("description"), "work_class": goal.get("work_class"),
                "current_step": goal.get("current_step","idle"), "current_organ": goal.get("current_organ"),
                "selected_colony": goal.get("selected_colony") or (selected.get("colony") if selected else None),
                "selected_model": selected_key, "intelligence_resource": resource_class,
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
                for entry in state.get("action_ledger", {}).values():
                    if entry.get("approval_request_id") == request_id:
                        entry["status"] = "SUPERSEDED"
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
            for entry in state.get("action_ledger", {}).values():
                if entry.get("approval_request_id") == request_id:
                    entry.update(status="VERIFIED" if result.success else "FAILED",
                                 action_id=result.action_id)
            state.update(status="awaiting_outcome", current_step="AWAITING_OUTCOME", current_organ=request["organ"],
                         last_observation=result.action_id, pending_approval=None)
            self.store.put("goals", state["id"], state)
            self._event("OUTCOME_AWAITING", "Approved body result awaits outcome evidence",
                        {"goal_id": state["id"], "action_id": result.action_id})

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
                raise ProviderUnavailable("NO_FREE_SAFE_INTELLIGENCE_AVAILABLE")
            persisted = json.loads(active[0]["state"]) if active else None
            answer = self._conversation_call(message, persisted)
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
