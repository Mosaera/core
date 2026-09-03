# ADR-0032: Adding a language — the LanguagePack seam, the SOP, and the per-pack sandbox image

- Status: accepted
- Date: 2026-07-14
- Owners: Alejandro Rengifo
- Related: [ADR-0001](ADR-0001-stack-and-architecture.md) (the Docker sandbox + validation), [ADR-0002](ADR-0002-deterministic-first-and-model-agnostic.md) (deterministic-first — validation is code, not a model call), [ADR-0013](ADR-0013-adding-an-agent.md) (the sibling "adding an agent" SOP this mirrors), [ADR-0025](ADR-0025-behaviour-smoke-gate.md) ("green" means "works" — the validation plan is the oracle), [ADR-0027](ADR-0027-benchmark-diversity-trustworthy-python.md) (Python-first-then-cross-language; benchmark cases are mandatory)
- Related threat model: docs/threat-models/TM-0001 (per-pack images + the embedded-Postgres SQL sandbox)

## Context

Validation used to be one `if/elif` chain in `detect_validation_plan` (`validation.py`): pytest
config → Python scripts → static site → config/data → "unavailable". Every language assumption —
which files mean "this is a project", which install/test commands to run, which sandbox image —
lived inline, and precedence was **implicit in branch order** (a TS repo with a stray `.py` fell
into `python-scripts`). Adding TS/JS and SQL by extending that chain would have repeated the
implicit-precedence bug two more times, then forced a refactor anyway.

The touchpoint audit found the important thing: **the engine is already language-agnostic.** The
workflow graph, the delivery gate, the reviewer, `run_plan`/`resolve_plan`, and the
`ValidationStep`/`ValidationPlan`/`ValidationOutcome` dataclasses reuse unchanged. The genuinely
language-tied part is exactly one thing — *how to recognise a project and build its deterministic
validation plan* (the install/test/smoke steps a sandbox runs, and on which toolchain image). So
rather than design an abstraction from N=1, we **extracted a minimal seam from what was already
language-specific**, ported Python onto it behaviour-preservingly, then added Node and SQL against
it. This ADR is written from N=3 concrete packs, not from a plan.

## Decision

**1. One seam — `LanguagePack.detect` (`mosaera_core/languages/`).** A pack supplies the only
language-tied behaviour:

```python
class LanguagePack(Protocol):
    name: str
    def detect(self, ctx: DetectContext) -> tuple[int, ValidationPlan] | None: ...
```

`detect` returns `(confidence, plan)` when it recognises the workspace, else `None` to defer.
`DetectContext` hands every pack the same precomputed inputs (workspace + file listing + install
flags) so packs don't each re-walk the tree; language-*specific* signals (a pytest config, a
`package.json`) are computed inside the owning pack. Everything downstream of the returned
`ValidationPlan` is the existing, shared machinery — the pack owns detection and plan-building and
**nothing else**.

**2. Confidence-scored dispatch replaces implicit branch order.** `languages/__init__.py` holds an
ordered `REGISTRY`; `dispatch` collects each pack's scored plan and the **highest confidence wins**
(registry order only breaks ties). The tiers make the old precedence explicit:
`CONFIDENCE_SUITE=100` (a test config/suite) > `CONFIDENCE_MANIFEST=80` (a package manifest) >
`CONFIDENCE_SOURCES=40` (bare sources) > `CONFIDENCE_STATIC=30` (html) > `CONFIDENCE_DATA=20`. A
Python app with a `schema.sql` is now unambiguously Python (pytest 100 > sql 40); a `package.json`
repo with a stray `.py` is Node (manifest 80 > bare sources 40). No pack can silently outrank a
stronger signal by being earlier in the list.

**3. Per-pack sandbox image via `ValidationPlan.image` (not a fat image).** A pack whose toolchain
isn't the default Python image sets `ValidationPlan.image` on the plan it returns; `run_plan`
passes it through as a per-command image override. This is cheap because **every sandbox command is
already a fresh `--rm` container**, so selecting the toolchain per plan needs no sandbox-factory
change. Python keeps the default `mosaera-sandbox:dev`; Node returns `mosaera-sandbox-node:dev`;
SQL returns `mosaera-sandbox-sql:dev`. Each image is CODEOWNERS-gated, digest-pinned, and built in
the three surfaces (`scripts/dev-up.sh`, `infra/dev-server-bootstrap.sh`, the `.gitlab-ci.yml`
sandbox-e2e job). We chose per-pack images over one fat image deliberately: a per-language image is
the plugin boundary a multi-language (and, later, community-authored) framework needs, keeps each
language's binary/attack surface to itself, and is unavoidable for SQL regardless (it needs its own
Postgres image).

