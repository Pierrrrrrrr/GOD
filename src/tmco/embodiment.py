"""Phase 2B: capability resolution, permissioned organs, and durable observations."""
from __future__ import annotations

import hashlib, ipaddress, json, socket, sqlite3, time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from enum import StrEnum
from urllib.parse import urlparse
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4

from .buses import BodyBus, OrganManifest, ProviderUnavailable


class PermissionDenied(RuntimeError): pass
class MCPUnavailable(ProviderUnavailable): pass
class SandboxUnavailable(ProviderUnavailable): pass


class VerificationLevel(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    TRANSPORT_VERIFIED = "TRANSPORT_VERIFIED"
    ARTIFACT_VERIFIED = "ARTIFACT_VERIFIED"
    EVIDENCE_VERIFIED = "EVIDENCE_VERIFIED"
    OUTCOME_VERIFIED = "OUTCOME_VERIFIED"


class OutcomeEvaluator(StrEnum):
    OWNER = "OWNER"; REGISTERED_VERIFIER = "REGISTERED_VERIFIER"; OBJECTIVE_TEST = "OBJECTIVE_TEST"


@dataclass(frozen=True, slots=True)
class OutcomeEvaluation:
    observation_id: str; evaluator: str; evidence_refs: tuple[str, ...]; correct: bool
    outcome: str; timestamp: float; reason: str


@dataclass(frozen=True, slots=True)
class DecisionProvenance:
    id: str; goal_id: str; episode_id: str; source_colony: str | None
    source_model_key: str | None; source_assembly_ids: tuple[str, ...]; source_neuron_ids: tuple[str, ...]
    body_demand_id: str; created_at: float


class ExternalComponentTrust(StrEnum):
    DISCOVERED = "DISCOVERED"; INSPECTED = "INSPECTED"; QUARANTINED = "QUARANTINED"
    TESTED = "TESTED"; SISTER_AUDITED = "SISTER_AUDITED"; APPROVED = "APPROVED"; REJECTED = "REJECTED"


@dataclass(slots=True)
class ExternalComponentCandidate:
    id: str; source_url: str; publisher: str; version_or_commit: str; license: str
    provenance: str; maintenance_evidence: tuple[str, ...]; security_advisories: tuple[str, ...]
    security_policy: str | None; dependencies: tuple[str, ...]; requested_permissions: tuple[str, ...]
    filesystem_access: tuple[str, ...]; network_access: tuple[str, ...]; credential_requirements: tuple[str, ...]
    sandbox_required: bool; test_results: tuple[str, ...]; risk_score: float
    trust_state: ExternalComponentTrust = ExternalComponentTrust.DISCOVERED


@dataclass(slots=True)
class CapabilityDemand:
    goal_id: str; task: str; required_capability: str; intent: str
    inputs: dict[str, Any]; expected_output: str
    risk: float = 0; side_effects: str = "none"; network_need: str = "none"
    filesystem_need: str = "none"; privacy: float = 1; budget: float = 0
    reversible: bool = True
    expected_evidence: str = ""; confidence: float = 0; goal_value: float = 0
    information_gain: float = 0; capability_gain: float = 0; uncertainty: float = 1
    id: str = field(default_factory=lambda: uuid4().hex); decision_provenance_id: str | None = None

@dataclass(slots=True)
class CapabilityGap:
    id: str; demand: dict[str, Any]; reason: str; created_at: float

@dataclass(slots=True)
class PermissionLease:
    id: str; principal: str; permissions: tuple[str, ...]; issued_by: str
    scope: str; organ: str; operation: str; maximum_cost: float
    allowed_side_effect_class: str; reversible_only: bool; created_at: float; expires_at: float
    status: str = "active"
    def permits(self, permission: str, *, organ: str, operation: str, scope: str,
                cost: float, side_effect_class: str, reversible: bool, now: float | None = None) -> bool:
        return (self.status == "active" and self.issued_by == "Pier" and (now or time.time()) < self.expires_at
                and permission in self.permissions and self.organ == organ and self.operation == operation
                and self.scope == scope and cost <= self.maximum_cost
                and self.allowed_side_effect_class == side_effect_class
                and (not self.reversible_only or reversible))

@dataclass(slots=True)
class HumanApprovalRequest:
    id: str; goal_id: str; organ: str; operation: str; permission: str
    reason: str; scope: str; risk: float; cost: float; side_effect_class: str; reversible: bool
    inputs: dict[str, Any]; status: str = "pending"; requested_at: float = field(default_factory=time.time)

@dataclass(slots=True)
class ObservationEnvelope:
    action_id: str; goal_id: str; task: str; organ: str; operation: str
    started_at: float; finished_at: float; success: bool; result: Any
    evidence_refs: tuple[str, ...]; provenance: str; content_hash: str
    cost: float; latency_ms: float; side_effects: str
    verification_state: str = VerificationLevel.UNVERIFIED.value; error_class: str | None = None
    actual_outcome: str | None = None; prediction_error: str | None = None
    decision_provenance_id: str | None = None; prediction_id: str | None = None

@dataclass(slots=True)
class Prediction:
    action_id: str; goal_id: str; expected: str; expected_evidence: str; confidence: float
    expected_value: float; information_gain: float; risk: float; cost: float; created_at: float
    capability_gain: float = 0; uncertainty: float = 1; decision_provenance_id: str | None = None


class EmbodimentStore:
    def __init__(self, path: Path):
        self.connection = sqlite3.connect(path)
        self.connection.execute("CREATE TABLE IF NOT EXISTS body(kind TEXT,id TEXT,state TEXT NOT NULL,PRIMARY KEY(kind,id))")
        self.connection.commit()
    def put(self, kind: str, identity: str, value: Any) -> None:
        data = asdict(value) if hasattr(value, "__dataclass_fields__") else value
        self.connection.execute("INSERT OR REPLACE INTO body VALUES(?,?,?)", (kind, identity, json.dumps(data, sort_keys=True, default=lambda v: sorted(v) if isinstance(v, set) else str(v))))
        self.connection.commit()
    def all(self, kind: str) -> list[dict[str, Any]]:
        return [json.loads(r[0]) for r in self.connection.execute("SELECT state FROM body WHERE kind=? ORDER BY rowid", (kind,))]
    def close(self) -> None:
        self.connection.commit(); self.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)"); self.connection.close()


