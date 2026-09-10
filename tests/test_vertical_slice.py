import asyncio
from pathlib import Path

import pytest

from tmco.buses import ProviderUnavailable
from tmco.fixtures import (DeterministicCognitionFixture, DeterministicExecutorFixture,
                           DeterministicObservationFixture)
from tmco.root import AuthorizationError
from tmco.runtime import Colony
from tmco.system import TMCOSystem
from tmco.types import AssemblyPurpose, ComputeBudget, GoalStatus, WorkspaceItem
from tmco.workspace import GlobalWorkspace


def system(path: Path, executor: DeterministicExecutorFixture | None = None) -> TMCOSystem:
    return TMCOSystem(path, DeterministicCognitionFixture(), secret="test-key",
                      executor=executor or DeterministicExecutorFixture(),
                      observation_provider=DeterministicObservationFixture())


def test_colonies_are_separate_and_cross_graph_edges_are_rejected(tmp_path: Path) -> None:
    organism = system(tmp_path)
    a, b = organism.colonies.values()
    assert a is not b and a.neurons.keys().isdisjoint(b.neurons)
    with pytest.raises(KeyError):
        a.connect(next(iter(a.neurons)), next(iter(b.neurons)), .5)
    a.neurons[next(iter(a.neurons))].local_state["private"] = True
    assert all("private" not in neuron.local_state for neuron in b.neurons.values())


def test_dynamic_rewiring_specialization_and_dormancy() -> None:
    colony = Colony.create("test", 3)
    ids = tuple(colony.neurons)
    colony.disconnect(ids[0], ids[1])
    assert f"{ids[0]}->{ids[1]}" not in colony.synapses
    colony.connect(ids[0], ids[2], .6)
    assert colony.synapses[f"{ids[0]}->{ids[2]}"].weight == .6
    neuron = colony.neurons[ids[1]]
    neuron.specialize("verifier", "new task")
    assert neuron.specialization == "verifier"
    assert neuron.epigenome["specialization_trigger"] == "new task"
    budget = ComputeBudget(3)
    assert budget.consumed == 0  # dormant population costs nothing
    assembly = colony.form_assembly(AssemblyPurpose.VERIFICATION, (ids[1],), budget)
    assert budget.consumed == neuron.metabolic_cost
    colony.dissolve_assembly(assembly.id)
    assert not neuron.active


def test_cells_process_only_addressed_events_asynchronously() -> None:
    colony = Colony.create("async", 2)
    first, dormant = colony.neurons.values()
    budget = ComputeBudget(4)
    assert first.signal("goal", {"id": "g1"})
    assert asyncio.run(first.process_next(budget)) == {"receptor": "goal", "payload": {"id": "g1"}}
    consumed = budget.consumed
    assert asyncio.run(dormant.process_next(budget)) is None
    assert budget.consumed == consumed and not dormant.active


def test_workspace_is_sparse_and_never_automatic_full_sharing() -> None:
    workspace = GlobalWorkspace(salience_threshold=.8, capacity=2)
    assert not workspace.publish(WorkspaceItem("A", "noise", "private state", .2))
    assert workspace.publish(WorkspaceItem("A", "finding", "small result", .9))
    assert len(workspace.items) == 1
    assert workspace.read_for("A") == ()
    assert workspace.read_for("B")[0].content == "small result"


def test_root_rejects_cognitive_self_privilege_and_bus_has_no_fake_fallback(tmp_path: Path) -> None:
    organism = system(tmp_path)
    with pytest.raises(AuthorizationError):
        organism.root.grant("Saphira-A", "Saphira-A", "shell")
    assert "shell" not in organism.root.permissions.get("Saphira-A", set())
    assert organism.root.verify_audit()
    with pytest.raises(ProviderUnavailable):
        organism.model_bus.request("imaginary", {})
    with pytest.raises(ProviderUnavailable):
        organism.body_bus.request("imaginary", "run", {})


def test_architecture_mutation_branches_without_touching_champion(tmp_path: Path) -> None:
    organism = system(tmp_path)
    champion = organism.evolution.champion_architecture.copy()
    candidate = organism.architectural_mutation({"population": 8})
    assert candidate.parent == organism.evolution.champion_id
    assert candidate.architecture["population"] == 8
    assert organism.evolution.champion_architecture == champion


@pytest.mark.parametrize("title", ["catalog lunar samples", "reduce queue latency", "prove theorem X"])
def test_arbitrary_goals_and_no_meaningless_idle_cycle(tmp_path: Path, title: str) -> None:
    organism = system(tmp_path / title.replace(" ", "-"))
    goal = organism.submit_goal(title, ("evidence exists",))
    assert organism.step() and goal.status == GoalStatus.VERIFIED
    event_count = len(organism.store.events())
    assert not organism.step()
    assert len(organism.store.events()) == event_count


def test_full_vertical_slice_survives_restart(tmp_path: Path) -> None:
    organism = system(tmp_path)
    identities = {name: colony.id for name, colony in organism.colonies.items()}
    graph_before = organism.colonies["Saphira-A"].graph()
    goal = organism.submit_goal("map an unfamiliar dependency", ("dependency is recorded",))
    assert organism.step()
    assert graph_before != organism.colonies["Saphira-A"].graph()
    planner = next(n for n in organism.colonies["Saphira-A"].neurons.values()
                   if n.specialization != "generalist")
    organism.checkpoint()

    restored = system(tmp_path)
    assert {name: colony.id for name, colony in restored.colonies.items()} == identities
    assert restored.colonies["Saphira-A"].graph() == organism.colonies["Saphira-A"].graph()
    assert restored.colonies["Saphira-A"].neurons[planner.id].epigenome
    assert restored.goals[goal.id].status == GoalStatus.VERIFIED
    assert restored.memory.episodic[0]["goal_id"] == goal.id
    assert restored.memory.self_model["verified_goals"] == 1
    assert "last_observation" in restored.memory.world_model
    assert restored.workspace.items[0].topic == "verified-result"
    assert restored.root.verify_audit()
    assert any(event["kind"] == "checkpoint" for event in restored.store.events())


