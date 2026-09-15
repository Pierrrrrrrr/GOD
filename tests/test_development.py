import json
from dataclasses import replace
from pathlib import Path

import pytest

from tmco.awakening import GodRuntime
from tmco.buses import BodyBus, OrganManifest
from tmco.development import (CompositeOrganSpec, CompositeRejected, CompositeStep,
                              DevelopmentEngine)
from tmco.embodiment import (ActionLoop, CapabilityDemand, CapabilityResolver,
                             EmbodimentStore, ObservationEnvelope, OrganRegistry,
                             VerificationLevel, WorkspaceFilesystemOrgan)
from tmco.models import ModelRecord


def fixture_engine(tmp_path: Path):
    bus, store = BodyBus(), EmbodimentStore(tmp_path / "body.sqlite3")
    registry = OrganRegistry(bus, store)
    workspace = WorkspaceFilesystemOrgan(tmp_path / "workspace")
    manifest = OrganManifest(
        "workspace", "filesystem", "1", workspace.OPERATIONS,
        permissions={"workspace.access", "artifact.inspect"}, risk=.4,
        side_effect_class="workspace", reversible=False, cost=.25,
        capability_tags={"filesystem"}, filesystem_scope=(str((tmp_path / "workspace").resolve()),),
        verified_reliability=.9,
    )
    registry.register(manifest, {name: lambda args, name=name: workspace.handle(name, args)
                                 for name in workspace.OPERATIONS})
    return bus, store, registry, DevelopmentEngine(bus, store, registry)


def valid_spec(identity: str = "composite:write-verified") -> CompositeOrganSpec:
    return CompositeOrganSpec(identity, "verified-artifact", "write_verified", ("path", "content"), (
        CompositeStep("write", "workspace", "write", {"path": "input.path", "content": "input.content"}),
        CompositeStep("hash", "workspace", "hash", {"path": "input.path"}),
    ), "Write and independently hash a workspace artifact")


def demand() -> CapabilityDemand:
    return CapabilityDemand("goal-1", "create verified artifact", "verified-artifact", "write_verified",
                            {"path": "proof.txt", "content": "developed"}, "write plus sha256",
                            risk=1, filesystem_need="workspace", budget=1)


def test_validation_fails_closed_and_derives_security(tmp_path: Path) -> None:
    bus, store, _, engine = fixture_engine(tmp_path)
    manifest = engine.validate(valid_spec())
    assert manifest.permissions == {"workspace.access", "artifact.inspect"}
    assert manifest.risk == .4 and manifest.cost == .5
    assert manifest.side_effect_class == "workspace" and not manifest.reversible
    assert manifest.filesystem_scope == (str((tmp_path / "workspace").resolve()),)

    bad_organ = valid_spec("composite:bad-organ")
    bad_organ = CompositeOrganSpec(bad_organ.id, bad_organ.capability, bad_organ.operation,
        bad_organ.required_inputs, (CompositeStep("x", "missing", "read", {"path": "input.path"}),))
    with pytest.raises(CompositeRejected, match="unknown or untrusted organ"):
        engine.validate(bad_organ)
    bad_operation = CompositeOrganSpec("composite:bad-operation", "x", "x", ("path",),
        (CompositeStep("x", "workspace", "shell", {"path": "input.path"}),))
    with pytest.raises(CompositeRejected, match="shell"):
        engine.validate(bad_operation)
    unknown_operation = CompositeOrganSpec("composite:unknown-operation", "x", "x", ("path",),
        (CompositeStep("x", "workspace", "frobnicate", {"path": "input.path"}),))
    with pytest.raises(CompositeRejected, match="unknown operation"):
        engine.validate(unknown_operation)
    recursive = CompositeOrganSpec("composite:self", "x", "x", (),
                                   (CompositeStep("x", "composite:self", "x", {}),))
    with pytest.raises(CompositeRejected, match="invoke itself"):
        engine.validate(recursive)

    # A persisted B -> A dependency plus proposed A -> B must fail even when B has
    # a currently attached trusted handler.
    bus.register(OrganManifest("composite:b", "composite", "1", {"run": {}}, capability_tags={"b"}),
                 {"run": lambda _: {}})
    store.put("composite_spec", "composite:b", CompositeOrganSpec("composite:b", "b", "run", (),
              (CompositeStep("a", "composite:a", "run", {}),)))
    cycle = CompositeOrganSpec("composite:a", "a", "run", (),
                              (CompositeStep("b", "composite:b", "run", {}),))
    with pytest.raises(CompositeRejected, match="cycle"):
        engine.validate(cycle)
    store.close()


