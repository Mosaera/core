# ADR-0116: Setup is a terminal wizard, and the browser only signs you in

- Status: accepted
- Implementation: shipped (the wizard 2026-08-25; the installer hand-off and the browser slimming 2026-08-26, the latter alongside [ADR-0117](ADR-0117-the-one-liner-installs-uv-and-pins-a-tag.md))
- Date accepted: 2026-08-25
- Owners: Alejandro Rengifo
- Related issue / MR: #119 (first-time setup)
- Supersedes / Superseded by: **supersedes** [ADR-0115](ADR-0115-first-run-is-a-gated-flow-resumed-from-facts.md) (the five-screen browser flow) and **supersedes** [ADR-0040](ADR-0040-first-run-setup-token.md) on the normal path (the one-time setup token)
- Related: [ADR-0004](ADR-0004-auth-and-session-model.md) (the first-admin self-lock this now relies on entirely), [ADR-0005](ADR-0005-config-in-ui-settings.md) (env > stored > default; infra knobs stay env-only), [ADR-0035](ADR-0035-infrastructure-failure-is-loud.md) (capability-degraded stores), [ADR-0039](ADR-0039-secrets-encrypted-at-rest.md) (the service token this writes to `.env`)
- Related threat model: [TM-0002](../threat-models/TM-0002-mosaera-api-web-server.md) (the browser can no longer create the first account; a new local process installs packages and can delete durable data)
- Review trigger: a headless deployment of the API appears (a container image, a managed host), or any step of setup becomes reachable from the browser again

**Decision summary:** First-run setup moves out of the browser and into `mosaera-setup`, an
interactive terminal application. It installs prerequisites **with per-item consent**, brings up the
database, chooses the bind, and creates the first administrator directly. The browser keeps a login
form. Models are configured **inside the application**, not during setup. Uninstall is part of the
same tool, and removes **only what the wizard itself installed**.

## Context

The browser flow of [ADR-0115](ADR-0115-first-run-is-a-gated-flow-resumed-from-facts.md) shipped and
did not survive first contact. The reason is structural, not aesthetic: **only Postgres is
containerised — the API runs on the host via `uv run mosaera-api`.** There is no headless deployment
of Mosaera, so *every* install already happens at a terminal, and a browser cannot install Docker,
start Postgres, or write `.env` even in principle. The web wizard was asking an operator to
configure a machine from the one place with no access to it, and could therefore only ever *report*
what was wrong.

Two further facts pushed the same way. The prerequisite advice was **wrong in a way that would break
a machine**: the wizard derived install commands from binary names, so on Debian it offered — and
executed — `apt-get install -y node`, which installs an amateur packet radio program, and
`install -y docker`, which is not the engine. On any distribution not explicitly matched, every tool
produced `curl get.docker.com | sh`, so "install git" ran the Docker installer. And a browser button
that shells out to `sudo` is a trust-boundary change this repo had already refused
(`scripts/install.sh`: *"We refuse to run `sudo apt-get install` on your behalf"*).

## Decision

### 1. `mosaera-setup`, in the terminal

A Textual application, entry point in `apps/api` because it needs `preflight` (core),
`store.create_user` (memory) **and** `hash_password` (api) at once, and `check_layer_imports` forbids
core importing api.

Not a prompt loop: the slow steps take minutes, and only a screen can show progress, the step you
are on, and what remains, all at once while they run.

### 2. Consent replaces refusal — because the terminal makes consent possible

`install.sh` refuses to install packages, and that refusal does not disappear: it **moves** to where
consent can be given. A script piped to `sh` cannot prompt at all — its own stdin is the script — so
the installer ends by handing over, and the wizard, running in a terminal the operator invoked,
shows each exact command beside its own row and runs only what is chosen.

**Corrected 2026-08-25.** That hand-off was described here and never shipped: `install.sh` ended with
`exec make up`, mentioned `mosaera-setup` only in a comment, and therefore started an API for an
instance with no database and no account — landing the operator on a login form they could not get
past. It now reopens the controlling terminal (`exec < /dev/tty`, the counterpart to the stdin
problem above) and runs `mosaera-setup` directly, falling back to printing the command where there
is no terminal. Starting the server is the wizard's own last step, not the installer's first.

This is the distinction that makes it defensible, and it is worth stating because it looks like a
reversal: **a command run in the operator's shell, with the operator's privileges, from a command
they typed, is not the same act as a web page shelling out to root.**

Privileged commands run inside `App.suspend()`. With Textual holding the terminal in raw mode a
`sudo` prompt is invisible and unanswerable and the wizard deadlocks; suspending hands the real
terminal back, so the operator sees the command, answers the prompt, and watches the output.

