#!/usr/bin/env bash
# One Playwright smoke path (Phase 7) — build the SPA, boot a throwaway Postgres + the API
# with a seeded admin, run the browser test, tear everything down.
#
# WHY A REAL POSTGRES. The in-memory fallback (no MOSAERA_DB_URL) does not support user
# accounts at all — `/api/auth/status` reports `auth_required: false` and every request
# passes straight through, so a login screen never renders. Multi-user auth requires a real
# database (`apps/api/mosaera_api/routes/auth.py`), so this harness starts one in a
# throwaway, uniquely-named Docker container and tears it down unconditionally on exit —
# never the developer's own Postgres, never anything under docker compose's project name.
#
# WHY MOSAERA_HOME IS A TEMP DIR. CLAUDE.md's live-data rule: never let a process inherit a
# store from cwd. `Settings.home` defaults to cwd-relative `.mosaera`, so this always passes
# an explicit `MOSAERA_HOME` outside the repo tree (`mktemp -d`), and removes it on exit.
#
# Run: npm --prefix apps/web run e2e   (or directly: bash scripts/e2e-smoke.sh)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

API_PORT="${MOSAERA_E2E_API_PORT:-8734}"
DB_PORT="${MOSAERA_E2E_DB_PORT:-55432}"
CONTAINER="mosaera-e2e-pg-$$"
ADMIN_USER="e2e-admin"
ADMIN_PASSWORD="Playwright-Smoke-Run-$$-2026"

TMP_HOME="$(mktemp -d -t mosaera-e2e-home.XXXXXX)"
API_LOG="$(mktemp -t mosaera-e2e-api.XXXXXX.log)"
API_PID=""

log() { printf '[e2e-smoke] %s\n' "$*" >&2; }

cleanup() {
  local status=$?
  if [ -n "$API_PID" ] && kill -0 "$API_PID" 2>/dev/null; then
    log "stopping API (pid $API_PID)"
    kill "$API_PID" 2>/dev/null || true
    wait "$API_PID" 2>/dev/null || true
  fi
  log "removing throwaway Postgres container $CONTAINER"
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
  rm -rf "$TMP_HOME"
  if [ "$status" -ne 0 ]; then
    log "FAILED (exit $status). API log: $API_LOG"
  else
    rm -f "$API_LOG"
  fi
  exit "$status"
}
trap cleanup EXIT

if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
  log "BLOCKED: no working Docker daemon. Multi-user auth (step 2 of the smoke) needs a real"
  log "Postgres. Fix: install/start Docker, or point MOSAERA_DB_URL at any throwaway Postgres"
  log "and adapt this script to skip the container it starts here."
  exit 1
fi

log "starting throwaway Postgres ($CONTAINER) on 127.0.0.1:$DB_PORT"
docker run -d --name "$CONTAINER" \
  -e POSTGRES_USER=mosaera -e POSTGRES_PASSWORD=mosaera -e POSTGRES_DB=mosaera \
  -p "127.0.0.1:${DB_PORT}:5432" \
  pgvector/pgvector:pg16 >/dev/null

log "waiting for Postgres to accept connections"
# Two checks in a row, not one: the pgvector image's entrypoint does an initial bootstrap
# server that answers `pg_isready` briefly, then stops it and starts the real one — a single
# success right after the bootstrap window is not durable readiness.
pg_ready=0
for _ in $(seq 1 90); do
  if docker exec "$CONTAINER" pg_isready -U mosaera >/dev/null 2>&1; then
    sleep 1
    if docker exec "$CONTAINER" pg_isready -U mosaera >/dev/null 2>&1; then
      pg_ready=1
      break
    fi
  fi
  sleep 1
done
if [ "$pg_ready" -ne 1 ]; then
  log "Postgres never became durably ready"
  docker logs "$CONTAINER" 2>&1 | tail -n 40 >&2 || true
  exit 1
fi

export MOSAERA_DB_URL="postgresql://mosaera:mosaera@127.0.0.1:${DB_PORT}/mosaera"

log "applying migrations"
uv run python scripts/db_migrate.py

log "building the SPA"
# `npm run build` (tsc -b && vite build) currently fails on a pre-existing type error in
# src/test/runs-workbench.test.tsx (a test-file mock literal, unrelated to this harness and
# outside this agent's edit scope — see the e2e summary). vite build alone (esbuild
# transpile, no cross-file type-check) produces the same dist/ the API serves.
npm --prefix apps/web run build \
  || { log "npm run build failed (see the tsc note above) — falling back to vite build only"; \
       (cd "$ROOT/apps/web" && npx vite build); }

if [ ! -d "$ROOT/apps/web/dist" ]; then
  log "apps/web/dist missing after build"
  exit 1
fi

log "installing the Playwright chromium browser (idempotent)"
npx --prefix apps/web playwright install chromium

log "starting the API on 127.0.0.1:${API_PORT} (MOSAERA_HOME=$TMP_HOME)"
(
  cd "$ROOT" && \
  MOSAERA_HOME="$TMP_HOME" \
  MOSAERA_DB_URL="$MOSAERA_DB_URL" \
  MOSAERA_API_HOST=127.0.0.1 \
  MOSAERA_API_PORT="$API_PORT" \
  MOSAERA_INITIAL_ADMIN_USER="$ADMIN_USER" \
  MOSAERA_INITIAL_ADMIN_PASSWORD="$ADMIN_PASSWORD" \
  uv run mosaera-api
) >"$API_LOG" 2>&1 &
API_PID=$!

log "waiting for /healthz"
for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:${API_PORT}/healthz" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
if ! curl -fsS "http://127.0.0.1:${API_PORT}/healthz" >/dev/null 2>&1; then
  log "API never answered /healthz — tail of its log:"
  tail -n 60 "$API_LOG" >&2 || true
  exit 1
fi

log "running the Playwright smoke spec"
E2E_BASE_URL="http://127.0.0.1:${API_PORT}" \
E2E_ADMIN_USER="$ADMIN_USER" \
E2E_ADMIN_PASSWORD="$ADMIN_PASSWORD" \
npx --prefix apps/web playwright test --config="$ROOT/apps/web/playwright.config.ts"
