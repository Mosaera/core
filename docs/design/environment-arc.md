# Design study — the environment arc: a persistent project workbench, and the deploy layer

> **STATUS: PROPOSED — DIRECTION, not started, not authorizing.** Researched and owner-reviewed over
> four rounds on 2026-08-07, then **deliberately parked** behind the run-reliability program (the
> owner's standing priority: a run should conclude cleanly ~90% of the time, autonomous and guided,
> with the model round-trips reduced). This file exists so the reasoning is not re-derived later —
> the failure this repo has now measured four times. It is a `docs/design/` study and therefore
> **never authority**; nothing here may be built without a tracked, authorizing issue, and the
> ADR below must be written and accepted first.

## Why this arc exists

Three questions from the owner: which SDLC layers Mosaera does not cover; why the engine cannot run
**git**; and why the sandbox is per-run when a project needs a persistent environment you can
browse, log into, and actually run the application in.

**The layer map**, against the standard DevOps eight — plan ✅ · code ✅ · build ⚠️ (install only,
**no artifact concept**) · test ✅ · release ⚠️ (opens an MR, a human merges — the declared handoff) ·
**deploy ❌ · operate ❌ · monitor ❌**. There is no `deploy` in `GATED_ACTIONS`, and more
fundamentally **no environment concept anywhere**.

**That absence is the connecting insight.** A deploy layer is impossible without environments —
nothing to deploy *to*, nothing to roll back, no artifact to promote. The workbench is therefore not
a convenience feature beside deployment; it is **the first environment**, and it is what would make
the deploy layer designable rather than speculative.

## Findings that shaped the design

1. **The persistent project *workspace* already exists.** `open_project_workspace`
   (`packages/core/mosaera_core/tools/repo/clone.py:134`) reopens `.mosaera/projects/<id>/repo/` on
   `mosaera/project-<id>` and preserves history — *"accumulation across item runs is the product
   model"* (ADR-0019). Files persist; the **machine** does not. That is the distinction the external
   research draws: a checkpoint captures node_modules, DB state, running services and env —
   **state git does not track**.
2. **There is no container to keep alive.** The sandbox is per **COMMAND**: `docker run --rm --name
   mosaera-sbx-<uuid>` on every call (`sandbox/_docker.py:218`). No create/start/exec, no handle.
   A persistent workbench is a new mechanism, not a lifetime tweak.
3. **`--network none` is about *this box*.** The code says why (`sandbox/_docker.py:27-32`): host
   networking would let repo code reach the loopback Mosaera API, Ollama and dev Postgres — and that
   API is **open by design when no token and no users are configured**, the normal dev-box state.
4. **The git gap is narrower than "no git".** `_stage_all` runs `git add -A`
   (`tools/repo/workspace.py:117`), which **stages deletions** — a coder that deleted a tracked file
   *would* untrack it in the delivered commit. Item 88 failed because `delete_file` is admin-off and
   because its test observed `git ls-files` **pre-commit**. Any future plan must state the agent gap
   precisely rather than as "the agent has no git".
5. **Prior art:** no ADR contemplates port exposure, a dev server, agent git, or deployment. The
   North Star lists *"the full regulated operate tail"* and *"automatic deployment authority"* under
   **Not Yet**. ADR-0063 sets the governing rule — containment openings arrive **one red-teamed MR
   at a time** (ADR-0064, the `/scratch` mount, is the worked example). ADR-0059's `sandbox_exec` is
   the standing answer to "let the agent run things" and is deliberately non-persistent and
   network-off; a persistent workbench is a conscious departure from it.

## The design, as reviewed

**Part 1 — an ADR (decide, do not build): environments, artifacts, deploy authority.**
- **What an ENVIRONMENT is**: a named, persistent place a project's code runs, with a lifecycle, an
  isolation posture, and a stated relationship to evidence. The workbench is instance #1.
- **What a release ARTIFACT is**: build produces nothing durable today. Name it, its provenance
  (run, commit, evidence package) and its identity — "promote" and "roll back" are meaningless
  without one.
- **Who may authorize a deploy**: *Deterministic Final Authority* one layer down. A model may
  propose or prepare a deploy, **never issue one**. The external research is blunt about the
  precondition: deployment becomes agent-executable *"only if rollback triggers, canary thresholds
  and blast-radius limits exist as machine-readable rules"* — Evidence-Gated Advancement restated.
  None exist, which is itself the answer to "why not yet".
- **One new named rule**: **the workbench is never an evidence source.** The gate reads only the
  sealed sandbox. This is what keeps `strength="suite"` meaning *passed from a clean tree with no
  network* — and what makes the workbench safe to make convenient, since nothing gates on it.
