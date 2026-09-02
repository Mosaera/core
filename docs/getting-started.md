# Getting started

Everything runs locally; there is no hosted service. **Linux** is the supported target; **macOS**
works; **Windows** means WSL2, run from inside the distro — see [Platform notes](#platform-notes).
*(Contributing? See [`onboarding/README.md`](onboarding/README.md).)*

## One command

```bash
curl -fsSL https://install.mosaera.dev | bash
```

It clones the newest release into `~/.mosaera/core`, builds the Python environment, and hands over
to **`mosaera-setup`** — a terminal wizard that installs what is missing *with your consent for each
item*, brings up the database, chooses the bind, creates your administrator account, and starts the
instance. It ends on a URL that resolves.

Two things it deliberately will not do. It **requires `git`** and installs no system packages
itself — that consent belongs in the wizard, and a script piped to a shell cannot ask for it
(ADR-0116). And it **installs exactly one thing**, `uv`, into `~/.local/bin` with no root, because
nothing Python can answer for itself until that exists — announced before it runs, and refusable
with `MOSAERA_NO_BOOTSTRAP=1` ([ADR-0117](adr/ADR-0117-the-one-liner-installs-uv-and-pins-a-tag.md)).

Re-running it updates you to the next release and changes nothing else: your `.env` is never
overwritten, and an install directory with uncommitted changes is left exactly where it is.

## From a clone instead

```bash
git clone <repo> && cd mosaera && uv run mosaera-setup
```

Or, once an instance is already configured, `make up` runs `scripts/dev-up.sh`: it picks a working
Docker CLI, builds the sandbox and scanner images if missing, starts Postgres + pgvector, builds the
dashboard, and runs the API, which serves it at one origin. Then open **http://localhost:8000**.

## Prerequisites

**You do not have to install these by hand** — the wizard offers each one, on this machine, with
the command it would run. The table is here so you know what it will ask for and why.

| Tool | Why | Who installs it |
|---|---|---|
| git | clones your projects, and Mosaera itself | **you** — it is the one thing the installer cannot bootstrap |
| uv | Python env + deps, and the interpreter itself | the installer, into `~/.local/bin`, no root |
| Docker | sandbox containers, Postgres | the wizard, via Docker's own script (the only one that brings the Compose v2 plugin). On macOS and WSL it points you at Docker Desktop, which is not ours to install |
| Node 20+ | builds the dashboard | the wizard, from your distribution's packages (`nodejs`, never `node` — that is a packet radio program) |
| Ollama | local model inference | you, if you want local models: <https://ollama.com> |

```bash
# The default local profile — Mosaera is BYOM, so swap any of these:
ollama pull gpt-oss:20b        # PM + Reviewer
ollama pull qwen3-coder:30b    # Coder
ollama pull nomic-embed-text   # embeddings (durable memory)
```

These are **defaults, not requirements**: point any role at any local or remote provider via
`MOSAERA_MODEL_*` (or the Settings UI). Models are **not** part of setup — they are chosen inside
the application, per agent, against what your endpoint actually grants (ADR-0116 §7).

## Hardware floor

| Path | Needs | What runs where |
|---|---|---|
| **On this machine only** | a GPU with roughly **12 GB+** for small models, **24–32 GB** for the defaults above | everything local; nothing you send leaves the box |
| **A hosted provider** | an API key, and network access | model inference is remote; the sandbox, Postgres and the dashboard still run locally |

Docker, ~10 GB of disk for the four sandbox images plus Postgres, and Linux are needed either way.
`mosaera doctor` checks all of it and prints the exact command for anything missing.

**What each preset means.** A preset is a routing *policy*, not a list of models we picked — it is
resolved against models you actually have:

| Preset | Policy |
|---|---|
| **On this machine only** | uses only models running here. Nothing you send can leave the box. |
| **Cheapest available** | prefers a local model; falls back to the cheapest you have configured. |
| **I'll choose** | you nominate the model per role. |

**Honestly: we do not rank models for you, and we could not if we wanted to.** Every capability
number this project publishes was measured on **one** binding (`qwen3-coder:30b` for the coder,
`gpt-oss:20b` elsewhere). There is no per-model comparison in `docs/engineering-history/`, so the
presets route on facts — where a model runs, and what it costs — and never on a claim about
quality. Running a different model may be better or worse; we have not measured it and will not
pretend otherwise.

## Checking a machine

```bash
uv run mosaera doctor        # every prerequisite, with the command that fixes each
uv run mosaera doctor --json # machine-readable, for scripting a fresh-machine install
```

It exits non-zero when something is genuinely broken. A missing database is reported as a
*heads-up*, not a failure — running without one is supported; you just lose history on restart.

### Proving a fresh machine works

`scripts/fresh-machine-check.sh` drives a clean box to "can run a task" without a browser:

```bash
git clone <repo> mosaera && cd mosaera
./scripts/fresh-machine-check.sh     # expect specific failures on a bare machine
# run each printed `fix`, then:
./scripts/fresh-machine-check.sh     # expect READY
uv run mosaera-setup                 # → creates the admin and starts the instance
```

It is report-only — it never installs a package, builds an image or pulls a model, because those
are multi-gigabyte decisions that belong to you. **This does not replace a real install by a real
person**, which is the only thing that proves the docs make sense to someone who did not write
them. It makes that person's pass a confirmation rather than a discovery.

## Run

```bash
git clone <repo> mosaera && cd mosaera
cp .env.example .env     # optional; defaults work
make up                  # → http://localhost:8000
```

Stop the API with `Ctrl+C`. Stop Postgres with `make down` (data persists in a Docker
volume).

## Configuration

All settings have working defaults; override via `.env` (copied from `.env.example`)
or real environment variables (which always win). The important ones:

| Variable | Default | Purpose |
|---|---|---|
| `MOSAERA_OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server |
| `MOSAERA_DB_URL` | _(set by `make up`)_ | Postgres for durable memory + History |
| `MOSAERA_SANDBOX` | `docker` | `docker` (hardened) or `subprocess` (fallback) |
| `MOSAERA_DOCKER_BIN` | _(auto)_ | Docker CLI; auto-detected, override if needed |
| `MOSAERA_API_PORT` | `8000` | API + dashboard port |
| `MOSAERA_API_HOST` | `127.0.0.1` | bind address; a non-loopback bind requires a token (below) |
| `MOSAERA_API_TOKEN` | _(unset)_ | service token — required for any public (non-loopback) bind; also a headless/API credential |
| `MOSAERA_ADMIN_TOKEN` | _(unset)_ | headless admin escape hatch (`X-Mosaera-Admin`) for config/secret writes |
| `MOSAERA_COOKIE_SECURE` | `0` | set `1` to mark the login cookie Secure (HTTPS-only) behind TLS |
| `MOSAERA_MODEL_*` | see `.env.example` | per-role model names |

Most operational config (budgets, iteration limits, the no-progress breaker, sandbox
and model-runtime tuning) is now managed in the dashboard **Settings** page (env still
overrides). Full env list: [`.env.example`](../.env.example).

## First run & login

- **No database → open.** With no `MOSAERA_DB_URL` and no `MOSAERA_API_TOKEN`, a loopback
  instance is open (dev default). `make up` sets `MOSAERA_DB_URL` (Postgres), which enables
  accounts.
- **With a database → create the admin (setup-token gated, ADR-0040).** On first start with a DB and
  no accounts, the server either **seeds the admin** from `MOSAERA_INITIAL_ADMIN_USER` /
  `MOSAERA_INITIAL_ADMIN_PASSWORD` (best for orchestrated deploys — no open window), or prints a
  **one-time setup token** to the startup logs (stderr) — or accepts an operator-supplied
  `MOSAERA_SETUP_TOKEN`. The dashboard's "create admin" screen then requires that token (it closes the
  first-admin race). The token has a **60-minute TTL** (`MOSAERA_SETUP_TOKEN_TTL`); a restart reissues
  it, and the endpoint self-locks once the admin exists. The admin adds up to 5 teammate accounts
  under **Settings → Users**. See the [user-management runbook](runbooks/user-management.md).
- **Exposing publicly.** A non-loopback `MOSAERA_API_HOST` still requires `MOSAERA_API_TOKEN`
  (and the Docker sandbox) — set up the admin on loopback first, then expose. Behind TLS, set
  `MOSAERA_COOKIE_SECURE=1`.

## Delivering a change

After an approved run with a commit, the delivery opens a reviewable **merge request** against the
configured remote — the run branch, with the delivery report as the description. It **never
merges**: a human reviews and merges.

**Both GitLab and GitHub deliver from the dashboard** (ADR-0112, ADR-0114). The Delivery page
states which provider a project's source implies and whether it can open a request at all, so a
project that cannot finish says so up front rather than at the finish line.

- **GitLab** — the project's own scoped token pushes and opens the merge request.
- **GitHub** — an admin registers a GitHub App once (`MOSAERA_GITHUB_APP_ID`,
  `MOSAERA_GITHUB_APP_PRIVATE_KEY`, `MOSAERA_GITHUB_APP_SLUG`), installs it on the repository, and
  presses **Connect** on the Delivery page. Each delivery then mints a fresh token scoped to that
  one repository, valid an hour and never stored. Two current limits, both shown on the page:
  **public repositories only** (a private GitHub clone cannot be authenticated yet) and one combined
  pull request per project rather than per-item ones.

Opening a request is **not** a graph-gated action (ADR-0102): the control is the authenticated
endpoint you call, or the explicit `auto_open_mr` opt-in. The CLI has its own GitHub draft-PR path
behind `--open-pr`, which confirms interactively — use `--pr-dry-run` to print the exact commands
first.

## Platform notes

### Linux (supported) · macOS (best-effort)

Native `docker` and Ollama at `localhost` — no special handling; `make up` just works. **Podman**
(rootless) is a drop-in: point `MOSAERA_DOCKER_BIN` at `podman`; the same `docker run` flags apply.

Linux is the environment the project is developed and tested on (Fedora since 2026-07-28). On
macOS the installer runs, and the wizard knows the two things that differ there: Docker Desktop is a
signed application it will not install for you, and `brew install …` is only offered when Homebrew
is actually present — it used to be offered regardless, then report *its own command* as the
failure. On Linux, one thing to watch: **SELinux** may require `:z`/`:Z` labels on container mounts
where another distro needs none.

### Windows (WSL2)

Run everything **inside the WSL2 shell**. Mosaera now knows it is there: `platform.system()` says
"Linux" under WSL and `/etc/os-release` is Ubuntu's, so until 2026-08-26 every piece of advice aimed
at it was native-Linux advice — `systemctl enable --now docker` on a distro with no systemd, and
"log out and back in" for a group that only takes effect after `wsl --shutdown`. Both are now
correct for WSL, and the machine screen says `(WSL)` so you can see it was recognised.

Docker has two legitimate routes here and the wizard names both rather than guessing: Docker Desktop
on Windows with WSL integration enabled for this distro (Settings → Resources → WSL Integration), or
`systemd=true` in `/etc/wsl.conf` and Docker Engine inside the distro.

Two mechanics `make up` still handles for you:

- **Docker**: if Desktop's WSL integration is not enabled, the on-PATH `docker` is a non-functional
  shim — the CLI is chosen by RUNNING each candidate, so `docker.exe` is used instead. That probe is
  deliberately not replaced by the WSL flag: only running it can tell a working CLI from a shim.
- **Ollama on the Windows host**: `localhost:11434` is not reachable from WSL, so `dev-up.sh` points
  at the host gateway automatically. The wizard does not do this yet — it has no model step at all —
  so set `MOSAERA_OLLAMA_BASE_URL` yourself if you configure models before your first `make up`.

Because `docker.exe` mounts Windows paths, keep the repo (and thus the default `.mosaera/`
workspace) under `/mnt/c` when you are on the `docker.exe` path.

**Not yet verified by anyone but the author.** The advice above is correct in code and covered by
tests; whether an install COMPLETES on macOS and WSL is an environment claim, and it is owed.

## Frontend development

To hot-reload the dashboard while editing `apps/web`:

```bash
make db-up            # Postgres
uv run mosaera-api    # API on :8000 (one terminal)
make web-dev          # Vite dev server on :5173, proxies the API (another terminal)
```

**Gotcha — the API serves the *built* bundle, not the source.** At `:8000` the API
serves `apps/web/dist/`, so UI changes only appear after a rebuild
(`npm --prefix apps/web run build`, or `make up`). Editing `apps/web/src` and
refreshing `:8000` shows nothing new until you rebuild — use the Vite dev server on
`:5173` for live editing. The API prints a startup warning when `dist/` is older
than `apps/web/src`.

## Troubleshooting

- **"No working Docker CLI"** — Docker isn't installed or the daemon isn't running.
  Start Docker Desktop / `dockerd`.
- **Run hangs at "PM · plan" / Ollama errors** — Ollama isn't reachable or the model
  isn't pulled. Check `MOSAERA_OLLAMA_BASE_URL` and `ollama list`.
- **History is empty** — durable memory needs Postgres; `make up` starts it. If running
  the API by hand, set `MOSAERA_DB_URL`.
- **Sandbox "daemon not reachable"** — Docker stopped, or on WSL the wrong CLI was
  chosen; set `MOSAERA_DOCKER_BIN=docker.exe`.
- **Rebuild the dashboard** after pulling changes: `make web-build`.
- **Reset a stuck run**: workspaces are disposable — delete `.mosaera/workspaces/<id>/`.
  The source repo is never modified.
