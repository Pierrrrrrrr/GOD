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

## Phase 2B embodiment

`tmco.embodiment` expands the existing `BodyBus` with typed capability demand and
resolution, durable predictions/observations/gaps/approvals/leases, a workspace-confined
filesystem, SSRF-protected read-only web research, registered OpenAPI operations, and
honest optional MCP and sandbox boundaries. `tmco.sisters` provides independent-first,
compact, bounded sister briefs and verified development digests. A completion claim is
impossible without an observation and verified learning is explicitly outcome-gated.

The production research-to-report path is: persist goal/demand, resolve `web.GET`, persist
prediction, receive and persist hashed HTTP evidence, independently assess important
evidence, optionally exchange a compact brief, synthesize, resolve `workspace.write`, and
verify the output with `workspace.exists`/`workspace.hash`. Network failure produces a
failed observation rather than research output. Optional MCP SDK and secure sandbox
providers are not installed automatically.

On Windows, install with `py -3.11 -m pip install -e .`, run tests with
`py -3.11 -m pytest -q`, and start with `START_GOD.bat`. Shutdown through Ctrl+C (or close
the UI process) so the runtime checkpoints SQLite WAL and closes its connection cleanly.
## Phase 2A awakening (Windows)

Install once with `py -3.11 -m pip install -e .`, then double-click
`START_GOD.bat`. The server binds only to `127.0.0.1` and opens the local UI at
`http://127.0.0.1:8765`. Connect OpenRouter, Gemini, or an OpenAI-compatible
endpoint; credentials are kept in a separate OS/user-protected vault and are
never displayed after submission.

Normal onboarding requires no model identifier or endpoint: import a local JSON
secrets file, connect OpenRouter with one key, or detect an existing Ollama
installation. G.O.D. discovers compatible models and routes them with `AUTO`,
`FREE FIRST`, or `LOCAL FIRST`; manual configuration remains under Advanced.
