from __future__ import annotations

import os
from pathlib import Path

from .root import WindowsRootSecretStore


class CredentialVault:
    """A credential store separate from immutable root authority."""

    def __init__(self, directory: Path):
        self.directory = directory / "credentials"
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)

    def save(self, name: str, credential: str) -> None:
        if not credential:
            raise ValueError("credential is required")
        path = self.directory / f"{name}.credential"
        data = credential.encode()
        if os.name == "nt":
            data = WindowsRootSecretStore._protect(data)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC
                             | getattr(os, "O_BINARY", 0), 0o600)
        try:
            os.write(descriptor, data)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        if os.name != "nt":
            os.chmod(path, 0o600)

    def load(self, name: str) -> str:
        data = (self.directory / f"{name}.credential").read_bytes()
        if os.name == "nt":
            data = WindowsRootSecretStore._unprotect(data)
        return data.decode()

    def exists(self, name: str) -> bool:
        return (self.directory / f"{name}.credential").exists()
