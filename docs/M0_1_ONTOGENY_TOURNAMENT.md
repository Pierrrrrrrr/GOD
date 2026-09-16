# M0-1 Digital Ontogeny tournament

## Hypotheses and fair evaluation

The lab compares: H0 fixed simple graph; H1 APGC + developmental genome + MUF; H2
neural-cellular-automata-like fixed topology; H3 bounded evolving-topology/NEAT-like; H4
stigmergic developmental cells; and H5 a simplified active-inference-like predictive baseline.
H3 is not NEAT and H5 is not a full Free Energy Principle implementation. All remain lab-only.

Tasks are distributed parity, noisy sensor fusion, multi-stage transformation, distributed
temporal memory, damage recovery, rule shift, communication scarcity, and corrupted simulated
messages. Cells receive local fragments, not the global answer. Training and held-out seeds differ.
Each hypothesis receives identical cell/episode/tick/dimension, edge/degree, compute,
communication, mutation, damage, input, and evaluator budgets. Resource use is counted.

Metrics cover performance, accuracy, latency, compute/communication, robustness, recovery,
adaptation, memory, held-out generalization, specialization/useful diversity, efficiencies,
developmental velocity, A/B divergence/complementarity, safety/resource violations, collective
advantage/synergy, and external-teacher dependency (zero).

Run `python -m tmco.ontogeny.tournament --quick --seed 42 --output <path>`. It writes
`results.json`, `metrics.csv`, `summary.md`, and `manifest.json`. The logical result is deterministic;
observational wall time is excluded from it. Full mode remains bounded and adds configured scales.

## Falsification and promotion boundary

Q1–Q7 test whether H1 beats H0, topology helps rather than costs, differentiation is useful,
specialization improves collective advantage, recovery improves, A/B divergence complements,
and recursive composition is economical. Q8 (declining teacher dependency) remains future work.
H1 is falsified as the preferred next direction if preregistered held-out multi-seed tests show no
resource-matched gain over H0 on distributed integration and damage, or gains vanish after cost
accounting. Safety/budget violations disqualify before Pareto selection. A frontier may yield
`NO_CLEAR_WINNER`; even a sole `M0_1_RESEARCH_LEADER` remains LAB-ONLY and needs a future explicit
production milestone.

Limitations: small synthetic proxies, deliberately minimal local learning, no formal PID, quick
mode cannot establish scaling, and one/few seeds cannot establish emergence.
