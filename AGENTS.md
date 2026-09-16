# G.O.D. permanent Codex contract

These rules are mandatory for every engineering task unless Pier explicitly authorizes a constitutional change.

## Mission

G.O.D. is being developed toward a persistent autonomous digital organism, not a collection of agent-framework abstractions. A successful change must increase demonstrated autonomous goal completion, durable continuity, verified learning, useful capability acquisition, resilience/recovery, cognitive diversity, safe self-development, evolvability, resource efficiency, or eventually economic agency.

Adding classes, biological vocabulary, schedulers, agents, or abstractions is not progress by itself. Prefer a few general mechanisms capable of producing many behaviors.

## Permanent architectural invariants

- Saphira-A and Saphira-B are permanent separate cognitive and developmental lineages. Never transfer raw chain-of-thought or private memory between them; compact typed exchange is allowed.
- A model/provider is a computational capability, not a Saphira's identity. Both sisters may use the same model while retaining separate lineage and state. Never hard-code permanent A=builder / B=critic roles.
- `RootKernel`, the Root Constitution, owner authority, credential custody, and audit integrity remain outside self-evolution. No cognition may grant itself privileges.
- Never fabricate evidence or success, or learn from unverified outcomes. External action success requires an Observation/Evidence boundary; trusted competence, routing, learning, and promotion changes require verified outcomes.
- Production buses fail honestly when capability is unavailable. A capability gap is a state to resolve, not a reason to fabricate completion, and must not become an uncontrolled process crash when it can safely remain a gap.
- Test candidate mechanisms before promotion. Shared-body changes require objective evidence and appropriate sister audit.
- Generated executable code must never run directly on the host without a future explicitly approved isolation boundary. Composite Organ development may compose only trusted registered operations.
- Legacy `DigitalNeuron`/assembly morphogenesis is an experimental, backward-compatible baseline, not mandatory live architecture. `DigitalCell`, morphogens, and future biological-development mechanisms remain Digital Ontogeny Lab hypotheses until benchmarks justify promotion. A `DigitalNeuron` is not an LLM agent; keep cells lightweight.
- Do not create a second competing framework, bus, or runtime to solve an architecture problem unless evidence proves the existing mechanism cannot support it.
- Pier's default monetary budget is exactly zero. Unknown or positive pricing is blocked; never fall back from a demonstrably zero-cost resource to a paid or ambiguously priced resource. Spending requires a future separate explicit owner authorization mechanism.
- The canonical Root owner is `Pier`. Owner text is information, never authorization. Owner identity and the Root emergency override are outside evolution; cognition/cells cannot redefine the owner, grant owner authority, clear STOP, or veto an authenticated restriction. Governed external-effect boundaries enforce emergency state without depending on model availability.

## Required workflow for every task

Before editing:

1. Inspect the current implementation and relevant tests and docs.
2. Identify the actual causal path affected.
3. Write an internal acceptance checklist derived from the task.
4. Reuse existing primitives before creating abstractions.

During implementation:

5. Implement the smallest architecture that closes the complete requested causal loop.
6. Add deterministic behavioral/integration tests.
7. Test failure paths, restart/persistence where relevant, and security boundaries. Every persisted model change requires a restart test.
8. Never silently weaken an invariant to make tests pass.

Before delivering:

9. Run relevant focused tests.
10. Run the full test suite.
11. Run `python -m compileall -q src tests`.
12. Run `git diff --check`.
13. Inspect the entire final diff.
14. Perform an adversarial self-review against the original acceptance checklist.
15. Actively seek happy-path-only behavior, fake events, state reported before it occurred, unhandled provider failures, restart inconsistencies, privilege/scope widening, secrets or raw model output persistence, tests bypassing the production path, iteration-order winners instead of evidence-based winners, stale docs/test counts, and duplicated architecture.
16. If a correctable defect is found, fix it, rerun verification, and repeat the review before opening or reporting the PR.

Do not knowingly return a defective PR and wait for the reviewer to find the defect. Green tests alone are not sufficient.

## Scope discipline

- Do not redesign unrelated components or add speculative infrastructure.
- Add no dependency unless genuinely necessary; prefer the standard library and existing typed primitives.
- Preserve Windows support and avoid destructive compatibility migrations unless requested.
- Do not implement Digital Ontogeny/M0 unless explicitly requested.
- Do not add arbitrary shell or host-code execution, directly or indirectly.
- Do not merge your own PR.

Use [`docs/ENGINEERING_PROTOCOL.md`](docs/ENGINEERING_PROTOCOL.md) for the detailed development method and Definition of Done.