class CapabilityResolver:
    def __init__(self, bus: BodyBus, store: EmbodimentStore): self.bus, self.store = bus, store
    def resolve(self, demand: CapabilityDemand) -> tuple[OrganManifest, str] | None:
        choices: list[tuple[float, OrganManifest, str]] = []
        for manifest in self.bus.manifests.values():
            if not manifest.available or not manifest.trusted or demand.required_capability not in manifest.capability_tags: continue
            for operation, schema in manifest.operations.items():
                if operation != demand.intent and demand.intent not in schema.get("intents", []): continue
                required = set(schema.get("required", []))
                if not required <= set(demand.inputs) or manifest.cost > demand.budget or manifest.risk > demand.risk: continue
                score = 4*manifest.verified_reliability - manifest.latency_ms/1000 - manifest.cost - manifest.risk + (1 if manifest.reversible else -1) + demand.privacy
                choices.append((score, manifest, operation))
        if choices: return max(choices, key=lambda item: item[0])[1:]
        gap = CapabilityGap(uuid4().hex, asdict(demand), "no safe compatible registered organ", time.time())
        self.store.put("gap", gap.id, gap); return None


class OrganRegistry:
    """Durable manifest catalog. Runtime handlers must be explicitly reattached after restart."""
    def __init__(self, bus: BodyBus, store: EmbodimentStore): self.bus, self.store = bus, store
    def register(self, manifest: OrganManifest, handlers: dict[str, Any]) -> None:
        self.bus.register(manifest, handlers); self.store.put("organ", manifest.id, manifest)
    def persisted(self) -> list[OrganManifest]:
        manifests = []
        for data in self.store.all("organ"):
            for key in ("permissions", "capability_tags"): data[key] = set(data.get(key, []))
            for key in ("network_scope", "filesystem_scope", "credential_handles"): data[key] = tuple(data.get(key, []))
            manifests.append(OrganManifest(**data))
        return manifests