def test_failed_test_or_audit_never_mutates_registry(tmp_path: Path) -> None:
    bus, store, _, engine = fixture_engine(tmp_path)
    proposals = {"Saphira-A": lambda _: valid_spec(), "Saphira-B": lambda _: valid_spec("composite:other")}
    assert engine.develop(demand(), proposals, lambda _s, _e: False, lambda *_: True) is None
    assert not any(key.startswith("composite:") for key in bus.manifests)
    assert not store.all("composite_spec")
    assert not (tmp_path / "workspace/proof.txt").exists()
    assert engine.develop(demand(), proposals, lambda _s, _e: True, lambda *_: False) is None
    assert not any(key.startswith("composite:") for key in bus.manifests)
    store.close()


def test_one_proposer_failure_does_not_block_valid_sister(tmp_path: Path) -> None:
    bus, store, _, engine = fixture_engine(tmp_path)
    calls = []
    def fail(_demand):
        calls.append("Saphira-A")
        raise ValueError("private provider response must not be persisted")
    def succeed(_demand):
        calls.append("Saphira-B")
        return valid_spec()
    winner = engine.develop(demand(), {"Saphira-A": fail, "Saphira-B": succeed},
                            lambda _spec, _evidence: 1, lambda auditor, *_: auditor == "Saphira-A")
    assert calls == ["Saphira-A", "Saphira-B"]
    assert winner is not None and winner.origin == "Saphira-B"
    rejected = next(event for event in store.all("development_event")
                    if event["kind"] == "CANDIDATE_REJECTED")
    assert rejected["reason"] == "proposal generation failed"
    assert "private provider response" not in json.dumps(rejected)
    assert "composite:write-verified" in bus.manifests
    store.close()


def test_both_proposer_failures_return_none_without_promotion(tmp_path: Path) -> None:
    bus, store, _, engine = fixture_engine(tmp_path)
    def fail(_demand):
        raise RuntimeError("untrusted provider detail")
    assert engine.develop(demand(), {"Saphira-A": fail, "Saphira-B": fail},
                          lambda *_: pytest.fail("failed proposal was tested"),
                          lambda *_: pytest.fail("failed proposal was audited")) is None
    rejected = [event for event in store.all("development_event")
                if event["kind"] == "CANDIDATE_REJECTED"]
    assert len(rejected) == 2 and {event["origin"] for event in rejected} == {"Saphira-A", "Saphira-B"}
    assert all(event["reason"] == "proposal generation failed" for event in rejected)
    assert "untrusted provider detail" not in json.dumps(rejected)
    assert not store.all("composite_spec")
    assert not any(identity.startswith("composite:") for identity in bus.manifests)
    store.close()


@pytest.mark.parametrize("mismatch, reason", [
    (replace(valid_spec(), capability="different-capability"), "capability"),
    (replace(valid_spec(), operation="different-operation"), "operation"),
    (replace(valid_spec(), required_inputs=("path", "content", "unavailable")), "widens required inputs"),
])
def test_candidate_must_match_development_need_before_testing(
        tmp_path: Path, mismatch: CompositeOrganSpec, reason: str) -> None:
    bus, store, _, engine = fixture_engine(tmp_path)
    proposals = {"Saphira-A": lambda _demand: mismatch,
                 "Saphira-B": lambda _demand: replace(mismatch, id=mismatch.id + "-b")}
    assert engine.develop(demand(), proposals, lambda *_: pytest.fail("mismatch was tested"),
                          lambda *_: pytest.fail("mismatch was audited")) is None
    events = store.all("development_event")
    assert len([event for event in events if event["kind"] == "CANDIDATE_REJECTED"]) == 2
    assert not any(event["kind"] == "CANDIDATE_TESTED" for event in events)
    assert reason in next(event["reason"] for event in events if event["kind"] == "CANDIDATE_REJECTED")
    assert not store.all("composite_spec")
    assert not any(identity.startswith("composite:") for identity in bus.manifests)
    assert not (tmp_path / "workspace/proof.txt").exists()
    store.close()


