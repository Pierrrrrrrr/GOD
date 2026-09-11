from dataclasses import replace
from pathlib import Path

import pytest

from tmco.capabilities import (CapabilityRequest, HumanCheckpoint,
                               OwnerCapabilityAuthority, SetupState)
from tmco.root import AuthorizationError, RootGuard, RootKernel
from tmco.web import App


def request(**changes):
    base = CapabilityRequest("Pier", "openrouter", "create_credential", "connect intelligence",
                             "workflow-1", "api_key", ("models.read",), ("email",), 0,
                             ("create_account",), 60)
    return replace(base, **changes)


def test_owner_capability_is_exact_expiring_single_use_and_not_self_authorized() -> None:
    clock = [100.0]
    root = RootKernel("Pier", RootGuard(b"root-secret"))
    authority = OwnerCapabilityAuthority(root, lambda: clock[0])
    approved = request()
    request_id = authority.request(approved)
    with pytest.raises(AuthorizationError, match="Pier approval"):
        authority.grant(request_id, approved, actor="model")
    lease = authority.grant(request_id, approved, actor="Pier")
    with pytest.raises(AuthorizationError, match="differs"):
        authority.consume(lease, request(service="gemini"), actor="Pier")
    with pytest.raises(AuthorizationError, match="differs"):
        authority.consume(lease, request(scopes=("models.write",)), actor="Pier")
    with pytest.raises(AuthorizationError, match="differs"):
        authority.consume(lease, request(maximum_cost=1), actor="Pier")
    authority.consume(lease, approved, actor="Pier")
    with pytest.raises(AuthorizationError, match="already"):
        authority.consume(lease, approved, actor="Pier")

    second_id = authority.request(replace(approved, workflow_id="workflow-2"))
    second = authority.grant(second_id, replace(approved, workflow_id="workflow-2"), actor="Pier")
    clock[0] = second.expires_at
    with pytest.raises(AuthorizationError, match="expired"):
        authority.consume(second, second.request, actor="Pier")


@pytest.mark.parametrize("checkpoint", list(HumanCheckpoint))
def test_human_only_checkpoint_pauses_for_pier(checkpoint: HumanCheckpoint) -> None:
    root = RootKernel("Pier", RootGuard(b"root-secret"))
    authority = OwnerCapabilityAuthority(root)
    request_id = authority.request(request())
    authority.pause(request_id, checkpoint)
    assert authority.states[request_id] == SetupState.PAUSED_FOR_PIER


def test_offline_onboarding_and_real_event_timeline_survive_restart(tmp_path: Path,
                                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tmco.web.OllamaConnector", lambda: type(
        "Absent", (), {"discover": lambda self: []})())
    first = App(tmp_path)
    assert "INTELLIGENCE OFFLINE" in first.onboarding()
    timeline = first.runtime.timeline()
    assert timeline and timeline[-1]["kind"] == "BOOT"
    assert all("prompt" not in event["state"] for event in timeline)
    first.runtime.set_routing_policy("LOCAL_FIRST")
    first.close()

    restored = App(tmp_path)
    assert restored.runtime.routing_policy == "LOCAL_FIRST"
    assert any(event["kind"] == "ROUTING" for event in restored.runtime.timeline())
    restored.close()
