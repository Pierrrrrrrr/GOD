"""Root-owned, exact and single-use leases for future external setup.

This module deliberately does not perform browser automation or create accounts.  It
is the authority boundary that a future Capability Forge executor must cross.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Callable
from uuid import uuid4

from .root import AuthorizationError, RootKernel


class SetupState(str, Enum):
    AWAITING_PIER = "AWAITING_PIER"
    AUTHORIZED = "AUTHORIZED"
    RUNNING = "RUNNING"
    PAUSED_FOR_PIER = "PAUSED_FOR_PIER"
    COMPLETE = "COMPLETE"
    DENIED = "DENIED"


class HumanCheckpoint(str, Enum):
    CAPTCHA = "CAPTCHA"
    MFA = "MFA"
    IDENTITY_VERIFICATION = "IDENTITY_VERIFICATION"
    UNEXPECTED_PAYMENT = "UNEXPECTED_PAYMENT"
    UNEXPECTED_PERMISSION = "UNEXPECTED_PERMISSION"
    LEGAL_CONFIRMATION = "LEGAL_CONFIRMATION"


@dataclass(frozen=True, slots=True)
class CapabilityRequest:
    owner: str
    service: str
    operation: str
    purpose: str
    workflow_id: str
    credential_type: str
    scopes: tuple[str, ...] = ()
    allowed_submitted_data: tuple[str, ...] = ()
    maximum_cost: float = 0.0
    allowed_side_effects: tuple[str, ...] = ()
    ttl_seconds: int = 900
    non_delegable: bool = True


@dataclass(frozen=True, slots=True)
class OwnerCapability:
    request: CapabilityRequest
    expires_at: float
    nonce: str
    signature: str


class OwnerCapabilityAuthority:
    """Issues and consumes leases; callers receive no signing primitive."""

    def __init__(self, root: RootKernel, now: Callable[[], float] = time.time):
        self.__root = root
        self.__now = now
        self.__used: set[str] = set()
        self.states: dict[str, SetupState] = {}
        self.__requests: dict[str, CapabilityRequest] = {}

    @staticmethod
    def _payload(request: CapabilityRequest, expires_at: float, nonce: str) -> bytes:
        return json.dumps({"request": asdict(request), "expires_at": expires_at, "nonce": nonce},
                          sort_keys=True, separators=(",", ":")).encode()

    def request(self, request: CapabilityRequest) -> str:
        if not request.non_delegable or request.owner != self.__root.owner:
            raise AuthorizationError("owner capability must be owner-bound and non-delegable")
        request_id = hashlib.sha256(json.dumps(asdict(request), sort_keys=True).encode()
                                    + uuid4().bytes).hexdigest()
        self.states[request_id] = SetupState.AWAITING_PIER
        self.__requests[request_id] = request
        self.__root.record("owner_capability_requested", {"request_id": request_id,
                           "service": request.service, "operation": request.operation})
        return request_id

    def grant(self, request_id: str, request: CapabilityRequest, *, actor: str) -> OwnerCapability:
        if (actor != self.__root.owner or self.states.get(request_id) != SetupState.AWAITING_PIER
                or self.__requests.get(request_id) != request):
            raise AuthorizationError("a fresh Pier approval is required")
        expiry, nonce = self.__now() + request.ttl_seconds, uuid4().hex
        signature = self.__root._guard.sign(self._payload(request, expiry, nonce))
        capability = OwnerCapability(request, expiry, nonce, signature)
        self.states[request_id] = SetupState.AUTHORIZED
        self.__root.record("owner_capability_granted", {"request_id": request_id,
                           "service": request.service, "nonce_hash": hashlib.sha256(nonce.encode()).hexdigest()})
        return capability

    def consume(self, capability: OwnerCapability, actual: CapabilityRequest, *, actor: str) -> None:
        if actor != capability.request.owner or actor != self.__root.owner:
            raise AuthorizationError("owner capability is non-delegable")
        if capability.nonce in self.__used:
            raise AuthorizationError("owner capability has already been used")
        if self.__now() >= capability.expires_at:
            raise AuthorizationError("owner capability has expired")
        if actual != capability.request:
            raise AuthorizationError("workflow differs from the approved capability")
        if not self.__root._guard.verify(self._payload(capability.request, capability.expires_at,
                                                       capability.nonce), capability.signature):
            raise AuthorizationError("owner capability signature is invalid")
        # Burn before handing control to an executor: even a failed attempt needs new approval.
        self.__used.add(capability.nonce)
        self.__root.record("owner_capability_consumed", {
            "service": actual.service, "operation": actual.operation,
            "nonce_hash": hashlib.sha256(capability.nonce.encode()).hexdigest()})

    def pause(self, request_id: str, checkpoint: HumanCheckpoint) -> None:
        if request_id not in self.states:
            raise KeyError(request_id)
        self.states[request_id] = SetupState.PAUSED_FOR_PIER
        self.__root.record("external_setup_paused", {"request_id": request_id,
                                                     "checkpoint": checkpoint.value})
