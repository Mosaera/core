"""Test-wide guards for the API suite.

THE ONE THAT MATTERS: the setup wizard's readiness probe falls back to
`postgresql://mosaera:mosaera@localhost:5432/mosaera` when no `MOSAERA_DB_URL` is set — and
`MemoryStore.open_or_reason` does not merely connect, it runs `alembic upgrade head`. So building a
`SetupApp` in a test opened and MIGRATED whatever real database happened to be listening on the
developer's machine.

Nothing was damaged (the live store was already at head), but that is a writable path from a test
run to live data, which is the failure this repository has already paid for once — see
`docs/engineering-history/evidence-store-loss-2026-08-10.md`. The tests point somewhere that cannot
exist instead.
"""

from __future__ import annotations

import pytest

#: Port 1 on loopback: refused instantly, reachable by nothing.
_NOWHERE = "postgresql://nobody:nobody@127.0.0.1:1/nowhere"


@pytest.fixture(autouse=True)
def _setup_tests_never_reach_a_real_store(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not request.module.__name__.rpartition(".")[2].startswith("test_setup"):
        return
    monkeypatch.setenv("MOSAERA_DB_URL", _NOWHERE)
