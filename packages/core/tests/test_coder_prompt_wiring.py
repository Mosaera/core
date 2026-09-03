"""The coder's system prompt must reflect the RUN, not a default.

Agent review 2026-08-19. `coder_system()` renders the test-ownership rule from
`tester_enabled` — but rendering correctly is worthless if the caller never passes the
setting. A parameter accepted and silently dropped is exactly the defect shipped the day
before in `build_pm_context` (`on_gitlab`), where the unit test passed because it exercised
the renderer directly instead of the assembly. So this drives `build_default_team`.
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.language_models import FakeMessagesListChatModel
from mosaera_core import agents_bridge
from mosaera_core.config import Settings


def _captured_coder_prompt(
    monkeypatch: pytest.MonkeyPatch, *, tester: bool, tools: bool | None = None
) -> str:
    seen: dict[str, Any] = {}

    def _fake_coder(*a: Any, **kw: Any) -> object:
        seen["prompt"] = kw["system_prompt"]
        return object()

    monkeypatch.setattr(agents_bridge, "build_coder_agent", _fake_coder)
    monkeypatch.setattr(agents_bridge, "build_reviewer_agent", lambda *a, **k: object())
    monkeypatch.setattr(agents_bridge.pm, "build_pm_agent", lambda *a, **k: object())
    monkeypatch.setattr(agents_bridge, "build_tester_agent", lambda *a, **k: object())
    monkeypatch.setattr(agents_bridge, "build_critic_agent", lambda *a, **k: object())

    settings = Settings.from_env()
    settings = type(settings)(**{**settings.__dict__, "tester_enabled": tester})
    agents_bridge.build_default_team(
        settings,
        [],
        [] if (tester if tools is None else tools) else None,
        lambda *a, **k: FakeMessagesListChatModel(responses=[]),
    )
    return str(seen["prompt"])


def test_the_run_s_tester_setting_reaches_the_coder_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    with_proctor = _captured_coder_prompt(monkeypatch, tester=True)
    without = _captured_coder_prompt(monkeypatch, tester=False)

    # Proctor on → tests/ is protected and a write is refused, whatever the plan says.
    assert "PROTECTED" in with_proctor
    assert "Writing tests" not in with_proctor
    # Proctor off → the coder genuinely owns its tests, so the MCB-01 craft rules stay.
    assert "Writing tests" in without


def test_the_prompt_follows_the_TOOLS_not_the_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    """RED TEAM 2026-08-19. The coder prompt read `settings.tester_enabled` while every other
    consumer reads `tester_enabled = tester_tools is not None` — the value this same factory sets
    two lines later. They agree only because `build_graph` derives both from one flag; a
    team_factory that passes tester_tools with the setting off (bench and tests inject one) told
    the coder it owned the tests while its writes were being refused.

    Driven with the two sources deliberately disagreeing, which is the only state that shows it.
    """
    protected = _captured_coder_prompt(monkeypatch, tester=False, tools=True)
    assert "PROTECTED" in protected, "the prompt followed the setting, not the built tools"
    assert "Writing tests" not in protected

    owned = _captured_coder_prompt(monkeypatch, tester=True, tools=False)
    assert "Writing tests" in owned, "told it was protected with no tester tools built"
    assert "PROTECTED" not in owned
