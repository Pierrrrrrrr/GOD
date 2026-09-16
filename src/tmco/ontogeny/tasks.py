from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TaskCase:
    observations: tuple[tuple[float, ...], ...]
    target: int


TASK_VERSIONS = {name: "1" for name in ("distributed_parity", "noisy_sensor_fusion",
    "multi_stage_transformation", "distributed_temporal_memory", "damage_recovery", "rule_shift",
    "communication_scarcity", "corrupted_message_resilience")}


def cases(task: str, seed: int, cells: int, episodes: int) -> tuple[TaskCase, ...]:
    rng = random.Random(f"{task}:{seed}"); result = []
    for episode in range(episodes):
        if task == "distributed_parity":
            bits = [rng.randrange(2) for _ in range(cells)]
            observations = tuple(((bit*2-1),) for bit in bits); target = sum(bits) % 2
        elif task == "noisy_sensor_fusion":
            target = rng.randrange(2); center = target*2-1
            observations = tuple(((center+rng.uniform(-1.4, 1.4)),) for _ in range(cells))
        elif task == "multi_stage_transformation":
            a, b = rng.randrange(2), rng.randrange(2); target = (a ^ b) ^ (episode % 2)
            observations = tuple((((a*2-1) if index % 2 == 0 else (b*2-1)), (episode%2)*2-1)
                                 for index in range(cells))
        elif task == "distributed_temporal_memory":
            target = rng.randrange(2); observations = tuple((((target*2-1) if index == episode%cells else 0.),)
                                                            for index in range(cells))
        elif task == "rule_shift":
            bit = rng.randrange(2); shifted = episode >= episodes//2; target = bit ^ shifted
            observations = tuple((bit*2-1, float(shifted)) for _ in range(cells))
        else:
            target = rng.randrange(2); center = target*2-1
            observations = tuple(((center+rng.uniform(-.8, .8)),) for _ in range(cells))
        result.append(TaskCase(observations, target))
    return tuple(result)
