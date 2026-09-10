from __future__ import annotations

import ctypes
import hashlib
import hmac
import json
import os
from abc import ABC, abstractmethod
from ctypes import wintypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


class AuthorizationError(PermissionError):
    pass


class SecretProtector(Protocol):
    def protect(self, plaintext: bytes) -> bytes: ...
    def unprotect(self, protected: bytes) -> bytes: ...


class RootGuard:
    """The narrow authority that owns key bytes and performs cryptography."""

    __slots__ = ("__secret", "key_reference")

    def __init__(self, secret: bytes, key_reference: str):
        if len(secret) < 16:
            raise ValueError("root secret is too short")
        self.__secret = secret
        self.key_reference = key_reference

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.__secret).hexdigest()

    def sign(self, payload: bytes) -> str:
        return hmac.new(self.__secret, payload, hashlib.sha256).hexdigest()

    def verifies(self, payload: bytes, signature: str) -> bool:
        return hmac.compare_digest(self.sign(payload), signature)


class RootSecretStore(ABC):
    """Platform storage boundary; callers receive only a signing guard."""

    @abstractmethod
    def open_guard(self, *, existing_organism: bool) -> RootGuard:
        raise NotImplementedError


class InjectedRootSecretStore(RootSecretStore):
    """Non-persistent deterministic key source for tests."""

    def __init__(self, secret: bytes):
        self._secret = hashlib.sha256(secret).digest()

    def open_guard(self, *, existing_organism: bool) -> RootGuard:
        return RootGuard(self._secret, "injected:test-only")


class PosixRootSecretStore(RootSecretStore):
    def __init__(self, directory: Path):
        self.path = directory / "root.key"

    def open_guard(self, *, existing_organism: bool) -> RootGuard:
        if self.path.exists():
            os.chmod(self.path, 0o600)
            secret = self.path.read_bytes()
        elif existing_organism:
            raise AuthorizationError("root key is unavailable; refusing to re-key existing organism")
        else:
            secret = os.urandom(32)
            descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                os.write(descriptor, secret)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        return RootGuard(secret, self.path.name)


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


class WindowsDPAPIProtector:
    """Windows DPAPI current-user protection via CryptProtectData."""

    @staticmethod
    def _libraries() -> tuple[Any, Any]:
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        blob_pointer = ctypes.POINTER(_DataBlob)
        crypt32.CryptProtectData.argtypes = [blob_pointer, wintypes.LPCWSTR,
                                             blob_pointer, ctypes.c_void_p,
                                             ctypes.c_void_p, wintypes.DWORD,
                                             blob_pointer]
        crypt32.CryptProtectData.restype = wintypes.BOOL
        crypt32.CryptUnprotectData.argtypes = [blob_pointer,
                                               ctypes.POINTER(wintypes.LPWSTR),
                                               blob_pointer, ctypes.c_void_p,
                                               ctypes.c_void_p, wintypes.DWORD,
                                               blob_pointer]
        crypt32.CryptUnprotectData.restype = wintypes.BOOL
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        return crypt32, kernel32

    @staticmethod
    def _blob(data: bytes) -> tuple[_DataBlob, Any]:
        buffer = ctypes.create_string_buffer(data)
        blob = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
        return blob, buffer

    def protect(self, plaintext: bytes) -> bytes:
        source, keepalive = self._blob(plaintext)
        destination = _DataBlob()
        crypt32, kernel32 = self._libraries()
        if not crypt32.CryptProtectData(ctypes.byref(source), "G.O.D. Root Secret", None,
                                        None, None, 1, ctypes.byref(destination)):
            raise ctypes.WinError()
        try:
            return ctypes.string_at(destination.pbData, destination.cbData)
        finally:
            kernel32.LocalFree(destination.pbData)
            del keepalive

    def unprotect(self, protected: bytes) -> bytes:
        source, keepalive = self._blob(protected)
        destination = _DataBlob()
        crypt32, kernel32 = self._libraries()
        if not crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None,
                                          1, ctypes.byref(destination)):
            raise ctypes.WinError()
        try:
            return ctypes.string_at(destination.pbData, destination.cbData)
        finally:
            kernel32.LocalFree(destination.pbData)
            del keepalive


class WindowsRootSecretStore(RootSecretStore):
    def __init__(self, directory: Path, protector: SecretProtector | None = None):
        self.path = directory / "root.secret.dpapi"
        self.protector = protector or WindowsDPAPIProtector()

    def open_guard(self, *, existing_organism: bool) -> RootGuard:
        if self.path.exists():
            secret = self.protector.unprotect(self.path.read_bytes())
        elif existing_organism:
            raise AuthorizationError("protected root material is unavailable; refusing to re-key")
        else:
            secret = os.urandom(32)
            protected = self.protector.protect(secret)
            if protected == secret:
                raise AuthorizationError("OS protector returned plaintext root material")
            # O_BINARY is required on Windows so the opaque DPAPI blob is never
            # altered by CRT text-mode newline translation.
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
            descriptor = os.open(self.path, flags)
            try:
                os.write(descriptor, protected)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        return RootGuard(secret, self.path.name)


def platform_root_secret_store(directory: Path) -> RootSecretStore:
    return WindowsRootSecretStore(directory) if os.name == "nt" else PosixRootSecretStore(directory)


@dataclass(slots=True)
class RootKernel:
    owner: str
    _guard: RootGuard = field(repr=False)
    constitution: tuple[str, ...] = (
        "root_policy_is_not_an_evolution_target",
        "cognition_cannot_grant_privileges",
        "external_effects_require_explicit_permission",
    )
    permissions: dict[str, set[str]] = field(default_factory=dict)
    audit: list[dict[str, Any]] = field(default_factory=list)

    @property
    def key_reference(self) -> str:
        return self._guard.key_reference

    @property
    def key_fingerprint(self) -> str:
        return self._guard.fingerprint

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
                    or not self._guard.verifies(encoded, entry["signature"])):
                return False
            previous = entry["signature"]
        return True
