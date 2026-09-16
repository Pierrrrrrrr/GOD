from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Any

from .paths import ProductPaths
from .root import AuthorizationError, RootKernel


class EmergencyState(IntEnum):
    RUNNING = 0
    PAUSED = 1
    LOCKDOWN = 2
    STOP_REQUESTED = 3


@dataclass(frozen=True, slots=True)
class EmergencySnapshot:
    state: EmergencyState
    sequence: int


class EmergencyAuthority:
    """Root-signed, monotonic, cross-process emergency authority.

    The cached state can only become more restrictive. Every permission method
    refreshes the signed file, so a second process can stop an existing runtime.
    """

    DOMAIN = b"GOD:EMERGENCY:v1\0"

    def __init__(self, root: RootKernel, paths: ProductPaths):
        self.__root, self.paths = root, paths
        self._state, self._sequence = EmergencyState.RUNNING, 0
        if paths.emergency_state.exists(): self.refresh()

    @property
    def state(self) -> EmergencyState:
        return self.refresh().state

    def _body(self, state: EmergencyState, sequence: int) -> bytes:
        return json.dumps({"sequence": sequence, "state": state.name},
                          sort_keys=True, separators=(",", ":")).encode()

    def refresh(self) -> EmergencySnapshot:
        path = self.paths.emergency_state
        if not path.exists(): return EmergencySnapshot(self._state, self._sequence)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            state, sequence = EmergencyState[value["state"]], int(value["sequence"])
            if sequence < 0 or not self.__root.verify_emergency(
                    self._body(state, sequence), str(value["signature"])):
                raise ValueError("invalid signature")
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            # Corruption is itself a restriction signal. It never lowers a state.
            self._state = max(self._state, EmergencyState.LOCKDOWN)
            raise AuthorizationError("emergency state is malformed or unauthenticated") from None
        self._state = max(self._state, state)
        self._sequence = max(self._sequence, sequence)
        return EmergencySnapshot(self._state, self._sequence)

    def restrict(self, state: EmergencyState) -> EmergencySnapshot:
        current = self.refresh()
        if state < current.state:
            raise AuthorizationError("emergency restrictions are monotonic")
        sequence = current.sequence + 1
        body = self._body(state, sequence)
        value = {"sequence": sequence, "state": state.name,
                 "signature": self.__root.sign_emergency(body)}
        self.paths.organism_root.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".emergency-", dir=self.paths.organism_root)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(value, stream, sort_keys=True); stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, self.paths.emergency_state)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)
        self._state, self._sequence = state, sequence
        return EmergencySnapshot(state, sequence)

    def require_external_effects_allowed(self) -> None:
        if self.refresh().state >= EmergencyState.PAUSED:
            raise AuthorizationError("external effects are disabled by emergency authority")

    def require_remote_models_allowed(self) -> None:
        if self.refresh().state >= EmergencyState.LOCKDOWN:
            raise AuthorizationError("remote models are disabled by emergency authority")

    def require_development_allowed(self) -> None:
        if self.refresh().state >= EmergencyState.PAUSED:
            raise AuthorizationError("development is disabled by emergency authority")

    def require_new_work_allowed(self) -> None:
        if self.refresh().state >= EmergencyState.STOP_REQUESTED:
            raise AuthorizationError("STOP_REQUESTED: new work is disabled")


class EmergencyFactor:
    """Temporary local fallback factor; plaintext is never persisted or logged."""

    def __init__(self, paths: ProductPaths): self.path = paths.emergency_verifier

    def enroll(self, phrase: str) -> None:
        if not phrase: raise ValueError("an emergency phrase is required")
        salt = os.urandom(16)
        digest = hashlib.pbkdf2_hmac("sha256", phrase.encode(), salt, 300_000)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        descriptor = os.open(self.path, flags, 0o600)
        try:
            payload = json.dumps({"salt": salt.hex(), "digest": digest.hex(),
                                  "iterations": 300_000}, sort_keys=True).encode()
            os.write(descriptor, payload); os.fsync(descriptor)
        finally: os.close(descriptor)

    def verify(self, phrase: str) -> bool:
        try:
            value: dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8"))
            actual = hashlib.pbkdf2_hmac("sha256", phrase.encode(), bytes.fromhex(value["salt"]),
                                         int(value["iterations"]))
            return hmac.compare_digest(actual.hex(), value["digest"])
        except (OSError, KeyError, ValueError, TypeError, json.JSONDecodeError):
            return False
