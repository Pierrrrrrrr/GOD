from pathlib import Path

import pytest

from tmco.awakening import GodRuntime
from tmco.buses import ModelBus, ProviderUnavailable
from tmco.fixtures import FakeProvider
from tmco.phase2 import CognitiveDemand, ModelCapabilityRegistry, RuntimeStore


def runtime(path: Path, *providers: tuple[str, FakeProvider]) -> GodRuntime:
    bus = ModelBus(production=False)
    organism = GodRuntime(path, bus=bus)
    for name, provider in providers:
        bus.register(name, provider)
        organism.registry.register(name, "fake-model")
    return organism


def test_fake_provider_is_impossible_in_production() -> None:
    with pytest.raises(ProviderUnavailable, match="test-only"):
        ModelBus({"fake": FakeProvider()})


def test_arbitrary_goal_dual_thought_state_chat_and_restart(tmp_path: Path) -> None:
    fake = FakeProvider()
    organism = runtime(tmp_path, ("fake", fake))
    result = organism.submit_goal("Find a way to map an unfamiliar system")
    assert set(result["interpretations"]) == {"Saphira-A", "Saphira-B"}
    assert result["interpretations"]["Saphira-A"] != result["interpretations"]["Saphira-B"]
    assert result["disagreement"] and result["selective_sister_audit"]
    assert len(organism.store.all("assemblies")) == 2
    answer = organism.chat("What are you doing?")["answer"]
    assert result["next_action"] in answer

    restarted = runtime(tmp_path, ("fake", FakeProvider()))
    assert restarted.status()["current_goal"]["id"] == result["id"]
    assert len(restarted.store.all("messages")) == 2
    assert restarted.organism.memory.episodic[-1]["goal_id"] == result["id"]
    assert restarted.store.all("model_registry")[0]["success_count"] == 2


def test_trivial_chat_uses_one_colony_call(tmp_path: Path) -> None:
    fake = FakeProvider()
    organism = runtime(tmp_path, ("fake", fake))
    organism.chat("Hello")
    assert len(fake.calls) == 1


def test_experience_changes_later_model_routing(tmp_path: Path) -> None:
    store = RuntimeStore(tmp_path)
    registry = ModelCapabilityRegistry(store)
    first = registry.register("one", "model")
    second = registry.register("two", "model")
    demand = CognitiveDemand("research", .5, .5)
    assert registry.route(demand)["id"] == first
    registry.observe(first, "research", False, 100)
    assert registry.route(demand)["id"] == second


def test_credential_not_in_sqlite_or_phase1_logs(tmp_path: Path) -> None:
    secret = "super-secret-provider-credential"
    organism = GodRuntime(tmp_path, bus=ModelBus(production=False))
    organism.vault.save("fake", secret)
    persisted = b"".join(path.read_bytes() for path in tmp_path.iterdir() if path.is_file())
    assert secret.encode() not in persisted
