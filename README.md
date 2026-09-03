# Mosaera

> **About this repository.** Development happens on a private GitLab instance. This is the public
> **distribution** of that work, published so `install.sh` has something to clone. Each release is
> published as a single commit built from the internal source ([ADR-0117](docs/adr/ADR-0117-the-one-liner-installs-uv-and-pins-a-tag.md) §3),
> so this repository carries no development history and nothing committed here is authoritative —
> the next release replaces it.
>
> **Mosaera is in alpha, and this phase is deliberately closed to outside commits.** Issues and
> Actions are disabled and non-collaborators cannot open pull requests, because a distribution
> cannot honour a pull request and an unwatched tracker is a promise made by accident. That is a
> statement about the current phase, not a policy: once Mosaera is polished enough to meet its own
> delivery standard, contribution opens up properly — with a real review path rather than a
> distribution pretending to have one.
>
> **What this phase is for.** Publishing early is how we find out whether anyone needs this, and
> what breaks in hands other than ours. Two kinds of response are actively wanted now:
>
> - **Does this solve a real problem for you?** Tell us what you tried to use it for, and whether it
>   held up.
> - **Security review.** Mosaera runs model-generated code in a sandbox and gates delivery on
>   deterministic controls; the trust boundary is the part most worth attacking. Findings are always
>   read — see [`SECURITY.md`](SECURITY.md) for how to report privately.
>
> Either way the channel is the security contact in [`SECURITY.md`](SECURITY.md), which is monitored.
> If you want to contribute code, say so there and we will work out how before the door opens
> formally.

**A governed execution engine — not a chatbot or a coding assistant.** Models generate the work;
**deterministic control points decide what is allowed to happen next.** Every significant action is
bounded by **policy, evidence, and explicit authority** — self-hosted, model-agnostic, and fully
auditable.

## What is Mosaera?

Mosaera runs an autonomous AI **firm** — you "hire teams" from it and operate it like an agency, while
keeping models, memory, tools, repositories, and approvals under your control. Its first and current
team, **Mosaera Lite**, is a governed AI software team: it plans work, operates on an **isolated
clone** of a target repository, validates in a sandbox, and **either delivers a reviewable merge
request or honestly refuses** — pausing at human approval gates.

```
User → Quincy (PM) → Team → Control Points → Artifacts → Human Approval
```

