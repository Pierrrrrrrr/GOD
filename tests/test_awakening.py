import json
from pathlib import Path

import pytest

from tmco.awakening import GodRuntime
from tmco.buses import ModelBus, ProviderUnavailable, TestProvider as ProviderFixture
from tmco.models import ModelRecord
from tmco.morphogenesis import AssemblyFormationPolicy
from tmco.vault import CredentialVault


class ScriptedOrgan:
    def __init__(self, perspective: str):
        self.perspective = perspective
        self.calls: list[dict] = []

    def infer(self, request: dict) -> dict:
        self.calls.append(request)
        prompt = request["prompt"]
        if "separate sister-audit" in prompt:
            return {"disagreements": ["sequence versus experiment"],
                    "synthesis": "Run a bounded experiment, then sequence evidence.",
                    "selected_next_action": "run bounded experiment", "rationale": "It tests both claims."}
        if "Reply naturally" in prompt:
            return {"answer": "Hello Pier. I am ready, and I have not invented any active work."}
        action = "map dependencies" if self.perspective == "A" else "run an experiment"
        return {"desired_outcome": "a realistic result", "success_evidence": ["measured result"],
                "constraints": ["bounded resources"], "unknowns": ["causal mechanism"],
                "risks": ["false confidence"], "subgoals": ["collect evidence"],
                "hypotheses": [self.perspective], "next_useful_action": action}


class FakeProvider(ProviderFixture):
    def infer(self, request: dict) -> dict:
        return {}


class RecordingPolicy(AssemblyFormationPolicy):
    def __init__(self):
        self.calls = 0

    def form(self, colonies, goal, budgets):
        self.calls += 1
        return super().form(colonies, goal, budgets)


def runtime(path: Path, policy=None) -> GodRuntime:
    return GodRuntime(path, {"alpha": ScriptedOrgan("A"), "beta": ScriptedOrgan("B")},
                      [ModelRecord("alpha", "one"), ModelRecord("beta", "two")],
                      formation_policy=policy, secret="awakening-test-key")


def test_full_awakening_audit_learning_and_restart(tmp_path: Path) -> None:
    policy = RecordingPolicy()
    first = runtime(tmp_path, policy)
    identities = {name: colony.id for name, colony in first.organism.colonies.items()}
    episode1 = first.submit_goal("Find a realistic way to reduce water waste")
    assert policy.calls == 1
    assert set(episode1["interpretations"]) == {"Saphira-A", "Saphira-B"}
    assert episode1["material_disagreement"] is True
    assert episode1["audit"]["disagreements"]
    assert episode1["audit"]["rationale"]
    learned = sum(n.verified_contribution for c in first.organism.colonies.values()
                  for n in c.neurons.values())
    episode2 = first.submit_goal("Find a realistic way to reduce water waste again")
    assert policy.calls == 2 and learned > 0
    # Compare task 2 with an inexperienced organism: the history, not just task wording,
    # changes the state-sensitive colony/assembly decision.
    control = runtime(tmp_path / "control")
    control_episode = control.submit_goal("Find a realistic way to reduce water waste again")
    assignment = lambda e: [(a["colony"], a["purpose"]) for a in e["assemblies"]]
    assert assignment(episode2) != assignment(control_episode)
    control.close()
    assert any(r.successes for r in first.records.values())
    assert "Hello Pier" in first.chat("Hello")
    calls_after_chat = sum(len(p.calls) for p in first.bus.providers.values())
    assert calls_after_chat >= 6  # independent calls, audits, then one ordinary conversation call
    first.close()

    restored = runtime(tmp_path)
    assert {name: colony.id for name, colony in restored.organism.colonies.items()} == identities
    assert len(restored.store.rows("SELECT * FROM goals")) == 2
    assert len(restored.store.rows("SELECT * FROM chat")) == 2
    assert len(restored.store.rows("SELECT * FROM episodes")) == 2
    assert any(r.successes for r in restored.records.values())
    assert sum(n.verified_contribution for c in restored.organism.colonies.values()
               for n in c.neurons.values()) > 0
    assert '"hypotheses": ["A"]' in restored.chat("What does Saphira-A think?")
    restored.close()
    # WAL was explicitly checkpointed and all handles are closed, permitting replacement on Windows.
    database = tmp_path / "awakening.sqlite3"
    moved = database.with_suffix(".moved")
    database.replace(moved); moved.replace(database)


def test_trivial_chat_uses_one_organ_and_fake_is_rejected(tmp_path: Path) -> None:
    organism = runtime(tmp_path)
    before = sum(len(p.calls) for p in organism.bus.providers.values())
    assert organism.chat("Good morning").startswith("Hello")
    after = sum(len(p.calls) for p in organism.bus.providers.values())
    assert after - before == 1
    assert not organism.store.rows("SELECT * FROM episodes")
    organism.close()
    with pytest.raises(ProviderUnavailable, match="test-only"):
        ModelBus({"fake": FakeProvider()}, production=True)


def test_credentials_are_separate_encrypted_and_binary_safe(tmp_path: Path) -> None:
    secret = "sk-plain-text-must-never-appear"
    vault = CredentialVault(tmp_path)
    vault.save({"provider": "OpenRouter", "model": "example", "key": secret})
    assert vault.load()["key"] == secret
    assert secret.encode() not in (tmp_path / "credentials.vault").read_bytes()
    assert not (tmp_path / "root.key").exists()
    for candidate in tmp_path.glob("*"):
        if candidate.is_file() and candidate.name != "credentials.local":
            assert secret.encode() not in candidate.read_bytes()
