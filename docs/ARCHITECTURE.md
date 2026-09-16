# G.O.D. architecture

G.O.D. is one governed system containing two permanently distinct cognitive and developmental lineages, Saphira-A and Saphira-B. Models supply computation; they do not define either sister's identity. Typed, compact exchange is allowed, while private memory and raw chain-of-thought stay separate.

## Live Core

### Corporate-safe product boundary

`CORPORATE_SAFE` is the permanent default web posture. The dependency-free UI binds only to
IPv4 loopback, validates the HTTP host and same-origin mutation context, and requires a
cryptographically random, process-memory-only mutation capability. Sensitive responses are
non-cacheable and carry a restrictive local-only content policy. Request, chat, form-field,
and queued-work bounds fail closed without returning provider details or exception text.

Remote inference has two explicit response contracts. Ordinary owner conversation uses
`TEXT`; cognitive decisions use validated `STRUCTURED` objects. Remote prompts are limited to
owner-authored text and compact operational/public context. Credentials, Root state, sister
private state, raw reasoning, and workspace file contents are not model context. Local Ollama
is discovered only when already installed and populated; the runtime never installs it.

The permanent owner monetary budget defaults to exactly zero. Routing eligibility requires
both input and output prices to be explicitly zero; positive pricing is `PAID — BLOCKED` and
missing or ambiguous pricing is `COST UNKNOWN — BLOCKED`. Exhaustion or failure may fall over
only to another eligible zero-cost record, otherwise the result is
`NO_FREE_SAFE_INTELLIGENCE_AVAILABLE`. Account credit is not spending authorization.

Model health is durable but bounded: transient failures enter an exponential cooldown and can
recover; authentication or permission failures remain blocked until reconfiguration. The
Intelligence Doctor uses synthetic text only and reports cost, privacy, response-mode support,
latency, cooldown, and safe failure classifications. OpenRouter calls require ZDR, deny data
collection, and require requested parameters. The central outbound policy permits only owner
text, public evidence, and compact operational metadata automatically; constitutional/private
sister data is never exportable and workspace-private disclosure requires an artifact-specific
owner approval.

Workspace disclosure approval reuses the Root-signed `OwnerCapabilityAuthority`; it is bound to
the exact artifact, content hash, provider, purpose, expiry, zero cost, and outbound-policy
executor, and is consumed once. A constructed value, altered scope, expiry, or replay cannot
authorize transmission. Constitutional credential, Root, and private-sister classes remain
non-exportable regardless of ordinary disclosure approval.

### Durable autonomous goal engine

The production runtime exposes one-step `advance_goal(goal_id)` and bounded
`run_goal(goal_id, max_steps)`. Goal creation persists a versioned GoalFrame containing the
exact owner intent, desired outcome, explicit constraints, immutable owner-traceable success
criteria, creation time, current milestone, blocker, evidence references, rejected completion
claims, next move, and bounded counters. Its immutable fields are integrity-digested and cannot
be silently loosened by later cognition. A durable compact GoalBrief carries the stable owner objective,
safe evidence references and hashes, blocker class, step count, attempted-action fingerprints,
and whether twin escalation is required. Each advance plans at most one bounded stage, invokes
the existing BodyBus/observation boundary, persists before returning, and never repeats an
already recorded action fingerprint after restart. Uncertainty, risk, stagnation, negative
outcomes, and ambiguous completion trigger metacognition and independent twin recruitment.
Only an owner/evaluator-verified downstream outcome can complete a goal or update trusted
competence; provider or transport success alone cannot.

One durable action ledger spans initial goal submission and every later advance. Canonical
semantic fingerprints transition through proposed, approval, execution, observation,
verification, failure, retryable, or superseded states. Same-step twin duplicates are recorded
as `AGREE` and execute once without stagnation; distinct compatible proposals are
`COMPLEMENTARY`; incompatible effects are `CONFLICT` and only the evidence/utility-arbitrated
move proceeds. Historical repetition without changed evidence alone increases stagnation.

Action-level outcome verification is separate from goal success. A completion request is only
`CANDIDATE_FOR_COMPLETION`; final completion requires a Root-authorized, single-use goal-level
verification bound to the stable success criteria and evidence references. The UI launches
arbitrary owner text explicitly as chat or as an autonomous goal; phrase inference is not
required. Gemini remains visibly blocked in Corporate Safe mode while its account-specific
zero-cost and privacy eligibility cannot be demonstrated.

When a goal reaches `CANDIDATE_FOR_COMPLETION`, the UI shows its stable criteria and verified
evidence. A CSRF-protected owner decision sends only the goal and evidence identities to the
trusted host. The host reconstructs the exact verification payload and requests a short-lived,
zero-cost, non-delegable Root capability bound to its digest, goal, evidence, evaluator, and
`goal-success-gate` executor. The capability is consumed once; it is never exposed to browser
JavaScript, cognition, models, or Body organs. Rejection preserves the same goal and evidence,
records the rejected claim, and resumes replanning rather than creating or failing a goal.

Router exclusions have two explicit meanings. Bounded provider failover uses strict exclusion,
so an attempted resource cannot be selected again within that call. Independent twin cognition
prefers a distinct eligible resource but may reuse the same model for two separate, attributed
Saphira calls when it is the only safe zero-cost capability. Twin comparison uses conservative
effect footprints (target, read/write/delete semantics, side effects, dependency, reversibility,
and risk): exact matches agree and execute once, compatible reads/actions are complementary,
evidence consumers are ordered after producers, and uncertain or conflicting mutations fail
closed to a single safety-arbitrated action.

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
