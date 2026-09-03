from pathlib import Path

from mosaera_core.config import Settings
from mosaera_core.settings_store import mask_secret, read_settings, write_settings


def test_write_read_roundtrip_and_filter(tmp_path: Path) -> None:
    write_settings(
        tmp_path, {"gitlab_url": "https://gl.example", "gitlab_token": "glpat-abc", "bogus": 1}
    )
    stored = read_settings(tmp_path)
    assert stored == {
        "gitlab_url": "https://gl.example",
        "gitlab_token": "glpat-abc",
    }  # bogus dropped


def test_none_removes_key(tmp_path: Path) -> None:
    write_settings(tmp_path, {"gitlab_token": "x"})
    write_settings(tmp_path, {"gitlab_token": None})
    assert "gitlab_token" not in read_settings(tmp_path)


def test_missing_file_is_empty(tmp_path: Path) -> None:
    assert read_settings(tmp_path / "nope") == {}


def test_retired_knob_in_a_stored_file_still_loads(tmp_path: Path) -> None:
    """A settings.json written before a knob was RETIRED must still load (#81 cleanup).

    `reviewer_advisory` was removed — it had zero engine reads while presenting an ON toggle over
    gate policy. An operator's existing file still carries it, so the store must drop the stale key
    rather than reject the file, and the next write must self-heal it off disk.
    """
    (tmp_path / "settings.json").write_text(
        '{"reviewer_advisory": true, "scan_enabled": false}\n', encoding="utf-8"
    )
    stored = read_settings(tmp_path)
    assert stored == {"scan_enabled": False}  # stale key dropped, the rest survives
    assert "reviewer_advisory" not in write_settings(tmp_path, {"doctrine_enabled": True})
    assert "reviewer_advisory" not in (tmp_path / "settings.json").read_text(encoding="utf-8")


def test_settings_has_no_retired_reviewer_advisory_field() -> None:
    """The field is gone from Settings too — a lingering attribute would let code read a knob
    nothing can set, which is how the honesty hazard survived in the first place."""
    assert not hasattr(Settings(), "reviewer_advisory")


def test_mask_secret() -> None:
    assert mask_secret("glpat-abcd1234") == "…1234"
    assert mask_secret("ab") == "…"
    assert mask_secret(None) == ""


def test_settings_precedence_env_over_file_over_default(tmp_path: Path) -> None:
    write_settings(tmp_path, {"gitlab_token": "from-file", "gitlab_url": "https://file.example"})
    env = {"MOSAERA_HOME": str(tmp_path)}
    # File is used when env var is absent.
    s = Settings.from_env(env=env)
    assert s.gitlab_token == "from-file"
    assert s.gitlab_url == "https://file.example"
    # Real env var wins over the file.
    s2 = Settings.from_env(env={**env, "MOSAERA_GITLAB_TOKEN": "from-env"})
    assert s2.gitlab_token == "from-env"


def test_byom_keys_are_allowed_and_persist(tmp_path: Path) -> None:
    # BYOM (#21) role_models + providers are allow-listed; strays still dropped.
    write_settings(
        tmp_path,
        {
            "providers": {"openai": {"api_key": "sk-secret"}},
            "role_models": {"coder": {"provider": "openai", "model": "gpt-4o"}},
            "stray": "dropped",
        },
    )
    data = read_settings(tmp_path)
    assert data["providers"] == {"openai": {"api_key": "sk-secret"}}
    assert data["role_models"]["coder"]["provider"] == "openai"
    assert "stray" not in data


def test_cost_mode_keys_are_allowed_and_persist(tmp_path: Path) -> None:
    # Cost-modes (#7) cost_modes + default_cost_mode are allow-listed.
    write_settings(
        tmp_path,
        {
            "cost_modes": {"premium": {"coder": {"provider": "openai", "model": "gpt-4o"}}},
            "default_cost_mode": "premium",
            "nope": 1,
        },
    )
    data = read_settings(tmp_path)
    assert data["cost_modes"]["premium"]["coder"]["model"] == "gpt-4o"
    assert data["default_cost_mode"] == "premium"
    assert "nope" not in data
