#!/usr/bin/env bash
# Mosaera dev/CI host bootstrap (Linux).
#
# Provisions a self-hosted server that (a) runs Mosaera for dev/hosting and/or
# (b) hosts a GitLab runner for this repo's CI — including the `sandbox-e2e`
# integration job, which needs Docker able to bind-mount the test workspace.
#
# This is INFRASTRUCTURE maintenance for operators — NOT the "try Mosaera"
# path. End users want `scripts/install.sh` (curl | bash) instead.
#
#   sudo bash infra/dev-server-bootstrap.sh            # do safe setup + print guidance
#   sudo bash infra/dev-server-bootstrap.sh --install-docker   # also install Docker Engine
#   bash infra/dev-server-bootstrap.sh --print-only    # just print the config/notes
#
# Idempotent: re-running only re-applies the shared tmp dir and re-prints notes.
set -euo pipefail

SHARED_TMP="/srv/mosaera-ci-tmp"
INSTALL_DOCKER=0
PRINT_ONLY=0

say()  { printf '\033[38;5;214m▸\033[0m %s\n' "$*"; }
warn() { printf '\033[33m! %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }
hr()   { printf '\033[2m%s\033[0m\n' "────────────────────────────────────────────────────────────"; }

usage() {
  sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
}

for arg in "$@"; do
  case "$arg" in
    --install-docker) INSTALL_DOCKER=1 ;;
    --print-only)     PRINT_ONLY=1 ;;
    -h|--help)        usage ;;
    *) die "unknown flag '$arg' (see --help)" ;;
  esac
done

[ "$(uname -s)" = "Linux" ] || die "This bootstrap targets Linux servers."

need_root() {
  [ "$(id -u)" -eq 0 ] || die "This step needs root. Re-run with sudo (or use --print-only)."
}

# ── 1. Docker daemon ─────────────────────────────────────────────────────────
ensure_docker() {
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    say "Docker daemon present and reachable."
    return
  fi
  if [ "$INSTALL_DOCKER" -eq 1 ]; then
    need_root
    say "installing Docker Engine via get.docker.com…"
    curl -fsSL https://get.docker.com | sh
    systemctl enable --now docker
    say "Docker installed and enabled."
  else
    warn "Docker is not installed / not running."
    warn "Install it with your package manager or the official script, then re-run:"
    warn "    curl -fsSL https://get.docker.com | sh && sudo systemctl enable --now docker"
    warn "Or re-run this script with --install-docker to do it for you."
    warn "Docs: https://docs.docker.com/engine/install/"
  fi
}

# ── 2. Shared tmp dir for sandbox-e2e bind mounts ────────────────────────────
# The sandbox tests run `docker run -v <workspace>:/work`. With a docker-socket
# runner (below), that <workspace> path must be identical on the host and inside
# the job container, so the host daemon can resolve the bind mount. We pin the
# job's TMPDIR to this shared host dir; the sandbox's _mountable_workdir() then
# creates workspaces under a path the daemon can actually see.
ensure_shared_tmp() {
  need_root
  if [ -d "$SHARED_TMP" ]; then
    say "shared tmp dir already exists: $SHARED_TMP"
  else
    install -d -m 1777 "$SHARED_TMP"
    say "created shared tmp dir: $SHARED_TMP (mode 1777)"
  fi
}

