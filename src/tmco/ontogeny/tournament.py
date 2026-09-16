"""Reproducible, zero-network M0-1 tournament for lab-only DigitalCell hypotheses."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from .cell import DigitalCell
from .colony import CellColony
from .genome import DigitalCellGenome
from .graph import AdaptiveGraph
from .hypotheses import HYPOTHESES, Hypothesis
from .metrics import MetricVector, collective_advantage, pareto_status, recovery_metrics, synergy
from .tasks import TASK_VERSIONS, cases
from .types import ResourceBudget


TASKS = tuple(TASK_VERSIONS)


def configuration(quick: bool) -> dict[str, Any]:
    return {"mode": "quick" if quick else "full", "cell_counts": [8] if quick else [8, 16, 32],
            "episodes": 8 if quick else 24, "ticks": 2 if quick else 3,
            "state_dimension": 16, "message_dimension": 8,
            "compute_budget": 4_000_000 if quick else 40_000_000,
            "communication_budget": 25_000 if quick else 250_000,
            "maximum_edges": 64, "maximum_degree": 4, "mutation_opportunities": 32,
            "damage_schedule": [0.1, 0.2, 0.3], "training_seed_offset": 0,
            "held_out_seed_offset": 100_000}


def _budget(config: dict[str, Any], cells: int) -> ResourceBudget:
    return ResourceBudget(cells, min(config["maximum_edges"], cells*4), config["maximum_degree"],
                          config["compute_budget"], config["communication_budget"],
                          config["mutation_opportunities"], 2)


def _colony(hypothesis: Hypothesis, seed: int, count: int, budget: ResourceBudget, lineage: str) -> CellColony:
    genome = DigitalCellGenome.create(seed)
    if not hypothesis.prediction: genome = replace(genome, prediction_learning_rate=0.)
    if not hypothesis.differentiation: genome = replace(genome, inhibition_strength=0.)
    cells = [DigitalCell(genome, lineage, seed*10_000+index) for index in range(count)]
    graph = AdaptiveGraph(count, budget); graph.ring()
    if hypothesis.adaptive_topology and count > 3:
        graph.reset_step()
        try: graph.add(0, count//2, .35)
        except ValueError: pass
    colony = CellColony(cells, graph, budget)
    if hypothesis.differentiation:
        density = [0.]*genome.epigenome_dim
        for cell in cells:
            distribution = cell.phenotype_distribution([.7]*genome.epigenome_dim,
                                                       [value/max(1, count) for value in density])
            cell.phenotype_channel = max(range(len(distribution)), key=lambda index: (distribution[index], -index))
            density[cell.phenotype_channel] += 1
        colony.governor.account(count*genome.epigenome_dim, 0)
    return colony


def _evaluate(hypothesis: Hypothesis, seed: int, count: int, config: dict[str, Any], lineage: str) -> tuple[MetricVector, dict[str, float]]:
    budget = _budget(config, count); colony = _colony(hypothesis, seed, count, budget, lineage)
    task_scores: dict[str, float] = {}; single_scores = []; ensemble_scores = []
    total_correct = held_correct = total = held_total = 0
    for task_index, task in enumerate(TASKS):
        if hypothesis.adaptive_topology and colony.governor.mutations_used < budget.mutation_opportunities:
            colony.graph.reset_step(); edge = (task_index % count, (task_index*3+2) % count)
            if edge[0] != edge[1] and edge not in colony.graph.edges:
                try:
                    colony.graph.add(*edge, .25); colony.governor.mutations_used += 1
                except ValueError:
                    pass
        correct = single_correct = ensemble_correct = 0
        for case in cases(task, seed+task_index, count, config["episodes"]):
            observations = list(case.observations)
            if task == "corrupted_message_resilience":
                for index in range(max(1, count//5)): observations[-1-index] = tuple(
                    -3*value for value in observations[-1-index])
            sensory = [tuple(values)+(0.,)*(16-len(values)) for values in observations]
            sources = {}
            if hypothesis.muf:
                sources = {"goal": [1.]+[0.]*(count-1),
                           "damage": ([.3]+[0.]*(count-1)) if task == "damage_recovery" else [0.]*count}
                if hypothesis.stigmergy:
                    sources["novelty"] = [abs(values[0]) for values in case.observations]
            output = ()
            original_edges = colony.graph.edges
            if task == "communication_scarcity":
                colony.graph.edges = {key: edge for position, (key, edge) in enumerate(sorted(original_edges.items()))
                                      if position % 2 == 0}
            for _ in range(config["ticks"]): output = colony.tick(sensory, sources)
            colony.graph.edges = original_edges
            raw = [values[0] for values in case.observations]
            single_prediction = int(raw[0] >= 0); ensemble_prediction = int(sum(raw) >= 0)
            # All hypotheses use the identical readout. Developmental mechanisms may only
            # alter the numeric colony message reaching it.
            prediction = int((output[0] if output else 0.) >= 0)
            correct += prediction == case.target; single_correct += single_prediction == case.target
            ensemble_correct += ensemble_prediction == case.target; total += 1
        score = correct/config["episodes"]; task_scores[task] = score; total_correct += correct
        single_scores.append(single_correct/config["episodes"]); ensemble_scores.append(ensemble_correct/config["episodes"])
        for case in cases(task, seed+config["held_out_seed_offset"]+task_index,
                          count, config["episodes"]):
            observations = list(case.observations)
            if task == "corrupted_message_resilience":
                for index in range(max(1, count//5)): observations[-1-index] = tuple(
                    -3*value for value in observations[-1-index])
            sensory = [tuple(values)+(0.,)*(16-len(values)) for values in observations]
            sources = {"goal": [1.]+[0.]*(count-1)} if hypothesis.muf else {}
            original_edges = colony.graph.edges
            if task == "communication_scarcity":
                colony.graph.edges = {key: edge for position, (key, edge) in enumerate(sorted(original_edges.items()))
                                      if position % 2 == 0}
            output = ()
            for _ in range(config["ticks"]): output = colony.tick(sensory, sources)
            colony.graph.edges = original_edges
            held_correct += int((output[0] if output else 0.) >= 0) == case.target; held_total += 1
    accuracy = total_correct/max(1, total); best_single = sum(single_scores)/len(single_scores)
    independent = sum(ensemble_scores)/len(ensemble_scores)
    phenotype_distributions = [cell.phenotype_distribution([.8,.6,.4,.2], [.75,.1,.1,.05]) for cell in colony.cells]
    specialization = sum(max(row)-min(row) for row in phenotype_distributions)/len(phenotype_distributions)
    divergence = sum(abs(a-b) for a, b in zip(colony.cells[0].state, colony.cells[-1].state))/16
    probes = cases("damage_recovery", seed+77_000, count, 4)
    def probe() -> float:
        correct = 0
        for case in probes:
            sensory = [tuple(values)+(0.,)*(16-len(values)) for values in case.observations]
            output = colony.tick(sensory, {"damage": ([.3]+[0.]*(count-1)) if hypothesis.muf else [0.]*count})
            correct += int((output[0] if output else 0.) >= 0) == case.target
        return correct/len(probes)
    pre = probe(); half_lives = []; recovered_fractions = []; damage_losses = []
    for fraction in config["damage_schedule"]:
        damaged_nodes = set(range(count-max(1, int(count*fraction)), count))
        saved_edges = dict(colony.graph.edges)
        for index in damaged_nodes: colony.cells[index].sleeping = True
        colony.graph.edges = {key: edge for key, edge in colony.graph.edges.items()
                              if edge.source not in damaged_nodes and edge.target not in damaged_nodes}
        drop = probe(); damage_losses.append(max(0., pre-drop))
        for index in damaged_nodes: colony.cells[index].sleeping = False
        colony.graph.edges = saved_edges
        half_life, recovered = recovery_metrics(pre, drop, [probe() for _ in range(4)])
        half_lives.append(half_life); recovered_fractions.append(recovered)
    half_life = sum(half_lives)/len(half_lives); recovered = sum(recovered_fractions)/len(recovered_fractions)
    cost = colony.governor.compute_used; communication = colony.governor.communication_used
    advantage = collective_advantage(accuracy, best_single, independent, .0)
    metrics = MetricVector(accuracy, accuracy, config["ticks"], cost, communication,
        max(0., 1-sum(damage_losses)/len(damage_losses)), half_life, 1/max(.01, task_scores["rule_shift"]),
        task_scores["distributed_temporal_memory"], held_correct/max(1, held_total), specialization,
        specialization*max(0., advantage), accuracy/max(1, communication), accuracy/max(1, cost),
        specialization/config["episodes"], divergence, divergence*max(0., advantage), 0, 0., advantage,
        synergy(advantage, cost, communication, 1-recovered), best_single, independent, 0., 0)
    return metrics, task_scores


def _git_sha(root: Path) -> str | None:
    git = root / ".git"
    if git.is_file():
        text = git.read_text().strip(); git = (root / text.removeprefix("gitdir: ")).resolve()
    try:
        head = (git / "HEAD").read_text().strip()
        return (git / head.removeprefix("ref: ")).read_text().strip() if head.startswith("ref: ") else head
    except OSError: return None


def run(seed: int, output: Path, *, quick: bool = True) -> dict[str, Any]:
    started = time.monotonic(); config = configuration(quick)
    config_hash = hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    rows = []
    for hypothesis in sorted(HYPOTHESES, key=lambda item: item.id):
        metrics, task_scores = _evaluate(hypothesis, seed, config["cell_counts"][0], config, "Saphira-A")
        twin, twin_tasks = _evaluate(hypothesis, seed+1, config["cell_counts"][0], config, "Saphira-B")
        complementary = (sum(max(task_scores[name], twin_tasks[name]) for name in TASKS)/len(TASKS)
                         - max(sum(task_scores.values())/len(TASKS),
                               sum(twin_tasks.values())/len(TASKS)))
        metrics = replace(metrics, a_b_divergence=abs(metrics.task_performance-twin.task_performance),
                          a_b_complementarity=max(0., complementary))
        rows.append({"hypothesis": hypothesis.id, "name": hypothesis.name,
                     "metrics": metrics.data(), "task_scores": task_scores,
                     "twin_operation_counts": {"compute": twin.compute_cost,
                                               "communication": twin.communication_cost},
                     "declared_budget": asdict(_budget(config, config["cell_counts"][0]))})
    h0 = next(row for row in rows if row["hypothesis"] == "H0")["metrics"]["task_performance"]
    for row in rows:
        metric = row["metrics"]; old = metric["collective_advantage"]
        metric["fixed_budget_baseline"] = h0
        metric["collective_advantage"] = min(old, metric["task_performance"]-h0) if row["hypothesis"] != "H0" else old
        metric["synergy"] += metric["collective_advantage"]-old
    statuses = pareto_status(rows)
    for row in rows: row["selection_status"] = statuses[row["hypothesis"]]
    non_dominated = sorted(key for key, value in statuses.items() if value == "NON_DOMINATED")
    leader = non_dominated[0] if len(non_dominated) == 1 else None
    result = {"run_id": hashlib.sha256(f"{config_hash}:{seed}".encode()).hexdigest()[:16],
              "seed": seed, "configuration_hash": config_hash, "results": rows,
              "scaling": [{"hypothesis": row["hypothesis"], "cell_count": config["cell_counts"][0],
                  "performance": row["metrics"]["task_performance"],
                  "compute": row["metrics"]["compute_cost"],
                  "communication": row["metrics"]["communication_cost"],
                  "synergy": row["metrics"]["synergy"]} for row in rows],
              "conclusion": f"M0_1_RESEARCH_LEADER:{leader}" if leader else "NO_CLEAR_WINNER",
              "lab_only": True}
    if not quick:
        for count in config["cell_counts"][1:]:
            for hypothesis in sorted(HYPOTHESES, key=lambda item: item.id):
                metric, _ = _evaluate(hypothesis, seed, count, config, "Saphira-A")
                result["scaling"].append({"hypothesis": hypothesis.id, "cell_count": count,
                    "performance": metric.task_performance, "compute": metric.compute_cost,
                    "communication": metric.communication_cost, "synergy": metric.synergy})
    output.mkdir(parents=True, exist_ok=True)
    (output / "results.json").write_text(json.dumps(result, sort_keys=True, indent=2), encoding="utf-8")
    fields = ["hypothesis", *MetricVector.__dataclass_fields__]
    with (output / "metrics.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fields); writer.writeheader()
        for row in rows: writer.writerow({"hypothesis": row["hypothesis"], **row["metrics"]})
    manifest = {"run_id": result["run_id"], "seed": seed, "configuration_hash": config_hash,
        "hypothesis_version": "M0-1-v1", "task_versions": TASK_VERSIONS,
        "cell_count": config["cell_counts"], "episode_limit": config["episodes"], "tick_limit": config["ticks"],
        "compute_budget": config["compute_budget"], "communication_budget": config["communication_budget"],
        "damage_schedule": config["damage_schedule"], "training_seeds": [seed+i for i in range(len(TASKS))],
        "held_out_seeds": [seed+config["held_out_seed_offset"]+i for i in range(len(TASKS))],
        "wall_clock_seconds": time.monotonic()-started,
        "operation_counts": {row["hypothesis"]: {"compute": row["metrics"]["compute_cost"],
            "communication": row["metrics"]["communication_cost"],
            "twin_compute": row["twin_operation_counts"]["compute"],
            "twin_communication": row["twin_operation_counts"]["communication"]} for row in rows},
        "git_commit_sha": _git_sha(Path(__file__).resolve().parents[3]), "monetary_cost": 0,
        "external_teacher_calls": 0}
    (output / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2), encoding="utf-8")
    _summary(output / "summary.md", result, config)
    return result


def _summary(path: Path, result: dict[str, Any], config: dict[str, Any]) -> None:
    rows = result["results"]; by_id = {row["hypothesis"]: row for row in rows}
    positive = [row["hypothesis"] for row in rows if row["metrics"]["collective_advantage"] > 0]
    h1, h0 = by_id["H1"]["metrics"], by_id["H0"]["metrics"]
    dominated = [row["hypothesis"] for row in rows if row["selection_status"] == "DOMINATED"]
    text = f"""# M0-1 tournament summary

