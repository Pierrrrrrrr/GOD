from __future__ import annotations

import math
from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class MetricVector:
    task_performance: float; accuracy: float; latency: float
    compute_cost: float; communication_cost: float; robustness: float
    recovery_half_life: float; adaptation_latency: float; memory_retention: float
    held_out_generalization: float; specialization: float; useful_diversity: float
    communication_efficiency: float; compute_efficiency: float; developmental_velocity: float
    a_b_divergence: float; a_b_complementarity: float; safety_violations: int
    external_teacher_dependency: float; collective_advantage: float; synergy: float
    best_isolated_cell: float; independent_ensemble: float; fixed_budget_baseline: float
    resource_budget_violations: int = 0

    def data(self) -> dict[str, float | int]: return asdict(self)


def collective_advantage(colony: float, best_single: float, independent_ensemble: float,
                         fixed_budget_baseline: float) -> float:
    return colony-max(best_single, independent_ensemble, fixed_budget_baseline)


def synergy(advantage: float, compute_delta: float, communication: float, fragility: float,
            *, compute_penalty: float = .000001, communication_penalty: float = .00001) -> float:
    return advantage-compute_penalty*max(0., compute_delta)-communication_penalty*communication-.1*fragility


def recovery_metrics(pre: float, dropped: float, recovered: list[float]) -> tuple[float, float]:
    loss = max(0., pre-dropped)
    if loss == 0: return 0., 1.
    threshold = dropped+.5*loss
    half = next((index+1 for index, value in enumerate(recovered) if value >= threshold), math.inf)
    fraction = max(0., min(1., (recovered[-1]-dropped)/loss)) if recovered else 0.
    return float(half), fraction


def pareto_status(rows: list[dict[str, object]]) -> dict[str, str]:
    eligible = [row for row in rows if row["metrics"]["safety_violations"] == 0
                and row["metrics"]["resource_budget_violations"] == 0]
    status = {row["hypothesis"]: "DISQUALIFIED" for row in rows if row not in eligible}
    for row in eligible:
        metric = row["metrics"]
        dominated = any(other is not row and
            other["metrics"]["task_performance"] >= metric["task_performance"] and
            other["metrics"]["robustness"] >= metric["robustness"] and
            other["metrics"]["compute_cost"] <= metric["compute_cost"] and
            other["metrics"]["communication_cost"] <= metric["communication_cost"] and
            any((other["metrics"][key] != metric[key]) for key in
                ("task_performance", "robustness", "compute_cost", "communication_cost")) for other in eligible)
        status[row["hypothesis"]] = "DOMINATED" if dominated else "NON_DOMINATED"
    return status
