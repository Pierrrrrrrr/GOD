# G.O.D. engineering protocol

This protocol turns a requested outcome into reviewable evidence. The permanent development sequence is:

> **goal → inspect → causal design → implement → behavioral test → adversarial self-review → repair → full verification → PR**

`AGENTS.md` supplies the constitutional constraints. This document explains how to apply them. A milestone should be a coherent increase in demonstrated competence, not a collection of names, modules, or partially connected mechanisms.

## Development method

### 1. Goal and inspection

Translate the request into an acceptance checklist before editing. Read the production entry point, every component on the affected path, its persistence and permission boundaries, and the tests that claim to cover it. Establish what actually runs by default rather than inferring architecture from class names or fixtures.

### 2. Causal design

Write the end-to-end causal sequence: trigger, decisions, action, observation, verification, durable state, continuation, and failure behavior. Mark authority and trust transitions explicitly. Reuse the live buses, stores, types, and policies; introduce a primitive only when the existing architecture cannot close the loop cleanly.

### 3. Implementation and behavioral proof

Implement the smallest complete loop. Tests should drive the public or production path and assert outcomes at meaningful boundaries. Include honest provider/capability failure, denied authority, invalid evidence, and partial progress as applicable. When behavior is persisted, close and reconstruct the runtime and prove restoration rather than merely rereading through the original object.

### 4. Adversarial review, repair, and verification

Review the whole diff as a hostile reviewer would. Challenge the evidence, ordering, error handling, persistence, privilege scopes, and claims in documentation. Repair every correctable defect, then repeat affected focused tests and the full verification sequence. Only then prepare a PR whose claims match commands actually run.

## Six kinds of correctness

- **Unit correctness:** a function or class produces the expected local result for controlled inputs.
- **Causal integration correctness:** the real trigger reaches each required boundary and the result causes the intended next transition end-to-end.
- **Live/runtime correctness:** the default runtime wires the mechanism to real production buses/providers and handles their availability and failures honestly.
- **Restart/durability correctness:** committed facts survive close/reconstruction, incomplete facts are not promoted, and restored handlers/state can continue safely.
- **Security correctness:** authority, permissions, credentials, evidence, isolation, and scope are fail-closed; untrusted input cannot widen them.
- **Architectural correctness:** the change preserves twin lineages, Root authority, evidence-before-learning, existing live mechanisms, and the boundary between production and experiments.

A fixture proving a function works is not proof that the live runtime path invokes it. Likewise, a persisted row is not proof that restart reconstructs usable behavior, and a successful call is not proof of a verified outcome.

## Definition of Done

A milestone is complete only when all applicable statements are true:

- The requested causal loop exists end-to-end, not only as disconnected types or events.
- Failure is honest and fail-closed; a safely representable capability gap does not crash the process.
- Persisted state reflects what really occurred and does not claim future or unverified state.
- Restart works wherever state is durable.
- Objective evidence precedes trusted learning, competence/routing changes, or candidate promotion.
- Root/owner authority, sister separation, capability, execution, and isolation invariants remain intact.
- Deterministic behavioral tests cover the production path and meaningful adjacent failures.
- Relevant focused tests and the full suite pass, compilation succeeds, and `git diff --check` is clean.
- The entire final diff and every PR claim were adversarially reviewed; found defects were repaired and checks rerun.

Live or platform-specific behavior that deterministic CI cannot establish must be named as requiring manual verification. Never upgrade fixture evidence into a live, external, or security claim.

## How to avoid review ping-pong

Do not patch only the first literal symptom and return immediately. Before submission, search the complete causal loop for adjacent instances of the same acceptance failure. For example, when asked to handle one provider error, inspect equivalent proposal, audit, and provider boundaries in that loop; when changing persisted state, inspect both write and restart paths; when fixing an authority check, inspect equivalent entry points that reach the protected operation.

This is bounded adjacency analysis, not permission for unrelated cleanup or speculative redesign. Follow the data/control path and shared invariant only as far as needed to make the requested loop consistently correct. Record unrelated defects as limitations instead of turning the milestone into a new project.

## Standard verification and PR evidence

Run focused tests during development, then before delivery run:

```text
python -m pytest -q
python -m compileall -q src tests
git diff --check
```

Inspect the resulting diff after those checks. The PR must state exact commands and results, changed files, causal loop, affected invariants, adversarial findings/fixes, limitations, and any genuine manual verification still needed.