- Hypotheses tested: {', '.join(row['hypothesis'] for row in rows)} under identical declared budgets.
- Tasks: {', '.join(TASKS)}.
- Budget: {config['cell_counts']} cells, {config['episodes']} episodes/task, {config['ticks']} ticks/case, {config['compute_budget']} compute operations, {config['communication_budget']} communicated values.
- Failures/disqualifications: {', '.join(row['hypothesis'] for row in rows if row['selection_status']=='DISQUALIFIED') or 'none'}.
- Positive collective advantage: {', '.join(positive) or 'none'}.
- Useful specialization emerged: {'yes' if h1['useful_diversity'] > 0 else 'not demonstrated'}; phenotype diversity alone is not sufficient.
- MUF improved organization over H0: {'yes' if h1['task_performance'] > h0['task_performance'] else 'not demonstrated'}.
- Adaptive topology improved held-out performance: {'yes' if by_id['H3']['metrics']['held_out_generalization'] > h0['held_out_generalization'] else 'not demonstrated'}.
- Damage recovery improved over H0: {'yes' if h1['recovery_half_life'] < h0['recovery_half_life'] else 'not demonstrated'}.
- A/B divergence was observed: {'yes' if h1['a_b_divergence'] > 0 else 'no'}; complementarity helped: {'yes' if h1['a_b_complementarity'] > 0 else 'not demonstrated'}.
- Pareto-dominated architectures: {', '.join(dominated) or 'none'}.
- Research conclusion: {result['conclusion']}. Every result remains LAB-ONLY.
- Recursive composition: contract tested separately; no production Saphira integration exists.
- Q8 external-teacher independence remains future work; dependency was fixed at zero because no teacher was called.
- Next falsification experiment: preregister held-out seeds and test whether H1 exceeds H0 on distributed parity and damage recovery across at least 30 seeds at the same operation budgets.
"""
    path.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--quick", action="store_true")
    parser.add_argument("--seed", type=int, default=42); parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv); run(args.seed, args.output, quick=args.quick); return 0


if __name__ == "__main__": raise SystemExit(main())
