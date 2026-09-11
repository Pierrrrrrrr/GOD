import json
import time
from dataclasses import replace
from pathlib import Path

import pytest

from tmco.capabilities import (CapabilityRequest, HumanCheckpoint, OwnerApproval,
                               OwnerCapabilityAuthority, OwnerControlSurface, SetupState)
from tmco.models import ModelRecord
from tmco.root import AuthorizationError, RootGuard, RootKernel
from tmco.vault import CredentialVault
from tmco.web import App, RuntimeWorker, read_safe_snapshot


def request(**changes):
    base = CapabilityRequest("Pier", "openrouter", "create_credential", "connect intelligence",
        "workflow-1", "body:external-account-setup", "api_key", "account-1",
        ("models.read",), ("email",), 0, ("create_account",), 60)
    return replace(base, **changes)


def authority(tmp_path, clock, root=None):
    root = root or RootKernel("Pier", RootGuard(b"root-secret"))
    return OwnerCapabilityAuthority(root, tmp_path / "capabilities.sqlite3", lambda: clock[0]), root


def test_owner_authority_exact_executor_persistent_restart_and_replay(tmp_path: Path) -> None:
    clock = [100.0]; auth, root = authority(tmp_path, clock); approved = request()
    request_id = auth.request(approved)
    assert auth.status(request_id) == SetupState.AWAITING_PIER
    with pytest.raises(TypeError):
        auth.decide(request_id, actor="Pier")  # a caller string is not an authority proof
    with pytest.raises(AuthorizationError):
        OwnerApproval(request_id, True, object(), object())
    lease = auth.decide(auth.owner_control().decide(request_id, True))
    assert lease is not None
    auth.close()

    restored, _ = authority(tmp_path, clock, root)
    assert restored.status(request_id) == SetupState.AUTHORIZED
    lease = restored.capability(request_id)
    with pytest.raises(AuthorizationError, match="executor"):
        restored.consume(lease, approved, executor_principal="cognition:Saphira-A")
    for changed in (request(service="gemini"), request(scopes=("models.write",)),
                    request(maximum_cost=1), request(account_id="account-2"),
                    request(purpose="unrelated")):
        with pytest.raises(AuthorizationError, match="differs"):
            restored.consume(lease, changed, executor_principal=approved.executor_principal)
    restored.consume(lease, approved, executor_principal=approved.executor_principal)
    restored.close()

    replay, _ = authority(tmp_path, clock, root)
    assert replay.status(request_id) == SetupState.COMPLETE
    with pytest.raises(AuthorizationError, match="already"):
        replay.consume(lease, approved, executor_principal=approved.executor_principal)
    assert not hasattr(replay, "_guard") and "RootGuard" not in vars(__import__("tmco.capabilities", fromlist=["*"]))
    replay.close()


def test_pending_denied_and_paused_exact_checkpoint_survive_restart(tmp_path: Path) -> None:
    clock = [100.0]; auth, root = authority(tmp_path, clock)
    pending = auth.request(request()); denied = auth.request(replace(request(), workflow_id="denied"))
    auth.decide(auth.owner_control().decide(denied, False))
    lease = auth.decide(auth.owner_control().decide(pending, True)); assert lease
    auth.pause(pending, HumanCheckpoint.MFA); auth.close()
    restored, _ = authority(tmp_path, clock, root)
    assert restored.status(pending) == SetupState.PAUSED_FOR_PIER
    assert restored.status(denied) == SetupState.DENIED
    with pytest.raises(AuthorizationError, match="exact"):
        restored.resume(restored.owner_control().decide(pending, True), request(scopes=("extra",)))
    restored.resume(restored.owner_control().decide(pending, True), request())
    assert restored.status(pending) == SetupState.AUTHORIZED
    restored.close()


@pytest.mark.parametrize("checkpoint", list(HumanCheckpoint))
def test_all_human_checkpoints_pause(checkpoint: HumanCheckpoint, tmp_path: Path) -> None:
    auth, _ = authority(tmp_path, [100.0]); identity = auth.request(request())
    assert auth.decide(auth.owner_control().decide(identity, True))
    auth.pause(identity, checkpoint)
    assert auth.status(identity) == SetupState.PAUSED_FOR_PIER
    auth.close()


class ProvenanceProvider:
    def __init__(self): self.calls = []
    def infer(self, request):
        self.calls.append(request["model_id"])
        return {"hypotheses": [request["model_id"]], "constraints": [],
                "next_useful_action": "observe"}


