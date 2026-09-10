# G.O.D. — Twin Morphogenetic Cognitive Organism

The first executable TMCO kernel vertical slice. It implements two independent
Saphira colonies, persistent digital-neuron graphs, sparse workspace exchange,
root authorization, typed goal execution, layered memory, explicit body/model buses,
candidate-only architecture evolution, crash-safe replay, idempotent action execution,
and checkpoint recovery. Production execution requires explicit executor and
observation-provider implementations.

Requires Python 3.11+. Root secrets use owner-only files on POSIX and Windows DPAPI
current-user protection on Windows; neither form is part of organism state.

```bash
python -m pytest
PYTHONPATH=src python scripts/demo.py --reset
```

The demo uses the deterministic fixture in `tmco.fixtures`; production buses never
substitute a fake provider.
