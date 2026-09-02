"""Hidden acceptance suite for MCB-06 (harden the config loader).

Ground truth — never shown to the agent, injected at grade time. Imports the
delivered module from the workspace cwd and asserts every failure mode becomes a
clean ``ConfigError`` rather than a leaked stdlib exception.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from config_loader import ConfigError, load_config


def _write(tmp: Path, payload: object) -> str:
    p = tmp / "config.json"
    p.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")
    return str(p)


def test_valid_config_loads(tmp_path: Path) -> None:
    cfg = load_config(_write(tmp_path, {"name": "svc", "port": 8080}))
    assert cfg["name"] == "svc"
    assert cfg["port"] == 8080


def test_missing_file_raises_configerror(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(str(tmp_path / "does-not-exist.json"))


def test_malformed_json_raises_configerror(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, "{ not valid json"))


def test_missing_required_key_raises_configerror(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, {"name": "svc"}))


def test_wrong_typed_port_raises_configerror(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, {"name": "svc", "port": "eighty"}))


def test_configerror_carries_a_message(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as exc:
        load_config(str(tmp_path / "missing.json"))
    assert str(exc.value).strip() != ""
