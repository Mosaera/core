# Mosaera SQL sandbox worker image.
#
# Runs a cloned SQL project's validation — apply schema/migrations to an EPHEMERAL Postgres
# booted INSIDE the container (data dir + socket on the writable /tmp tmpfs), then run assertion
# queries — under the SAME hard isolation as the other sandboxes: --network none (the DB is a
# local unix socket, no sidecar), --read-only root, --cap-drop ALL, non-root user, single /work
# mount. Proven feasible by the sandbox spike (initdb -> pg_ctl start -> psql all succeed under
# those flags). See mosaera_core.languages.sql.SqlPack and docs/threat-models/TM-0001. Selected
# per-plan via ValidationPlan.image; the Python/Node repos keep their own images.
#
# Base pinned by digest for reproducibility (postgres:16-bookworm). Refresh deliberately; do not
# float the tag. Built by scripts/dev-up.sh, infra/dev-server-bootstrap.sh, and the .gitlab-ci.yml
# sandbox-e2e job (alongside the Python/Node/scan images). Threat-model note (TM-0001): a database
# engine now runs in the sandbox — but strictly local (unix socket in /tmp), ephemeral (torn down
# with the --rm container), and network-off; containment is unchanged, only the in-image binary
# surface grows.
FROM postgres:16-bookworm@sha256:53acb9d8524ff2f66d4fb81a964365027ccc275411d4d83d71e9266aa48535d9

# git: repos import their VCS in setup; ripgrep: search parity. Postgres (initdb/pg_ctl/psql)
# ships in the base image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ripgrep \
    && rm -rf /var/lib/apt/lists/*

# A non-root "sandbox" user at uid/gid 1000 (matches the Python/Node images so DockerSandbox's
# default --user works across images). The postgres base's own "postgres" user is uid 999, so
# 1000 is free. initdb/pg_ctl refuse to run as root but are happy as any non-root user; the DB
# superuser is a separate Postgres role ("app"), created by SqlPack at validation time.
RUN groupadd --gid 1000 sandbox \
    && useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash sandbox

USER sandbox
WORKDIR /work

# No ENTRYPOINT (the postgres base sets one — override it) so DockerSandbox supplies the full
# argv per invocation, exactly like the other sandbox images.
ENTRYPOINT []
CMD ["/bin/bash"]
