"""Deployment readiness over HTTP — what the degradation banner renders (#119).

The same `mosaera_core.preflight` module the `mosaera doctor` CLI prints and the launch endpoints
refuse on. One origin, three readers, so the banner, the CLI and a refused run cannot tell an
operator three different stories about one instance.

THIS OUTLIVED THE FIRST-RUN FLOW IT WAS BUILT FOR (ADR-0116). `GET /preflight` is polled by
`SetupBanner` inside the authenticated shell, every minute, for every signed-in user — it reports a
backend that went away long after setup, which is a running instance's concern and not a new one's.
The three routes that WERE first-run only — `/setup/presets`, `/setup/state` and the
`/setup/ack/{step}` record — went with the flow.

**Read-only, and secret-safe by construction.** Nothing here writes config — the wizard's writes go
through the endpoints that already own them (`PUT /providers`, `PUT /cost-modes`, `POST
/providers/test`), each already admin-gated. And no check ever returns a key: `preflight` reports
whether a key is PRESENT and whether the provider ACCEPTED it, never the value and not even a
masked hint.

Session-authenticated rather than admin-gated: this is the screen a stranger needs before they can
do anything, it discloses no secret, and locking it behind the admin tier would leave a member
staring at an instance that silently cannot run.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from mosaera_core.config import Settings
from mosaera_core.preflight import config_gap, run_preflight


def make_preflight_router() -> APIRouter:
    api = APIRouter()

    @api.get("/preflight")
    def preflight(verify: bool = True) -> dict[str, Any]:
        """Every readiness check, the discovered inventory, and the single `can_run` verdict.

        ``verify=false`` skips the provider key round-trip — the wizard uses it while the operator
        is still typing, so a half-entered key is not sent anywhere, and re-checks with
        verification when they commit.
        """
        return run_preflight(Settings.from_env(), verify_keys=verify).as_dict()

    return api


def guard_can_run() -> None:
    """Refuse a launch on an instance with no model backend, naming what is missing (#119).

    An unconfigured instance used to ACCEPT a run and fail somewhere downstream — the
    silent-degradation shape this issue exists to close. A refusal beats a disabled button: a
    disabled control tells the operator less than an error naming the cause and the fix.

    Uses `config_gap`, NOT the wizard's `can_run`: the launch path must be network-free (see that
    function for why — it costs latency, it lets a blip refuse a real run, and it would make the
    test suite depend on whether the machine happens to be running Ollama). Reachability is the
    setup screen's question and the run's own loud failure, not this guard's.

    Lives here rather than in either router so `runs` and `backlog` share one definition — a copy
    per caller is how two endpoints end up disagreeing about whether the same box can run.
    """
    gap = config_gap(Settings.from_env())
    if gap:
        raise HTTPException(
            status_code=503,
            detail=(
                f"this instance is not set up to run: {gap} — "
                "finish setup (Settings \u2192 Models), or run `mosaera doctor` for the fix"
            ),
        )
