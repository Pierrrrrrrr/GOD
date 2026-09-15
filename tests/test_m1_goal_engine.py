from pathlib import Path
import time
import hashlib
import json
from dataclasses import asdict, replace

from tmco.awakening import GoalSuccessVerification, GodRuntime
from tmco.embodiment import OutcomeEvaluation, OutcomeEvaluator
from tmco.models import ModelRecord
from tmco.capabilities import CapabilityRequest


class GoalProvider:
    def __init__(self):
        self.advance_contexts = []

    def infer(self, request):
        prompt = request["prompt"]
        if "Assess only whether" in prompt:
            return {"material_disagreement": False, "reasons": []}
        if "compact GoalBrief" in prompt:
            self.advance_contexts.append(prompt)
            if "content_hash" not in prompt:
                return {"next_useful_action": "write a bounded artifact", "completion_requested": False,
                        "uncertainty": .3, "risk": .1, "blocker": None,
                        "body_demands": [{"required_capability": "filesystem", "intent": "write",
                          "inputs": {"path": "m1-proof.txt", "content": "verified first step"},
                          "expected_output": "artifact", "expected_evidence": "hash", "risk": 0,
                          "side_effect_class": "workspace", "budget": 0, "reversibility": True,
                          "confidence": .8, "goal_value": 1, "information_gain": .5,
                          "capability_gain": 0, "uncertainty": .2, "network_need": "none",
                          "filesystem_need": "workspace"}]}
            return {"next_useful_action": "request verified completion", "completion_requested": True,
                    "uncertainty": 0, "risk": 0, "blocker": None, "body_demands": []}
        return {"desired_outcome": "verified artifact", "success_evidence": ["outcome evaluation"],
                "constraints": ["zero cost"], "unknowns": [], "risks": [], "subgoals": ["write"],
                "hypotheses": ["bounded write"], "next_useful_action": "plan", "body_demands": []}


def make_runtime(path: Path, provider: GoalProvider) -> GodRuntime:
    return GodRuntime(path, {"local": provider},
        [ModelRecord("local", "free", input_cost=0, output_cost=0, privacy="local")], secret="m1")


def test_multistep_goal_restart_exact_continuity_and_true_completion(tmp_path: Path) -> None:
    first_provider = GoalProvider()
    runtime = make_runtime(tmp_path, first_provider)
    episode = runtime.submit_goal("Create a small verified proof artifact", important=False)
    goal_id = episode["goal_id"]
    step = runtime.advance_goal(goal_id)
    assert step["step_count"] == 2
    assert (tmp_path / "workspace" / "m1-proof.txt").read_text() == "verified first step"
    observation = next(o for o in runtime.embodiment_store.all("observation")
                       if o.get("goal_id") == goal_id and o.get("operation") == "write")
    action_id = observation["action_id"]
    runtime.close()

    second_provider = GoalProvider()
    restored = make_runtime(tmp_path, second_provider)
    continued = restored.advance_goal(goal_id)
    assert continued["step_count"] == 3 and continued["completion_requested"] is True
    observations = [o for o in restored.embodiment_store.all("observation")
                    if o.get("goal_id") == goal_id and o.get("operation") == "write"]
    assert len(observations) == 1
    evaluation = OutcomeEvaluation(action_id, OutcomeEvaluator.OWNER.value,
                                   ("owner-confirmed-artifact",), True, "accepted", time.time(), "meets goal")
    assert restored.evaluate_outcome(evaluation)
    candidate = restored.advance_goal(goal_id)
    assert candidate["status"] != "completed"
    goal_check = GoalSuccessVerification(goal_id, "OWNER", ("credible evidence of progress",),
        ("owner-goal-verification",), True, time.time(), "the complete objective is satisfied")
    digest = hashlib.sha256(json.dumps(asdict(goal_check), sort_keys=True,
                            separators=(",", ":")).encode()).hexdigest()
    request = CapabilityRequest(restored.organism.root.owner, "goal-verification", "OWNER",
        "verify stable owner goal", digest, "goal-success-gate", "goal-verification", goal_id,
        allowed_submitted_data=goal_check.evidence_refs, maximum_cost=0)
    request_id = restored.owner_capabilities.request(request)
    capability = restored.owner_capabilities.decide(
        restored.owner_capabilities.owner_control().decide(request_id, True))
    assert capability is not None
    import pytest
    with pytest.raises(PermissionError):
        restored.verify_goal_success(replace(goal_check, reason="altered"), capability)
    assert restored.verify_goal_success(goal_check, capability)
    restored.close()
    final_runtime = make_runtime(tmp_path, GoalProvider())
    completed = final_runtime.advance_goal(goal_id)
    assert completed["status"] == "completed"
    final_runtime.close()


