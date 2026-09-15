import json
import re
import threading
import time
import urllib.error
import urllib.request
from http.server import HTTPServer
from pathlib import Path

import pytest

from tmco.models import HTTPModelProvider
from tmco.awakening import GodRuntime
from tmco.models import ModelRecord
from tmco.web import App, serve


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def read(self, *_):
        return json.dumps(self.payload).encode()


def test_provider_text_and_structured_contracts(monkeypatch: pytest.MonkeyPatch) -> None:
    requests = []

    def open_request(request, timeout):
        requests.append(json.loads(request.data))
        content = "ordinary conversation" if len(requests) == 1 else '{"verified":true}'
        return _Response({"choices": [{"message": {"content": content}}]})

    monkeypatch.setattr("urllib.request.urlopen", open_request)
    provider = HTTPModelProvider("https://provider.invalid/chat/completions", "test-secret")
    assert provider.infer({"model_id": "m", "prompt": "hello", "response_mode": "text"}) == "ordinary conversation"
    assert "response_format" not in requests[0]
    assert provider.infer({"model_id": "m", "prompt": "verify", "response_mode": "structured"}) == {"verified": True}
    assert requests[1]["response_format"] == {"type": "json_object"}


def test_conversation_fails_over_without_leaking_provider_error(tmp_path: Path) -> None:
    class Provider:
        def __init__(self, answer=None):
            self.answer = answer

        def infer(self, request):
            if self.answer is None:
                raise RuntimeError("provider-body-test-secret")
            return self.answer if request["response_mode"] == "text" else {}

    runtime = GodRuntime(tmp_path, {"z-failing": Provider(), "a-working": Provider("safe answer")},
        [ModelRecord("z-failing", "first", input_cost=0, output_cost=0, corporate_safe=True), ModelRecord("a-working", "second", input_cost=0, output_cost=0, corporate_safe=True)], secret="root-test-key")
    try:
        assert runtime.chat("hello") == "safe answer"
        assert any(event["kind"] == "MODEL_FAILOVER" for event in runtime.timeline())
        database_bytes = (tmp_path / "awakening.sqlite3").read_bytes()
        assert b"provider-body-test-secret" not in database_bytes
    finally:
        runtime.close()


def test_corporate_safe_http_boundary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ready = threading.Event()
    holder = {}

    class ObservableServer(HTTPServer):
        def server_activate(self):
            super().server_activate()
            holder["server"] = self
            ready.set()

    monkeypatch.setattr("tmco.web.HTTPServer", ObservableServer)
    thread = threading.Thread(target=serve, args=(tmp_path, 0), kwargs={"open_browser": False})
    thread.start()
    assert ready.wait(5)
    server = holder["server"]
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urllib.request.urlopen(base + "/", timeout=5) as response:
            page = response.read().decode()
            headers = response.headers
        assert "CORPORATE_SAFE" in page
        token = re.search(r'name=csrf-token content="([^"]+)"', page).group(1)
        assert headers["Cache-Control"].startswith("no-store")
        assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["Referrer-Policy"] == "no-referrer"

        request = urllib.request.Request(base + "/policy", data=b"policy=LOCAL_FIRST", method="POST")
        with pytest.raises(urllib.error.HTTPError) as denied:
            urllib.request.urlopen(request, timeout=5)
        assert denied.value.code == 403

        external = urllib.request.Request(base + "/policy", data=b"policy=LOCAL_FIRST", method="POST",
            headers={"X-GOD-CSRF": token, "Origin": "https://attacker.invalid"})
        with pytest.raises(urllib.error.HTTPError) as denied_origin:
            urllib.request.urlopen(external, timeout=5)
        assert denied_origin.value.code == 403

        valid = urllib.request.Request(base + "/policy", data=b"policy=LOCAL_FIRST", method="POST",
            headers={"X-GOD-CSRF": token, "Origin": base})
        with urllib.request.urlopen(valid, timeout=5) as response:
            assert response.status == 200

        doctor = urllib.request.Request(base + "/doctor", data=b"synthetic=true", method="POST",
            headers={"X-GOD-CSRF": token, "Origin": base})
        with urllib.request.urlopen(doctor, timeout=5) as response:
            assert json.loads(response.read()) == {"models": []}

        bad_host = urllib.request.Request(base + "/api/status", headers={"Host": "attacker.invalid"})
        with pytest.raises(urllib.error.HTTPError) as denied_host:
            urllib.request.urlopen(bad_host, timeout=5)
        assert denied_host.value.code == 400

        huge = urllib.request.Request(base + "/chat", data=b"message=" + b"x" * 65_537, method="POST",
            headers={"X-GOD-CSRF": token, "Origin": base})
        with pytest.raises(urllib.error.HTTPError) as denied_huge:
            urllib.request.urlopen(huge, timeout=5)
        assert denied_huge.value.code == 413
    finally:
        server.shutdown()
        thread.join(5)
    assert not thread.is_alive()