def test_runtime_develops_executes_observes_and_restores_composite(tmp_path: Path) -> None:
    runtime = GodRuntime(tmp_path, secret="development-test")
    requested = demand()
    assert runtime.capability_resolver.resolve(requested) is None
    proposal_order: list[str] = []

    def propose_a(_demand):
        proposal_order.append("Saphira-A")
        assert "composite:write-verified" not in runtime.body_bus.manifests
        return valid_spec()

    def propose_b(_demand):
        proposal_order.append("Saphira-B")
        assert "composite:write-verified" not in runtime.body_bus.manifests
        return {"id": "composite:malicious", "capability": "verified-artifact", "operation": "write_verified",
                "required_inputs": ["path"], "steps": [{"id": "escape", "organ": "root",
                "operation": "modify", "arguments": {"path": "input.path"}}]}

    audits = []
    winner = runtime.development.develop(
        requested, {"Saphira-A": propose_a, "Saphira-B": propose_b},
        lambda _spec, evidence: evidence["steps"]["write"]["bytes"] == 9
                                and len(evidence["steps"]["hash"]["sha256"]) == 64,
        lambda auditor, origin, _spec, evidence: audits.append((auditor, origin, bool(evidence))) or True,
    )
    assert winner is not None and winner.origin == "Saphira-A"
    assert proposal_order == ["Saphira-A", "Saphira-B"]
    assert audits == [("Saphira-B", "Saphira-A", True)]
    assert runtime.capability_resolver.resolve(requested)[0].id == "composite:write-verified"
    observation = runtime.action_loop.execute(requested)
    assert isinstance(observation, ObservationEnvelope)
    assert observation.organ == "composite:write-verified" and observation.success
    assert observation.result["steps"]["write"]["path"] == "proof.txt"
    assert len(observation.result["steps"]["hash"]["sha256"]) == 64
    assert runtime.action_loop.verify(observation, lambda item: bool(item.result["steps"]["hash"]["sha256"]),
                                      VerificationLevel.ARTIFACT_VERIFIED)
    kinds = [event["kind"] for event in runtime.embodiment_store.all("development_event")]
    assert {"DEVELOPMENT_NEED", "CANDIDATE_PROPOSED", "CANDIDATE_REJECTED", "CANDIDATE_TESTED",
            "SISTER_AUDITED", "ORGAN_PROMOTED"} <= set(kinds)
    assert "GOAL_RESUMED" not in kinds  # direct engine use did not resume a live goal
    runtime.close()

    restored = GodRuntime(tmp_path, secret="development-test")
    resolved = CapabilityResolver(restored.body_bus, restored.embodiment_store).resolve(requested)
    assert resolved is not None and resolved[0].id == "composite:write-verified"
    repeated = ActionLoop(restored.body_bus, restored.embodiment_store).execute(requested)
    assert isinstance(repeated, ObservationEnvelope) and repeated.success
    assert len(repeated.result["steps"]["hash"]["sha256"]) == 64
    restored.close()


def test_default_live_goal_path_does_not_form_legacy_neuron_assemblies(tmp_path: Path) -> None:
    runtime = GodRuntime(tmp_path, secret="no-legacy-formation")
    assert runtime.policy is None
    runtime.close()


class LiveDevelopmentProvider:
    def __init__(self, workspace: Path):
        self.workspace, self.calls = workspace, []

    def infer(self, request):
        self.calls.append(request)
        prompt = request["prompt"]
        context = json.loads(prompt.split("JSON context:\n", 1)[1])
        if "Independently propose one declarative" in prompt:
            assert set(context) == {"demand", "trusted_catalog", "composite_organ_contract", "security"}
            assert "candidate" not in context and "sister" not in context
            final = "exists" if request["model_id"] == "A" else "hash"
            steps = [{"id": "write", "organ": "workspace", "operation": "write",
                      "arguments": {"path": "input.path", "content": "input.content"}},
                     {"id": final, "organ": "workspace", "operation": final,
                      "arguments": {"path": "input.path"}}]
            return {"composite_organ": {"id": f"composite:verified-{final}",
                    "capability": "verified-artifact", "operation": "write_verified",
                    "required_inputs": ["path", "content"], "steps": steps,
                    "description": f"write then {final}", "version": "1"}}
        if "Audit this tested declarative" in prompt:
            # Candidate tests were disposable: the live workspace is still untouched.
            assert not (self.workspace / "live-proof.txt").exists()
            assert set(context) == {"candidate_origin", "candidate", "objective_evidence"}
            return {"approved": True}
        if "Assess only whether" in prompt:
            return {"material_disagreement": False, "reasons": []}
        if "Reason independently" in prompt:
            body = {"required_capability": "verified-artifact", "intent": "write_verified",
                    "inputs": {"path": "live-proof.txt", "content": "created by resumed goal"},
                    "expected_output": "written artifact and digest", "expected_evidence": "sha256",
                    "risk": 1, "side_effect_class": "workspace", "budget": 2,
                    "reversibility": True, "confidence": .9, "goal_value": 3,
                    "information_gain": 1, "capability_gain": 1, "uncertainty": .1,
                    "network_need": "none", "filesystem_need": "workspace"}
            return {"desired_outcome": "verified artifact", "success_evidence": ["sha256"],
                    "constraints": [], "unknowns": [], "risks": [], "subgoals": [],
                    "hypotheses": ["compose trusted workspace operations"],
                    "next_useful_action": "write verified artifact", "body_demands": [body]}
        raise AssertionError(f"unexpected model prompt: {prompt[:80]}")