def test_goal_max_steps_is_a_hard_bound(tmp_path: Path) -> None:
    provider = GoalProvider(); runtime = make_runtime(tmp_path, provider)
    goal_id = runtime.submit_goal("Create a bounded proof", important=False)["goal_id"]
    result = runtime.run_goal(goal_id, max_steps=1)
    assert result["status"] == "budget_exhausted"
    assert len(provider.advance_contexts) == 1
    runtime.close()


def test_negative_verified_outcome_replans_without_trusted_learning(tmp_path: Path) -> None:
    provider = GoalProvider(); runtime = make_runtime(tmp_path, provider)
    goal_id = runtime.submit_goal("Create a proof that may fail", important=False)["goal_id"]
    runtime.advance_goal(goal_id)
    observation = next(o for o in runtime.embodiment_store.all("observation")
                       if o.get("goal_id") == goal_id and o.get("operation") == "write")
    before = runtime.records["local:free"].quality_observations
    evaluation = OutcomeEvaluation(observation["action_id"], OutcomeEvaluator.OWNER.value,
        ("owner-negative",), False, "failed", time.time(), "did not satisfy objective")
    assert runtime.evaluate_outcome(evaluation) is False
    state = runtime.store.rows("SELECT state FROM goals WHERE id=?", (goal_id,))[0]["state"]
    import json
    state = json.loads(state)
    assert state["current_step"] == "REPLAN" and state["blocker"] == "STRATEGY"
    assert runtime.records["local:free"].quality_observations == before
    runtime.close()


def test_uncertainty_recruits_twins_without_replaying_verified_action(tmp_path: Path) -> None:
    provider = GoalProvider(); runtime = make_runtime(tmp_path, provider)
    goal_id = runtime.submit_goal("Create a repeated bounded proof", important=False)["goal_id"]
    runtime.advance_goal(goal_id)
    # Force a persisted trigger exactly as a high-uncertainty prior step would.
    row = runtime.store.rows("SELECT state FROM goals WHERE id=?", (goal_id,))[0]
    import json
    state = json.loads(row["state"]); state["escalate_twin"] = True
    runtime.store.put("goals", goal_id, state)
    runtime.advance_goal(goal_id)
    event = [e for e in runtime.timeline() if e["kind"] == "GOAL_ADVANCED"][-1]
    assert event["state"]["twin_recruited"] is True
    assert len([o for o in runtime.embodiment_store.all("observation")
                if o.get("goal_id") == goal_id and o.get("operation") == "write"]) == 1
    runtime.close()


def test_equivalent_actions_escalate_then_block_honestly(tmp_path: Path) -> None:
    class Repeating(GoalProvider):
        def infer(self, request):
            if "compact GoalBrief" not in request["prompt"]:
                return super().infer(request)
            self.advance_contexts.append(request["prompt"])
            return {"next_useful_action": "repeat", "completion_requested": False,
                    "uncertainty": .8, "risk": 0, "blocker": "STRATEGY",
                    "body_demands": [{"required_capability": "filesystem", "intent": "write",
                      "inputs": {"path": "repeat.txt", "content": "same"}, "expected_output": "artifact",
                      "expected_evidence": "hash", "risk": 0, "side_effect_class": "workspace",
                      "budget": 0, "reversibility": True, "confidence": .5, "goal_value": 1,
                      "information_gain": 0, "capability_gain": 0, "uncertainty": .8,
                      "network_need": "none", "filesystem_need": "workspace"}]}
    provider = Repeating(); runtime = make_runtime(tmp_path, provider)
    goal_id = runtime.submit_goal("Test repeated strategy", important=False)["goal_id"]
    runtime.advance_goal(goal_id)
    runtime.advance_goal(goal_id)
    runtime.advance_goal(goal_id)
    runtime.advance_goal(goal_id)
    blocked = runtime.advance_goal(goal_id)
    assert blocked["status"] == "blocked" and blocked["blocker"] == "STRATEGY"
    assert blocked["current_step"] == "BLOCKED"
    assert len([o for o in runtime.embodiment_store.all("observation")
                if o.get("goal_id") == goal_id and o.get("operation") == "write"]) == 1
    runtime.close()


