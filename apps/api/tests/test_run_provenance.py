"""What a run STARTED with is recorded, so a finished run reads as an observation (ADR-0122)."""

from __future__ import annotations

from pathlib import Path

import pytest
from mosaera_api.runner._provenance import run_controls, run_profiles
from mosaera_core.config import Settings
from mosaera_core.settings_store import write_settings


def test_the_selected_profiles_are_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MOSAERA_EFFORT_PROFILE", raising=False)
    write_settings(tmp_path, {"effort_profile": "persistent"})
    assert run_profiles(tmp_path) == {"effort_profile": "persistent"}


def test_an_unset_profile_is_omitted_rather_than_reported_as_a_choice(tmp_path: Path) -> None:
    """A null profile is not a selection. Emitting it would put a value on the run record that
    the operator never picked."""
    assert run_profiles(tmp_path) == {}


def test_env_wins_over_the_stored_choice(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_settings(tmp_path, {"effort_profile": "cautious"})
    monkeypatch.setenv("MOSAERA_EFFORT_PROFILE", "persistent")
    assert run_profiles(tmp_path)["effort_profile"] == "persistent"


def test_the_control_roster_includes_the_ones_that_are_OFF(tmp_path: Path) -> None:
    """The roster used to be inferred from observed events, which could not distinguish a
    disabled control from one that had not run yet."""
    controls = run_controls(Settings(home=tmp_path, critic_enabled=False, tester_enabled=True))
    assert controls["critic_enabled"] is False
    assert controls["tester_enabled"] is True
