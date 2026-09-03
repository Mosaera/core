# infra/docker — sandbox worker images

The hardened container images the sandbox runs every tool command in (ADR-0001, ADR-0032,
TM-0001): a throwaway container per command that mounts a single run workspace read-write at
`/work`, runs as a non-root `sandbox` user (uid/gid 1000), read-only root filesystem,
`--cap-drop ALL`, `--security-opt no-new-privileges`, CPU/memory/pids limits, and a hard
wall-clock timeout. The test phase is always `--network none`; only the dependency-install
phase opens egress. These implement the `SandboxWorker` contract in
`packages/core/mosaera_core/sandbox/` (the `DockerSandbox` backend).

Each image's base is **digest-pinned**; a `LanguagePack` selects its image per plan via
`ValidationPlan.image` (Stage 1a). CODEOWNERS-gated (`/infra/`).

| Dockerfile | Tag | Base (digest-pinned) | For |
|---|---|---|---|
| `sandbox.Dockerfile` | `mosaera-sandbox:dev` | `python:3.12-slim-bookworm` | Python — the default image (`pytest`, `compileall`) |
| `sandbox-node.Dockerfile` | `mosaera-sandbox-node:dev` | `node:22-bookworm-slim` | Node/TS — `npm`/`pnpm`/`yarn` install, `tsc`, the test suite |
| `sandbox-sql.Dockerfile` | `mosaera-sandbox-sql:dev` | `postgres:16-bookworm` | SQL — an **ephemeral in-container Postgres** (initdb → pg_ctl → psql), network-off |
| `scan.Dockerfile` | `mosaera-scan:dev` | (see file) | the security scanners (semgrep/gitleaks) |

All four are built by `scripts/dev-up.sh` (first run only), the GitLab `sandbox-e2e` job
(blocking), and `infra/dev-server-bootstrap.sh`. GitHub CI builds the Python + scan images
only; the Node/SQL executed e2e tests (`packages/core/tests/test_langpack_e2e.py`) gate on
`docker_image_present`, so they run on GitLab + locally and skip cleanly where the image
isn't built.
