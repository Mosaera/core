#!/usr/bin/env bash
# One-command local bring-up for Mosaera: detects your Docker CLI, builds the
# sandbox/scanner images if missing, starts Postgres, builds the dashboard, and
# runs the API (which serves the dashboard). Idempotent — safe to re-run.
#
#   ./scripts/dev-up.sh            # then open http://localhost:8000
#
# Prerequisites: Docker, uv (https://astral.sh/uv), Node 20+, and Ollama with the
# models pulled (see docs/runbooks/deployment.md).
set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
say() { printf '\033[38;5;214m▸\033[0m %s\n' "$*"; }
die() { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

# --- Docker CLI: pick one whose --version actually runs (the Docker Desktop WSL
# shim can be on PATH but non-functional when integration is off) ---
DOCKER=""
for c in docker docker.exe; do
  if command -v "$c" >/dev/null 2>&1 && "$c" --version >/dev/null 2>&1; then DOCKER="$c"; break; fi
done
[ -n "$DOCKER" ] || die "No working Docker CLI. Install Docker Desktop / Docker Engine and start it."
$DOCKER info >/dev/null 2>&1 || die "Docker CLI works but the daemon isn't reachable. Start Docker and retry."
say "docker: $DOCKER"

command -v uv  >/dev/null 2>&1 || die "uv not found — install from https://astral.sh/uv"
command -v npm >/dev/null 2>&1 || die "node/npm not found — install Node 20+"

# Load .env so its settings (Ollama URL, DB port/URL, ports) drive this script,
# docker compose, and the API — not just the app. Real env vars still win.
if [ -f .env ]; then
  say "using .env"
  set -a; . ./.env; set +a
fi

# --- WSL: reach Ollama on the Windows host if localhost is unreachable ---
if grep -qiE "microsoft|wsl" /proc/version 2>/dev/null; then
  if [ -z "${MOSAERA_OLLAMA_BASE_URL:-}" ] \
     && ! curl -sf --max-time 2 http://localhost:11434/api/version >/dev/null 2>&1; then
    gw="$(ip route show default | head -1 | awk '{print $3}')"
    [ -n "$gw" ] && export MOSAERA_OLLAMA_BASE_URL="http://${gw}:11434" \
      && say "WSL detected → Ollama at $MOSAERA_OLLAMA_BASE_URL"
  fi
fi
OLLAMA_URL="${MOSAERA_OLLAMA_BASE_URL:-http://localhost:11434}"

# --- Python deps ---
say "syncing Python deps…"
uv sync --all-packages >/dev/null

# --- sandbox + scanner images ---
for img in sandbox sandbox-node sandbox-sql scan; do
  tag="mosaera-${img}:dev"
  if ! $DOCKER image inspect "$tag" >/dev/null 2>&1; then
    say "building ${tag} (first run only)…"
    $DOCKER build -f "infra/docker/${img}.Dockerfile" -t "$tag" . >/dev/null
  fi
done

# --- Postgres (durable memory) ---
# One knob for the host port (MOSAERA_DB_PORT) drives both the published port
# and the connection URL, so they can't drift out of sync.
export MOSAERA_DB_PORT="${MOSAERA_DB_PORT:-5432}"
export MOSAERA_DB_URL="${MOSAERA_DB_URL:-postgresql://mosaera:mosaera@localhost:${MOSAERA_DB_PORT}/mosaera}"
say "starting Postgres (host port ${MOSAERA_DB_PORT})…"
# `--project-directory .` scopes this deployment to the directory it lives in: its container,
# network and volume all carry that project prefix, and it can neither see nor remove another
# install's. Run from the repo root, which is where the Makefile invokes this from.
$DOCKER compose --project-directory . -f infra/docker/compose.yaml up -d >/dev/null

# --- dashboard build ---
if [ ! -f apps/web/dist/index.html ]; then
  say "building the dashboard…"
  npm --prefix apps/web install --silent
  npm --prefix apps/web run build --silent
fi

# --- readiness: delegate to `mosaera doctor` (#119) ---
# This block used to check a HARDCODED `gpt-oss:20b qwen3-coder:30b nomic-embed-text`, so an
# operator who rebound a role got a green note about a model nothing uses and no warning about the
# one that was actually missing. `doctor` derives the required set from the ACTIVE bindings and is
# the same module the first-run wizard and the launch refusal read — one origin for "is this
# deployment ready". Advisory here on purpose: bring-up continues so the operator can reach the
# setup screen and fix it there.
MOSAERA_OLLAMA_BASE_URL="$OLLAMA_URL" uv run --no-sync mosaera doctor || \
  say "some checks did not pass (above) — the setup screen will walk you through them"

export MOSAERA_DOCKER_BIN="${MOSAERA_DOCKER_BIN:-$DOCKER}"
# Loopback by default: the API runs code + holds tokens and has no auth unless
# MOSAERA_API_TOKEN is set. Bind to a public interface only deliberately (and
# with a token — the server refuses an unauthenticated public bind).
HOST="${MOSAERA_API_HOST:-127.0.0.1}"
PORT="${MOSAERA_API_PORT:-8000}"
printf '\n\033[38;5;214m  Mosaera is ready → http://localhost:%s\033[0m\n' "$PORT"
printf '  Ctrl+C stops the API. Postgres keeps running (\x60make down\x60 to stop it).\n\n'
MOSAERA_API_HOST="$HOST" MOSAERA_API_PORT="$PORT" exec uv run mosaera-api
