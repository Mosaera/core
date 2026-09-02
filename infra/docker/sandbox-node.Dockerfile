# Mosaera Node/TS sandbox worker image.
#
# The TS/JS counterpart to sandbox.Dockerfile: executes a cloned Node/TypeScript repo's
# validation (npm install -> tsc --noEmit -> the test suite) under the SAME hard isolation as
# the Python sandbox — --network none (test phase), --read-only root, resource caps, non-root
# user, and a single writable /work mount. See mosaera_core.languages.node.NodePack and
# docs/threat-models/TM-0001. Selected per-plan via ValidationPlan.image; Python repos keep
# sandbox.Dockerfile.
#
# Base pinned by digest for reproducibility (node:22-bookworm-slim). Refresh the digest
# deliberately; do not float the tag. Built by scripts/dev-up.sh, infra/dev-server-bootstrap.sh,
# and the .gitlab-ci.yml sandbox-e2e job (alongside the Python/scan images).
FROM node:22-bookworm-slim@sha256:6c74791e557ce11fc957704f6d4fe134a7bc8d6f5ca4403205b2966bd488f6b3

# git: repos import their VCS in test setup; ripgrep: search parity with the host tool. No
# build toolchain — native npm deps needing one are out of scope for the initial "Node CLIs +
# libraries" support; keep the attack surface small.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ripgrep \
    && rm -rf /var/lib/apt/lists/*

# Enable corepack so pnpm/yarn resolve from a project's `packageManager` field during the
# network-ON install phase (they are never invoked in the network-off test phase). npm ships
# with node.
RUN corepack enable

# The read-only container root means npm/pnpm/yarn caches must live on the writable /tmp tmpfs.
# NodePack also passes per-command cache flags; this is the belt-and-suspenders default.
ENV npm_config_cache=/tmp/.npm-cache

# Match the Python image's non-root "sandbox" user at uid/gid 1000 so DockerSandbox's default
# `--user sandbox` works across images. node:slim ships a uid-1000 "node" user; rename it (keeps
# uid/gid 1000, so bind-mounted /work stays writable exactly as with the Python image).
RUN groupmod -n sandbox node \
    && usermod -l sandbox -d /home/sandbox -m node

USER sandbox
WORKDIR /work

# No ENTRYPOINT: DockerSandbox supplies the full argv per invocation.
CMD ["/bin/bash"]
