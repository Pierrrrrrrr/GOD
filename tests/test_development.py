from pathlib import Path

import pytest

from tmco.awakening import GodRuntime
from tmco.buses import BodyBus, OrganManifest
from tmco.development import (CompositeOrganSpec, CompositeRejected, CompositeStep,
                              DevelopmentEngine)
from tmco.embodiment import (ActionLoop, CapabilityDemand, CapabilityResolver,
                             EmbodimentStore, ObservationEnvelope, OrganRegistry,
                             VerificationLevel, WorkspaceFilesystemOrgan)


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
    assert engine.develop(demand(), proposals, lambda _s, _e: True, lambda *_: False) is None
    assert not any(key.startswith("composite:") for key in bus.manifests)
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
    winner = runtime.develop_capability(
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
            "SISTER_AUDITED", "ORGAN_PROMOTED", "GOAL_RESUMED"} <= set(kinds)
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
