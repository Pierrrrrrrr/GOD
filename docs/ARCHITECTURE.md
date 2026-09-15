# G.O.D. architecture

G.O.D. is one governed system containing two permanently distinct cognitive and developmental lineages, Saphira-A and Saphira-B. Models supply computation; they do not define either sister's identity. Typed, compact exchange is allowed, while private memory and raw chain-of-thought stay separate.

## Live Core

### Root and authority

`RootKernel` is the signed authorization boundary and remains outside cognition and evolution. `RootSecretStore` separates its secret from checkpoint/event state (mode-0600 on POSIX and a DPAPI current-user protected blob on Windows); persisted state contains only its fingerprint/reference. `RootGuard` exposes bounded signing and verification. The HMAC-chained audit detects mutation, and restored permissions derive from signed grants rather than checkpoint claims.

Owner-governed capability leases bind principal, scope, organ, operation, cost, side-effect class, reversibility, and expiry. Cognition may request authority but cannot issue it or modify Root policy. Credential custody remains behind its dedicated boundary.

### Persistent twin cognition

The default `GodRuntime` restores the persistent `TMCOSystem`, including Saphira-A and Saphira-B identities and lineage state, then restores awakening, sister-exchange, embodiment, and development state. Work may recruit both lineages independently and exchange only typed briefs/responses. Roles are selected by evidence and context rather than permanent builder/critic labels.

`ModelBus` is the explicit model-provider boundary. Routing chooses computational capability without changing sister identity, including when both sisters use the same provider/model. An unconfigured production model call fails explicitly rather than substituting a fixture.

### Embodiment, capability, and evidence

`BodyBus` registers trusted organs and their typed operations. `CapabilityDemand` describes intent, inputs, expected output/evidence, risk, privacy, budget, and capability requirements; `CapabilityResolver` ranks compatible registered organs. If none exists, it persists and returns a capability gap rather than claiming completion.

Before body execution, the action loop persists a prediction. It then invokes the selected organ and persists a real `ObservationEnvelope`, including success/failure, evidence references, provenance, content hash, cost, latency, side effects, and any provider error class. Verification is a separate transition. Competence, routing, or learning may become trusted only after verified outcomes.

Embodiment state, permission/lease decisions, capability gaps, predictions, observations, and development events/specifications are persistent. Dangerous or irreversible operations require an applicable owner lease and otherwise pause for approval. Production buses fail honestly when a provider, handler, or safe capability is unavailable.

### Composite Organ development and same-demand continuation

The current safe self-construction path is:

> missing capability → `DEVELOPMENT_NEED` → independent A/B proposals → validation against the original `CapabilityDemand` → trusted-operation validation → isolated test → objective score → sister audit → promotion → persistent declarative spec → resolver retry → the original **same demand** executes → `ObservationEnvelope` → verified continuation → restart restoration

Each proposed Composite Organ must answer the original gap without widening required inputs. It may invoke only available, trusted, registered operations; Root, credentials, shell/code execution, and privilege grants are not composable. Candidates run against disposable compatible organs, are ranked by objective evidence with a non-lineage-order tie-breaker, and require the other sister's audit before attachment and persistence. A promoted declarative specification is restored by revalidation and handler reattachment after restart.

The resolver then retries the unchanged demand. Goal resumption is recorded only after the promoted organ produces an observation, and verified continuation follows the normal evidence boundary.

This is capability construction by recombination of trusted primitives. **It is not arbitrary self-generated code execution.**

## Legacy / experimental baseline

`AssemblyFormationPolicy` and `DigitalNeuron` morphogenetic assembly formation remain available for backward compatibility and controlled experiments. They are no longer required by the default `GodRuntime` goal path, live capability resolution, or Composite Organ development. They must not be described or treated as mandatory live cognition. A `DigitalNeuron` is a lightweight cell abstraction, not an LLM agent.

## Future architecture direction

Digital Ontogeny is a separate laboratory track, documented in `DIGITAL_ONTOGENY.md`. `DigitalCell`, morphogen fields, stigmergy, regeneration, and related biological-development mechanisms are research hypotheses, not production components. They may enter the Live Core only after beating simpler baselines under identical evaluators without weakening Root, sister-separation, evidence, or isolation boundaries.