# ── 3. GitLab runner config (docker-socket) ──────────────────────────────────
print_runner_config() {
  hr
  say "GitLab runner — docker-socket config (register a runner, then edit /etc/gitlab-runner/config.toml):"
  cat <<'TOML'

  [[runners]]
    name = "mosaera-ci"
    url  = "https://gitlab.rengifo.me/"
    token = "<runner-token-from-registration>"
    executor = "docker"
    builds_dir = ""            # default is fine
    [runners.docker]
      image = "python:3.12"
      # Bind the HOST Docker socket so `docker` in the job drives the host
      # daemon (sibling containers), and share the tmp dir at an IDENTICAL path
      # so `-v <workspace>:/work` resolves on the daemon's filesystem.
      volumes = [
        "/var/run/docker.sock:/var/run/docker.sock",
        "/srv/mosaera-ci-tmp:/srv/mosaera-ci-tmp",
        "/cache",
      ]
TOML
  echo
  say "…then restart the runner:  sudo gitlab-runner restart"
  echo
  say "Paired .gitlab-ci.yml change for the sandbox-e2e job (drop dind, use the socket):"
  cat <<'YAML'

  sandbox-e2e:
    stage: integration
    image: python:3.12
    services:
      - name: postgres:16
        alias: postgres
    variables:
      MOSAERA_DOCKER_BIN: docker
      TMPDIR: /srv/mosaera-ci-tmp        # shared host path → bind mounts resolve
      POSTGRES_USER: mosaera
      POSTGRES_PASSWORD: mosaera
      POSTGRES_DB: mosaera_test
      MOSAERA_TEST_DB_URL: postgresql://mosaera:mosaera@postgres:5432/mosaera_test
    # A BLOCKING gate (validated green on the socket runner) — no allow_failure.
    before_script:
      - apt-get update && apt-get install -y --no-install-recommends docker-cli git ripgrep
      - pip install uv
      - docker build -t mosaera-sandbox:dev -f infra/docker/sandbox.Dockerfile .
      - docker build -t mosaera-sandbox-node:dev -f infra/docker/sandbox-node.Dockerfile .
      - docker build -t mosaera-sandbox-sql:dev -f infra/docker/sandbox-sql.Dockerfile .
      - docker build -t mosaera-scan:dev   -f infra/docker/scan.Dockerfile .
      - uv sync --all-packages
    script:
      - uv run pytest packages/core packages/memory apps/api
YAML
}

# ── 4. sandbox-e2e warning ───────────────────────────────────────────────────
print_sandbox_warning() {
  hr
  warn "sandbox-e2e: why it needs the docker-socket runner (now a blocking gate)"
  cat <<'TXT'
  The @requires_docker tests bind-mount a workspace into /work. Under
  docker-in-docker (dind), that workspace lives only in the JOB container, which
  the separate dind daemon cannot see — so the mount is empty and the tests fail.
  The docker-socket runner above fixes this: the job talks to the host daemon,
  and TMPDIR=/srv/mosaera-ci-tmp (shared into the job at the same path) makes the
  bind mount resolve. sandbox-e2e is now a BLOCKING merge gate (no allow_failure);
  it also builds the per-language images (node/sql) that the LanguagePack e2e runs on.
TXT
}

# ── 5. Firewall / bind-host + API token ──────────────────────────────────────
print_network_notes() {
  hr
  say "Networking: firewall, bind host, and the API token"
  cat <<'TXT'
  The API binds to 127.0.0.1 by default (loopback = the trust boundary). To reach
  it from other machines you must bind a public interface AND set a token:

    MOSAERA_API_HOST=0.0.0.0
    MOSAERA_API_TOKEN=$(openssl rand -hex 32)   # REQUIRED for any non-loopback bind
    MOSAERA_SANDBOX=docker                        # required for a public bind

  The server REFUSES a non-loopback bind without a token (it runs code and holds
  repository tokens). The dashboard then shows a login screen; paste the token.

  Firewall: expose ONLY what you need. Prefer keeping the API on loopback and
  reaching it over an SSH tunnel or a reverse proxy (TLS) rather than opening
  8000 to the world. If you must open it, restrict the source:

    sudo ufw allow from <trusted-cidr> to any port 8000 proto tcp
    # and DENY 8000 from anywhere else; do not `ufw allow 8000` unqualified.

  Postgres (5432) and Ollama (11434) should never be world-reachable — bind them
  to localhost / the private network only.
TXT
}

# ── 6. Security warning (must read) ──────────────────────────────────────────
print_security_warning() {
  hr
  printf '\033[31m'
  cat <<'TXT'
  SECURITY — docker-socket runner is TRUSTED-REPO ONLY.
  Mounting /var/run/docker.sock into CI jobs gives those jobs full control of the
  host Docker daemon, which is equivalent to ROOT on this server. Any code that
  runs in the pipeline (tests, dependencies, a malicious MR) can take over the box.

  Only use this runner for repositories and merge requests you trust. Do NOT
  enable it for public forks or untrusted contributors. Keep this host dedicated
  and isolated; do not co-host anything sensitive on it. If you need to run
  untrusted CI, use an ephemeral/isolated runner (VM per job, or a rootless/
  dind-in-VM setup) instead of the host socket.
TXT
  printf '\033[0m'
}

main() {
  say "Mosaera dev/CI host bootstrap"
  if [ "$PRINT_ONLY" -eq 0 ]; then
    ensure_docker
    ensure_shared_tmp
  else
    say "--print-only: skipping any changes; printing guidance only."
  fi
  print_runner_config
  print_sandbox_warning
  print_network_notes
  print_security_warning
  hr
  say "Done. Review the runner config + security warning above before enabling CI."
}

main "$@"
