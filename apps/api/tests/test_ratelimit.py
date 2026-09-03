"""Per-credential rate limiting + the daily run quota (#34, ADR-0050).

Almost all of this runs with no database: the limiter is a leaf, so the window is a pure unit and
the quota's store call is duck-typed. The atomic-consume behaviour that genuinely needs Postgres
lives in ``packages/memory/tests/test_quota.py`` (DB-gated, self-skipping).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mosaera_api.auth import SESSION_COOKIE, hash_token
from mosaera_api.ratelimit import (
    RUN_CREATE_PATH,
    _FixedWindow,
    _seconds_to_utc_midnight,
    install_rate_limit,
    load_config,
)

_TOKEN = "service-token-value"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """No stray limit config leaks in from the developer's shell — and, since #37, the quota is
    read via ``Settings.from_env()`` (env > stored > default), so point ``MOSAERA_HOME`` at an empty
    tmp dir too, or a real ``.mosaera/settings.json`` in the cwd would leak a stored quota in."""
    monkeypatch.delenv("MOSAERA_RATE_LIMIT_PER_MIN", raising=False)
    monkeypatch.delenv("MOSAERA_RUN_QUOTA_PER_DAY", raising=False)
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))


# --- config: env-only, bounded, loud on nonsense ---


def test_config_defaults_rate_on_quota_off() -> None:
    cfg = load_config()
    assert cfg.per_min == 300  # a runaway client is the common failure -> protected by default
    assert cfg.quota_per_day == 0  # a fairness POLICY has no safe universal default
    assert cfg.enabled is True


def test_config_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOSAERA_RATE_LIMIT_PER_MIN", "10")
    monkeypatch.setenv("MOSAERA_RUN_QUOTA_PER_DAY", "5")
    assert load_config() == (10, 5)


def test_config_zero_disables_both(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOSAERA_RATE_LIMIT_PER_MIN", "0")
    monkeypatch.setenv("MOSAERA_RUN_QUOTA_PER_DAY", "0")
    assert load_config().enabled is False


@pytest.mark.parametrize("bad", ["1O0", "abc", "1.5", "-1", "100001", ""])
def test_config_rejects_nonsense_loudly(monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    """A control you can't read is a failure, not a suggestion (ADR-0035).

    The key case is ``1O0`` (letter O): silently falling back to the default would run at 300
    while the operator believes they configured 100.
    """
    monkeypatch.setenv("MOSAERA_RATE_LIMIT_PER_MIN", bad)
    if bad == "":
        assert load_config().per_min == 300  # unset/blank is not a typo — it's "use the default"
        return
    with pytest.raises(SystemExit):
        load_config()


# --- the window: a pure unit, clock injected ---


def test_window_admits_up_to_limit_then_blocks() -> None:
    w = _FixedWindow()
    assert [w.check("s", 3, now=0.0) for _ in range(3)] == [0, 0, 0]
    retry = w.check("s", 3, now=0.0)
    assert retry > 0  # 4th in the same window is refused, with a wait


def test_window_rolls_to_a_fresh_bucket() -> None:
    w = _FixedWindow()
    for _ in range(3):
        w.check("s", 3, now=0.0)
    assert w.check("s", 3, now=0.0) > 0
    assert w.check("s", 3, now=60.0) == 0  # next minute: fresh allowance


def test_window_isolates_subjects() -> None:
    w = _FixedWindow()
    assert w.check("a", 1, now=0.0) == 0
    assert w.check("a", 1, now=0.0) > 0
    assert w.check("b", 1, now=0.0) == 0  # b is unaffected by a exhausting its bucket


def test_window_retry_after_counts_down_within_the_window() -> None:
    w = _FixedWindow()
    w.check("s", 1, now=0.0)
    assert w.check("s", 1, now=0.0) == 60  # full window remaining
    assert w.check("s", 1, now=59.5) == 1  # never 0 — a Retry-After of 0 invites a hot retry loop


def test_window_dict_is_bounded_against_credential_rotation() -> None:
    """A caller rotating credentials must not grow the tracking dict without limit — that would
    turn a memory-protection control into a memory leak."""
    w = _FixedWindow(max_subjects=50)
    for i in range(500):
        w.check(f"subject-{i}", 10, now=0.0)
    assert len(w._hits) <= 50


def test_window_prune_drops_stale_windows_first() -> None:
    w = _FixedWindow(max_subjects=10)
    for i in range(10):  # fill with window-0 subjects
        w.check(f"old-{i}", 10, now=0.0)
    w.check("new", 10, now=600.0)  # a later window triggers the prune
    assert "new" in w._hits
    assert len(w._hits) <= 10


# --- subject selection ---


def test_subject_prefers_the_cookie_so_the_spa_does_not_share_one_bucket() -> None:
    """The SPA sends BOTH a cookie and the service token. Keying on the token first would
    collapse every logged-in user into one bucket and let one busy tab throttle the team."""
    from starlette.datastructures import Headers
    from starlette.requests import Request

    def _req(headers: dict[str, str], query: str = "") -> Request:
        return Request(
            {
                "type": "http",
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": "/api/x",
                "raw_path": b"/api/x",
                "query_string": query.encode(),
                "root_path": "",
                "headers": Headers(headers).raw,
                "client": ("10.0.0.1", 1234),
                "server": ("testserver", 80),
            }
        )

    from mosaera_api.ratelimit import subject_for

    both = _req({"cookie": f"{SESSION_COOKIE}=abc", "authorization": f"Bearer {_TOKEN}"})
    assert subject_for(both, _TOKEN) == f"session:{hash_token('abc')[:32]}"

    only_token = _req({"authorization": f"Bearer {_TOKEN}"})
    assert subject_for(only_token, _TOKEN) == "token"

    via_query = _req({}, query=f"token={_TOKEN}")  # SSE/header-less transport
    assert subject_for(via_query, _TOKEN) == "token"

    wrong_token = _req({"authorization": "Bearer nope"})
    assert subject_for(wrong_token, _TOKEN) is None

    assert subject_for(_req({}), _TOKEN) is None  # no credential -> not our problem


def test_subject_never_holds_a_live_session_token() -> None:
    """The bucket key is a hash: a live session token must not sit in a process dict key, for
    the same reason the store only ever holds hashes."""
    from mosaera_api.ratelimit import subject_for
    from starlette.datastructures import Headers
    from starlette.requests import Request

    secret = "super-secret-session"
    req = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/x",
            "raw_path": b"/api/x",
            "query_string": b"",
            "root_path": "",
            "headers": Headers({"cookie": f"{SESSION_COOKIE}={secret}"}).raw,
            "client": ("10.0.0.1", 1234),
            "server": ("testserver", 80),
        }
    )
    subject = subject_for(req, _TOKEN)
    assert subject is not None
    assert secret not in subject


# --- middleware behaviour ---


class _FakeStore:
    """Duck-typed stand-in: only the two methods the limiter actually calls."""

    def __init__(self, user: dict[str, Any] | None = None, allow: int | None = 1) -> None:
        self._user = user
        self._allow = allow
        self.consumed: list[tuple[str, str, int]] = []

    def session_user(self, token_hash: str, now: datetime) -> dict[str, Any] | None:
        return self._user

    def try_consume_run_quota(self, subject: str, day: str, limit: int) -> int | None:
        self.consumed.append((subject, day, limit))
        return self._allow


def _app(history: Any = None, api_token: str = _TOKEN) -> FastAPI:
    app = FastAPI()
    install_rate_limit(app, history=history, api_token=api_token)

    @app.get("/api/ping")
    def ping() -> dict[str, str]:
        return {"ok": "yes"}

    @app.post("/api/runs", status_code=201)
    def runs() -> dict[str, str]:
        return {"started": "yes"}

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


def test_over_limit_returns_429_with_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOSAERA_RATE_LIMIT_PER_MIN", "2")
    client = TestClient(_app())
    headers = {"Authorization": f"Bearer {_TOKEN}"}
    assert client.get("/api/ping", headers=headers).status_code == 200
    assert client.get("/api/ping", headers=headers).status_code == 200
    blocked = client.get("/api/ping", headers=headers)
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0
    assert "rate limit exceeded" in blocked.json()["detail"]
    assert "2 requests/minute" in blocked.json()["detail"]  # the message names the actual limit


def test_credential_less_and_non_api_paths_are_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOSAERA_RATE_LIMIT_PER_MIN", "1")
    client = TestClient(_app())
    for _ in range(5):
        # No credential: auth 401s these anyway, and on an unconfigured dev box they're open.
        assert client.get("/api/ping").status_code == 200
        # /healthz is not under /api and must never be metered — it's how an orchestrator
        # decides this process is alive.
        assert client.get("/healthz").status_code == 200


def test_disabled_limiter_registers_no_middleware(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOSAERA_RATE_LIMIT_PER_MIN", "0")
    monkeypatch.setenv("MOSAERA_RUN_QUOTA_PER_DAY", "0")
    app = FastAPI()
    before = len(app.user_middleware)
    install_rate_limit(app, history=None, api_token=_TOKEN)
    assert len(app.user_middleware) == before  # zero cost per request when off


def test_separate_credentials_get_separate_buckets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOSAERA_RATE_LIMIT_PER_MIN", "1")
    client = TestClient(_app())
    assert client.get("/api/ping", cookies={SESSION_COOKIE: "user-a"}).status_code == 200
    assert client.get("/api/ping", cookies={SESSION_COOKIE: "user-a"}).status_code == 429
    # A different user is unaffected by user-a exhausting their allowance.
    assert client.get("/api/ping", cookies={SESSION_COOKIE: "user-b"}).status_code == 200


# --- quota ---


def test_quota_meters_run_creation_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOSAERA_RATE_LIMIT_PER_MIN", "0")
    monkeypatch.setenv("MOSAERA_RUN_QUOTA_PER_DAY", "3")
    store = _FakeStore(user={"id": 7, "is_admin": False})
    client = TestClient(_app(history=store))
    client.get("/api/ping", cookies={SESSION_COOKIE: "x"})
    assert store.consumed == []  # a plain read must not burn quota
    client.post("/api/runs", cookies={SESSION_COOKIE: "x"})
    assert store.consumed == [("user:7", store.consumed[0][1], 3)]


def test_quota_exhausted_returns_429(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOSAERA_RATE_LIMIT_PER_MIN", "0")
    monkeypatch.setenv("MOSAERA_RUN_QUOTA_PER_DAY", "3")
    store = _FakeStore(user={"id": 7, "is_admin": False}, allow=None)  # store says: over quota
    resp = TestClient(_app(history=store)).post("/api/runs", cookies={SESSION_COOKIE: "x"})
    assert resp.status_code == 429
    assert "daily run quota reached (3 runs/day)" in resp.json()["detail"]
    assert int(resp.headers["Retry-After"]) > 0


def test_quota_keys_on_the_account_not_the_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two sessions of the SAME user share one bucket — otherwise a user resets their daily cap
    by logging in again, which would make the quota decorative."""
    monkeypatch.setenv("MOSAERA_RATE_LIMIT_PER_MIN", "0")
    monkeypatch.setenv("MOSAERA_RUN_QUOTA_PER_DAY", "3")
    store = _FakeStore(user={"id": 7, "is_admin": False})
    client = TestClient(_app(history=store))
    client.post("/api/runs", cookies={SESSION_COOKIE: "session-one"})
    client.post("/api/runs", cookies={SESSION_COOKIE: "session-two"})
    assert [c[0] for c in store.consumed] == ["user:7", "user:7"]


