"""Persistent root-authorized leases for resumable external setup workflows."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from .root import AuthorizationError, RootKernel


class SetupState(StrEnum):
    AWAITING_PIER = "AWAITING_PIER"; AUTHORIZED = "AUTHORIZED"; RUNNING = "RUNNING"
    PAUSED_FOR_PIER = "PAUSED_FOR_PIER"; COMPLETE = "COMPLETE"; DENIED = "DENIED"


class HumanCheckpoint(StrEnum):
    CAPTCHA = "CAPTCHA"; MFA = "MFA"; IDENTITY_VERIFICATION = "IDENTITY_VERIFICATION"
    UNEXPECTED_PAYMENT = "UNEXPECTED_PAYMENT"; UNEXPECTED_PERMISSION = "UNEXPECTED_PERMISSION"
    LEGAL_CONFIRMATION = "LEGAL_CONFIRMATION"


@dataclass(frozen=True, slots=True)
class CapabilityRequest:
    owner: str; service: str; operation: str; purpose: str; workflow_id: str
    executor_principal: str; credential_type: str; account_id: str
    scopes: tuple[str, ...] = (); allowed_submitted_data: tuple[str, ...] = ()
    maximum_cost: float = 0; allowed_side_effects: tuple[str, ...] = ()
    ttl_seconds: int = 900; non_delegable: bool = True


@dataclass(frozen=True, slots=True)
class OwnerCapability:
    request_id: str; request: CapabilityRequest; expires_at: float; nonce: str; signature: str


class OwnerApproval:
    """Opaque proof minted by the authority-bound host control surface."""
    __slots__ = ("request_id", "approved", "__token")
    def __init__(self, request_id: str, approved: bool, token: object, expected: object):
        if token is not expected: raise AuthorizationError("approval requires host owner control")
        self.request_id, self.approved, self.__token = request_id, approved, token


class OwnerControlSurface:
    """Host UI adapter; never passed to cognition or workflow executors."""
    __slots__ = ("__token",)
    def __init__(self, token: object): self.__token = token
    def decide(self, request_id: str, approved: bool) -> OwnerApproval:
        return OwnerApproval(request_id, approved, self.__token, self.__token)


class CapabilityRequester:
    """Narrow interface safe to provide to cognition/body components."""
    __slots__ = ("__request",)
    def __init__(self, request: Callable[[CapabilityRequest], str]): self.__request = request
    def request(self, request: CapabilityRequest) -> str: return self.__request(request)


class OwnerCapabilityAuthority:
    def __init__(self, root: RootKernel, path: Path, now: Callable[[], float] = time.time,
                 emergency: Any | None = None):
        self.__root, self.__now = root, now
        self.__emergency = emergency
        self.__host_token = object()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.__db = sqlite3.connect(path)
        self.__db.execute("CREATE TABLE IF NOT EXISTS owner_capabilities(request_id TEXT PRIMARY KEY,state TEXT NOT NULL)")
        self.__db.commit()

    def requester(self) -> CapabilityRequester: return CapabilityRequester(self.request)
    def owner_control(self) -> OwnerControlSurface: return OwnerControlSurface(self.__host_token)

    @staticmethod
    def _request(data: dict) -> CapabilityRequest:
        for key in ("scopes", "allowed_submitted_data", "allowed_side_effects"):
            data[key] = tuple(data.get(key, ()))
        return CapabilityRequest(**data)

    @staticmethod
    def _payload(request_id: str, request: CapabilityRequest, expiry: float, nonce: str) -> bytes:
        return json.dumps({"request_id": request_id, "request": asdict(request), "expires_at": expiry,
                           "nonce": nonce}, sort_keys=True, separators=(",", ":")).encode()

    def _get(self, request_id: str) -> dict:
        row = self.__db.execute("SELECT state FROM owner_capabilities WHERE request_id=?", (request_id,)).fetchone()
        if not row: raise KeyError(request_id)
        return json.loads(row[0])

    def _put(self, request_id: str, state: dict) -> None:
        self.__db.execute("INSERT OR REPLACE INTO owner_capabilities VALUES(?,?)",
                          (request_id, json.dumps(state, sort_keys=True))); self.__db.commit()

    def request(self, request: CapabilityRequest) -> str:
        if self.__emergency is not None: self.__emergency.require_new_work_allowed()
        if request.owner != self.__root.owner or not request.non_delegable or not request.executor_principal:
            raise AuthorizationError("request must be owner-bound, executor-bound, and non-delegable")
        request_id = uuid4().hex
        self._put(request_id, {"request": asdict(request), "status": SetupState.AWAITING_PIER,
                               "checkpoint": None, "capability": None, "nonce_hash": None,
                               "consumed": False, "revoked": False})
        self.__root.record("owner_capability_requested", {"request_id": request_id,
                           "service": request.service, "operation": request.operation})
        return request_id

    def decide(self, approval: OwnerApproval) -> OwnerCapability | None:
        self._verify_owner_approval(approval)
        state = self._get(approval.request_id)
        if state["status"] != SetupState.AWAITING_PIER: raise AuthorizationError("fresh approval required")
        if not approval.approved:
            state["status"], state["revoked"] = SetupState.DENIED, True; self._put(approval.request_id, state); return None
        request = self._request(state["request"]); expiry, nonce = self.__now()+request.ttl_seconds, uuid4().hex
        signature = self.__root.sign_owner_capability(self._payload(approval.request_id, request, expiry, nonce))
        capability = OwnerCapability(approval.request_id, request, expiry, nonce, signature)
        state.update(status=SetupState.AUTHORIZED, capability={**asdict(capability), "request": asdict(request)},
                     nonce_hash=hashlib.sha256(nonce.encode()).hexdigest())
        self._put(approval.request_id, state); return capability

    def capability(self, request_id: str) -> OwnerCapability:
        state = self._get(request_id); data = state.get("capability")
        if not data: raise AuthorizationError("workflow is not authorized")
        data["request"] = self._request(data["request"]); return OwnerCapability(**data)

    def _verify_owner_approval(self, approval: OwnerApproval) -> None:
        if not isinstance(approval, OwnerApproval) or getattr(approval, "_OwnerApproval__token", None) is not self.__host_token:
            raise AuthorizationError("approval is not bound to this host authority")

    def start(self, capability: OwnerCapability, actual: CapabilityRequest, *, executor_principal: str) -> None:
        if self.__emergency is not None:
            self.__emergency.require_new_work_allowed()
            self.__emergency.require_external_effects_allowed()
        state = self._get(capability.request_id)
        if state["consumed"]: raise AuthorizationError("owner capability has already been used")
        if state["revoked"] or state["status"] != SetupState.AUTHORIZED: raise AuthorizationError("workflow is not authorized")
        if executor_principal != capability.request.executor_principal: raise AuthorizationError("wrong workflow executor")
        if actual != capability.request: raise AuthorizationError("workflow differs from approved capability")
        if self.__now() >= capability.expires_at: raise AuthorizationError("owner capability has expired")
        if hashlib.sha256(capability.nonce.encode()).hexdigest() != state["nonce_hash"] or not \
                self.__root.verify_owner_capability(self._payload(capability.request_id, capability.request,
                    capability.expires_at, capability.nonce), capability.signature):
            raise AuthorizationError("owner capability signature is invalid")
        state.update(consumed=True, status=SetupState.RUNNING); self._put(capability.request_id, state)

    # Compatibility name: consumption means consuming the right to START, not completion.
    def consume(self, capability: OwnerCapability, actual: CapabilityRequest, *, executor_principal: str) -> None:
        self.start(capability, actual, executor_principal=executor_principal)

    def pause(self, request_id: str, checkpoint: HumanCheckpoint) -> None:
        state = self._get(request_id)
        if state["status"] != SetupState.RUNNING: raise AuthorizationError("workflow cannot pause")
        state.update(status=SetupState.PAUSED_FOR_PIER, checkpoint=checkpoint); self._put(request_id, state)

    def resume(self, approval: OwnerApproval, actual: CapabilityRequest) -> None:
        self._verify_owner_approval(approval)
        state = self._get(approval.request_id)
        if not approval.approved or state["status"] != SetupState.PAUSED_FOR_PIER or self._request(state["request"]) != actual:
            raise AuthorizationError("checkpoint resume must match the exact approved workflow")
        state.update(status=SetupState.RUNNING, checkpoint=None); self._put(approval.request_id, state)

    def complete(self, request_id: str, *, executor_principal: str) -> None:
        state = self._get(request_id); request = self._request(state["request"])
        if state["status"] != SetupState.RUNNING or executor_principal != request.executor_principal:
            raise AuthorizationError("only the exact running workflow executor may complete")
        state["status"] = SetupState.COMPLETE; self._put(request_id, state)

    def status(self, request_id: str) -> SetupState: return SetupState(self._get(request_id)["status"])
    def close(self) -> None: self.__db.commit(); self.__db.close()
