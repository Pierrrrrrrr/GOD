import json
from pathlib import Path

import pytest

from tmco.awakening import GodRuntime
from tmco.buses import ModelBus, ProviderUnavailable, TestProvider as ProviderFixture
from tmco.models import ModelRecord
from tmco.morphogenesis import AssemblyFormationPolicy
from tmco.vault import CredentialVault
from tmco.web import App


class ScriptedOrgan:
    def __init__(self, perspective: str):
        self.perspective = perspective
        self.calls: list[dict] = []

    def infer(self, request: dict) -> dict:
        self.calls.append(request)
        prompt = request["prompt"]
        if "Assess only whether" in prompt:
            return {"material_disagreement": True, "reasons": ["actions conflict"]}
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
    weights = {name: colony.graph() for name, colony in first.organism.colonies.items()}
    episode1 = first.submit_goal("Find a realistic way to reduce water waste")
    assert policy.calls == 1
    assert set(episode1["interpretations"]) == {"Saphira-A", "Saphira-B"}
    assert episode1["material_disagreement"] is True
    assert episode1["audit"]["disagreements"]
    assert episode1["audit"]["rationale"]
    assert sum(n.verified_contribution for c in first.organism.colonies.values()
               for n in c.neurons.values()) == 0
    assert {name: colony.graph() for name, colony in first.organism.colonies.items()} == weights
    learned_specializations = sum(n.specialization != "generalist"
                                  for c in first.organism.colonies.values() for n in c.neurons.values())
    episode2 = first.submit_goal("Find a realistic way to reduce water waste again")
    assert policy.calls == 2 and learned_specializations > 0
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
               for n in c.neurons.values()) == 0
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


class SameProviderOrgan:
    def __init__(self, *, cosmetic: bool = False):
        self.model_ids: list[str] = []
        self.cosmetic = cosmetic

    def infer(self, request: dict) -> dict:
        self.model_ids.append(request["model_id"])
        prompt = request["prompt"]
        if "Assess only whether" in prompt:
            return {"material_disagreement": True, "reasons": ["different next actions"]}
        if "separate sister-audit" in prompt:
            return {"disagreements": ["action"], "synthesis": "test both", "selected_next_action": "test",
                    "rationale": "bounded evidence"}
        action = "same action" if self.cosmetic else f"action from {request['model_id']}"
        result = {"hypotheses": ["same"] if self.cosmetic else [request["model_id"]],
                  "constraints": ["same"], "next_useful_action": action}
        if self.cosmetic: result["wording"] = request["model_id"]
        return result


def test_same_provider_routes_actual_models_and_cosmetic_difference_skips_audit(tmp_path: Path) -> None:
    organ = SameProviderOrgan(cosmetic=True)
    organism = GodRuntime(tmp_path, {"shared": organ},
                          [ModelRecord("shared", "model-one"), ModelRecord("shared", "model-two")],
                          secret="test-key")
    episode = organism.submit_goal("Find a realistic way to compare harmless wording")
    assert set(organ.model_ids) == {"model-one", "model-two"}
    assert len(organ.model_ids) == 2  # no materiality assessment and no full audit
    assert episode["candidate_disagreement"] is False
    assert episode["material_disagreement"] is False
    assert episode["materiality_reasons"] == [] and episode["audit"] is None
    organism.close()


class ProbeProvider:
    valid = True

    def __init__(self, endpoint: str, key: str, *, gemini: bool = False):
        self.key = key

    def infer(self, request: dict) -> dict:
        if not self.valid: raise RuntimeError("safe failure")
        if "Capability probe" in request["prompt"]: return {"probe": True}
        return {"answer": "persist me"}

    def catalog(self) -> list[dict]:
        return [{"id": "chosen", "context_length": 8192,
                 "architecture": {"input_modalities": ["text", "image"]},
                 "pricing": {"prompt": "0.000001", "completion": "0.000002"}}]


def test_connection_probe_metadata_and_visible_chat_restart(tmp_path: Path,
                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tmco.web.HTTPModelProvider", ProbeProvider)
    values = {"provider": "OpenRouter", "model": "chosen", "endpoint": "https://safe.invalid/chat/completions",
              "key": "connection-secret"}
    ProbeProvider.valid = False
    failed = App(tmp_path)
    with pytest.raises(RuntimeError): failed.connect(values)
    assert failed.runtime is None and not (tmp_path / "credentials.vault").exists()

    ProbeProvider.valid = True
    assert failed.connect(values).startswith("Connected")
    record = next(iter(failed.runtime.records.values()))
    assert record.context_capability == 8192 and record.modalities == ["text", "image"]
    assert record.input_cost == .000001 and record.output_cost == .000002
    assert "Intelligence CONNECTED" in failed.status()
    assert failed.chat("hello") == "persist me"
    failed.close()

    restored = App(tmp_path)
    assert "Pier: hello" in restored.transcript and "G.O.D.: persist me" in restored.transcript
    assert "Saphira-A ONLINE" in restored.status() and "Root SECURE" in restored.status()
    restored.close()
