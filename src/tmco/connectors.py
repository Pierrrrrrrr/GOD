"""Host-side provider plugins. Cognition sees only the neutral ModelBus contract."""
from __future__ import annotations

import json
import urllib.request
from typing import Any, Protocol

from .models import HTTPModelProvider, ModelRecord, ResponseMode


class ProviderConnector(Protocol):
    name: str

    def probe(self, model_id: str) -> None: ...
    def discover(self) -> list[ModelRecord]: ...
    def infer(self, request: dict[str, Any]) -> dict[str, Any] | str: ...


def _price(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class CatalogConnector:
    name: str

    def __init__(self, transport: HTTPModelProvider):
        self.transport = transport

    def infer(self, request: dict[str, Any]) -> dict[str, Any] | str:
        return self.transport.infer(request)

    def probe(self, model_id: str) -> None:
        answer = self.infer({"model_id": model_id,
                             "prompt": "Capability probe. Return only JSON: {\"probe\": true}"})
        if answer.get("probe") is not True:
            raise RuntimeError("provider capability probe failed")


class OpenRouterConnector(CatalogConnector):
    name = "openrouter"

    def __init__(self, api_key: str):
        super().__init__(HTTPModelProvider("https://openrouter.ai/api/v1/chat/completions", api_key))

    def discover(self) -> list[ModelRecord]:
        records = [self._normalize(item) for item in self.transport.catalog()]
        records = [record for record in records if record is not None]
        # This gateway alias selects a currently available free model; it is not a
        # hard-coded underlying model and remains useful if catalog pricing is sparse.
        if not any(record.model_id == "openrouter/free" for record in records):
            records.append(ModelRecord(self.name, "openrouter/free", input_cost=0, output_cost=0))
        return records

    def _normalize(self, item: dict[str, Any]) -> ModelRecord | None:
        model_id = item.get("id")
        if not model_id:
            return None
        architecture, pricing = item.get("architecture", {}), item.get("pricing", {})
        return ModelRecord(self.name, model_id,
                           modalities=list(architecture.get("input_modalities", ["text"])),
                           context_capability=item.get("context_length"),
                           tool_capability=bool(item.get("supported_parameters") and
                                                "tools" in item["supported_parameters"]),
                           input_cost=_price(pricing.get("prompt")),
                           output_cost=_price(pricing.get("completion")))


class GeminiConnector(CatalogConnector):
    name = "gemini"

    def __init__(self, api_key: str):
        super().__init__(HTTPModelProvider("https://generativelanguage.googleapis.com/v1beta",
                                           api_key, gemini=True))

    def discover(self) -> list[ModelRecord]:
        records = []
        for item in self.transport.catalog():
            methods = item.get("supportedGenerationMethods", [])
            if "generateContent" not in methods:
                continue
            model_id = item.get("name", "").removeprefix("models/")
            if model_id:
                records.append(ModelRecord(self.name, model_id,
                                           context_capability=item.get("inputTokenLimit"),
                                           tool_capability="tools" in methods))
        return records


class OpenAICompatibleConnector(CatalogConnector):
    """Future-compatible boundary for Groq, LiteLLM, and similar gateways."""
    def __init__(self, name: str, endpoint: str, api_key: str):
        self.name = name
        super().__init__(HTTPModelProvider(endpoint, api_key))

    def discover(self) -> list[ModelRecord]:
        return [ModelRecord(self.name, item["id"]) for item in self.transport.catalog() if item.get("id")]


class OllamaConnector:
    name = "ollama"

    def __init__(self, endpoint: str = "http://127.0.0.1:11434"):
        self.endpoint = endpoint.rstrip("/")

    def _json(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        request = urllib.request.Request(self.endpoint + path,
                                         data=json.dumps(body).encode() if body else None,
                                         headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=2) as response:
            return json.load(response)

    def discover(self) -> list[ModelRecord]:
        try:
            models = self._json("/api/tags").get("models", [])
        except Exception:
            return []
        return [ModelRecord(self.name, item["name"], input_cost=0, output_cost=0,
                            privacy="local", availability=True)
                for item in models if item.get("name")]

    def probe(self, model_id: str) -> None:
        if not any(record.model_id == model_id for record in self.discover()):
            raise RuntimeError("local model is unavailable")

    def infer(self, request: dict[str, Any]) -> dict[str, Any] | str:
        mode = ResponseMode(request.get("response_mode", ResponseMode.STRUCTURED.value))
        payload = self._json("/api/chat", {"model": request["model_id"], "stream": False,
                                           **({"format": "json"} if mode is ResponseMode.STRUCTURED else {}), "messages": [
                                               {"role": "user", "content": request["prompt"]}]})
        content = payload["message"]["content"]
        if mode is ResponseMode.TEXT:
            return str(content)
        value = json.loads(content)
        if not isinstance(value, dict):
            raise RuntimeError("structured model response must be an object")
        return value