def test_zero_cost_router_never_selects_paid_or_unknown() -> None:
    from tmco.models import ModelRouter

    router = ModelRouter()
    paid = ModelRecord("remote", "paid", input_cost=0.01, output_cost=0, corporate_safe=True)
    unknown = ModelRecord("remote", "unknown")
    free = ModelRecord("remote", "free", input_cost=0, output_cost=0, corporate_safe=True)
    assert paid.cost_classification == "PAID — BLOCKED"
    assert unknown.cost_classification == "COST UNKNOWN — BLOCKED"
    assert free.cost_classification == "REMOTE FREE"
    assert router.choose([paid, unknown, free], "conversation").model_id == "free"
    with pytest.raises(RuntimeError, match="NO_FREE_SAFE_INTELLIGENCE_AVAILABLE"):
        router.choose([paid, unknown], "conversation")


def test_zero_cost_failover_does_not_fall_back_to_paid(tmp_path: Path) -> None:
    calls = []

    class Provider:
        def infer(self, request):
            calls.append(request["model_id"])
            raise RuntimeError("unavailable")

    runtime = GodRuntime(tmp_path, {"remote": Provider()}, [
        ModelRecord("remote", "free", input_cost=0, output_cost=0, corporate_safe=True),
        ModelRecord("remote", "paid", input_cost=1, output_cost=1),
    ], secret="zero-cost-test")
    try:
        with pytest.raises(Exception, match="NO_FREE_SAFE_INTELLIGENCE_AVAILABLE"):
            runtime.chat("hello")
        assert calls == ["free"]
    finally:
        runtime.close()