def test_checkpoint_and_events_never_contain_root_key(tmp_path: Path) -> None:
    key = "an-explicit-test-signing-key"
    organism = TMCOSystem(tmp_path, DeterministicCognitionFixture(), secret=key,
                          executor=DeterministicExecutorFixture(),
                          observation_provider=DeterministicObservationFixture())
    organism.checkpoint()
    assert key not in (tmp_path / "checkpoint.json").read_text()
    assert key not in (tmp_path / "events.jsonl").read_text()
    assert (tmp_path / "root.key").exists() is False  # injected test keys are never persisted


def test_production_root_key_is_random_and_locally_protected(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    organism = TMCOSystem(first, DeterministicCognitionFixture())
    TMCOSystem(second, DeterministicCognitionFixture())
    organism.checkpoint()
    key = (first / "root.key").read_bytes()
    assert key != (second / "root.key").read_bytes()
    assert len(key) == 32
    assert (first / "root.key").stat().st_mode & 0o777 == 0o600
    assert key not in (first / "checkpoint.json").read_bytes()
    assert key not in (first / "events.jsonl").read_bytes()


def test_copied_checkpoint_cannot_rekey_or_self_grant(tmp_path: Path) -> None:
    source, copied = tmp_path / "source", tmp_path / "copied"
    organism = system(source)
    organism.checkpoint()
    copied.mkdir()
    (copied / "checkpoint.json").write_bytes((source / "checkpoint.json").read_bytes())
    (copied / "events.jsonl").write_bytes((source / "events.jsonl").read_bytes())
    with pytest.raises(AuthorizationError):
        TMCOSystem(copied, DeterministicCognitionFixture())
    with pytest.raises(AuthorizationError):
        TMCOSystem(copied, DeterministicCognitionFixture(), secret="attacker-key")


def test_modified_checkpoint_permissions_are_rejected(tmp_path: Path) -> None:
    import json

    organism = system(tmp_path)
    organism.checkpoint()
    checkpoint = json.loads((tmp_path / "checkpoint.json").read_text())
    checkpoint["state"]["root"]["permissions"]["Saphira-A"] = ["root"]
    (tmp_path / "checkpoint.json").write_text(json.dumps(checkpoint))
    # Remove later state events so recovery must inspect the modified checkpoint.
    (tmp_path / "events.jsonl").write_text("")
    with pytest.raises(AuthorizationError, match="not authorized"):
        system(tmp_path)


def test_execution_requires_explicit_real_boundary(tmp_path: Path) -> None:
    organism = TMCOSystem(tmp_path, DeterministicCognitionFixture(), secret="test-key")
    organism.submit_goal("do external work", ("evidence",))
    with pytest.raises(ProviderUnavailable):
        organism.step()


def test_task_requirements_produce_different_emergent_assemblies(tmp_path: Path) -> None:
    organism = system(tmp_path)
    first = organism.submit_goal("verify a known ledger", ("verified",),
                                 {"required_functions": ["verification"]})
    organism.step()
    second = organism.submit_goal("explore an unknown landscape", ("mapped",),
                                  {"required_functions": ["exploration", "planning"]})
    organism.step()
    first_assemblies = organism.memory.episodic[0]["assemblies"]
    second_assemblies = organism.memory.episodic[1]["assemblies"]
    assert first.status == second.status == GoalStatus.VERIFIED
    assert first_assemblies != second_assemblies
    assert {item["purpose"] for item in second_assemblies} == {"exploration", "planning"}


def test_either_colony_can_emerge_in_any_cognitive_role(tmp_path: Path) -> None:
    organism = system(tmp_path)
    a = organism.colonies["Saphira-A"]
    b = organism.colonies["Saphira-B"]
    a_verifier = next(iter(a.neurons.values()))
    b_planner = next(iter(b.neurons.values()))
    a_verifier.specialize("verification", "competence history")
    a_verifier.verified_contribution = 20
    b_planner.specialize("planning", "competence history")
    b_planner.verified_contribution = 20
    organism.submit_goal("coordinate a novel audit", ("audited",),
                         {"required_functions": ["planning", "verification"]})
    organism.step()
    assignments = {item["purpose"]: item["colony"]
                   for item in organism.memory.episodic[-1]["assemblies"]}
    assert assignments == {"planning": "Saphira-B", "verification": "Saphira-A"}


def test_replay_after_crash_preserves_verification_and_does_not_repeat_effect(tmp_path: Path) -> None:
    executor = DeterministicExecutorFixture()
    organism = system(tmp_path, executor)
    goal = organism.submit_goal("persist this one external effect", ("evidence",))
    with pytest.raises(RuntimeError, match="simulated process death"):
        organism.step(crash_after_commit=True)
    assert executor.effect_count == 1

    restarted = system(tmp_path, executor)
    assert restarted.goals[goal.id].status == GoalStatus.VERIFIED
    assert not restarted.step()
    assert executor.effect_count == 1
    assert restarted.memory.episodic[-1]["action_id"] == restarted.goals[goal.id].action_id
