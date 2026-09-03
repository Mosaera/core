# Language-agnostic command contract (see coding-standards.md).
# Implemented over uv + ruff + mypy + pytest. CI calls exactly these targets.

.PHONY: bootstrap fmt fmt-check lint check-sizes check-imports check-docs check-liveness \
	check-doc-claims typecheck test build ci \
        run bench bench-all bench-compare \
        clean up down db-up db-down db-migrate web-install web-dev web-build

bootstrap:
	uv sync --all-packages

fmt:
	uv run ruff format .

fmt-check:
	uv run ruff format --check .

lint: check-sizes check-imports check-docs check-liveness check-doc-claims check-state-keys check-migration-chain
	uv run ruff check .

# Migration-chain guard: fail if the Alembic revisions are not ONE linear chain with ONE head.
# Two parallel sessions each add a migration chaining the current head; the FILENAMES differ, so
# git merges both with no conflict and the repo silently gets two heads. The schema-drift test
# that would notice is requires_db-gated and skips on `make test` (ADR-0114).
# See scripts/check_migration_chain.py.
check-migration-chain:
	uv run python scripts/check_migration_chain.py

# God-file guard: fail if a source module grows past the modularity ceiling (500 lines).
# Blocks NEW god-files; existing over-limit modules are grandfathered + being worked down.
# See scripts/check_file_sizes.py and coding-standards.md 'Modularity'.
check-sizes:
	uv run python scripts/check_file_sizes.py

# RunState key guard: fail if production code reads a key RunState does not declare. LangGraph
# DROPS undeclared keys (ADR-0026), so such a read is a permanent empty value that never errors —
# the quietest bug shape this repo produces (F66, and two more found by the 2026-08-07 audit).
# See scripts/check_state_keys.py.
check-state-keys:
	uv run python scripts/check_state_keys.py

# Layer-boundary guard: fail if a package imports ACROSS the one-way dependency graph
# (a lower layer reaching up — e.g. core -> agents). Blocks NEW crossings; the known DI
# debt is grandfathered + being worked down. See scripts/check_layer_imports.py.
check-imports:
	uv run python scripts/check_layer_imports.py

# Doc-link guard: fail if a Markdown file has a broken relative link, so the governed
# doc set (see docs/README.md) stays navigable as files move. See scripts/check_doc_links.py.
check-docs:
	uv run python scripts/check_doc_links.py

# Control-liveness guard (ADR-0081): fail if a posture knob has no liveness record, if a NEW
# posture knob sits below C4, or if a registry row cites a test that does not exist. Was
# report-only and wired nowhere, so the guard against controls-that-cannot-fire could not
# itself fire. See scripts/check_control_liveness.py.
check-liveness:
	uv run python scripts/check_control_liveness.py

# Doc-claims guard: fail where a DOCUMENTED claim contradicts another fact already in this repo —
# an ADR cited by shipped code while claiming to be unbuilt, a reference to an ADR that does not
# exist, an index row disagreeing with its file, one-way supersession, or a documented `make lint`
# contract that does not match this Makefile. Never judges prose; only reports two facts that
# disagree. Built after two findings turned out to be rediscoveries of knowledge already written
# down (2026-08-06). See scripts/check_doc_claims.py.
check-doc-claims:
	uv run python scripts/check_doc_claims.py

typecheck:
	uv run mypy packages apps

test:
	uv run pytest

build:
	uv build --all-packages

# The full merge gate as ONE target, so the CI files can't drift from the local contract —
# the M1 root cause was GitLab inlining these steps and silently dropping the god-file guard.
# Both .gitlab-ci.yml (the live gate) and .github/workflows/ci.yml call `make ci`, never the
# individual commands, so a new gate (a guard, a step) is added in exactly one place.
ci: fmt-check lint typecheck test build

# Usage: make run REPO=/path/to/repo TASK="make the failing test pass"
run:
	uv run mosaera run --repo "$(REPO)" --task "$(TASK)"

# Usage: make bench MCB-01
# Capability benchmark (NS-3): runs the governed loop over a fixed brief, grades
# the delivered code, and writes a scorecard. Heavy + opt-in — needs a model + a
# Docker daemon, and is NOT part of `make test`. See packages/core/mosaera_core/bench.
bench:
	uv run mosaera-bench $(filter-out bench,$(MAKECMDGOALS))

# Usage: make bench-all           — run every benchmark case
# Usage: make bench-compare MCB-01 — run (x3, averaged) and diff vs the committed
#   baseline; exits non-zero on a regression. The regression net for releases.
bench-all:
	uv run mosaera-bench --all

bench-compare:
	uv run mosaera-bench $(filter-out bench-compare,$(MAKECMDGOALS)) --compare

# The case id (e.g. MCB-01) rides as a goal to `make bench*`; swallow it as a no-op
# so make doesn't try to build it as its own target.
MCB-%:
	@:

clean:
	rm -rf dist .pytest_cache .mypy_cache .ruff_cache

# Docker CLI, auto-detected: a working `docker` (its --version runs), else the
# Windows `docker.exe` (WSL without native integration — the on-PATH `docker`
# shim is non-functional there). Override with `make <t> DOCKER=podman`.
DOCKER ?= $(shell docker --version >/dev/null 2>&1 && echo docker || echo docker.exe)

# One-command local bring-up (build images, start DB, build web, run API).
up:
	bash scripts/dev-up.sh

# Stop the bundled services (the API is stopped with Ctrl+C).
#
# `-p` comes from THIS install's .env, where setup records it. It outranks any ambient
# COMPOSE_PROJECT_NAME, which would otherwise retarget `make down` at somebody else's project — a
# leftover export in a shell is enough to do that.
COMPOSE_PROJECT := $(shell sed -n 's/^COMPOSE_PROJECT_NAME=//p' .env 2>/dev/null | head -1 | sed 's/^/-p /')

# `--project-directory .` on every compose call is what scopes a deployment to the directory it was
# installed into. Without it Compose derives the project from the compose file's own parent —
# `docker` — so every checkout on a machine shared one container, one network and one volume, and a
# `down --volumes` in a scratch clone erased the real install's database.
down:
	-$(DOCKER) compose $(COMPOSE_PROJECT) --project-directory . -f infra/docker/compose.yaml down

db-up:
	$(DOCKER) compose $(COMPOSE_PROJECT) --project-directory . -f infra/docker/compose.yaml up -d

db-down:
	$(DOCKER) compose $(COMPOSE_PROJECT) --project-directory . -f infra/docker/compose.yaml down

# Apply Alembic migrations to head. Alembic is driven programmatically (no alembic.ini),
# so this runs scripts/db_migrate.py, not the bare `alembic` CLI. Needs MOSAERA_DB_URL.
db-migrate:
	uv run python scripts/db_migrate.py

# Web dashboard (apps/web, Vite + React). Node-only; separate from Python gates.
# The built dist/ is served by the API (mosaera-api) at the same origin.
web-install:
	npm --prefix apps/web install

web-dev:
	npm --prefix apps/web run dev

web-build:
	npm --prefix apps/web run build
