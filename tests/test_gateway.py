import json
from pathlib import Path

import pytest

from tmco.connectors import OllamaConnector, OpenRouterConnector
from tmco.models import ModelRecord
from tmco.web import App


class GatewayConnector:
    name = "openrouter"
    instances = []

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.requests: list[dict] = []
        self.instances.append(self)

    def discover(self) -> list[ModelRecord]:
        return [ModelRecord(self.name, "openrouter/free", input_cost=0, output_cost=0, corporate_safe=True),
                ModelRecord(self.name, "paid-model", input_cost=.1, output_cost=.2)]

    def probe(self, model_id: str) -> None:
        assert self.infer({"model_id": model_id, "prompt": "probe"})["probe"]

    def infer(self, request: dict) -> dict:
        self.requests.append(request.copy())
        if request["prompt"] == "probe":
            return {"probe": True}
        return {"hypotheses": ["bounded test"], "constraints": ["safe"],
                "next_useful_action": "collect evidence"}


def test_secrets_import_discovers_models_without_manual_id_and_never_reaches_cognition(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    GatewayConnector.instances.clear()
    monkeypatch.setattr("tmco.web.OpenRouterConnector", GatewayConnector)
    secret = "sk-host-only-super-secret"
    source = tmp_path / "secrets.json"
    source.write_text(json.dumps({"providers": {"openrouter": {"api_key": secret}}}))

    app = App(tmp_path / "runtime")
    identities = {name: colony.id for name, colony in app.runtime.organism.colonies.items()}
    assert app.import_secrets(str(source), delete_source=True) == 2
    assert not source.exists()
    assert len(app.runtime.records) == 2
    assert "openrouter:openrouter/free" in app.runtime.records
    app.runtime.submit_goal("Find a realistic way to test automatic onboarding")
    connector = GatewayConnector.instances[-1]
    assert any(request["model_id"] == "openrouter/free" for request in connector.requests)
    assert all(secret not in json.dumps(request) for request in connector.requests)
    assert {name: colony.id for name, colony in app.runtime.organism.colonies.items()} == identities
    app.close()

    vault = tmp_path / "runtime" / "credentials.vault"
    assert secret.encode() not in vault.read_bytes()
    for path in (tmp_path / "runtime").rglob("*"):
        if path.is_file() and path.name not in {"credentials.vault", "credentials.local"}:
            assert secret.encode() not in path.read_bytes()


def test_source_file_is_deleted_only_with_explicit_confirmation(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tmco.web.OpenRouterConnector", GatewayConnector)
    source = tmp_path / "keep.json"
    source.write_text('{"providers":{"openrouter":{"api_key":"keep-me"}}}')
    app = App(tmp_path / "runtime")
    app.import_secrets(str(source), delete_source=False)
    assert source.exists()
    app.close()


def test_openrouter_catalog_keeps_only_concrete_catalog_models(monkeypatch: pytest.MonkeyPatch) -> None:
    connector = OpenRouterConnector("secret")
    monkeypatch.setattr(connector.transport, "catalog", lambda: [{
        "id": "community/free-model", "context_length": 4096,
        "architecture": {"input_modalities": ["text"]},
        "supported_parameters": ["tools", "response_format"],
        "pricing": {"prompt": "0", "completion": "0"},
    }])
    records = connector.discover()
    discovered = {record.model_id: record for record in records}
    assert discovered["community/free-model"].input_cost == 0
    assert discovered["community/free-model"].context_capability == 4096
    assert discovered["community/free-model"].tool_capability
    assert discovered["community/free-model"].structured_capability
    assert "openrouter/free" not in discovered


class LocalConnector:
    name = "ollama"

    def discover(self) -> list[ModelRecord]:
        return [ModelRecord("ollama", "installed-local", input_cost=0, output_cost=0,
                            privacy="local")]

    def probe(self, model_id: str) -> None:
        assert model_id == "installed-local"

    def infer(self, request: dict) -> dict:
        return {"answer": "local"}


def test_ollama_absence_is_harmless_and_local_discovery_needs_no_credential(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = App(tmp_path)
    identities = {name: colony.id for name, colony in app.runtime.organism.colonies.items()}
    monkeypatch.setattr("tmco.web.OllamaConnector", lambda: type(
        "Absent", (), {"discover": lambda self: []})())
    assert app.detect_local_models() == 0
    assert not app.runtime.intelligence_connected

    monkeypatch.setattr("tmco.web.OllamaConnector", LocalConnector)
    assert app.detect_local_models() == 1
    assert app.runtime.records["ollama:installed-local"].privacy == "local"
    assert not app.vault.handles()
    app.runtime.set_routing_policy("LOCAL_FIRST")
    assert app.runtime.router.choose(list(app.runtime.records.values()), "conversation",
                                     policy=app.runtime.routing_policy).provider == "ollama"
    assert {name: colony.id for name, colony in app.runtime.organism.colonies.items()} == identities
    app.runtime.detach_intelligence()
    assert not app.runtime.intelligence_connected
    assert {name: colony.id for name, colony in app.runtime.organism.colonies.items()} == identities
    app.close()


def test_real_ollama_absence_returns_empty_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(*args, **kwargs):
        raise OSError("offline")

    monkeypatch.setattr("urllib.request.urlopen", unavailable)
    assert OllamaConnector().discover() == []
