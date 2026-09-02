import json
from pathlib import Path

from config_loader import load_config


def test_valid_config_loads(tmp_path: Path) -> None:
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"name": "svc", "port": 8080}), encoding="utf-8")
    cfg = load_config(str(p))
    assert cfg["name"] == "svc"
    assert cfg["port"] == 8080
