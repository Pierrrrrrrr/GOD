from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from tmco.fixtures import (DeterministicCognitionFixture, DeterministicExecutorFixture,
                           DeterministicObservationFixture)
from tmco.system import TMCOSystem


def compact_graph(system: TMCOSystem, colony: str) -> list[dict[str, object]]:
    identity = system.colonies[colony].id
    return [{"source": source.removeprefix(identity + ":"),
             "target": target.removeprefix(identity + ":"), "weight": weight}
            for source, target, weight in system.colonies[colony].graph()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the deterministic TMCO vertical slice")
    parser.add_argument("--state", type=Path, default=Path(".demo-state"))
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    if args.reset:
        shutil.rmtree(args.state, ignore_errors=True)
    cognition = DeterministicCognitionFixture()
    executor = DeterministicExecutorFixture()
    observer = DeterministicObservationFixture()
    organism = TMCOSystem(args.state, cognition, executor=executor,
                          observation_provider=observer)
    before = compact_graph(organism, "Saphira-A")
    goal = organism.submit_goal("characterize an unknown local artifact", ("evidence is persisted",))
    organism.step()
    after = compact_graph(organism, "Saphira-A")
    organism.checkpoint()
    restarted = TMCOSystem(args.state, cognition, executor=executor,
                           observation_provider=observer)
    report = {"goal": goal.description, "status_after_restart": restarted.goals[goal.id].status,
              "colony_identities": {k: v.id for k, v in restarted.colonies.items()},
              "graph_before": before, "graph_after": after,
              "episode_count": len(restarted.memory.episodic),
              "external_effect_count": executor.effect_count,
              "specializations": sorted({n.specialization for n in restarted.colonies["Saphira-A"].neurons.values()}),
              "root_audit_valid": restarted.root.verify_audit()}
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
