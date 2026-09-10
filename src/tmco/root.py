from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class AuthorizationError(PermissionError):
    pass


@dataclass(slots=True)
class RootKernel:
    owner: str
    _secret: bytes = field(repr=False)
    key_reference: str = "root.key"
    constitution: tuple[str, ...] = (
        "root_policy_is_not_an_evolution_target",
        "cognition_cannot_grant_privileges",
        "external_effects_require_explicit_permission",
    )
    permissions: dict[str, set[str]] = field(default_factory=dict)
    audit: list[dict[str, Any]] = field(default_factory=list)

    def authorize(self, principal: str, permission: str, *, cognitive: bool = False) -> None:
        allowed = not cognitive and permission in self.permissions.get(principal, set())
        self.record("authorization", {"principal": principal, "permission": permission,
                                      "allowed": allowed})
        if not allowed:
            raise AuthorizationError(f"{principal} cannot acquire {permission}")

    def grant(self, actor: str, principal: str, permission: str) -> None:
        if actor != self.owner:
            self.record("privilege_rejected", {"actor": actor, "permission": permission})
            raise AuthorizationError("only owner root authority may grant permissions")
        self.permissions.setdefault(principal, set()).add(permission)
        self.record("privilege_granted", {"principal": principal, "permission": permission})

    def record(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        previous = self.audit[-1]["signature"] if self.audit else "GENESIS"
        body = {"sequence": len(self.audit), "kind": kind, "payload": payload,
                "previous": previous}
        encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        body["signature"] = hmac.new(self._secret, encoded, hashlib.sha256).hexdigest()
        self.audit.append(body)
        return body

    def verify_audit(self) -> bool:
        previous = "GENESIS"
        for index, entry in enumerate(self.audit):
            body = {k: entry[k] for k in ("sequence", "kind", "payload", "previous")}
            expected = hmac.new(self._secret, json.dumps(
                body, sort_keys=True, separators=(",", ":")).encode(), hashlib.sha256).hexdigest()
            if entry["sequence"] != index or entry["previous"] != previous or not hmac.compare_digest(expected, entry["signature"]):
                return False
            previous = entry["signature"]
        return True

    @property
    def key_fingerprint(self) -> str:
        return hashlib.sha256(self._secret).hexdigest()


class RootKeyStore:
    """Non-organism storage for root signing material."""

    def __init__(self, directory: Path, injected_key: bytes | None = None):
        self.path = directory / "root.key"
        self.injected_key = injected_key

    def load_or_create(self, *, existing_organism: bool) -> bytes:
        if self.injected_key is not None:
            return self.injected_key
        if self.path.exists():
            os.chmod(self.path, 0o600)
            return self.path.read_bytes()
        if existing_organism:
            raise AuthorizationError("root key is unavailable; refusing to re-key existing organism")
        key = os.urandom(32)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        descriptor = os.open(self.path, flags, 0o600)
        try:
            os.write(descriptor, key)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return key