### 3. One prerequisite table, three readers

`mosaera_core.prereqs` declares each prerequisite: the binary, **what it is for**, and per-family
packages. `mosaera doctor`, the wizard and `install.sh` read it, so they cannot disagree again.

- A binary name is not a package name (`node` is `nodejs`), and every package name is declared, never
  derived.
- Docker installs via **Docker's own script**, which is the one method that works across
  distributions and brings the **compose v2 plugin** — a separate package we previously never
  checked for, while the database step ran `docker compose up -d`.
- An unrecognised platform gets documentation. It never gets a command belonging to another tool,
  and never one for another operating system.

### 4. The first administrator is created locally, and the token is retired

`create_admin` writes the account directly. ADR-0040 minted a one-time token so a browser form could
prove the person filling it in had server access; **running this command is that proof.** The race
ADR-0040 closed (CWE-1188) is closed here by construction: no unauthenticated endpoint creates an
account, and `POST /auth/users` already refuses when none exist.

The consequence is real and accepted: **an instance with an empty database has no way in from a
browser.** Recovery is to be on the server, or to pre-provision with `MOSAERA_INITIAL_ADMIN_*`, which
remains supported for orchestrated deploys.

### 5. Re-running changes nothing

Idempotence is a tested property, not a claim. Every step reads the machine first and writes only
what differs. The first cut minted a **fresh service token on every run**, rewriting the live one and
invalidating every credential already issued, while reporting success.

`.env` is written atomically — a temp file created `0600` *before* any content exists, then
`os.replace` — because it is the operator's file, it now holds a token, and the previous version
truncated in place and set the mode afterwards.

### 6. Uninstall removes only what we installed

The wizard **records** each install (`setup_installed` in `settings.json`). Nothing else is ever
offered: most machines had Docker or git long before Mosaera, "present" and "we put it there" are
indistinguishable afterwards, and taking away a tool someone else's work depends on is not a repair.

Two further rules. A tick-box is not consent for something irreversible — deleting project data
(`docker compose down --volumes`) is a separate choice, labelled, and confirmed on its own screen.
And a **system package is never removed on the operator's behalf**; that needs their terminal and
their judgement.

**Amended 2026-08-25: the typed word is gone, and the gate is a resting cursor.** The confirm screen
lists what will go and offers two rows — `Cancel` first, so the cursor starts on it. Enter alone
cancels; removing requires deliberately moving down first. This is a smaller gate than `REMOVE`
looked, and the same size as it actually was: a spelling test stops nobody who has already decided,
while costing every *reversible* removal the same ceremony as the irreversible one. What matters is
that the default action is the harmless one, and it now is.

**A removal ends in a result, never in a step.** The flow used to return to wherever Ctrl-X was
pressed, defaulting to the completion step — so finishing an uninstall walked into the code that
builds the dashboard and starts the server, and tried to start the instance it had just removed.
Starting an instance is the one thing that must not follow removing one.

### 7. Models are not part of setup

Nothing here chooses a model. Mosaera is bring-your-own-model: the hardware is unknown to us, the
operator may be cloud-only, and every capability number this project has published was measured on
one binding. Models are configured in the application, where `guard_can_run` and the setup banner
already report that a run cannot proceed without them.

### 8. A database is not optional — there is no such thing as an install without one

Amended 2026-08-25, after a run reached the end without one. The step offered "Skip — I'll sort the
database out myself", and skipping produced a directory rather than an instance: no account, no
login, and an Administrator screen whose only remaining offer was "Continue without an account".

**Every account, project, backlog item and run lives in Postgres.** An install with no database is
not a degraded install, it is an absence of one, and offering to walk past it was the wizard telling
an operator that a state it cannot function in is a state it supports.

So the step cannot be passed. An operator with their own server points at it — the URL is **opened
and migrated before it is written**, so `.env` can never end up naming a database that does not
answer. The honest exits are Ctrl-Q (leave, exit 1) and Ctrl-X (abandon and remove); both say what
they do, which "Skip" did not.

The same amendment deletes the account-less administrator route and makes **uninstall reachable from
every step** rather than only from the finished screen — requiring an operator to complete a setup
they had decided against, in order to be allowed to undo it, was its own kind of trap.

### 9. The wizard starts the instance, and hands over an address that resolves

Also 2026-08-25. The final screen said `Start it with make up` — a completion screen that is not one.
The wizard now builds the dashboard if it is missing and starts `mosaera-api` itself, **detached**
(`start_new_session=True`, output to `.mosaera/api.log`, pid to `.mosaera/api.pid`), because the
screen closes itself after sixty seconds and a foreground child would die with it.

