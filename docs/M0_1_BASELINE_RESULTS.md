# M0-1 quick baseline evidence

This is a factual snapshot from the lab-only quick tournament, not a production promotion or an
emergence claim.

- Seed: 42
- Run ID: `ba48fdf498daf46a`
- Configuration hash: `4ca0e36179a1d69a55733cb32e45384cd060ec89a96f39fa23f4d60d31329422`
- Budget per lineage/hypothesis: 8 cells, 8 episodes/task, 2 ticks/case, 4,000,000 compute
  operations, 25,000 communicated values, 64 edges, degree 4, zero money, zero teacher calls.
- Tasks: parity, sensor fusion, multi-stage transformation, temporal memory, damage, rule shift,
  communication scarcity, and corrupted simulated messages.
- Same-seed logical results reproduced exactly; seed 43 produced different logical results.
- Observed quick runtime in the development container: approximately 7.0 seconds.

| Hypothesis | Development performance | Held-out | Compute | Communication | Pareto status |
|---|---:|---:|---:|---:|---|
| H0 | 0.421875 | 0.53125 | 2,238,720 | 20,352 | NON_DOMINATED |
| H1 | 0.421875 | 0.53125 | 2,238,752 | 20,352 | DOMINATED |
| H2 | 0.421875 | 0.53125 | 2,238,720 | 20,352 | NON_DOMINATED |
| H3 | 0.421875 | 0.53125 | 2,238,720 | 20,352 | NON_DOMINATED |
| H4 | 0.40625 | 0.53125 | 2,238,752 | 20,352 | DOMINATED |
| H5 | 0.421875 | 0.53125 | 2,238,752 | 20,352 | DOMINATED |

Conclusion: `NO_CLEAR_WINNER`. Collective advantage was not positive. H1 did not beat H0;
useful specialization and improved recovery were not demonstrated. A/B outcome divergence and a
small cross-task complementarity proxy appeared for H1, but did not improve aggregate performance
and is not sufficient evidence of useful twin development. The preferred hypothesis therefore has
**not** won M0-1.

Next falsification experiment: preregister at least 30 held-out seeds and test H1 versus H0 on
distributed parity and actual 10/20/30% cell-and-edge damage under the same operation budgets,
including confidence intervals and ablation of MUF, differentiation, and topology adaptation.
