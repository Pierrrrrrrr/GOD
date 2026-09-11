"""Replaceable HTTP model organs and persistent routing evidence."""
from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ModelRecord:
    provider: str
    model_id: str
    availability: bool = True
    modalities: list[str] = field(default_factory=lambda: ["text"])
    context_capability: int | None = None
    tool_capability: bool = False
    input_cost: float | None = None
    output_cost: float | None = None
    latency_ms: float = 0.0
    successes: int = 0
    failures: int = 0
    task_performance: dict[str, float] = field(default_factory=dict)
    calibration: float = .5
    last_tested: float | None = None

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.model_id}"


class HTTPModelProvider:
    """One provider connection capable of serving multiple routed model records."""

    def __init__(self, endpoint: str, api_key: str, *, gemini: bool = False):
        self.endpoint, self.api_key, self.gemini = endpoint.rstrip("/"), api_key, gemini

    def infer(self, request: dict[str, Any]) -> dict[str, Any]:
        prompt = request.get("prompt", "")
        model_id = request.get("model_id")
        if not isinstance(model_id, str) or not model_id:
            raise ValueError("model_id is required for every model request")
        if self.gemini:
            body = {"contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"responseMimeType": "application/json"}}
            headers = {"Content-Type": "application/json", "x-goog-api-key": self.api_key}
            endpoint = f"{self.endpoint}/models/{model_id}:generateContent"
        else:
            body = {"model": model_id, "messages": [{"role": "user", "content": prompt}],
                    "response_format": {"type": "json_object"}}
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}
            endpoint = self.endpoint
        call = urllib.request.Request(endpoint, json.dumps(body).encode(), headers=headers)
        try:
            with urllib.request.urlopen(call, timeout=60) as response:
                payload = json.load(response)
        except Exception:
            # Provider responses can reflect requests and keys; never include their body/message.
            raise RuntimeError("model provider request failed") from None
        if self.gemini:
            content = payload["candidates"][0]["content"]["parts"][0]["text"]
        else:
            content = payload["choices"][0]["message"]["content"]
        return json.loads(content) if isinstance(content, str) else content

    def catalog(self) -> list[dict[str, Any]]:
        if self.gemini:
            url = f"{self.endpoint}/models"
            headers = {"x-goog-api-key": self.api_key}
        else:
            url = self.endpoint.rsplit("/chat/completions", 1)[0] + "/models"
            headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20) as response:
                payload = json.load(response)
            return payload.get("models", payload.get("data", []))
        except Exception:
            return []


class ModelRouter:
    """Evidence-driven routing; no colony is pinned to a provider or function."""

    def choose(self, records: list[ModelRecord], task: str, *, privacy: bool = False,
               exclude: set[str] | None = None) -> ModelRecord:
        candidates = [r for r in records if r.availability and r.key not in (exclude or set())]
        if not candidates:
            candidates = [r for r in records if r.availability]
        if not candidates:
            raise RuntimeError("no available model is configured")
        def score(r: ModelRecord) -> tuple[float, str]:
            quality = r.task_performance.get(task, r.calibration)
            reliability = (r.successes + 1) / (r.successes + r.failures + 2)
            cost = (r.input_cost or 0) + (r.output_cost or 0)
            latency = r.latency_ms / 100_000
            privacy_penalty = .25 if privacy and r.provider == "openrouter" else 0
            return quality + reliability - cost - latency - privacy_penalty, r.key
        return max(candidates, key=score)

    @staticmethod
    def learn(record: ModelRecord, task: str, success: bool, latency_ms: float) -> None:
        record.last_tested = time.time()
        record.latency_ms = latency_ms if not record.latency_ms else .7 * record.latency_ms + .3 * latency_ms
        record.successes += int(success)
        record.failures += int(not success)
        prior = record.task_performance.get(task, .5)
        record.task_performance[task] = .8 * prior + .2 * float(success)
        record.calibration = record.successes / max(1, record.successes + record.failures)
