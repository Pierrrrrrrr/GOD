from pathlib import Path

from tmco.awakening import GodRuntime


runtime = GodRuntime(Path.home() / ".god")
if not runtime.bus.providers:
    raise SystemExit("No intelligence is connected. Start G.O.D. and connect a provider first.")
result = runtime.submit_goal("Return a safe next step for verifying that this model connection works.",
                             importance=0.1, difficulty=0.1)
print(result["next_action"])