- **The agent gap, stated precisely** and deferred as an ordered set of future openings: scaffold a
  project, install/manage dependencies, run migrations, rename/move files, branch and history
  operations, observe staged state, run long-running processes. For each — why it is out of
  capability and what control it would need.
- **Explicitly deferred** to the Regulated-posture arc the North Star already names: canary,
  rollback mechanics, SLOs, telemetry, incident handling.

**Part 2 — build the per-project workbench, HUMAN SURFACE ONLY.** The agent's tool allowlist and
sandbox are untouched, so the producer trust boundary does not move.

- **Isolation** — a dedicated user-defined bridge network per project: egress yes (installs need
  it), host loopback no. **The property that actually protects the box is that the host's services
  bind loopback-only** (Postgres `127.0.0.1:5432`, the API and Ollama likewise), so a bridged
  container cannot reach them via the gateway address. That is load-bearing and currently
  **implicit**: the workbench must assert it at startup and refuse to run if a host service is
  reachable. If anyone ever binds Ollama to `0.0.0.0`, the protection evaporates silently — the
  check turns an invisible hole into a visible refusal.
- **Working tree** — its **own clone**, not the run's tree and not a `git worktree` (shared `.git`
  means lock contention and git refusing the same branch twice, and runs use both
  `mosaera/project-<id>` and `mosaera/item-<id>`). A run's `reset --hard` can never destroy your
  experiments; your uncommitted edits can never reach a run's diff. Accepted trade: you browse the
  last committed state plus your own changes. **This is the decision most likely to want revisiting.**
- **Lifecycle** — one long-lived container per project, started on demand, idling cheaply,
  surviving Mosaera restarts, stopped after an idle timeout with disk state preserved. Independent
  of runs.
- **Dev-server preview** — binds inside the container; Mosaera proxies it behind the existing
  session/token auth. **The threat must be designed for:** proxying model-authored HTML under
  Mosaera's own origin is XSS-equivalent against the session cookie. So: `sandbox` CSP, no cookie
  forwarding upstream, embedded in a sandboxed iframe — the preview never runs same-origin with the
  control plane. If that breaks HMR in practice the fallback is a separate origin, never a relaxed
  sandbox.
- **File browsing** — no directory-listing endpoint exists (`/files` returns only *changed* files
  from a diff) and the UI has no file browser. Both new, reusing `_pathsafe.contained_path` and the
  `Workspace.file_listing` guards.
- **Terminal** — a websocket to `docker exec`, admin-gated, deliberately the **last** slice.

**Slices**, each independently reviewable per ADR-0063: (1) ADR + threat model, no code · (2)
container lifecycle + own clone + network isolation, with the host-unreachability assertion — the
slice that proves the posture · (3) file browsing · (4) dev-server preview · (5) terminal.

## Verification, when this is built

**The security test, and it is the one that matters:** from inside a running workbench, attempt to
reach the host's Mosaera API, Ollama and Postgres — each must fail, asserted per service and again
after a restart. A second test asserts the startup check **refuses to start** when a host service is
reachable.

- **Persistence** — install a dependency, stop, start, it is still there.
- **Non-contamination, both directions** — a run's `reset --hard` leaves the workbench tree
  untouched; workbench edits never appear in a run's diff or `RunState`.
- **The evidence invariant, structurally** — no workbench output has any path into `RunState` or the
  gate payload, asserted as an absence (the shape F70 and F71 taught).
- **Preview** — unauthenticated access refused; a hostile dev server cannot read the session cookie
  or act same-origin.
- **Path safety** — the listing endpoint refuses traversal and symlink escape (ADR-0038 guards).

**RED TEAM required, 3 rounds**, on the containment slice. Target: *can anything in the workbench
reach the host, another project's workbench, or the evidence path?* Probe the gateway address, DNS,
the docker socket, shared volumes, and the proxy as an SSRF pivot into the control plane.

## What this arc would NOT deliver

No new agent capability — **item 88 would still fail**, and "zero to complete" is not closer except
that it would have an environment to happen in. No deploy capability. No claim that the workbench
says anything about whether the software works.

## Why it is parked

Run reliability comes first: a run should conclude cleanly ~90% of the time in both modes, with
fewer model round-trips. An environment arc adds surface to a system whose core loop is not yet at
the reliability bar — and the standing baseline (2026-08-05, n=72) is 91.7% clean-conclusion with a
30% over-park rate, measured. Fix the loop, then give it somewhere to live.
