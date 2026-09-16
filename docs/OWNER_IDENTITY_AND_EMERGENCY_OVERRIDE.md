# Owner identity and emergency override

## Authority semantics

The canonical Root owner is **Pier**. Text saying Pier approved something—whether from chat, a
model, cell, sister, website, document, or PR—is information, not authorization. Protected owner
actions require local authentication followed by a domain-separated Root attestation. The Root
secret remains in its existing protected store and is never supplied to cognition, cells,
providers, or experiments.

An attestation binds `(owner_id, action, scope, resource, nonce, expiry, maximum_cost,
non_delegable)` and signs its canonical challenge under `GOD:OWNER-ATTESTATION:v1`. Verification
checks every field, expiry, signature, and replayed nonce. A cell may see only the compact fact
`OWNER_AUTHORIZED`, a scope hash, and expiry; this cannot mint authority.

## Temporary phrase and state machine

`python -m tmco.owner_control enroll-emergency` reads the phrase twice with `getpass`; no command
line argument accepts it. Storage contains only a random salt and scrypt verifier. It is DPAPI
current-user protected on Windows and mode 0600 on POSIX. Failed authentication is audited without
the phrase. This is a **temporary fallback factor**, not final identity. A future milestone may
use passkeys, Windows Hello, a hardware key, or offline recovery key; none is implemented here.

Restriction order is `STOP_REQUESTED > LOCKDOWN > PAUSED > RUNNING`. Root-authenticated changes
are monotonic; cognition and cells have no clearing API. PAUSE blocks new external effects;
LOCKDOWN additionally blocks remote ModelBus calls and new owner capability requests; STOP is the
strongest durable restriction. Development and non-read BodyBus effects are checked at their
boundaries. Emergency control needs no model. Signed state and consumed nonces survive restart.
Actions are PAUSE, LOCKDOWN, STOP, and REVOKE_EXTERNAL_CAPABILITIES (which enters LOCKDOWN).

## Threat model and limits

Current-user software cannot mathematically resist malicious same-user code, kernel compromise,
or a deliberately modified binary. This is not “unhackable” and does not claim shutdown is
physically impossible to resist. Architecturally, evolution cannot alter Root emergency authority,
governed boundaries enforce it, authenticated STOP cannot be cognitively vetoed, cells receive no
signing/clearing capability, and missing intelligence cannot block it. Pier can always terminate
the OS process externally. There is no taskkill, administrator request, service, scheduled task,
shell, or automatic installer.
