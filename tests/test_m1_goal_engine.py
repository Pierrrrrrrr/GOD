from pathlib import Path
import time

from tmco.awakening import GodRuntime
from tmco.embodiment import OutcomeEvaluation, OutcomeEvaluator
from tmco.models import ModelRecord


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
    completed = restored.advance_goal(goal_id)
    assert completed["status"] == "completed"
    restored.close()


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
    blocked = runtime.advance_goal(goal_id)
    assert blocked["status"] == "blocked" and blocked["blocker"] == "STRATEGY"
    assert blocked["current_step"] == "BLOCKED"
    assert len([o for o in runtime.embodiment_store.all("observation")
                if o.get("goal_id") == goal_id and o.get("operation") == "write"]) == 1
    runtime.close()