class PermissionAuthority:
    """Pier is the sole lease issuer; cognitive principals can only request."""
    def __init__(self, store: EmbodimentStore): self.store = store
    def issue(self, approver: str, principal: str, permissions: tuple[str, ...], duration_seconds: float,
              *, scope: str, organ: str, operation: str, maximum_cost: float,
              side_effect_class: str, reversible_only: bool) -> PermissionLease:
        if approver != "Pier": raise PermissionDenied("models and colonies cannot approve permission requests")
        now = time.time()
        lease = PermissionLease(uuid4().hex, principal, permissions, approver, scope, organ, operation,
                                maximum_cost, side_effect_class, reversible_only, now, now+duration_seconds)
        self.store.put("lease", lease.id, lease); return lease
    def approve(self, request_id: str, *, approver: str, principal: str = "body", duration_seconds: float = 300) -> PermissionLease:
        matches = [x for x in self.store.all("approval") if x["id"] == request_id]
        if not matches: raise KeyError(request_id)
        request = matches[-1]
        if request["status"] != "pending": raise PermissionDenied("approval request is not pending")
        lease = self.issue(approver, principal, (request["permission"],), duration_seconds,
                           scope=request["scope"], organ=request["organ"], operation=request["operation"],
                           maximum_cost=request["cost"], side_effect_class=request["side_effect_class"],
                           reversible_only=request["reversible"])
        request["status"] = "approved"; self.store.put("approval", request_id, request); return lease
    def deny(self, request_id: str, *, approver: str) -> None:
        if approver != "Pier": raise PermissionDenied("only Pier may deny requests")
        matches = [x for x in self.store.all("approval") if x["id"] == request_id]
        if not matches: raise KeyError(request_id)
        request = matches[-1]; request["status"] = "denied"; self.store.put("approval", request_id, request)


class WorkspaceFilesystemOrgan:
    OPERATIONS = {name: {"required": ["path"]} for name in ("read","write","append","list","metadata","exists","hash")}
    def __init__(self, workspace: Path, protected: tuple[Path, ...] = ()):
        self.workspace = workspace.resolve(); self.workspace.mkdir(parents=True, exist_ok=True)
        self.protected = tuple(p.resolve() for p in protected)
    def _path(self, raw: str) -> Path:
        candidate = (self.workspace / raw).resolve()
        if candidate != self.workspace and self.workspace not in candidate.parents: raise PermissionDenied("workspace traversal blocked")
        if any(candidate == p or p in candidate.parents for p in self.protected): raise PermissionDenied("protected RootGuard/CredentialVault path")
        return candidate
    def handle(self, operation: str, args: dict[str, Any]) -> Any:
        path = self._path(str(args["path"]))
        if operation == "read": return {"text": path.read_text(encoding="utf-8")}
        if operation in {"write", "append"}:
            path.parent.mkdir(parents=True, exist_ok=True); mode = "a" if operation == "append" else "w"
            with path.open(mode, encoding="utf-8") as stream: stream.write(str(args.get("content", "")))
            return {"path": str(path.relative_to(self.workspace)), "bytes": path.stat().st_size}
        if operation == "list": return {"entries": sorted(p.name for p in path.iterdir())}
        if operation == "metadata":
            stat = path.stat(); return {"size": stat.st_size, "modified": stat.st_mtime, "is_file": path.is_file()}
        if operation == "exists": return {"exists": path.exists()}
        if operation == "hash": return {"sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        raise ProviderUnavailable(operation)


class WebResearchOrgan:
    def __init__(self, *, test_allow_hosts: set[str] | None = None): self.test_allow_hosts = test_allow_hosts or set()
    def _validate(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}: raise PermissionDenied("only HTTP(S) is permitted")
        if parsed.scheme == "http" and parsed.hostname not in self.test_allow_hosts: raise PermissionDenied("production research requires HTTPS")
        if not parsed.hostname: raise PermissionDenied("URL host required")
        for item in socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM):
            address = ipaddress.ip_address(item[4][0])
            if parsed.hostname not in self.test_allow_hosts and (not address.is_global): raise PermissionDenied("SSRF target blocked")
    def request(self, args: dict[str, Any]) -> dict[str, Any]:
        url, method = str(args["url"]), str(args.get("method", "GET")).upper()
        if method not in {"GET", "HEAD"}: raise PermissionDenied("web research is read-only")
        self._validate(url); started = time.monotonic(); owner = self
        class SafeRedirect(HTTPRedirectHandler):
            def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
                owner._validate(newurl)
                return super().redirect_request(req, fp, code, msg, headers, newurl)
        with build_opener(SafeRedirect()).open(Request(url, method=method), timeout=float(args.get("timeout", 15))) as response:
            body = response.read(2_000_000); mime = response.headers.get_content_type()
            text = body.decode(response.headers.get_content_charset() or "utf-8", errors="replace") if mime.startswith("text/") or mime in {"application/json", "application/xml"} else ""
            title = ""
            if "<title" in text.lower():
                import re
                found = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S); title = found.group(1).strip() if found else ""
            return {"requested_url": url, "final_url": response.url, "timestamp": time.time(), "status": response.status,
                    "mime_type": mime, "content_hash": hashlib.sha256(body).hexdigest(), "text": text, "title": title,
                    "latency_ms": (time.monotonic()-started)*1000}


