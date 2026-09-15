"""Safe, declarative development of reusable BodyBus compositions."""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Mapping
from uuid import uuid4

from .buses import BodyBus, OrganManifest
from .embodiment import CapabilityDemand, EmbodimentStore, OrganRegistry


class CompositeRejected(ValueError):
    """A proposal cannot be represented safely by the trusted body."""


@dataclass(frozen=True, slots=True)
class CompositeStep:
    id: str
    organ: str
    operation: str
    arguments: dict[str, str]


@dataclass(frozen=True, slots=True)
class CompositeOrganSpec:
    id: str
    capability: str
    operation: str
    required_inputs: tuple[str, ...]
    steps: tuple[CompositeStep, ...]
    description: str = ""
    version: str = "1"


@dataclass(slots=True)
class DevelopmentCandidate:
    id: str
    need_id: str
    origin: str
    spec: CompositeOrganSpec
    tested: bool = False
    evidence: dict[str, Any] = field(default_factory=dict)
    audit_by: str | None = None


class DevelopmentEngine:
    """Validate, test, audit, and retain compositions; never execute generated code."""

    _SIDE_EFFECT_RANK = {"none": 0, "read": 1, "workspace": 2, "mutation": 3}

    def __init__(self, bus: BodyBus, store: EmbodimentStore, registry: OrganRegistry,
                 event: Callable[[str, dict[str, Any]], None] | None = None):
        self.bus, self.store, self.registry = bus, store, registry
        self.event = event or (lambda _kind, _state: None)

    def _record(self, kind: str, identity: str, state: dict[str, Any]) -> None:
        value = {"kind": kind, "created_at": time.time(), **state}
        self.store.put("development_event", identity, value)
        self.event(kind, state)

    @staticmethod
    def _spec(data: CompositeOrganSpec | Mapping[str, Any]) -> CompositeOrganSpec:
        if isinstance(data, CompositeOrganSpec):
            return data
        steps = tuple(CompositeStep(str(s["id"]), str(s["organ"]), str(s["operation"]),
                                    {str(k): str(v) for k, v in s.get("arguments", {}).items()})
                      for s in data.get("steps", ()))
        return CompositeOrganSpec(str(data["id"]), str(data["capability"]), str(data["operation"]),
                                  tuple(map(str, data.get("required_inputs", ()))), steps,
                                  str(data.get("description", "")), str(data.get("version", "1")))

    def _dependency_graph(self, proposed: CompositeOrganSpec) -> dict[str, set[str]]:
        specs = [self._spec(item) for item in self.store.all("composite_spec")]
        graph = {spec.id: {step.organ for step in spec.steps if step.organ.startswith("composite:")}
                 for spec in specs}
        graph[proposed.id] = {step.organ for step in proposed.steps if step.organ.startswith("composite:")}
        return graph

    def validate(self, spec: CompositeOrganSpec) -> OrganManifest:
        if not spec.id.startswith("composite:") or not spec.steps or len({s.id for s in spec.steps}) != len(spec.steps):
            raise CompositeRejected("composite id, non-empty steps, and unique step ids are required")
        if spec.id in {step.organ for step in spec.steps}:
            raise CompositeRejected("a composite may not invoke itself")
        available_steps: set[str] = set()
        parts: list[OrganManifest] = []
        for step in spec.steps:
            manifest = self.bus.manifests.get(step.organ)
            if manifest is None or not manifest.available or not manifest.trusted:
                raise CompositeRejected(f"unknown or untrusted organ: {step.organ}")
            boundary_name = f"{step.organ} {manifest.kind}".lower()
            unsafe_operation = step.operation.lower().replace("_", "-")
            if (any(token in boundary_name for token in ("root", "credential", "vault", "shell"))
                    or unsafe_operation in {"shell", "exec", "execute", "execute-code", "grant", "grant-privilege"}):
                raise CompositeRejected("authority, credentials, shell, and privilege grants are not composable")
            if step.operation not in manifest.operations or (step.organ, step.operation) not in self.bus.handlers:
                raise CompositeRejected(f"unknown operation: {step.organ}.{step.operation}")
            for reference in step.arguments.values():
                root, _, remainder = reference.partition(".")
                if root == "input":
                    if remainder not in spec.required_inputs: raise CompositeRejected(f"undeclared input: {reference}")
                elif root == "steps":
                    dependency = remainder.split(".", 1)[0]
                    if dependency not in available_steps: raise CompositeRejected(f"forward/unknown step reference: {reference}")
                else:
                    raise CompositeRejected(f"unsafe argument reference: {reference}")
            required = set(manifest.operations[step.operation].get("required", ()))
            if not required <= set(step.arguments): raise CompositeRejected(f"missing arguments for {step.id}")
            available_steps.add(step.id); parts.append(manifest)

        graph = self._dependency_graph(spec)
        def visit(node: str, path: set[str]) -> None:
            if node in path: raise CompositeRejected("composition cycle detected")
            for child in graph.get(node, ()): visit(child, path | {node})
        visit(spec.id, set())
        effects = [self._SIDE_EFFECT_RANK.get(part.side_effect_class) for part in parts]
        if any(rank is None for rank in effects): raise CompositeRejected("ambiguous side-effect classification")
        rank = max(int(value) for value in effects)
        return OrganManifest(spec.id, "composite", spec.version,
            {spec.operation: {"required": list(spec.required_inputs)}}, description=spec.description,
            permissions=set().union(*(part.permissions for part in parts)), risk=max(part.risk for part in parts),
            side_effect_class=next(name for name, value in self._SIDE_EFFECT_RANK.items() if value == rank),
            reversible=all(part.reversible for part in parts), cost=sum(part.cost for part in parts),
            latency_ms=sum(part.latency_ms for part in parts),
            verified_reliability=min(part.verified_reliability for part in parts), provenance="developed:declarative",
            capability_tags={spec.capability},
            network_scope=tuple(sorted({scope for part in parts for scope in part.network_scope})),
            filesystem_scope=tuple(sorted({scope for part in parts for scope in part.filesystem_scope})),
            credential_handles=tuple(sorted({handle for part in parts for handle in part.credential_handles})),
            trusted=True)

    def _execute(self, spec: CompositeOrganSpec, inputs: dict[str, Any]) -> dict[str, Any]:
        missing = set(spec.required_inputs) - set(inputs)
        if missing: raise CompositeRejected(f"missing composite inputs: {sorted(missing)}")
        results: dict[str, Any] = {}
        for step in spec.steps:
            arguments: dict[str, Any] = {}
            for name, reference in step.arguments.items():
                root, _, path = reference.partition(".")
                value: Any = inputs if root == "input" else results
                for component in path.split("."):
                    if not isinstance(value, dict) or component not in value:
                        raise CompositeRejected(f"unresolved argument reference: {reference}")
                    value = value[component]
                arguments[name] = value
            results[step.id] = self.bus.request(step.organ, step.operation, arguments)
        return {"steps": results, "final": results[spec.steps[-1].id]}

    def attach(self, spec: CompositeOrganSpec) -> OrganManifest:
        manifest = self.validate(spec)
        self.registry.register(manifest, {spec.operation: lambda inputs, s=spec: self._execute(s, inputs)})
        return manifest

    def restore(self) -> None:
        pending = [self._spec(data) for data in self.store.all("composite_spec")]
        while pending:
            progressed = False
            for spec in pending[:]:
                try: self.attach(spec)
                except CompositeRejected: continue
                pending.remove(spec); progressed = True
            if not progressed: break  # unavailable dependencies remain unavailable, never half-attached

    def develop(self, demand: CapabilityDemand,
                proposals: Mapping[str, Callable[[CapabilityDemand], CompositeOrganSpec | Mapping[str, Any]]],
                evaluator: Callable[[CompositeOrganSpec, dict[str, Any]], bool],
                auditor: Callable[[str, str, CompositeOrganSpec, dict[str, Any]], bool]) -> DevelopmentCandidate | None:
        need_id = uuid4().hex
        self._record("DEVELOPMENT_NEED", need_id, {"need_id": need_id, "goal_id": demand.goal_id,
                                                    "capability": demand.required_capability})
        # Materialize both private first-pass proposals before validating either.
        raw = [(lineage, proposer(demand)) for lineage, proposer in proposals.items()]
        candidates: list[DevelopmentCandidate] = []
        for lineage, proposal in raw:
            candidate: DevelopmentCandidate | None = None
            try:
                candidate = DevelopmentCandidate(uuid4().hex, need_id, lineage, self._spec(proposal))
                self.store.put("development_candidate", candidate.id, candidate)
                self._record("CANDIDATE_PROPOSED", candidate.id + ":proposed",
                             {"candidate_id": candidate.id, "origin": lineage, "spec_id": candidate.spec.id})
                self.validate(candidate.spec)
                evidence = self._execute(candidate.spec, demand.inputs)
                candidate.tested = bool(evaluator(candidate.spec, evidence)); candidate.evidence = evidence
                self.store.put("development_candidate", candidate.id, candidate)
                self._record("CANDIDATE_TESTED", candidate.id + ":tested",
                             {"candidate_id": candidate.id, "passed": candidate.tested})
                if not candidate.tested: raise CompositeRejected("objective test failed")
                candidates.append(candidate)
            except (CompositeRejected, KeyError, TypeError, ValueError) as exc:
                identity = candidate.id if candidate is not None else uuid4().hex
                self._record("CANDIDATE_REJECTED", identity + ":rejected",
                             {"candidate_id": identity, "origin": lineage, "reason": str(exc)})
        for candidate in candidates:
            sisters = [name for name in proposals if name != candidate.origin]
            if not sisters: continue
            sister = sisters[0]
            approved = bool(auditor(sister, candidate.origin, candidate.spec, candidate.evidence))
            self._record("SISTER_AUDITED", candidate.id + ":audit",
                         {"candidate_id": candidate.id, "auditor": sister, "approved": approved})
            if not approved:
                self._record("CANDIDATE_REJECTED", candidate.id + ":audit-rejected",
                             {"candidate_id": candidate.id, "origin": candidate.origin,
                              "reason": "sister audit rejected candidate"})
                continue
            candidate.audit_by = sister
            self.store.put("composite_spec", candidate.spec.id, candidate.spec)
            self.attach(candidate.spec)
            self.store.put("development_candidate", candidate.id, candidate)
            self._record("ORGAN_PROMOTED", candidate.id + ":promoted",
                         {"candidate_id": candidate.id, "organ": candidate.spec.id})
            self._record("GOAL_RESUMED", candidate.id + ":resumed", {"goal_id": demand.goal_id, "demand_id": demand.id})
            return candidate
        return None
