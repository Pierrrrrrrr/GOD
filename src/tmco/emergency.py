"""Root-governed emergency control, independent of cognition and model availability."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from dataclasses import asdict, dataclass
from enum import IntEnum, StrEnum
from pathlib import Path
from typing import Callable
from uuid import uuid4

from .root import AuthorizationError, RootKernel, WindowsRootSecretStore


class EmergencyState(IntEnum):
    RUNNING = 0
    PAUSED = 1
    LOCKDOWN = 2
    STOP_REQUESTED = 3


class EmergencyAction(StrEnum):
    PAUSE = "PAUSE"
    LOCKDOWN = "LOCKDOWN"
    STOP = "STOP"
    REVOKE_EXTERNAL_CAPABILITIES = "REVOKE_EXTERNAL_CAPABILITIES"


@dataclass(frozen=True, slots=True)
class OwnerAttestation:
    owner_id: str
    action: str
    scope: str
    resource: str
    nonce: str
    expires_at: float
    maximum_cost: float
    non_delegable: bool
    signature: str

    def fact(self) -> dict[str, object]:
        return {"status": "OWNER_AUTHORIZED", "scope_hash": hashlib.sha256(
            f"{self.scope}\0{self.resource}".encode()).hexdigest(), "expires_at": self.expires_at}


def _attestation_payload(data: dict[str, object]) -> bytes:
    bounded = {key: data[key] for key in ("owner_id", "action", "scope", "resource", "nonce",
                                          "expires_at", "maximum_cost", "non_delegable")}
    return json.dumps(bounded, sort_keys=True, separators=(",", ":")).encode()


class EmergencyPhraseStore:
    """Stores only a salted scrypt verifier, protected for the current local user."""
    def __init__(self, directory: Path):
        self.path = directory / "emergency.verifier"
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)

    def enroll(self, phrase: str) -> None:
        if self.path.exists():
            raise AuthorizationError("emergency phrase is already enrolled")
        if len(phrase) < 12:
            raise ValueError("emergency phrase must contain at least 12 characters")
        salt = os.urandom(16)
        verifier = hashlib.scrypt(phrase.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
        raw = json.dumps({"version": 1, "salt": salt.hex(), "verifier": verifier.hex()},
                         sort_keys=True).encode()
        protected = WindowsRootSecretStore._protect(raw) if os.name == "nt" else raw
        descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(descriptor, protected); os.fsync(descriptor)
        finally:
            os.close(descriptor)
        if os.name != "nt": os.chmod(self.path, 0o600)

    def verify(self, phrase: str) -> bool:
        if not self.path.exists(): return False
        raw = WindowsRootSecretStore._unprotect(self.path.read_bytes()) if os.name == "nt" else self.path.read_bytes()
        data = json.loads(raw)
        actual = hashlib.scrypt(phrase.encode(), salt=bytes.fromhex(data["salt"]),
                                n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(actual, bytes.fromhex(data["verifier"]))


class EmergencyAuthority:
    """Host-only root attestation issuer and monotonic emergency-state boundary."""
    def __init__(self, root: RootKernel, directory: Path, now: Callable[[], float] = time.time):
        self.__root, self.__now = root, now
        self.__path = directory / "emergency.state"
        self.__used: set[str] = set()
        self._state = EmergencyState.RUNNING
        if self.__path.exists(): self._restore()

    @property
    def state(self) -> EmergencyState: return self._state

    def attest(self, phrase_store: EmergencyPhraseStore, phrase: str, action: EmergencyAction,
               *, scope: str = "root-emergency", resource: str = "organism",
               ttl_seconds: int = 60) -> OwnerAttestation:
        if not phrase_store.verify(phrase):
            self.__root.record("owner_emergency_authentication_failed", {"action": action.value})
            raise AuthorizationError("owner emergency authentication failed")
        data = {"owner_id": self.__root.owner, "action": action.value, "scope": scope,
                "resource": resource, "nonce": uuid4().hex,
                "expires_at": self.__now() + min(max(ttl_seconds, 1), 300),
                "maximum_cost": 0.0, "non_delegable": True}
        signature = self.__root.sign_owner_attestation(_attestation_payload(data))
        self.__root.record("owner_emergency_attested", {"action": action.value,
                           "resource_hash": hashlib.sha256(resource.encode()).hexdigest()})
        return OwnerAttestation(**data, signature=signature)

    def apply(self, attestation: OwnerAttestation) -> EmergencyState:
        payload = asdict(attestation); signature = payload.pop("signature")
        if (attestation.owner_id != self.__root.owner or attestation.maximum_cost != 0
                or not attestation.non_delegable or self.__now() >= attestation.expires_at
                or attestation.nonce in self.__used
                or not self.__root.verify_owner_attestation(_attestation_payload(payload), signature)):
            raise AuthorizationError("owner emergency attestation is invalid")
        self.__used.add(attestation.nonce)
        target = {EmergencyAction.PAUSE.value: EmergencyState.PAUSED,
                  EmergencyAction.LOCKDOWN.value: EmergencyState.LOCKDOWN,
                  EmergencyAction.STOP.value: EmergencyState.STOP_REQUESTED,
                  EmergencyAction.REVOKE_EXTERNAL_CAPABILITIES.value: EmergencyState.LOCKDOWN}[attestation.action]
        self._state = max(self._state, target)
        self._persist()
        self.__root.record("emergency_state_changed", {"state": self._state.name})
        return self._state

    def require_external_effects_allowed(self) -> None:
        if self._state >= EmergencyState.PAUSED:
            raise AuthorizationError(f"external effects blocked by {self._state.name}")

    def require_remote_models_allowed(self) -> None:
        if self._state >= EmergencyState.LOCKDOWN:
            raise AuthorizationError(f"remote models blocked by {self._state.name}")

    def require_development_allowed(self) -> None: self.require_external_effects_allowed()

    def _persist(self) -> None:
        body = {"state": self._state.name, "used_nonces": sorted(self.__used)}
        signature = self.__root.sign_owner_attestation(
            b"GOD:EMERGENCY-STATE:v1\0" + json.dumps(body, sort_keys=True).encode())
        temporary = self.__path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"body": body, "signature": signature}, sort_keys=True), encoding="utf-8")
        if os.name != "nt": os.chmod(temporary, 0o600)
        os.replace(temporary, self.__path)

    def _restore(self) -> None:
        envelope = json.loads(self.__path.read_text(encoding="utf-8")); body = envelope["body"]
        payload = b"GOD:EMERGENCY-STATE:v1\0" + json.dumps(body, sort_keys=True).encode()
        if not self.__root.verify_owner_attestation(payload, envelope["signature"]):
            raise AuthorizationError("emergency state integrity check failed")
        self._state = EmergencyState[body["state"]]; self.__used = set(body["used_nonces"])
