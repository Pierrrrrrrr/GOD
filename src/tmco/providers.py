from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


class ProviderError(RuntimeError):
    pass


@dataclass(slots=True)
class OpenAICompatibleProvider:
    base_url: str
    model: str
    api_key: str
    test_only: bool = False

    def _request(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(f"{self.base_url.rstrip('/')}/{path.lstrip('/')}",
                                         data=data, headers=headers,
                                         method="POST" if data else "GET")
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read())
        except (urllib.error.URLError, json.JSONDecodeError) as error:
            raise ProviderError(f"model provider request failed: {error}") from error

    def infer(self, request: dict[str, Any]) -> dict[str, Any]:
        payload = {**request, "model": request.get("model", self.model)}
        return self._request("chat/completions", payload)

    def models(self) -> list[dict[str, Any]]:
        return list(self._request("models").get("data", []))


class OpenRouterProvider(OpenAICompatibleProvider):
    def __init__(self, model: str, api_key: str):
        super().__init__("https://openrouter.ai/api/v1", model, api_key)


@dataclass(slots=True)
class GeminiProvider:
    model: str
    api_key: str
    base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    test_only: bool = False

    def _request(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        separator = "&" if "?" in path else "?"
        url = f"{self.base_url.rstrip('/')}/{path.lstrip('/')}{separator}key={self.api_key}"
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"},
                                         method="POST" if data else "GET")
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read())
        except (urllib.error.URLError, json.JSONDecodeError) as error:
            raise ProviderError(f"Gemini request failed: {error}") from error

    def infer(self, request: dict[str, Any]) -> dict[str, Any]:
        messages = request.get("messages", [])
        contents = [{"role": "model" if item["role"] == "assistant" else "user",
                     "parts": [{"text": item["content"]}]} for item in messages]
        response = self._request(f"models/{self.model}:generateContent", {"contents": contents,
                                                                          "generationConfig": {"responseMimeType": "application/json"}})
        text = response["candidates"][0]["content"]["parts"][0]["text"]
        return {"choices": [{"message": {"content": text}}], "usage": response.get("usageMetadata", {})}

    def models(self) -> list[dict[str, Any]]:
        return list(self._request("models").get("models", []))
