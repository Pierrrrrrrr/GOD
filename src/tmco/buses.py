from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class ProviderUnavailable(RuntimeError):
    pass


class ModelProvider(Protocol):
    def infer(self, request: dict[str, Any]) -> dict[str, Any]: ...


class TestProvider:
    """Marker base class for deterministic providers, which are never production organs."""

    test_only = True


@dataclass(slots=True)
class OrganManifest:
    id: str
    kind: str  # MCP/OpenAPI/GraphQL/OAuth/A2A/browser/Python/CLI/database/cloud/sandbox
    version: str
    operations: dict[str, dict[str, Any]]
    auth_scheme: str | None = None
    endpoint: str | None = None
    permissions: set[str] = field(default_factory=set)


class ModelBus:
    def __init__(self, providers: dict[str, ModelProvider] | None = None, *, production: bool = False):
        self.production = production
        self.providers: dict[str, ModelProvider] = {}
        for name, provider in (providers or {}).items():
            self.register(name, provider)

    def register(self, name: str, provider: ModelProvider) -> None:
        if self.production and getattr(provider, "test_only", False):
            raise ProviderUnavailable("test-only model providers are rejected by the production bus")
        self.providers[name] = provider

    def request(self, provider: str, request: dict[str, Any]) -> dict[str, Any]:
        if provider not in self.providers:
            raise ProviderUnavailable(f"model provider {provider!r} is not configured")
        return self.providers[provider].infer(request)


class BodyBus:
    def __init__(self) -> None:
        self.manifests: dict[str, OrganManifest] = {}
        self.handlers: dict[tuple[str, str], Any] = {}

    def register(self, manifest: OrganManifest, handlers: dict[str, Any]) -> None:
        self.manifests[manifest.id] = manifest
        for operation, handler in handlers.items():
            self.handlers[(manifest.id, operation)] = handler

    def request(self, organ: str, operation: str, arguments: dict[str, Any]) -> Any:
        handler = self.handlers.get((organ, operation))
        if handler is None:
            raise ProviderUnavailable(f"organ operation {organ}.{operation} is not configured")
        return handler(arguments)