def test_initial_action_ledger_prevents_restart_reexecution(tmp_path: Path) -> None:
    class InitialRepeating(GoalProvider):
        demand = {"required_capability": "filesystem", "intent": "write",
            "inputs": {"path": "initial-once.txt", "content": "once"}, "expected_output": "artifact",
            "expected_evidence": "hash", "risk": 0, "side_effect_class": "workspace", "budget": 0,
            "reversibility": True, "confidence": .8, "goal_value": 1, "information_gain": .5,
            "capability_gain": 0, "uncertainty": .2, "network_need": "none", "filesystem_need": "workspace"}
        def infer(self, request):
            result = super().infer(request)
            if "compact GoalBrief" not in request["prompt"]:
                result["body_demands"] = [self.demand]
            elif isinstance(result, dict):
                result["body_demands"] = [self.demand]
            return result
    provider = InitialRepeating(); runtime = make_runtime(tmp_path, provider)
    goal_id = runtime.submit_goal("Write one initial durable artifact", important=False)["goal_id"]
    writes = [o for o in runtime.embodiment_store.all("observation") if o.get("operation") == "write"]
    assert len(writes) == 1
    runtime.close()
    restored = make_runtime(tmp_path, InitialRepeating())
    state = restored.advance_goal(goal_id)
    writes = [o for o in restored.embodiment_store.all("observation") if o.get("operation") == "write"]
    assert len(writes) == 1
    assert next(iter(state["action_ledger"].values()))["status"] == "VERIFIED"
    restored.close()


def test_twin_agree_complementary_and_conflict_semantics(tmp_path: Path) -> None:
    from tmco.embodiment import CapabilityDemand
    runtime = make_runtime(tmp_path, GoalProvider())
    views = {"Saphira-A": {}, "Saphira-B": {}}
    def candidate(intent, value=1, risk=0, reversible=True):
        demand = CapabilityDemand("g", "t", "filesystem", intent, {"path": intent}, "out",
                                  risk=risk, side_effects="workspace", reversible=reversible)
        return (value, demand, {})
    same = candidate("write")
    relation, selected = runtime._twin_decision([same, same], views)
    assert relation == "AGREE" and len(selected) == 1
    relation, selected = runtime._twin_decision([candidate("write"), candidate("hash")], views)
    assert relation == "COMPLEMENTARY" and len(selected) == 2
    relation, selected = runtime._twin_decision([candidate("write", risk=.8), candidate("delete", risk=.9)], views)
    assert relation == "CONFLICT" and len(selected) == 1
    runtime.close()


def test_same_step_twin_duplicate_is_consensus_not_stagnation(tmp_path: Path) -> None:
    class Consensus(GoalProvider):
        def infer(self, request):
            if "compact GoalBrief" not in request["prompt"]:
                return super().infer(request)
            return {"next_useful_action": "agree", "completion_requested": False,
                "uncertainty": 0, "risk": 0, "blocker": None,
                "body_demands": [{"required_capability": "filesystem", "intent": "write",
                  "inputs": {"path": "consensus.txt", "content": "one"}, "expected_output": "artifact",
                  "expected_evidence": "hash", "risk": 0, "side_effect_class": "workspace", "budget": 0,
                  "reversibility": True, "confidence": .8, "goal_value": 1, "information_gain": .5,
                  "capability_gain": 0, "uncertainty": 0, "network_need": "none", "filesystem_need": "workspace"}]}
    runtime = make_runtime(tmp_path, Consensus())
    goal_id = runtime.submit_goal("Test twin consensus", important=False)["goal_id"]
    import json
    state = json.loads(runtime.store.rows("SELECT state FROM goals WHERE id=?", (goal_id,))[0]["state"])
    state["escalate_twin"] = True; runtime.store.put("goals", goal_id, state)
    advanced = runtime.advance_goal(goal_id)
    assert advanced["twin_decision"] == "AGREE"
    assert advanced["stagnation_count"] == 0
    assert len([o for o in runtime.embodiment_store.all("observation") if o.get("operation") == "write"]) == 1
    runtime.close()
