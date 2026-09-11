# G.O.D. — Twin Morphogenetic Cognitive Organism

The first executable TMCO kernel vertical slice. It implements two independent
Saphira colonies, persistent digital-neuron graphs, sparse workspace exchange,
root authorization, typed goal execution, layered memory, explicit body/model buses,
candidate-only architecture evolution, crash-safe replay, idempotent action execution,
and checkpoint recovery. Production execution requires explicit executor and
observation-provider implementations. Root signing material is stored separately:
owner-only mode `0600` on POSIX and DPAPI current-user protection on Windows.

Requires Python 3.11+.

```bash
python -m pytest
PYTHONPATH=src python scripts/demo.py --reset
```

The demo uses the deterministic fixture in `tmco.fixtures`; production buses never
substitute a fake provider.
## Phase 2A awakening (Windows)

Install once with `py -3.11 -m pip install -e .`, then double-click
`START_GOD.bat`. The server binds only to `127.0.0.1` and opens the local UI at
`http://127.0.0.1:8765`. Connect OpenRouter, Gemini, or an OpenAI-compatible
endpoint; credentials are kept in a separate OS/user-protected vault and are
never displayed after submission.