**4. The SOP — the checklist to add a language `L`.** Gated vs un-gated, mirroring ADR-0013:

*Gated (CODEOWNERS — owner review required):*
- `infra/docker/sandbox-L.Dockerfile` — the toolchain image, **pinned by digest** (no floating
  tag), non-root `sandbox` user at uid/gid 1000 (so the default `--user sandbox` works across
  images), no build toolchain beyond the runtime. Wire its build into `scripts/dev-up.sh`,
  `infra/dev-server-bootstrap.sh`, and the `.gitlab-ci.yml` sandbox-e2e job.
- A **threat-model note** (`docs/threat-models/TM-0001`) whenever the image widens the surface —
  a new install-egress toolchain (npm/pnpm), or a runtime that runs an engine in-sandbox (the SQL
  image runs Postgres). Containment must be shown preserved.
- An **ADR** (a design change; see `AGENTS.md`) + a `docs/adr/README.md` row.
- `packages/policies/` **only if** the scanner allowlist changes (usually not — gitleaks/semgrep
  are language-general).

*Un-gated (normal review):*
- `packages/core/mosaera_core/languages/L.py` — the pack: `detect` + its `_install_step` /
  `_test_step` helpers, returning steps stamped for the network-ON install phase (install) and
  network-off for the test phase, with an honest "unavailable" plan (empty steps) when no offline
  oracle exists rather than a false green.
- **`ValidationPlan.strength` — declare what a PASS of your plan is actually worth (ADR-0034).**
  `"suite"` only when a real test suite executes; `"shallow"` when the plan merely proves the code
  parses (compile / parse / typecheck-without-tests / markup well-formedness); `"none"` when nothing
  runs. This is load-bearing security, not metadata: the autonomous reviewer-silence backstop
  delivers **only** on `"suite"`, so a pack that over-claims lets unvalidated code ship unattended.
  The field defaults to `"unknown"` (≠ `"suite"`), so forgetting to declare fails **safe** — the run
  parks. Be honest about your own plan: a `--help` behaviour-smoke is a floor, not a suite; applying
  a schema without assertion queries proves the DDL is valid, not that it is correct.
- The `REGISTRY` entry in `languages/__init__.py`, and the per-pack image constant.
- Detection tests **including precedence** (`L` beats a weaker signal; a stronger signal beats `L`),
  and a test asserting the plan's `strength` for each shape the pack can produce.

*Mandatory (the bar, not optional):*
- **Benchmark cases `MCB-L-*`** that deliver end-to-end through the governed loop. Per ADR-0027 you
  cannot claim a language works without them — the same bar Python is held to. A pack that detects
  but has no benchmark coverage is unproven.

**5. Community/external packs are FUTURE, and gated on internal proof.** A pack defines the *oracle*
(what counts as correct) and the *toolchain image* — it therefore runs with **engine trust**. An
externally-authored pack needs a public-API stability contract and an **untrusted-plugin threat
model** (a hostile pack could weaken the oracle or ship a poisoned image) before it can be loaded.
This ADR deliberately proves the interface on three first-party packs first and points at the
external-plugin contract without building it.

## The worked reference — three packs

- **PythonPack** — the behaviour-preserving extraction of the old chain (pytest config / scripts /
  static-site / config-data, plus `_install_step` / `_behaviour_smoke_step` / `_implements_help`).
  The existing `test_validation.py` (including the false-park corpus) is the proof it changed
  nothing for Python. Keeps the default image.
- **NodePack** (`mosaera-sandbox-node:dev`, confidence `MANIFEST`) — `package.json` → lockfile-aware
  install (`npm ci` / `pnpm` / `yarn` frozen, else `npm install`, hash-stamped, network-ON, caches
  to `/tmp`) → `tsc --noEmit` when a `tsconfig.json` is present → the test suite (`npm test` if
  real, else vitest/jest/mocha from deps via `npx --no-install`, network-off). Scope is Node CLIs +
  libraries; a browser-runtime web app can't be validated offline, so it returns "unavailable"
  rather than a false green when there's no typecheck and no test suite.
