from __future__ import annotations

import hashlib
import hmac
import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class AuthorizationError(PermissionError):
    pass


class RootGuard:
    """The only object allowed to hold the plaintext root secret."""

    __slots__ = ("__secret",)

    def __init__(self, secret: bytes):
        self.__secret = secret

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.__secret).hexdigest()

    def sign(self, payload: bytes) -> str:
        return hmac.new(self.__secret, payload, hashlib.sha256).hexdigest()

    def verify(self, payload: bytes, signature: str) -> bool:
        return hmac.compare_digest(self.sign(payload), signature)


class RootSecretStore(ABC):
    """Platform storage boundary for persistent root signing material."""

    def __init__(self, directory: Path):
        self.path = directory / "root.key"

    @abstractmethod
    def load_or_create(self, *, existing_organism: bool) -> RootGuard:
        """Load a protected secret or create one for a new organism."""

    def _unavailable(self, existing_organism: bool) -> None:
        if existing_organism:
            raise AuthorizationError("root key is unavailable; refusing to re-key existing organism")


class PosixRootSecretStore(RootSecretStore):
    def load_or_create(self, *, existing_organism: bool) -> RootGuard:
        if self.path.exists():
            os.chmod(self.path, 0o600)
            secret = self.path.read_bytes()
            if len(secret) != 32:
                raise AuthorizationError("stored root key is invalid")
            return RootGuard(secret)
        self._unavailable(existing_organism)
        secret = os.urandom(32)
        descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(descriptor, secret)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return RootGuard(secret)


class WindowsRootSecretStore(RootSecretStore):
    """DPAPI current-user protected root-secret storage."""

    def load_or_create(self, *, existing_organism: bool) -> RootGuard:
        if self.path.exists():
            try:
                secret = self._unprotect(self.path.read_bytes())
            except OSError as error:
                raise AuthorizationError("root key cannot be unprotected by this user") from error
            if len(secret) != 32:
                raise AuthorizationError("stored root key is invalid")
            return RootGuard(secret)
        self._unavailable(existing_organism)
        secret = os.urandom(32)
        protected = self._protect(secret)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        descriptor = os.open(self.path, flags)
        try:
            os.write(descriptor, protected)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return RootGuard(secret)

    @staticmethod
    def _crypt(data: bytes, *, protect: bool) -> bytes:
        import ctypes
        from ctypes import wintypes

        class DataBlob(ctypes.Structure):
            _fields_ = (("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_byte)))

        source_buffer = ctypes.create_string_buffer(data)
        source = DataBlob(len(data), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte)))
        destination = DataBlob()
        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        function = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
        function.argtypes = (
            ctypes.POINTER(DataBlob), ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DataBlob),
        )
        function.restype = wintypes.BOOL
        # CRYPTPROTECT_UI_FORBIDDEN; no entropy means standard current-user scope.
        if not function(ctypes.byref(source), None, None, None, None, 0x1,
                        ctypes.byref(destination)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return ctypes.string_at(destination.data, destination.size)
        finally:
            ctypes.windll.kernel32.LocalFree(destination.data)

    @classmethod
    def _protect(cls, data: bytes) -> bytes:
        return cls._crypt(data, protect=True)

    @classmethod
    def _unprotect(cls, data: bytes) -> bytes:
        return cls._crypt(data, protect=False)


def root_secret_store(directory: Path) -> RootSecretStore:
    return WindowsRootSecretStore(directory) if os.name == "nt" else PosixRootSecretStore(directory)


@dataclass(slots=True)
class RootKernel:
    _owner: str
    _guard: RootGuard = field(repr=False)
    key_reference: str = "root.key"
    constitution: tuple[str, ...] = (
        "root_policy_is_not_an_evolution_target",
        "cognition_cannot_grant_privileges",
        "external_effects_require_explicit_permission",
        "owner_identity_is_not_an_evolution_target",
        "root_emergency_override_is_not_an_evolution_target",
        "cognition_cannot_redefine_owner",
        "cognition_cannot_clear_emergency_stop",
        "cells_cannot_grant_owner_authority",
        "authenticated_owner_stop_has_absolute_priority",
        "emergency_lockdown_blocks_new_external_effects",
        "absence_of_intelligence_cannot_block_owner_stop",
    )
    permissions: dict[str, set[str]] = field(default_factory=dict)
    audit: list[dict[str, Any]] = field(default_factory=list)

    @property
    def owner(self) -> str: return self._owner

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
        body["signature"] = self._guard.sign(encoded)
        self.audit.append(body)
        return body

    def verify_audit(self) -> bool:
        previous = "GENESIS"
        for index, entry in enumerate(self.audit):
            body = {key: entry[key] for key in ("sequence", "kind", "payload", "previous")}
            encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
            if (entry["sequence"] != index or entry["previous"] != previous
                    or not self._guard.verify(encoded, entry["signature"])):
                return False
            previous = entry["signature"]
        return True

    def sign_owner_capability(self, payload: bytes) -> str:
        """Domain-separated signing for the host-side capability authority only."""
        return self._guard.sign(b"GOD:OWNER-CAPABILITY:v1\0" + payload)

    def verify_owner_capability(self, payload: bytes, signature: str) -> bool:
        return self._guard.verify(b"GOD:OWNER-CAPABILITY:v1\0" + payload, signature)

    def sign_owner_attestation(self, payload: bytes) -> str:
        return self._guard.sign(b"GOD:OWNER-ATTESTATION:v1\0" + payload)

    def verify_owner_attestation(self, payload: bytes, signature: str) -> bool:
        return self._guard.verify(b"GOD:OWNER-ATTESTATION:v1\0" + payload, signature)

    @property
    def key_fingerprint(self) -> str:
        return self._guard.fingerprint
