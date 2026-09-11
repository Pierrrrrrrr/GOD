from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


class ProviderUnavailable(RuntimeError):
    pass


class ModelProvider(Protocol):
    def infer(self, request: dict[str, Any]) -> dict[str, Any]: ...


class TestProvider:
    """Marker base class for deterministic providers, never production organs."""
    test_only = True


@dataclass(slots=True)
class OrganManifest:
    id: str
    kind: str
    version: str
    operations: dict[str, dict[str, Any]]
    description: str = ""
    permissions: set[str] = field(default_factory=set)
    risk: float = 0.0
    side_effect_class: str = "read"
    reversible: bool = True
    cost: float = 0.0
    latency_ms: float = 0.0
    verified_reliability: float = .5
    provenance: str = "local"
    available: bool = True
    capability_tags: set[str] = field(default_factory=set)
    network_scope: tuple[str, ...] = ()
    filesystem_scope: tuple[str, ...] = ()
    credential_handles: tuple[str, ...] = ()
    auth_scheme: str | None = None
    endpoint: str | None = None
    trusted: bool = True


class ModelBus:
    def __init__(self, providers: dict[str, ModelProvider] | None = None, *, production: bool = False):
        self.production = production
        self.providers: dict[str, ModelProvider] = {}
        for name, provider in (providers or {}).items(): self.register(name, provider)

    def register(self, name: str, provider: ModelProvider) -> None:
        if self.production and getattr(provider, "test_only", False):
            raise ProviderUnavailable("test-only model providers are rejected by the production bus")
        self.providers[name] = provider

    def request(self, provider: str, request: dict[str, Any]) -> dict[str, Any]:
        if provider not in self.providers:
            raise ProviderUnavailable(f"model provider {provider!r} is not configured")
        return self.providers[provider].infer(request)


class BodyBus:
    """Single typed boundary for all physical capabilities; no fallback effects."""
    def __init__(self) -> None:
        self.manifests: dict[str, OrganManifest] = {}
        self.handlers: dict[tuple[str, str], Callable[[dict[str, Any]], Any]] = {}

    def register(self, manifest: OrganManifest, handlers: dict[str, Any]) -> None:
        unknown = set(handlers) - set(manifest.operations)
        if unknown: raise ValueError(f"handlers absent from manifest: {sorted(unknown)}")
        self.manifests[manifest.id] = manifest
        for operation, handler in handlers.items(): self.handlers[(manifest.id, operation)] = handler

    def request(self, organ: str, operation: str, arguments: dict[str, Any]) -> Any:
        manifest = self.manifests.get(organ)
        handler = self.handlers.get((organ, operation))
        if manifest is None or not manifest.available or handler is None:
            raise ProviderUnavailable(f"organ operation {organ}.{operation} is not configured")
        return handler(arguments)
