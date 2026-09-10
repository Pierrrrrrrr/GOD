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

## Local awakening interface

Install once with `python -m pip install .`, then double-click `START_GOD.bat` on
Windows (or run `god-local`). The browser interface stores runtime data under
`~/.god`, connects OpenRouter, Gemini, or a generic OpenAI-compatible endpoint without
requiring an `.env` file, and exposes chat plus natural-language goal submission.
Credentials live in a vault separate from root authority and use current-user DPAPI
protection on Windows. After connecting, the optional real-provider check is:

```bash
PYTHONPATH=src python scripts/smoke_provider.py
```
