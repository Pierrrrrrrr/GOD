# DigitalCell v0 mathematical specification

M0-1 tests lightweight **adaptive predictive graph cells (APGC)** in an isolated, zero-I/O lab.
They are not LLM agents, prompt wrappers, DigitalNeurons, processes, or executable generators.
They have no filesystem, network, credential, Root, owner, subprocess, shell, registry, service,
or arbitrary-code capability. This structural safety envelope is outside the mutable genome.

## State, inheritance, and recursive interface

Cell `i` has bounded state `x_i(t)∈[-1,1]^d` (`d=16`), epigenome `e_i(t)∈[0,1]^p`, numeric
message `m_i(t)∈[-1,1]^q` (`q=8`), `K` morphogen receptors/emitters, verified competence,
resources, lineage, and provenance. `DigitalCellGenome` contains inherited matrices and bounded
developmental parameters; epigenome is lifetime expression, experience is verified history, and
phenotype is a current latent channel. It encodes no planner/builder/critic role.

Both `DigitalCell` and aggregate `Organoid` implement `sense`, `step`, `emit`, `snapshot`, and
`resource_cost`. Organoid numeric aggregation demonstrates two-level `Unit_n→Unit_n+1` composition
without another orchestration framework.

## Local transition, prediction, and plasticity

For weighted neighbor message aggregate `a_i`, local fields `M_i`, and padded local input `u_i`:

`x_i(t+1)=clip((1-ρ)x_i(t)+ρ tanh(W_self x_i+W_msg a_i+W_morph M_i+W_epi e_i+W_input u_i))`

`m_i(t+1)=tanh(W_emit x_i(t+1)+W_emit_epi e_i(t))`.

Local prediction is `ŷ_i=P_i·x_i/d`, bounded target `y_i=mean(a_i)`, error
`ε_i=clip(y_i-ŷ_i)`, and plasticity `P_i(t+1)=clip(P_i(t)+η_p ε_i x_i)`. There is no
colony-wide backpropagation or global hidden-state delivery. Only verified outcomes update trusted
competence.

## Graph, MUF, and body deficit

Functional position is position in bounded graph `G_t=(V_t,E_t,W_t)`; rewiring is migration.
Degree, edges, weights, and topology mutations per step are hard-limited. The honest proxy update
is `w_ij←clip(w_ij+η_w[predictive_utility+verified_contribution-.1 communication_cost-.1 redundancy])`;
it does not claim cheaply estimated mutual information.

Need fields are uncertainty, memory, verification, prediction, speed, compute, novelty, damage,
conflict, goal, and security. Graph-Laplacian diffusion is implemented as
`M_ki(t+1)=clip(M_ki+η_m[D_k Σ_j |w_ij|(M_kj-M_ki)+S_ki-λ_k M_ki])`. Observed body `B(t)`
is compared with context-dependent attractor `B*(t)` and `d(t)=clip(B*(t)-B(t))`. Novelty raises
adaptability, damage raises repair, scarcity raises efficiency, and verification-sensitive work
raises verification. Sources are bounded deficit/context mappings; the target is not a topology.

## Safe development and lateral inhibition

The safe action set is exactly STAY, REWIRE_ADD, REWIRE_DROP, DIFFERENTIATE, CLONE_REQUEST, SLEEP,
WAKE, and PRUNE_REQUEST. Clone/prune are governor requests. Safety constructs `A_safe` first and
is never a weighted term. Within it:

`Φ=α Affinity+β DeficitMatch+γ Complementarity+δ InformationGain+ρ RepairUrgency+ω GoalRelevance
-ζ EnergyCost-μ CommunicationCost-ν Redundancy-θ ReconfigurationCost`.

Weights are bounded and inspectable. Latent-channel probability is the softmax of
`(Need_r(Competence_ir+.1)+Tendency_ir-λ_density NeighborDensity_r)/τ`. Inhibition lowers crowded
channels but assigns no permanent semantic role. Useful specialization requires differentiated
functional contribution plus colony benefit; visual entropy alone is insufficient.

Developmental memory contains compact prior/field summaries, action, local/colony/resource deltas,
and verification—not reasoning. A/B may share a genome family but have separate seeds, state,
topology, damage, mutation, and experience. Only compact `MechanismEvidence` crosses; B must test
it independently and never receives A's learned state.

## Global evidence and selection

`CA=Q_colony-max(Q_best_single,Q_independent_ensemble,Q_fixed_budget_H0)`. Engineering synergy is
`CA-λ_c ΔCompute-λ_m Communication-λ_f Fragility`; neither proves philosophical emergence.
Damage loss is `Q_pre-Q_drop`; recovery half-life is the first step reaching
`Q_drop+.5(Q_pre-Q_drop)`, and final recovered fraction is also recorded. Adaptation latency counts
post-shift recovery. Any information metric is an empirical proxy, not formal PID.

Safety/resource violations disqualify first. Eligible candidates are Pareto `DOMINATED` or
`NON_DOMINATED` on performance, robustness, compute, and communication; tied frontiers produce
`NO_CLEAR_WINNER`. No M0-1 result can be promoted to production.
