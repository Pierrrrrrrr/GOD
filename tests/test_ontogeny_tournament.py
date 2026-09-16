import json

from tmco.ontogeny.metrics import collective_advantage, pareto_status, recovery_metrics
from tmco.ontogeny.tournament import run


def logical(path):
    data = json.loads((path / "results.json").read_text())
    return data


def test_tournament_is_fair_reproducible_held_out_and_complete(tmp_path):
    first, second, different = tmp_path/"a", tmp_path/"b", tmp_path/"c"
    one = run(42, first); two = run(42, second); other = run(43, different)
    assert one == two and one != other
    assert len(one["scaling"]) == 6 and {row["cell_count"] for row in one["scaling"]} == {8}
    assert [row["hypothesis"] for row in one["results"]] == ["H0", "H1", "H2", "H3", "H4", "H5"]
    budgets = {json.dumps(row["declared_budget"], sort_keys=True) for row in one["results"]}
    assert len(budgets) == 1
    for row in one["results"]:
        metric = row["metrics"]
        assert metric["collective_advantage"] == pytest.approx(metric["task_performance"]-max(
            metric["best_isolated_cell"], metric["independent_ensemble"], metric["fixed_budget_baseline"]))
    manifest = json.loads((first/"manifest.json").read_text())
    required = {"run_id", "seed", "configuration_hash", "hypothesis_version", "task_versions",
        "cell_count", "episode_limit", "tick_limit", "compute_budget", "communication_budget",
        "damage_schedule", "wall_clock_seconds", "operation_counts", "git_commit_sha"}
    assert required <= manifest.keys()
    assert set(manifest["training_seeds"]).isdisjoint(manifest["held_out_seeds"])
    assert manifest["monetary_cost"] == 0 and manifest["external_teacher_calls"] == 0
    assert {item.name for item in first.iterdir()} == {"results.json", "metrics.csv", "summary.md", "manifest.json"}
    assert one["conclusion"] == "NO_CLEAR_WINNER" or one["conclusion"].startswith("M0_1_RESEARCH_LEADER:")


def test_collective_damage_and_pareto_metrics_are_honest():
    assert collective_advantage(.8, .6, .7, .5) == pytest.approx(.1)
    half, recovered = recovery_metrics(.9, .5, [.6, .7, .8]); assert half == 2 and recovered > 0
    rows = [{"hypothesis": "unsafe", "metrics": {"safety_violations": 1,
        "resource_budget_violations": 0, "task_performance": 1., "robustness": 1.,
        "compute_cost": 0., "communication_cost": 0.}},
        {"hypothesis": "safe", "metrics": {"safety_violations": 0,
        "resource_budget_violations": 0, "task_performance": .5, "robustness": .5,
        "compute_cost": 1., "communication_cost": 1.}},
        {"hypothesis": "over-budget", "metrics": {"safety_violations": 0,
        "resource_budget_violations": 1, "task_performance": 1., "robustness": 1.,
        "compute_cost": 1., "communication_cost": 1.}}]
    assert pareto_status(rows) == {"unsafe": "DISQUALIFIED", "over-budget": "DISQUALIFIED",
                                   "safe": "NON_DOMINATED"}


import pytest
