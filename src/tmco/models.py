"""Replaceable HTTP model organs and persistent routing evidence."""
from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

MAX_MODEL_RESPONSE_BYTES = 2 * 1024 * 1024


def _bounded_json(response: Any) -> dict[str, Any]:
    raw = response.read(MAX_MODEL_RESPONSE_BYTES + 1)
    if len(raw) > MAX_MODEL_RESPONSE_BYTES:
        raise RuntimeError("model provider response exceeded the safe limit")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise RuntimeError("model provider response must be an object")
    return value


class ResponseMode(str, Enum):
    """Explicit trust contract for a model response."""

    TEXT = "text"
    STRUCTURED = "structured"


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
    quality_observations: int = 0
    last_tested: float | None = None
    privacy: str = "remote"

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.model_id}"

    @property
    def cost_classification(self) -> str:
        costs = (self.input_cost, self.output_cost)
        if any(cost is not None and cost > 0 for cost in costs):
            return "PAID — BLOCKED"
        if costs != (0, 0):
            return "COST UNKNOWN — BLOCKED"
        return "LOCAL FREE" if self.privacy == "local" else "REMOTE FREE"

    @property
    def zero_cost_eligible(self) -> bool:
        return self.input_cost == 0 and self.output_cost == 0


class HTTPModelProvider:
    """One provider connection capable of serving multiple routed model records."""

    def __init__(self, endpoint: str, api_key: str, *, gemini: bool = False):
        self.endpoint, self.api_key, self.gemini = endpoint.rstrip("/"), api_key, gemini

    def infer(self, request: dict[str, Any]) -> dict[str, Any] | str:
        prompt = request.get("prompt", "")
        try:
            mode = ResponseMode(request.get("response_mode", ResponseMode.STRUCTURED.value))
        except ValueError:
            raise ValueError("unknown model response mode") from None
        model_id = request.get("model_id")
        if not isinstance(model_id, str) or not model_id:
            raise ValueError("model_id is required for every model request")
        if self.gemini:
            body = {"contents": [{"parts": [{"text": prompt}]}]}
            if mode is ResponseMode.STRUCTURED:
                body["generationConfig"] = {"responseMimeType": "application/json"}
            headers = {"Content-Type": "application/json", "x-goog-api-key": self.api_key}
            endpoint = f"{self.endpoint}/models/{model_id}:generateContent"
        else:
            body = {"model": model_id, "messages": [{"role": "user", "content": prompt}]}
            if mode is ResponseMode.STRUCTURED:
                body["response_format"] = {"type": "json_object"}
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}
            endpoint = self.endpoint
        call = urllib.request.Request(endpoint, json.dumps(body).encode(), headers=headers)
        try:
            with urllib.request.urlopen(call, timeout=60) as response:
                payload = _bounded_json(response)
        except Exception:
            # Provider responses can reflect requests and keys; never include their body/message.
            raise RuntimeError("model provider request failed") from None
        if self.gemini:
            content = payload["candidates"][0]["content"]["parts"][0]["text"]
        else:
            content = payload["choices"][0]["message"]["content"]
        if mode is ResponseMode.TEXT:
            if not isinstance(content, str):
                raise RuntimeError("model provider returned an invalid text response")
            return content
        if isinstance(content, dict):
            return content
        if not isinstance(content, str):
            raise RuntimeError("model provider returned an invalid structured response")
        try:
            structured = json.loads(content)
        except (TypeError, ValueError):
            raise RuntimeError("model provider returned invalid structured data") from None
        if not isinstance(structured, dict):
            raise RuntimeError("structured model response must be an object")
        return structured

    def catalog(self) -> list[dict[str, Any]]:
        if self.gemini:
            url = f"{self.endpoint}/models"
            headers = {"x-goog-api-key": self.api_key}
        else:
            url = self.endpoint.rsplit("/chat/completions", 1)[0] + "/models"
            headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20) as response:
                payload = _bounded_json(response)
            return payload.get("models", payload.get("data", []))
        except Exception:
            return []


class ModelRouter:
    """Evidence-driven routing; no colony is pinned to a provider or function."""

    def choose(self, records: list[ModelRecord], task: str, *, privacy: bool = False,
               exclude: set[str] | None = None, policy: str = "ZERO_COST",
               requires_tools: bool = False, min_context: int = 0,
               required_modality: str = "text") -> ModelRecord:
        candidates = [r for r in records if r.availability and r.zero_cost_eligible
                      and r.key not in (exclude or set())]
        candidates = [r for r in candidates if (not requires_tools or r.tool_capability)
                      and (r.context_capability is None or r.context_capability >= min_context)
                      and required_modality in r.modalities]
        if not candidates:
            candidates = [r for r in records if r.availability and r.zero_cost_eligible
                          and (not requires_tools or r.tool_capability)
                          and (r.context_capability is None or r.context_capability >= min_context)
                          and required_modality in r.modalities]
        if not candidates:
            raise RuntimeError("NO_FREE_INTELLIGENCE_AVAILABLE")
        def score(r: ModelRecord) -> tuple[float, str]:
            quality = r.task_performance.get(task, r.calibration)
            reliability = (r.successes + 1) / (r.successes + r.failures + 2)
            cost = (r.input_cost or 0) + (r.output_cost or 0)
            latency = r.latency_ms / 100_000
            privacy_penalty = .25 if privacy and r.provider == "openrouter" else 0
            known_free = r.input_cost == 0 and r.output_cost == 0
            preference = (1.0 if policy == "LOCAL_FIRST" and r.privacy == "local" else
                          1.0 if policy == "FREE_FIRST" and known_free else
                          .15 if policy == "ZERO_COST" and r.privacy == "local" else 0.0)
            return preference + quality + reliability - cost - latency - privacy_penalty, r.key
        return max(candidates, key=score)

    @staticmethod
    def reason(record: ModelRecord, task: str, policy: str = "ZERO_COST") -> str:
        """A short, inspectable routing explanation based only on routing evidence."""
        parts = [f"available for {task}"]
        if record.privacy == "local": parts.append("local privacy")
        if record.input_cost == 0 and record.output_cost == 0: parts.append("zero catalog cost")
        if record.task_performance.get(task) is not None: parts.append("verified task quality")
        elif record.successes: parts.append("observed provider reliability")
        if record.latency_ms: parts.append(f"{record.latency_ms:.0f} ms observed latency")
        if policy != "AUTO": parts.append(f"{policy.lower().replace('_', ' ')} policy")
        return "; ".join(parts)

    @staticmethod
    def observe_call(record: ModelRecord, success: bool, latency_ms: float) -> None:
        """Record transport/schema health, never cognitive correctness."""
        record.last_tested = time.time()
        record.latency_ms = latency_ms if not record.latency_ms else .7 * record.latency_ms + .3 * latency_ms
        record.successes += int(success)
        record.failures += int(not success)
        record.availability = success

    @staticmethod
    def observe_verified_outcome(record: ModelRecord, task: str, correct: bool) -> None:
        """Update quality only when an explicit later evaluation supplies ground truth."""
        prior = record.task_performance.get(task, .5)
        record.task_performance[task] = .8 * prior + .2 * float(correct)
        total = record.quality_observations
        record.calibration = (record.calibration * total + float(correct)) / (total + 1)
        record.quality_observations += 1
