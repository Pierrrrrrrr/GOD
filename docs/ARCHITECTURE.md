# TMCO architecture

G.O.D. is one system containing two independently identified cognitive organisms,
Saphira-A and Saphira-B. Each owns its neurons, synapses, lineage, local memories,
and assemblies. Cross-colony edges are invalid. Only explicitly salient, bounded
items enter the shared Global Workspace.

`RootKernel` is the signed authorization boundary. A random key lives in a mode-0600
file separate from checkpoint/event state; checkpoints contain only its fingerprint
and reference. The HMAC-chained audit detects mutation, and restored permissions are
derived from signed grants rather than trusted checkpoint claims. Cognition cannot
grant permission or target root policy through evolution. `Colony` is the
morphogenetic runtime: lightweight persistent cells
activate against a compute budget, specialize epigenetically, rewire, and join
temporary purpose-specific assemblies. Numeric neuromodulators bias future routing;
they make no claim about emotion or consciousness.

`ExecutiveKernel` accepts typed arbitrary goals and follows decomposition, scored
action selection, observation, verification, learning, and replanning boundaries.
Its score is goal value plus information and capability gain, less cost, risk, and
irreversibility. `MemoryKernel` separates working, episodic, semantic, procedural,
self, and world stores and exposes relevance retrieval rather than whole-memory
injection.

External actions and observations cross explicit executor/provider protocols and carry
stable action IDs. No evidence is manufactured by the system. `ModelBus` and `BodyBus`
are explicit production boundaries. `OrganManifest` describes
heterogeneous future organs through one operation schema. Unconfigured calls fail;
the deterministic cognition fixture is isolated to tests and the local demo.

Assembly formation ranks both colonies and their neurons from task functions,
specialization, contribution, confidence, affinity, neuromodulation, budget, novelty,
and diversity; colony roles are not assigned in the orchestrator.

Durability combines an append-only, fsynced JSONL event stream with atomic JSON
checkpoints. Committed state after the checkpoint is replayed, action completion is
durable before learning, and retries reuse the same executor idempotency key.
Architectural evolution always branches a candidate from the champion, then requires
sandbox benchmark and sister audit data before an explicit promote/reject decision.
The root is outside this mechanism.
