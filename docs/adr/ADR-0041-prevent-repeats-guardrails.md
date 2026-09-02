# ADR-0041: Prevent-repeats guardrails — make a fixed bug-class un-writable, un-reachable, and provably closed

- Status: accepted
- Date: 2026-07-15
- Owners: Alejandro Rengifo
- Related: [ADR-0038](ADR-0038-url-ids-are-untrusted-path-input.md) (the path-traversal class these guardrails lock shut), [ADR-0039](ADR-0039-secrets-encrypted-at-rest.md) / [ADR-0040](ADR-0040-first-run-setup-token.md) (the secret + auth chokepoints proven total here), the god-file guard (`scripts/check_file_sizes.py`, the size rung of the same idea)

## Context

The 2026-07-14 diligence audit and the 2026-07-15 re-audit fixed real defects (two path
traversals, a secret-at-rest gap, an unauthenticated first-admin race, layer-inversion debt).
Fixing an instance is necessary but not sufficient: the same *class* recurs the moment a new
call site forgets the safe chokepoint. Mosaera writes a lot of its own code (it is an agent that
edits repos), so "remember to do the safe thing" is the weakest possible control — a reviewer or
an agent will eventually join a URL id onto a path, decrypt a secret in a read path, or import a
higher layer from a lower one, and a point-in-time fix does nothing to stop them.

The audits kept surfacing the same shape: a **safe chokepoint already exists** (`_pathsafe.contained_path`,
`mosaera_memory.secrets`, the layer graph), but nothing *forces* code through it. The lesson is
not "add more chokepoints" — it is "make the unsafe alternative impossible to ship."

## Decision

For a bug class we have fixed, add up to three cheap, deterministic guardrails — the same
philosophy as the existing god-file guard, generalised:

1. **Un-writable (lint).** A deterministic guard fails CI when code takes the unsafe path. New
   in this ADR: `scripts/check_layer_imports.py` — an AST scan that fails when a package imports
   *across* the one-way dependency graph (a lower layer reaching up, e.g. `core → agents`). Like
   the god-file guard it is a **ratchet**: the known pre-existing crossings (the `agents_bridge` /
   CLI DI debt) are grandfathered and may only shrink; a *new* crossing fails the build. Wired
   into `make lint` and the GitLab `quality` job (the real merge gate).

2. **Un-reachable (architecture/boundary test).** The structure itself denies the unsafe state.
   The layer guard above is one; `guard_bind` / `guard_memory` (refuse to start unsafe) and the
   ADR-0040 setup gate (no admin without the token) are others. The point is that the dangerous
   state is closed *by construction*, not by a runtime check a caller can skip.

3. **Prove chokepoint totality (property test).** Where a single function is the safe boundary,
   a Hypothesis property test proves it holds over *arbitrary* input, not just the examples we
   thought of. New here: `contained_path` never returns a path outside its base for any string
   (the ADR-0038 fuzz proof, now permanent); `try_decrypt` never raises for any input and
   `decrypt_secret` round-trips any text (the ADR-0039/M-2 read-path invariant). A property that
   fails is a real gap found before an attacker finds it.

Guardrails are chosen per class — not every fix needs all three. The bar is: *could this class
recur silently?* If yes, add the cheapest guardrail that makes recurrence loud.

## Consequences

- A new cross-layer import, a new god-file, or a regression in the path/secret chokepoints now
  fails CI deterministically — the classes from the two audits cannot silently return.
- Adds two dev-time guards (`check_layer_imports.py`, wired into `make lint`) and a dev
  dependency (`hypothesis`) for the property tests. No runtime dependency, no production code
  path changes.
- The layer guard's grandfather list is the honest, machine-checked ledger of remaining DI debt
  (the engine still imports the agents via `agents_bridge`; the CLI wires the connector directly)
  — paid down by the AgentTeam-protocol work, and the ratchet guarantees it only shrinks.
- New guards must stay **deterministic and fast** (no network, no model calls) — they run on
  every `make lint`; a flaky or slow guard would be worse than none.