Three properties this must keep:

- **Already-serving short-circuits.** The port is probed before anything is started, so a re-run
  changes nothing — the same rule as every other step.
- **The environment is passed, not inherited.** `mosaera-api` reads `os.environ` and does not load
  `.env`; the child is given the file's values explicitly.
- **The address shown is one that resolves.** A `0.0.0.0` bind is displayed as the machine's real
  LAN address, and when the port never answers **no link is shown at all** — the log path is, which
  is the only useful thing left to say.

This is the trust-boundary-adjacent half of the amendment: the wizard now leaves a **detached daemon**
behind it. It is recorded, checked by pid before being offered for removal, and offered only when the
process we recorded is still one we may signal — a reused pid number is treated as *not ours*.

### 10. A deployment is identified by the directory it was installed into

Amended 2026-08-25, on the owner's requirement: *"if I were to deploy it to my server, there are a
lot of different Postgres containers running, and it would be catastrophic if our script or our TUI
were to mess with any of them."*

Compose derives the project name from the compose file's own parent directory. Ours lives in
`infra/docker/`, so **every checkout on a machine resolved to the same project `docker`, the same
container `mosaera-postgres` and the same volume `docker_mosaera-pgdata`** — measured on a box with
thirteen of them. A `docker compose down --volumes` run from a scratch clone destroyed the real
install's database, and nothing on screen said which database was about to go.

Naming things explicitly is the wrong fix and was briefly the wrong answer here: an absolute
`name:`, `container_name:` or volume `name:` ignores the project entirely, which makes sharing
mandatory rather than accidental. So **nothing in `compose.yaml` is named absolutely**, and every
caller — the Makefile, `dev-up.sh`, the wizard's bring-up and its teardown — passes
`--project-directory <install root>`. The install directory becomes the identity: each deployment
owns exactly the container, network and volume carrying its own project prefix, and `make down` or
the wizard's uninstall can reach nothing else on the host.

**Red-teamed 2026-08-25, three attacks against the live daemon.** A compose file cannot destroy an
`external:` volume — Compose refuses, verified. The other two were breaches. `COMPOSE_PROJECT_NAME`
exported in a shell outranks every value Compose reads from a file, so a leftover export retargeted
`down --volumes` at another project entirely; every invocation now passes `-p` explicitly, whose
value comes from the install's own `.env` and never from the environment, and `-p` is the only
precedence level above the export. And `api.pid` is an integer in a file: pointing it at an
unrelated process got that process SIGTERMed and reported as success — a `sleep 900` was killed this
way — so the pid is now checked against `/proc` for a `mosaera-api` running out of this install, and
anything unverifiable fails closed. The derived name carries a digest of the install's real path, so
two checkouts sharing a directory basename are still separate.

`COMPOSE_PROJECT_NAME` in an install's own `.env` overrides the derived name — for two checkouts
sharing a directory name, or an install that predates this and must keep the volume it already has.
Compose reads that file from the project directory, so the identity lives with the install rather
than in the repository.

## Consequences

- The browser surface shrinks to a login form. `GET /preflight` and `guard_can_run` stay; the
  five-screen flow, `POST /auth/setup`, `POST /auth/setup/check` and `setup_steps_acked` go.
- A local process can now install packages and delete durable data. Both are gated on explicit,
  per-item consent, and the destructive one on a typed word — but the threat model gains an actor it
  did not have.
- macOS is a second-class path by construction: Docker Desktop is a signed application, so the
  wizard reports and links rather than installing.
- **Resume is derived, never restored.** A breadcrumb (`setup_progress`) records the step a run
  stopped on, and produces one sentence on the next run — "picking up where you left off". It selects
  no step and skips no check: the position always comes from probing the machine, because a stored
  "you were at images" is a lie the moment someone removes Docker in between.
- **The `setup_tokens` table (Alembic 0012) stays.** Dropping it earns nothing and costs a
  migration; the code that mints from it is what goes.

## Alternatives considered

- **Keep the browser flow and add a CLI beside it.** Rejected: two surfaces for one job, and the
  browser half still cannot do the thing setup exists to do.
- **Per-distro Docker packages instead of Docker's script.** Verified on Fedora: `docker` resolves to
  moby-engine and the compose plugin is packaged separately, so this needs a per-family matrix of
  engine *and* plugin names, and gets the daemon and group wrong by default.
- **Unattended install.** A piped script running `sudo` with no prompt is precisely what the original
  refusal was written against.