> **Where we're going vs. where we are:** [`docs/architecture/north-star.md`](docs/architecture/north-star.md)
> is the authority on direction; the live build status is the roadmap's
> [Current focus](docs/roadmap.md#current-focus-the-now). The **firm layer** (hireable teams) and the
> **posture-governance model** (Free/Business/Regulated,
> [ADR-0046](docs/adr/ADR-0046-posture-and-autonomy-governance.md)) remain direction, not yet built.
> The per-run *oracle posture* that scopes how hard verification tries does ship
> ([ADR-0057](docs/adr/ADR-0057-autonomous-oracle-posture.md)) — similar word, different thing.

## Why governed execution?

The difference from an AI assistant is the **control model**, not the interface:

- **Models propose; deterministic gates decide.** No change ships on a model's say-so — a
  deterministic delivery gate checks the *evidence*.
- **Review claims, not code.** Nothing advances without tool-backed evidence per acceptance
  criterion; the system never trusts a "done" it cannot prove.
- **Honest outcomes.** It delivers cleanly or **parks with a reason** — never dressed-up non-delivery.
- **Governed & auditable.** Scoped, deny-by-default tools; isolated repo workspaces; a human approval
  gate; an auditable decision trail.
- **Local-first & model-agnostic.** Runs on your infrastructure; any role, any provider.

The delivery shape is stable even as the implementation evolves:

```
Planning → Execution → Verification → Delivery Gate → Human Approval
```

## Status

**Maturity: `beta`** ([ADR-0088](docs/adr/ADR-0088-engine-maturity-channel.md)) — outcomes are
**measured on a held-out benchmark** with published snapshots, and the trust boundary plus honest
terminal outcomes are enforced. It is **not production-authorized**: that milestone is `1.0`, defined
as four *measured* gates rather than a feeling
([ADR-0061](docs/adr/ADR-0061-v1-measured-definition-of-done.md)). `beta` is a reading off stated
criteria, not a mood — the ladder and what moves it are in ADR-0088.

The current version and per-release benchmark snapshots live in
[`CHANGELOG.md`](CHANGELOG.md); `mosaera --version` prints both version and channel.

- Current focus: the software-engineering team (Mosaera Lite), **Python-first**, behind a hardened
  trust boundary + independent-oracle delivery gate
  ([ADR-0044](docs/adr/ADR-0044-oracle-make-real.md)).
- Supported: the newest release tag. Maintainer: Alejandro Rengifo (security@mosaera.dev).

## Quick start

```bash
curl -fsSL https://install.mosaera.dev | bash
```

It clones the newest release, builds the Python environment, and hands over to `mosaera-setup` — a
terminal wizard that installs what is missing with your consent for each item, brings up Postgres,
creates your administrator account and starts the instance on a URL that resolves. Re-run it to
move to the next release; it never overwrites your `.env`.

It requires **git** and installs exactly one thing on your behalf: **uv**, into `~/.local/bin`, no
root, announced before it runs and refusable with `MOSAERA_NO_BOOTSTRAP=1`
([ADR-0117](docs/adr/ADR-0117-the-one-liner-installs-uv-and-pins-a-tag.md)). Everything else —
Docker, Compose, Node — the wizard offers you, because a script piped to a shell cannot ask and a
terminal can.

**Platform:** **Linux** is the supported target; **macOS** works; **Windows** means WSL2, from
inside the distro. Also wanted, and started for you by the wizard or by `make up`: **Postgres 16 +
pgvector**. A model provider ([Ollama](https://ollama.com) for local) is yours to choose.

**Bring your own models** — Mosaera reaches local and remote providers through one model gateway
(`get_chat_model`); nothing is hardwired. Point each role at whatever provider you run, inside the
application.

From a clone instead:

```bash
git clone <repo> && cd mosaera && uv run mosaera-setup
```

Prefer the CLI, or run the local checks:

```bash
make run REPO=/path/to/repo TASK="make the failing test pass"
make ci                 # the whole gate: fmt-check lint typecheck test build
```

Full install, configuration, and troubleshooting: **[`docs/getting-started.md`](docs/getting-started.md)**.

## Repository layout

A `uv` workspace. The dependency direction is **enforced** by a lint guard
(`scripts/check_layer_imports.py`, wired into `make lint`), not merely intended:

```
agents / connectors / api  →  core  →  policies          memory is a leaf
```

| Path | What lives there |
|---|---|
| [`packages/core`](packages/core) | The engine: run graph, sandbox, validation, tools, config, CLI |
| [`packages/agents`](packages/agents) | Model-facing roles — PM, coder, reviewer, Proctor, critic |
| [`packages/policies`](packages/policies) | The trust boundary: deny-by-default tool allowlist + the delivery gate |
| [`packages/memory`](packages/memory) | Durable Postgres + pgvector store, Alembic migrations |
| [`packages/connectors`](packages/connectors) | GitLab client + merge-request assembly; a GitHub draft-PR path |
| [`apps/api`](apps/api) | FastAPI — submit runs, stream over SSE, resolve the gate, serve the SPA |
| [`apps/web`](apps/web) | The operator dashboard (React SPA) |

## Current capabilities

- **Project-scoped onboarding and a durable map**
  ([ADR-0047](docs/adr/ADR-0047-project-onboarding-and-the-durable-map.md)) — a project is
  interviewed and reconned into a map + charter, so a run is scoped as *gap-analysis against the
  project's actual state* and respects the repo's own conventions, rather than "point it at a repo
  and a task."
- Plans an issue, implements on an isolated clone, validates in a sandbox, reviews against acceptance
  criteria, and opens a reviewable merge request — or parks honestly.
- **Independent verification, by separated authority** — a deterministic delivery **evidence gate**,
  the **Proctor** authoring acceptance tests the coder may not edit
  ([ADR-0058](docs/adr/ADR-0058-proctor-validates-repairs-tests.md),
  [ADR-0013](docs/adr/ADR-0013-adding-an-agent.md)), and a **held-out critic**
  ([ADR-0065](docs/adr/ADR-0065-held-out-critic.md)). No ship on the coder's own green tests.
- An independent **security gate** ([ADR-0076](docs/adr/ADR-0076-independent-security-gate.md)) — an
  unverifiable scan parks, never false-greens.
- **Measured, not asserted** — a capability benchmark
  ([ADR-0007](docs/adr/ADR-0007-capability-benchmark-suite.md)) and reliability scoreboard
  ([ADR-0053](docs/adr/ADR-0053-reliability-scoreboard.md)) classify every run's terminal outcome, so
  progress is a published number against a hidden grader. Current figures: the roadmap's
  [Current focus](docs/roadmap.md#current-focus-the-now).
- A web dashboard — projects, then per project: start, overview, PM, backlog, changes, artifacts,
  runs, activity, settings — plus a CLI and multi-user login (≤5 seats). See the
  [dashboard guide](docs/user-guide/dashboard.md).

## Current limitations

Mosaera is `beta`, and the honest list matters more than the feature list:

- **The `1.0` correctness gate does not pass yet.** `false_ship` is not yet bounded near zero against
  the hidden grader — it is the one v1.0 gate the engine outright fails, and the current critical
  path. The live measurement and its caveats are in the roadmap's
  [Current focus](docs/roadmap.md#current-focus-the-now).
- **Over-parking is the active defect** — runs that stop honestly but stop too early, declining work
  they could have completed. Honest about stopping, wrong about the work.
- Validation quality depends on the project's tests; test generation + validation planning are not
  mature yet.
- Artifact curation/packaging is still maturing.
- Multi-user login caps at 5 seats (self-hosted small-team scope).

## Documentation map

| Doc | Answers |
|---|---|
| [`project-brief.md`](project-brief.md) | What Mosaera is + who it's for |
| [`docs/README.md`](docs/README.md) | **The authority map** — which doc is canonical vs. historical |
| [`docs/architecture/north-star.md`](docs/architecture/north-star.md) | **Why** — the enduring vision + invariants |
| [`docs/architecture/`](docs/architecture/) | How it's designed |
| [`docs/roadmap.md`](docs/roadmap.md) | What's being built next + live status |
| [`CHANGELOG.md`](CHANGELOG.md) | Release history, each with its benchmark snapshot |
| [`docs/runbooks/`](docs/runbooks/) | Operational procedures (user management, releasing a version) |
| [`CLAUDE.md`](CLAUDE.md) | How an AI agent must behave in this repo |
| [`coding-standards.md`](coding-standards.md) | How code is written |
| [`AGENTS.md`](AGENTS.md) · [`SECURITY.md`](SECURITY.md) · [`docs/threat-models/`](docs/threat-models/) | Security policy + threat surface |
| [`docs/adr/`](docs/adr/) | Architectural decisions |

## Security

Deny-by-default tools, isolated repo workspaces under `.mosaera/workspaces/`, no secrets in the tree
(`.env` gitignored + CI secret scanning), and a human approval gate on delivery. See
[`SECURITY.md`](SECURITY.md) and [`docs/threat-models/`](docs/threat-models/).

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) — Conventional Commits, MR review, required checks. `main` is
protected and is promoted to from `staging`, the long-lived deploy branch: work is exercised on a
running instance first, then merged. CI green is not validation.

## License

Apache-2.0 — see [LICENSE](LICENSE).