- **SqlPack** (`mosaera-sandbox-sql:dev`, confidence `SOURCES`) — `*.sql` schema/migrations → one
  network-off step that boots an **ephemeral Postgres inside the test container** (data dir + socket
  on the writable `/tmp` tmpfs, so `--network none` + read-only root are preserved), applies
  `migrations/*.sql` / `schema.sql` / `./*.sql` in order under `ON_ERROR_STOP`, then runs any
  `tests/*.sql` assertions. Feasibility was de-risked with a spike (`initdb` → `pg_ctl` → `psql` all
  run under the hard-isolation flags as a non-root user) before the pack was written, and it fails
  honestly (non-zero, with a fix-it message) when a detected SQL repo keeps its schema somewhere the
  applier doesn't look — no "applied nothing, reported OK" false pass.

**Executed coverage (H-9, follow-through).** The Node/SQL packs shipped with detection-only
(plan-shape) tests — nothing ran on their images, so the SQL spike above was the only evidence the
containers worked. `test_langpack_e2e.py` now runs both packs end-to-end on the real images
(NodePack install→test; SqlPack `initdb`→apply→assert), positive and negative, gated on
`docker_image_present` so it runs on GitLab `sandbox-e2e` (blocking) + locally. MCB-26's SQL grader
— which can't be proven host-side — is proven winnable in the same sandbox path. The mandatory
`MCB-L-*` benchmark bar (item 4) is met by MCB-23 (Node) + MCB-26 (SQL). The first executed run also
surfaced a real NodePack bug (a zero-dependency `npm install` never creates `node_modules/`, so the
stamp `touch` failed) — the value of executed coverage over shape-only assertions.

## Options considered

- **Keep extending the `if/elif` chain.** Rejected — it repeats the implicit-precedence bug per
  language and we'd refactor at N=2/3 regardless; a confidence registry makes precedence explicit
  now.
- **One fat sandbox image carrying every toolchain.** Rejected — per-pack images are the plugin
  boundary a multi-language/community framework needs, keep each language's surface to itself, and
  SQL needs its own Postgres image anyway. (An in-flight fat-image change was closed in favour of
  this.)
- **The full 5-item pack interface up front** (test-dir/glob, tester + coder-prompt fragments, a
  hygiene hook). Deferred — ship the minimal seam (detect + per-plan image) proven on three packs
  first; the tester/hygiene fragments are additive when a language actually needs a distinct test
  convention or linter, and building them speculatively is design-from-N=0.

## Security implications

Low, and the boundary is explicit. A pack grants **no capability** — `detect` returns a
deterministic validation *plan* (fixed steps, no model call) that runs in the same sandbox under the
same flags as every other run. The one per-pack lever is *which toolchain image*, and every image
is CODEOWNERS-gated and digest-pinned. The SQL image adds a database engine to the in-image binary
surface, but containment is unchanged — the DB is a local unix socket in `/tmp`, ephemeral (torn
down with the `--rm` container), non-root, and the step runs `--network none` (recorded in TM-0001).
The install phase's network-ON window is the existing, deterministic, manifest-only egress (now
also npm/pnpm, same posture as pip). The genuine future risk is a **community-authored** pack (it
defines the oracle + image = engine trust) — explicitly deferred behind a public-API + untrusted-
plugin contract.

## Operational implications

- Adding a language = a pack module + a `REGISTRY` line + a CODEOWNERS-gated, digest-pinned image
  (built in three surfaces) + mandatory `MCB-L-*` benchmark cases. No migration; the dispatcher,
  graph, and gate don't change.
- A new pack surfaces automatically through `dispatch` the moment it's in `REGISTRY`; confidence
  tiers keep precedence correct without editing existing packs.

## Consequences

The engine now supports a language via a small, self-contained pack, proven end-to-end on Python,
Node/TS, and SQL — extract-from-N, not design-from-1. What remains deferred (and is the load-bearing
work toward community packs): the additive pack surface (test-dir/glob + tester/coder-prompt
fragments + a hygiene hook, added when a language needs them), and the public-API stability contract
+ untrusted-plugin threat model that an externally-authored pack requires — each of which this ADR
points at without building.