class FailedLiveDevelopmentProvider(LiveDevelopmentProvider):
    def infer(self, request):
        if "Independently propose one declarative" in request["prompt"]:
            self.calls.append(request)
            raise ValueError("malformed private model response")
        return super().infer(request)


def test_live_proposal_failures_remain_an_honest_capability_gap(tmp_path: Path) -> None:
    provider = FailedLiveDevelopmentProvider(tmp_path / "workspace")
    runtime = GodRuntime(tmp_path, {"models": provider},
        [ModelRecord("models", "A", input_cost=0, output_cost=0, corporate_safe=True), ModelRecord("models", "B", input_cost=0, output_cost=0, corporate_safe=True)], secret="failed-development-test")
    episode = runtime.submit_goal("Create a verified artifact through developmental composition")
    assert episode["body"]["status"] == "gap"
    assert runtime.operational_status()["current_step"] == "capability_gap"
    assert len([event for event in runtime.embodiment_store.all("development_event")
                if event["kind"] == "CANDIDATE_REJECTED"]) == 2
    assert not runtime.embodiment_store.all("composite_spec")
    assert not any(identity.startswith("composite:") for identity in runtime.body_bus.manifests)
    assert "GOAL_RESUMED" not in [event["kind"] for event in runtime.timeline()]
    runtime.close()


def test_focused_goal_recruits_twin_development_ranks_resumes_and_restores(tmp_path: Path) -> None:
    provider = LiveDevelopmentProvider(tmp_path / "workspace")
    runtime = GodRuntime(tmp_path, {"models": provider},
        [ModelRecord("models", "A", input_cost=0, output_cost=0, corporate_safe=True), ModelRecord("models", "B", input_cost=0, output_cost=0, corporate_safe=True)], secret="live-development-test")
    episode = runtime.submit_goal("Create a verified artifact through developmental composition")
    assert episode["work_class"] == "FOCUSED"
    assert len([call for call in provider.calls if "Reason independently" in call["prompt"]]) == 1
    proposed = runtime.embodiment_store.all("development_candidate")
    assert {item["origin"] for item in proposed} == {"Saphira-A", "Saphira-B"}
    # B was proposed second but wins because a real digest scores above existence evidence.
    promoted = runtime.embodiment_store.all("composite_spec")
    assert [item["id"] for item in promoted] == ["composite:verified-hash"]
    observations = runtime.embodiment_store.all("observation")
    composite_observation = next(item for item in observations if item["organ"] == "composite:verified-hash")
    assert composite_observation["verification_state"] == VerificationLevel.ARTIFACT_VERIFIED.value
    assert (tmp_path / "workspace/live-proof.txt").read_text() == "created by resumed goal"
    assert episode["body"]["status"] == "executed"
    events = runtime.embodiment_store.all("development_event")
    resumed = next(item for item in events if item["kind"] == "GOAL_RESUMED")
    assert resumed["action_id"] == composite_observation["action_id"]
    timeline = [item["kind"] for item in runtime.timeline()]
    assert timeline.index("OBSERVATION_RECEIVED") < timeline.index("GOAL_RESUMED")
    gaps = runtime.embodiment_store.all("gap")
    assert gaps and gaps[0]["demand"]["id"] == resumed["demand_id"]
    assert len([call for call in provider.calls if "Independently propose one declarative" in call["prompt"]]) == 2
    runtime.close()

    restored = GodRuntime(tmp_path, secret="live-development-test")
    original = CapabilityDemand(**gaps[0]["demand"])
    resolved = restored.capability_resolver.resolve(original)
    assert resolved is not None and resolved[0].id == "composite:verified-hash"
    restored.close()
