"""Mosaera core: config, model gateway, sandbox, repo tools, orchestrator, CLI."""

from typing import Final

# THE engine version (ADR-0055). Single runtime source of truth — stamped into the reliability
# scoreboard trend, run reports, the API /config, and `mosaera --version`, so every measured
# outcome is attributable to the engine that produced it. 0.x maturity-anchored (0.5.0 = the first
# MEASURED release: scoreboard live). Post-0.6.0 a completed ARC bumps PATCH (ADR-0055 amendment
# 2026-07-23); MINOR/MAJOR are rationed toward 1.0 = SWE-team production-stable (the four measured
# ADR-0061 gates). Keep in lockstep with the workspace pyproject versions + apps/web/package.json —
# `uv run python scripts/bump_version.py` moves them together.
__version__: Final[str] = "0.6.3"

# THE engine maturity channel (ADR-0088) — a SEPARATE axis from the number, because a maturity
# label is not a version fact: 0.6.0 says "how far", `beta` says "how much you may trust it".
# Ladder (criteria first, label read off them — never the reverse):
#   alpha  — runs end-to-end, outcomes NOT measured on a held-out benchmark
#   beta   — outcomes measured on a held-out benchmark with published snapshots; trust boundary and
#            honest terminal outcomes enforced; NOT production-authorized
#   rc     — 3 of the 4 ADR-0061 v1.0 gates green on one held-out run
#   stable — all four green; ships as 1.0.0
# Advancing this requires the same evidence a version bump does: a CHANGELOG benchmark snapshot
# naming the suite, run count, and posture configuration. Kept OUT of the run-seal preimage on
# purpose (ADR-0088 Consequences) — adding it would rewrite every receipt id.
__maturity__: Final[str] = "beta"

# The closed set the ladder allows. Guarded by tests/test_cli_version.py.
MATURITY_CHANNELS: Final[tuple[str, ...]] = ("alpha", "beta", "rc", "stable")