def test_admin_is_exempt_from_the_quota(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOSAERA_RATE_LIMIT_PER_MIN", "0")
    monkeypatch.setenv("MOSAERA_RUN_QUOTA_PER_DAY", "1")
    store = _FakeStore(user={"id": 1, "is_admin": True}, allow=None)
    resp = TestClient(_app(history=store)).post("/api/runs", cookies={SESSION_COOKIE: "x"})
    assert resp.status_code == 201
    assert store.consumed == []  # never even asked


def test_service_token_is_one_quota_bucket(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOSAERA_RATE_LIMIT_PER_MIN", "0")
    monkeypatch.setenv("MOSAERA_RUN_QUOTA_PER_DAY", "2")
    store = _FakeStore(user=None)  # no account behind the request -> the shared token
    TestClient(_app(history=store)).post("/api/runs", headers={"Authorization": f"Bearer {_TOKEN}"})
    assert [c[0] for c in store.consumed] == ["token"]


def test_configured_quota_without_a_database_refuses_to_boot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A quota with nowhere to count is a policy that silently does nothing — the class
    guard_memory refuses to boot on (ADR-0035)."""
    monkeypatch.setenv("MOSAERA_RUN_QUOTA_PER_DAY", "5")
    with pytest.raises(SystemExit, match="durable memory"):
        install_rate_limit(FastAPI(), history=None, api_token=_TOKEN)


def test_stored_quota_is_read_live_with_no_restart(tmp_path: Any) -> None:
    """#37: the quota is a UI knob now. A value written to settings.json (NO env var, NO restart)
    is enforced — the middleware re-reads it on POST /runs. This is the promotion's teeth."""
    from pathlib import Path

    from mosaera_core.settings_store import write_settings

    write_settings(Path(tmp_path), {"run_quota_per_day": 2})  # tmp_path == MOSAERA_HOME (autouse)

    class _Counting:
        def __init__(self) -> None:
            self.n = 0
            self.limits: list[int] = []

        def session_user(self, token_hash: str, now: datetime) -> None:
            return None  # -> the shared-token bucket

        def try_consume_run_quota(self, subject: str, day: str, limit: int) -> int | None:
            self.limits.append(limit)
            self.n += 1
            return None if self.n > 2 else self.n  # allow 2/day, then over

    store = _Counting()
    client = TestClient(_app(history=store))
    headers = {"Authorization": f"Bearer {_TOKEN}"}
    codes = [client.post("/api/runs", headers=headers).status_code for _ in range(3)]
    assert codes == [201, 201, 429]  # the STORED limit of 2 took effect — no env, no restart
    assert set(store.limits) == {2}  # try_consume saw the live stored limit, not a boot value


def test_live_quota_layers_env_over_stored_over_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    from pathlib import Path

    from mosaera_api.ratelimit import _live_quota
    from mosaera_core.settings_store import write_settings

    assert _live_quota() == 0  # default: no cap (empty MOSAERA_HOME, no env)
    write_settings(Path(tmp_path), {"run_quota_per_day": 4})
    assert _live_quota() == 4  # stored (UI) value
    monkeypatch.setenv("MOSAERA_RUN_QUOTA_PER_DAY", "9")
    assert _live_quota() == 9  # env wins over stored


def test_seconds_to_utc_midnight_is_always_positive() -> None:
    assert _seconds_to_utc_midnight(datetime(2026, 7, 17, 23, 59, 59, tzinfo=UTC)) == 1
    assert _seconds_to_utc_midnight(datetime(2026, 7, 17, 0, 0, 0, tzinfo=UTC)) == 86_400


# --- wiring into the real app ---


def _never_called_graph(
    req: Any, run_id: str
) -> tuple[Any, dict[str, Any], dict[str, Any] | None, Any]:
    """A graph factory that would fail loudly if used. These tests exercise the middleware
    stack, which rejects (429/401) or reaches a route that never builds a graph — so a factory
    that runs would mean the test is measuring something other than what it claims."""
    raise AssertionError("the graph must never be built in a rate-limit test")


def test_run_create_path_still_exists() -> None:
    """The quota matches POST /api/runs literally, so a route rename would silently un-meter it.
    This fails loudly instead.

    Asserted against the OpenAPI schema rather than ``app.routes``: an included router is kept as
    an opaque ``_IncludedRouter`` here and never flattened into ``app.routes``, so walking that
    list finds nothing and would make this guard silently vacuous — the exact failure it exists to
    prevent. The schema is also the contract clients actually see.
    """
    from mosaera_api.app import create_app

    app = create_app(graph_factory=_never_called_graph, memory=None, web_dist="/nonexistent")
    paths = app.openapi()["paths"]
    assert RUN_CREATE_PATH in paths, (
        f"{RUN_CREATE_PATH} not served — the quota would silently stop metering"
    )
    assert "post" in paths[RUN_CREATE_PATH], (
        f"POST {RUN_CREATE_PATH} not served — the quota would silently stop metering"
    )


def test_limiter_runs_after_auth_so_a_401_wins_over_a_429(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ordering is the load-bearing property: the limiter sits INSIDE auth, so an unauthenticated
    flood is rejected by auth (401) and never reaches or pollutes a rate-limit bucket."""
    from mosaera_api.app import create_app

    monkeypatch.setenv("MOSAERA_API_TOKEN", _TOKEN)  # auth configured
    monkeypatch.setenv("MOSAERA_RATE_LIMIT_PER_MIN", "1")
    client = TestClient(
        create_app(graph_factory=_never_called_graph, memory=None, web_dist="/nonexistent")
    )
    for _ in range(4):
        assert client.get("/api/runs").status_code == 401  # never 429
    # And a VALID credential is metered normally.
    headers = {"Authorization": f"Bearer {_TOKEN}"}
    assert client.get("/api/runs", headers=headers).status_code == 200
    assert client.get("/api/runs", headers=headers).status_code == 429
