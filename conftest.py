"""Repo-root test hygiene: isolate every test from the developer's real Mosaera config.

``Settings.from_env()`` (``packages/core/mosaera_core/config/_settings.py``) reads
``MOSAERA_*`` env vars and layers the on-disk ``<MOSAERA_HOME>/settings.json`` (default
``.mosaera/``) on top of the class defaults — precedence ``env > stored > default``. On a
developer machine that file is REAL: it holds saved role models, provider API keys, and cost
knobs. A test asserting a DEFAULT would then silently read the developer's saved value instead
and pass (or fail) by coincidence — the H2 finding from the 2026-07-14 audit.

This autouse fixture makes ``from_env()`` deterministic across machines: it strips every
``MOSAERA_*`` var (and the native provider keys ``from_env`` reads) from ``os.environ`` and
points ``MOSAERA_HOME`` at an empty per-test tmp dir. Tests that call ``from_env()`` with no
argument are fully isolated by this backstop.

It does NOT reach a test that passes an explicit ``env=`` dict (that bypasses ``os.environ``):
such a test must isolate ``MOSAERA_HOME`` itself via the established
``env={"MOSAERA_HOME": str(tmp_path)}`` idiom (see ``packages/core/tests/test_config.py``).
"""

from __future__ import annotations

import functools
import os

import pytest

# ---------------------------------------------------------------- integration gates
#
# The Docker/Postgres-gated tests used to carry eight copy-pasted `skipif`s, each
# probing at its own import. That made the probe invisible (no reason printed, no
# count asserted), and #58 was the result: `sandbox-e2e` — the job whose whole
# purpose is running these tests — skipped ~105 of them and reported success. A
# control point that fails OPEN, in a repo whose posture is fail-closed.
#
# The gates now live here, probed ONCE at collection, and the skip reason carries
# the underlying error so a log says *why*, not just "unavailable". Set
# MOSAERA_INTEGRATION=required (CI does) and a missing precondition becomes an
# ERROR instead of a skip: a job may not pass by not running its tests.

# Read BEFORE the isolation fixture below strips MOSAERA_* from the environment.
_DB_URL = os.environ.get("MOSAERA_TEST_DB_URL")
_DOCKER_BIN = os.environ.get("MOSAERA_DOCKER_BIN", "docker")
_SANDBOX_IMAGE = os.environ.get("MOSAERA_SANDBOX_IMAGE", "mosaera-sandbox:dev")
_REQUIRED = os.environ.get("MOSAERA_INTEGRATION", "skip").strip().lower() == "required"


@functools.cache
def _docker_unavailable(image: str = _SANDBOX_IMAGE) -> str:
    """ "" if Docker AND `image` are usable, else the reason they are not.

    The image is per-marker: the sandbox tests need `mosaera-sandbox:dev`, the
    scanner tests `mosaera-scan:dev`. Cached, so the daemon is probed once.
    """
    try:
        from mosaera_core.sandbox._base import docker_available, docker_image_present
    except Exception as exc:  # pragma: no cover - import failure is itself the reason
        return f"mosaera_core.sandbox import failed: {exc!r}"
    if not docker_available(_DOCKER_BIN):
        return f"no Docker daemon reachable via {_DOCKER_BIN!r} (`docker info` failed)"
    if not docker_image_present(image, _DOCKER_BIN):
        return f"Docker is up but the image {image!r} is not built"
    return ""


@functools.cache
def _db_unavailable() -> str:
    """ "" if the test database is usable, else the reason it is not.

    Reachability is proven by connecting and running the schema DDL — a set
    MOSAERA_TEST_DB_URL proves nothing on its own.
    """
    if not _DB_URL:
        return "MOSAERA_TEST_DB_URL is not set"
    try:
        from mosaera_memory import MemoryStore

        MemoryStore.from_url(_DB_URL).init()
    except Exception as exc:
        return f"database at MOSAERA_TEST_DB_URL is unreachable or unmigratable: {exc!r}"
    return ""


def _gate_reason(item: pytest.Item) -> tuple[str, str]:
    """The (gate, reason) blocking this item, or ("", "") when nothing does."""
    docker = item.get_closest_marker("requires_docker")
    if docker is not None:
        image = docker.args[0] if docker.args else _SANDBOX_IMAGE
        reason = _docker_unavailable(image)
        if reason:
            return "requires_docker", reason
    if item.get_closest_marker("requires_db") is not None:
        reason = _db_unavailable()
        if reason:
            return "requires_db", reason
    return "", ""


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Apply the integration gates: skip by default, ERROR when they are required."""
    for item in items:
        gate, reason = _gate_reason(item)
        if not gate:
            continue
        item.add_marker(
            pytest.mark.fail_integration_gate(gate, reason)
            if _REQUIRED
            else pytest.mark.skip(reason=f"{gate}: {reason}")
        )


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Under MOSAERA_INTEGRATION=required, a missing precondition FAILS the test."""
    marker = item.get_closest_marker("fail_integration_gate")
    if marker is not None:
        gate, reason = marker.args
        pytest.fail(
            f"{gate} is REQUIRED here but unavailable — {reason}. "
            "This run may not report success without executing these tests (#58).",
            pytrace=False,
        )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "fail_integration_gate(gate, reason): internal — see conftest"
    )


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    """State the gate status in the log on EVERY run, including the healthy one.

    The whole of #58 was that a vacant run and a real one looked identical. They
    no longer do, whatever the outcome.
    """
    mode = "required (missing = error)" if _REQUIRED else "skip (missing = skipped)"
    terminalreporter.write_sep("-", "integration gates")
    terminalreporter.write_line(f"  mode: MOSAERA_INTEGRATION={mode}")
    for name, reason in (
        ("requires_docker", _docker_unavailable()),
        ("requires_db", _db_unavailable()),
    ):
        terminalreporter.write_line(
            f"  {name}: {'AVAILABLE' if not reason else f'UNAVAILABLE — {reason}'}"
        )


@pytest.fixture(autouse=True)
def _isolate_mosaera_config(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    for key in list(os.environ):
        if key.startswith("MOSAERA_"):
            monkeypatch.delenv(key, raising=False)
    # Provider keys are read natively by models.py (_has_provider_env_key), not as MOSAERA_*.
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    # An empty home → read_settings finds no settings.json → pristine class defaults.
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path_factory.mktemp("mosaera-home")))