class OpenAPIOrgan:
    def __init__(self, document: dict[str, Any], web: WebResearchOrgan): self.document, self.web = document, web
    def operations(self) -> dict[str, tuple[str, str, dict[str, Any]]]:
        return {spec.get("operationId", f"{method}:{path}"): (method.upper(), path, spec)
                for path, methods in self.document.get("paths", {}).items() for method, spec in methods.items()
                if method.lower() in {"get","head","post","put","patch","delete"}}
    def validate(self, operation: str, inputs: dict[str, Any]) -> tuple[str, str]:
        if operation not in self.operations(): raise ValueError("unknown OpenAPI operation")
        method, path, spec = self.operations()[operation]
        required = {p["name"] for p in spec.get("parameters", []) if p.get("required")}
        missing = required-set(inputs)
        if missing: raise ValueError(f"missing required OpenAPI inputs: {sorted(missing)}")
        for parameter in spec.get("parameters", []):
            name = parameter["name"]
            if parameter.get("in", "path") == "path" and name in inputs: path = path.replace("{"+name+"}", str(inputs[name]))
        body_schema = spec.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {})
        if spec.get("requestBody", {}).get("required") and "body" not in inputs: raise ValueError("request body is required")
        missing_body = set(body_schema.get("required", []))-set(inputs.get("body", {}))
        if missing_body: raise ValueError(f"missing required request body fields: {sorted(missing_body)}")
        return method, path
    def execute(self, operation: str, inputs: dict[str, Any]) -> dict[str, Any]:
        method, path = self.validate(operation, inputs)
        base = self.document.get("servers", [{}])[0].get("url", ""); spec = self.operations()[operation][2]
        from urllib.parse import urlencode
        query = {p["name"]: inputs[p["name"]] for p in spec.get("parameters", []) if p.get("in") == "query" and p["name"] in inputs}
        url = base.rstrip("/")+"/"+path.lstrip("/") + (("?"+urlencode(query)) if query else "")
        if method in {"GET", "HEAD"}: return self.web.request({"url": url, "method": method})
        self.web._validate(url)
        payload = json.dumps(inputs.get("body", {})).encode(); started = time.monotonic()
        request = Request(url, data=payload, method=method, headers={"Content-Type": "application/json"})
        class NoMutationRedirect(HTTPRedirectHandler):
            def redirect_request(self, *args: Any, **kwargs: Any) -> Any: return None
        with build_opener(NoMutationRedirect()).open(request, timeout=15) as response:
            body = response.read(2_000_000)
            return {"requested_url": url, "final_url": response.url, "timestamp": time.time(), "status": response.status,
                    "mime_type": response.headers.get_content_type(), "content_hash": hashlib.sha256(body).hexdigest(),
                    "text": body.decode("utf-8", errors="replace"), "latency_ms": (time.monotonic()-started)*1000}


class MCPAdapter:
    def available(self) -> bool:
        try: import mcp  # type: ignore[import-not-found] # optional official SDK
        except ImportError: return False
        return True
    def invoke(self, *_: Any) -> Any:
        if not self.available(): raise MCPUnavailable("official MCP SDK is not installed")
        raise MCPUnavailable("an explicitly configured MCP transport is required")

class MCPRegistry:
    def __init__(self): self.entries: list[dict[str, Any]] = []
    def discover(self, entry: dict[str, Any]) -> None: self.entries.append({**entry, "trusted": False, "executable": False})

