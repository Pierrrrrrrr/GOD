"""Credential storage, deliberately independent of root authority and checkpoints."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path


class CredentialVault:
    def __init__(self, directory: Path):
        self.path = directory / "credentials.vault"
        self.key_path = directory / "credentials.local"
        directory.mkdir(parents=True, exist_ok=True)

    def save(self, values: dict[str, str]) -> None:
        raw = json.dumps(values).encode()
        protected = self._dpapi(raw, True) if os.name == "nt" else self._seal(raw)
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0)
        fd = os.open(self.path, flags, 0o600)
        try:
            os.write(fd, protected); os.fsync(fd)
        finally:
            os.close(fd)

    def load(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        protected = self.path.read_bytes()
        raw = self._dpapi(protected, False) if os.name == "nt" else self._unseal(protected)
        return json.loads(raw)

    def _local_key(self) -> bytes:
        if not self.key_path.exists():
            fd = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try: os.write(fd, os.urandom(32))
            finally: os.close(fd)
        os.chmod(self.key_path, 0o600)
        return self.key_path.read_bytes()

    def _seal(self, raw: bytes) -> bytes:
        nonce, key = os.urandom(16), self._local_key()
        stream = hashlib.shake_256(key + nonce).digest(len(raw))
        ciphertext = bytes(a ^ b for a, b in zip(raw, stream))
        return nonce + hmac.new(key, nonce + ciphertext, hashlib.sha256).digest() + ciphertext

    def _unseal(self, blob: bytes) -> bytes:
        nonce, tag, ciphertext = blob[:16], blob[16:48], blob[48:]
        key = self._local_key()
        if not hmac.compare_digest(tag, hmac.new(key, nonce + ciphertext, hashlib.sha256).digest()):
            raise ValueError("credential vault integrity check failed")
        stream = hashlib.shake_256(key + nonce).digest(len(ciphertext))
        return bytes(a ^ b for a, b in zip(ciphertext, stream))

    @staticmethod
    def _dpapi(data: bytes, protect: bool) -> bytes:
        # Reuse only the operating-system primitive, never RootGuard material or storage.
        from .root import WindowsRootSecretStore
        return WindowsRootSecretStore._crypt(data, protect=protect)