def test_observatory_uses_actual_persisted_model_and_colony_without_rerouting(tmp_path: Path,
                                                                              monkeypatch) -> None:
    provider = ProvenanceProvider()
    app = App(tmp_path)
    app.runtime.attach_intelligence({"actual": provider}, [ModelRecord("actual", "model-used")])
    episode = app.runtime.submit_goal("summarize this", important=False)
    expected_colony = next(iter(episode["interpretations"]))
    monkeypatch.setattr(app.runtime.router, "choose", lambda *a, **k: (_ for _ in ()).throw(AssertionError("render routed")))
    status = app.runtime.operational_status()
    assert status["selected_model"] == "actual:model-used"
    assert status["selected_colony"] == expected_colony
    assert status["sisters"][expected_colony]["status"] == "IDLE"
    kinds = [event["kind"] for event in status["timeline"]]
    assert {"GOAL_ACCEPTED", "PRIMARY_COLONY_SELECTED", "MODEL_SELECTED", "SISTER_RESULT_READY"} <= set(kinds)
    app.close()


class SlowGateway:
    name = "openrouter"
    def __init__(self, key): self.key = key
    def discover(self): return [ModelRecord("openrouter", "one"), ModelRecord("openrouter", "two")]
    def probe(self, model_id): return None
    def infer(self, request):
        time.sleep(.35)
        return {"hypotheses": ["safe"], "constraints": [], "next_useful_action": "wait"}


def test_runtime_worker_exposes_progress_during_long_call(tmp_path: Path, monkeypatch) -> None:
    CredentialVault(tmp_path).set_provider("openrouter", "never-visible-key")
    monkeypatch.setattr("tmco.web.OpenRouterConnector", SlowGateway)
    monkeypatch.setattr("tmco.web.OllamaConnector", lambda: type("Absent", (), {"discover": lambda self: []})())
    worker = RuntimeWorker(tmp_path)
    job_id, reply = worker.submit("chat", "Find a realistic way to wait")
    deadline = time.time() + 2
    snapshot = {}
    while time.time() < deadline:
        snapshot = read_safe_snapshot(tmp_path)
        if snapshot.get("selection") and snapshot["selection"]["finished_at"] is None: break
        time.sleep(.02)
    assert job_id and snapshot["selection"]["model_id"] in {"one", "two"}
    assert any(event["kind"] == "MODEL_SELECTED" for event in snapshot["timeline"])
    assert reply.get(timeout=5)[0]
    worker.close()
    assert b"never-visible-key" not in (tmp_path / "awakening.sqlite3").read_bytes()


class BootstrapConnector:
    def __init__(self, name, valid=True): self.name, self.valid = name, valid
    def discover(self):
        if not self.valid: raise RuntimeError("invalid credential body must stay private")
        return [ModelRecord(self.name, f"{self.name}-one"), ModelRecord(self.name, f"{self.name}-two")]
    def probe(self, model_id): return None
    def infer(self, request): return {"answer": "connected"}


def test_stored_openrouter_and_gemini_reconnect_independently_without_ids(tmp_path: Path, monkeypatch) -> None:
    vault = CredentialVault(tmp_path); vault.set_provider("openrouter", "bad-key"); vault.set_provider("gemini", "good-key")
    monkeypatch.setattr("tmco.web.OpenRouterConnector", lambda key: BootstrapConnector("openrouter", False))
    monkeypatch.setattr("tmco.web.GeminiConnector", lambda key: BootstrapConnector("gemini", True))
    monkeypatch.setattr("tmco.web.OllamaConnector", lambda: type("Absent", (), {"discover": lambda self: []})())
    app = App(tmp_path)
    assert app.provider_states["openrouter"] == "RECONNECT_REQUIRED"
    assert app.provider_states["gemini"] == "CONNECTED"
    assert set(app.runtime.records) == {"gemini:gemini-one", "gemini:gemini-two"}
    assert "bad-key" not in json.dumps(app.runtime.operational_status())
    app.close()


def test_direct_gemini_onboarding_discovers_catalog_without_model_id(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("tmco.web.GeminiConnector", lambda key: BootstrapConnector("gemini", True))
    monkeypatch.setattr("tmco.web.OllamaConnector", lambda: type("Absent", (), {"discover": lambda self: []})())
    app = App(tmp_path)
    assert app.connect_gemini("gemini-secret") == 2
    assert app.provider_states["gemini"] == "CONNECTED"
    assert len(app.runtime.records) == 2
    app.close()
