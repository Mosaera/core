# Mosaera sandbox worker image.
#
# Minimal, non-root image used to execute agent tool commands (notably the test
# suite of a cloned repo) with hard isolation: the container is run with
# --network none, --read-only, resource caps, and a single writable mount at
# /work (the run workspace). See mosaera_core.sandbox.DockerSandbox and
# docs/threat-models/TM-0001-mosaera-lite-repo-agent.md.
#
# Base pinned by digest for reproducibility (python:3.12-slim-bookworm).
# Refresh the digest deliberately; do not float the tag.
FROM python:3.12-slim-bookworm@sha256:8a7e7cc04fd3e2bd787f7f24e22d5d119aa590d429b50c95dfe12b3abe52f48b

# git: repos frequently import their VCS in test setup; ripgrep: fast search
# parity with the host tool. No build toolchain — keep the attack surface small.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ripgrep \
    && rm -rf /var/lib/apt/lists/*

# pytest is the sandbox's primary job (running a cloned repo's suite). Repos with
# third-party deps are handled by the install phase (mosaera_core.validation):
# `python -m venv --system-site-packages .venv` layers the repo's deps on top of
# this pinned pytest, installed with network ON (run_setup) — the TEST phase then
# runs `.venv/bin/python -m pytest` with --network none. So this stays the pinned
# system pytest the venv reuses.
#
# coverage: the change-coverage oracle (oracle-make-real #29) runs the suite via
# `coverage run -m pytest` with per-test dynamic contexts, so the sandbox needs it
# alongside pytest (same --system-site-packages reuse). The HOST then reads the
# resulting .coverage to build the code↔test map. Pinned to match the core dep.
RUN pip install --no-cache-dir pytest==8.3.4 coverage==7.15.2

# Non-root user owning the workspace mount. UID/GID 1000 matches the common
# host developer UID so bind-mounted files stay writable.
RUN groupadd --gid 1000 sandbox \
    && useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash sandbox

USER sandbox
WORKDIR /work

# No ENTRYPOINT: DockerSandbox supplies the full argv per invocation.
CMD ["/bin/bash"]