def test_paid_manual_model_is_blocked_before_probe_or_credential_save(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    class Catalog:
        def __init__(self, *_args, **_kwargs): pass
        def catalog(self):
            return [{"id": "paid", "pricing": {"prompt": "0.1", "completion": "0"}}]
        def infer(self, request):
            calls.append(request)
            return {"probe": True}

    monkeypatch.setattr("tmco.web.HTTPModelProvider", Catalog)
    app = App(tmp_path)
    try:
        with pytest.raises(RuntimeError, match="PAID — BLOCKED"):
            app.connect({"provider": "OpenRouter", "model": "paid", "key": "must-not-save"})
        assert calls == []
        assert not app.vault.handles()
        assert "Resource openrouter:paid — PAID — BLOCKED" in app.status()
    finally:
        app.close()


def test_transient_health_persists_cooldown_and_recovers_after_restart(tmp_path: Path) -> None:
    from tmco.models import ModelRouter

    record = ModelRecord("remote", "free", input_cost=0, output_cost=0, corporate_safe=True)
    now = time.time()
    ModelRouter.observe_call(record, False, 10, "RATE_LIMIT", now=now)
    assert record.consecutive_failures == 1 and record.cooldown_until == now + 5
    assert record.last_failure_class == "RATE_LIMIT" and not record.blocked
    runtime = GodRuntime(tmp_path, {"remote": type("P", (), {"infer": lambda *_: "ok"})()}, [record], secret="health")
    runtime._save_models(); runtime.close()
    restored = GodRuntime(tmp_path, {"remote": type("P", (), {"infer": lambda *_: "ok"})()},
                          [ModelRecord("remote", "free", input_cost=0, output_cost=0, corporate_safe=True)], secret="health")
    saved = restored.records["remote:free"]
    assert saved.consecutive_failures == 1 and saved.last_failure_class == "RATE_LIMIT"
    assert saved.cooldown_until == now + 5 and saved.health_state == "cooldown"
    saved.cooldown_until = 0
    assert ModelRouter().choose([saved], "conversation") is saved
    ModelRouter.observe_call(saved, True, 8)
    assert saved.consecutive_failures == 0 and saved.last_failure_class is None
    assert saved.last_success is not None and saved.health_state == "healthy"
    restored.close()


def test_openrouter_requests_enforce_corporate_safe_provider_route(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = []
    def open_request(request, timeout):
        sent.append(json.loads(request.data))
        return _Response({"choices": [{"message": {"content": '{"ok":true}'}}]})
    monkeypatch.setattr("urllib.request.urlopen", open_request)
    provider = HTTPModelProvider("https://openrouter.ai/api/v1/chat/completions", "secret", openrouter=True)
    assert provider.infer({"model_id": "proven-free", "prompt": "synthetic", "response_mode": "structured"}) == {"ok": True}
    assert sent[0]["provider"] == {"zdr": True, "data_collection": "deny", "require_parameters": True}
    assert sent[0]["response_format"] == {"type": "json_object"}


def test_outbound_data_policy_blocks_private_remote_context(tmp_path: Path) -> None:
    from tmco.capabilities import CapabilityRequest, OwnerCapability
    from tmco.data_policy import DataClass

    calls = []
    provider = type("Remote", (), {"privacy": "remote", "infer": lambda self, request: calls.append(request) or {}})()
    runtime = GodRuntime(tmp_path, {"remote": provider},
        [ModelRecord("remote", "free", input_cost=0, output_cost=0, corporate_safe=True)], secret="disclosure")
    bus = runtime.bus
    bus.register("other", provider)
    with pytest.raises(PermissionError):
        bus.request("remote", {"data_classes": [DataClass.CREDENTIAL.value]})
    with pytest.raises(PermissionError):
        bus.request("remote", {"data_classes": [DataClass.WORKSPACE_PRIVATE.value], "artifact_id": "a"})
    request = CapabilityRequest(runtime.organism.root.owner, "remote", "disclose_workspace", "summarize", "workflow",
        "outbound-data-policy", "workspace-disclosure", "artifact-a",
        allowed_submitted_data=("hash-a",), maximum_cost=0, ttl_seconds=60)
    request_id = runtime.owner_capabilities.request(request)
    capability = runtime.owner_capabilities.decide(
        runtime.owner_capabilities.owner_control().decide(request_id, True))
    assert capability is not None
    common = {"data_classes": [DataClass.WORKSPACE_PRIVATE.value], "artifact_id": "artifact-a",
              "content_hash": "hash-a", "outbound_purpose": "summarize"}
    for changed in ({"artifact_id": "wrong"}, {"content_hash": "altered"},
                    {"outbound_purpose": "other"}):
        with pytest.raises(PermissionError):
            bus.request("remote", {**common, **changed, "disclosure_approval": capability})
    forged = OwnerCapability(capability.request_id, capability.request, capability.expires_at,
                             capability.nonce, "0" * 64)
    with pytest.raises(PermissionError):
        bus.request("remote", {**common, "disclosure_approval": forged})
    with pytest.raises(PermissionError):
        bus.request("other", {**common, "disclosure_approval": capability})
    expired = OwnerCapability(capability.request_id, capability.request, 0, capability.nonce,
                              capability.signature)
    with pytest.raises(PermissionError):
        bus.request("remote", {**common, "disclosure_approval": expired})
    bus.request("remote", {**common, "disclosure_approval": capability})
    with pytest.raises(PermissionError):
        bus.request("remote", {**common, "disclosure_approval": capability})
    assert len(calls) == 1
    runtime.close()


def test_startup_and_intelligence_doctor_are_redacted(tmp_path: Path) -> None:
    from tmco.web import startup_doctor
    report = startup_doctor(tmp_path)
    assert report["root_audit"] == "verified"
    assert report["database_recovery"] == "ok"
    assert report["workspace_confinement"] is True
    assert report["loopback"] == "available"
    assert report["ok"] is True
    assert "secret" not in json.dumps(report).lower()


def test_http_chat_tracks_exact_job_allows_second_message_and_refresh(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ready = threading.Event(); holder = {}
    class ObservableServer(HTTPServer):
        def server_activate(self):
            super().server_activate(); holder["server"] = self; ready.set()
    def chat(self, message):
        self.runtime.store.chat("user", message); time.sleep(.12)
        answer = "safe:" + message; self.runtime.store.chat("assistant", answer); return answer
    monkeypatch.setattr("tmco.web.HTTPServer", ObservableServer)
    monkeypatch.setattr("tmco.web.App.chat", chat)
    thread = threading.Thread(target=serve, args=(tmp_path, 0), kwargs={"open_browser": False}); thread.start()
    assert ready.wait(5); server = holder["server"]; base = f"http://127.0.0.1:{server.server_port}"
    try:
        page = urllib.request.urlopen(base + "/").read().decode()
        token = re.search(r'name=csrf-token content="([^"]+)"', page).group(1)
        for message in ("first", "second"):
            request = urllib.request.Request(base + "/chat", data=("message=" + message).encode(), method="POST",
                headers={"X-GOD-CSRF": token, "Origin": base})
            response = json.loads(urllib.request.urlopen(request).read())
            job_id = response["job_id"]
            states = []
            for _ in range(30):
                status = json.loads(urllib.request.urlopen(base + "/api/status?job_id=" + job_id).read())
                states.append(status["job"]["state"])
                if states[-1] == "COMPLETE": break
                time.sleep(.02)
            assert states[-1] == "COMPLETE"
        refreshed = urllib.request.urlopen(base + "/").read().decode()
        assert "first" in refreshed and "second" in refreshed
    finally:
        server.shutdown(); thread.join(5)


def test_explicit_http_goal_launch_returns_tracked_durable_goal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ready = threading.Event(); holder = {}
    class ObservableServer(HTTPServer):
        def server_activate(self):
            super().server_activate(); holder["server"] = self; ready.set()
    def launch(self, message):
        goal_id = "durable-explicit-goal"
        self.runtime.store.put("goals", goal_id, {"id": goal_id, "description": message,
            "status": "active", "current_step": "reasoning", "step_count": 1})
        return goal_id
    monkeypatch.setattr("tmco.web.HTTPServer", ObservableServer)
    monkeypatch.setattr("tmco.web.App.launch_goal", launch)
    thread = threading.Thread(target=serve, args=(tmp_path, 0), kwargs={"open_browser": False}); thread.start()
    assert ready.wait(5); server = holder["server"]; base = f"http://127.0.0.1:{server.server_port}"
    try:
        page = urllib.request.urlopen(base + "/").read().decode()
        assert "Run as autonomous goal" in page and "COST OR PRIVACY NOT PROVEN — BLOCKED" in page
        token = re.search(r'name=csrf-token content="([^"]+)"', page).group(1)
        text = "Analizza questo problema e trova una soluzione"
        request = urllib.request.Request(base + "/goal", data=("message=" + text).encode(), method="POST",
            headers={"X-GOD-CSRF": token, "Origin": base})
        submitted = json.loads(urllib.request.urlopen(request).read())
        assert submitted["kind"] == "AUTONOMOUS_GOAL"
        for _ in range(30):
            status = json.loads(urllib.request.urlopen(
                base + "/api/status?job_id=" + submitted["job_id"]).read())
            if status["job"]["state"] == "COMPLETE": break
            time.sleep(.02)
        assert status["job"]["result"] == "durable-explicit-goal"
        assert status["goal"]["id"] == "durable-explicit-goal"
        assert status["goal"]["description"] == text
    finally:
        server.shutdown(); thread.join(5)
