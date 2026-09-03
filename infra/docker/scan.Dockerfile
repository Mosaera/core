# Mosaera scanner image — runs security scanners over a cloned workspace inside
# the same hardened sandbox as test execution (--network none, read-only root,
# non-root user, /work mount). Kept separate from sandbox.Dockerfile so scanner
# tooling does not bloat the test-execution image.
#
# Ships Gitleaks (secrets) and Semgrep (SAST). Trivy (deps/IaC) is the next
# same-interface addition (mosaera_core.tools.scan.Scanner); see that module.
FROM debian:bookworm-slim@sha256:60eac759739651111db372c07be67863818726f754804b8707c90979bda511df

ARG GITLEAKS_VERSION=8.30.1
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && curl -fsSL \
        "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz" \
        -o /tmp/gitleaks.tar.gz \
    && tar -xzf /tmp/gitleaks.tar.gz -C /usr/local/bin gitleaks \
    && rm /tmp/gitleaks.tar.gz \
    && rm -rf /var/lib/apt/lists/* \
    && gitleaks version

# Semgrep (SAST), installed via pip (curl kept for gitleaks above, purged after).
ARG SEMGREP_VERSION=1.97.0
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip \
    && pip3 install --no-cache-dir --break-system-packages "semgrep==${SEMGREP_VERSION}" \
    && apt-get purge -y curl \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/* \
    && semgrep --version

# Vendored local ruleset — the scan sandbox is --network none, so no `p/`
# registry or `auto` config can be fetched; semgrep runs `--config` this dir.
COPY infra/semgrep-rules/ /etc/semgrep-rules/

# The sandbox root is read-only with only /tmp (tmpfs) + /work writable, so point
# semgrep's home/cache at /tmp and hard-disable its phone-home paths.
ENV HOME=/tmp \
    SEMGREP_SEND_METRICS=off \
    SEMGREP_ENABLE_VERSION_CHECK=0

RUN groupadd --gid 1000 sandbox \
    && useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash sandbox

USER sandbox
WORKDIR /work
CMD ["gitleaks", "version"]
