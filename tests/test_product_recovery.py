import json
import re
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer
from pathlib import Path

import pytest

from tmco.models import HTTPModelProvider
from tmco.awakening import GodRuntime
from tmco.models import ModelRecord
from tmco.web import serve


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
        [ModelRecord("z-failing", "first"), ModelRecord("a-working", "second")], secret="root-test-key")
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