class SandboxBus:
    def __init__(self, test_handler: Any = None): self.test_handler = test_handler
    def execute(self, request: dict[str, Any], *, testing: bool = False) -> Any:
        if not testing or self.test_handler is None: raise SandboxUnavailable("no secure sandbox is configured")
        return self.test_handler(request)


def normalize_a2a_card(card: dict[str, Any]) -> OrganManifest:
    safe = {"name": str(card.get("name", "external-agent")), "url": str(card.get("url", ""))}
    operations = {str(s.get("id")): {"description": str(s.get("description", ""))} for s in card.get("skills", []) if s.get("id")}
    return OrganManifest("a2a:"+safe["name"], "a2a", str(card.get("version", "unknown")), operations,
                         description="External A2A card", endpoint=safe["url"], capability_tags=set(operations), trusted=False)


class ActionLoop:
    def __init__(self, bus: BodyBus, store: EmbodimentStore): self.bus, self.store, self.resolver = bus, store, CapabilityResolver(bus, store)
    def execute(self, demand: CapabilityDemand, *, lease: PermissionLease | None = None) -> ObservationEnvelope | HumanApprovalRequest | CapabilityGap:
        resolved = self.resolver.resolve(demand)
        if not resolved: return CapabilityGap(**self.store.all("gap")[-1])
        organ, operation = resolved; permission = next(iter(organ.permissions), ""); scope = demand.network_need if demand.network_need != "none" else demand.filesystem_need
        dangerous = operation.upper() in {"POST","PUT","PATCH","DELETE"} or organ.side_effect_class not in {"read","workspace"} or not organ.reversible
        if dangerous and (lease is None or not lease.permits(permission, organ=organ.id, operation=operation,
                scope=scope, cost=organ.cost, side_effect_class=organ.side_effect_class, reversible=organ.reversible)):
            request = HumanApprovalRequest(uuid4().hex, demand.goal_id, organ.id, operation, permission,
                "side effect requires Pier approval", scope, demand.risk, organ.cost, organ.side_effect_class,
                organ.reversible, demand.inputs)
            self.store.put("pending_demand", request.id, {**asdict(demand), "approval_request_id": request.id})
            self.store.put("approval", request.id, request); return request
        action_id = uuid4().hex
        prediction = Prediction(action_id, demand.goal_id, demand.expected_output, demand.expected_evidence,
                                demand.confidence, demand.goal_value, demand.information_gain, demand.risk,
                                organ.cost, time.time(), demand.capability_gain, demand.uncertainty,
                                demand.decision_provenance_id)
        self.store.put("prediction", action_id, prediction)
        started = time.time()
        try:
            result = self.bus.request(organ.id, operation, demand.inputs); success, error = True, None
        except Exception as exc:
            result, success, error = {"error": str(exc)}, False, type(exc).__name__
        finished = time.time(); digest = hashlib.sha256(json.dumps(result, sort_keys=True, default=str).encode()).hexdigest()
        observation = ObservationEnvelope(action_id, demand.goal_id, demand.task, organ.id, operation, started, finished,
                                          success, result, (f"sha256:{digest}",), organ.provenance, digest, organ.cost,
                                          (finished-started)*1000, organ.side_effect_class, error_class=error,
                                          decision_provenance_id=demand.decision_provenance_id, prediction_id=action_id)
        self.store.put("observation", action_id, observation); return observation
    def verify(self, observation: ObservationEnvelope, verifier: Any,
               level: VerificationLevel = VerificationLevel.ARTIFACT_VERIFIED) -> bool:
        verified = bool(observation.success and verifier(observation))
        observation.verification_state = level.value if verified else VerificationLevel.UNVERIFIED.value
        observation.actual_outcome = "success" if observation.success else "failure"
        prediction = next((p for p in self.store.all("prediction") if p["action_id"] == observation.action_id), None)
        observation.prediction_error = None if verified else f"expected {prediction['expected'] if prediction else 'success'}; observed {observation.actual_outcome}"
        self.store.put("observation", observation.action_id, observation); return verified
    @staticmethod
    def completion(observation: ObservationEnvelope | None) -> str:
        if observation is None: raise ValueError("completion claim requires an ObservationEnvelope")
        return ("Action completed and observed." if observation.verification_state != VerificationLevel.UNVERIFIED.value
                else "An action was observed but is not verified.")
