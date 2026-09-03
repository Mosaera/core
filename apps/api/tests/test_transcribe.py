"""Voice transcription endpoint + engine tests (fake model, no downloads)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from mosaera_api.app import create_app
from mosaera_api.transcribe import TranscriptionError, VoiceConfig, WhisperEngine, voice_status
from test_api import _fake_factory


class _FakeInfo:
    def __init__(self, duration: float, language: str = "en"):
        self.duration = duration
        self.language = language


class _FakeSegment:
    def __init__(self, text: str):
        self.text = text


class _FakeModel:
    def __init__(self, text: str = "hello mosaera", duration: float = 3.0):
        self.text = text
        self.duration = duration
        self.calls: list[Any] = []

    def transcribe(self, audio: Any, language: str | None = None) -> Any:
        self.calls.append(audio)
        return iter([_FakeSegment(self.text)]), _FakeInfo(self.duration)


def _ready_engine(text: str = "hello mosaera", duration: float = 3.0) -> WhisperEngine:
    eng = WhisperEngine()
    eng._model = _FakeModel(text, duration)
    eng._state = "ready"
    return eng


def _client() -> TestClient:
    return TestClient(create_app(graph_factory=_fake_factory))


def test_status_reflects_disabled_and_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOSAERA_ENABLE_TRANSCRIPTION", "false")
    assert voice_status()["state"] == "disabled"
    monkeypatch.setenv("MOSAERA_ENABLE_TRANSCRIPTION", "true")
    s = voice_status(_ready_engine())
    assert s["state"] == "ready" and s["prefer"] == "browser_first"
    monkeypatch.setenv("MOSAERA_VOICE_PREFER", "whisper_first")
    assert voice_status(_ready_engine())["prefer"] == "whisper_first"
    monkeypatch.setenv("MOSAERA_VOICE_PREFER", "nonsense")
    assert voice_status(_ready_engine())["prefer"] == "browser_first"  # safe default


def test_transcribe_endpoint_happy_and_guards(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    monkeypatch.setenv("MOSAERA_ENABLE_TRANSCRIPTION", "true")
    eng = _ready_engine("add a backlog item for the hero section", 5.5)
    monkeypatch.setattr("mosaera_api.routes.voice.ENGINE", eng)
    c = _client()

    r = c.post("/api/transcribe", files={"audio": ("v.webm", b"fake-bytes", "audio/webm")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["text"] == "add a backlog item for the hero section"
    assert body["duration_seconds"] == 5.5 and body["model"] == "base"

    # Guardrail 7: raw audio never touches disk — nothing under home at all.
    written = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert written == [], written

    # 403 when disabled (guardrail 8).
    monkeypatch.setenv("MOSAERA_ENABLE_TRANSCRIPTION", "false")
    assert (
        c.post("/api/transcribe", files={"audio": ("v.webm", b"x", "audio/webm")}).status_code
        == 403
    )
    monkeypatch.setenv("MOSAERA_ENABLE_TRANSCRIPTION", "true")

    # 422 empty and oversized.
    assert (
        c.post("/api/transcribe", files={"audio": ("v.webm", b"", "audio/webm")}).status_code == 422
    )
    monkeypatch.setenv("MOSAERA_MAX_AUDIO_MB", "0")
    big = c.post("/api/transcribe", files={"audio": ("v.webm", b"xx", "audio/webm")})
    assert big.status_code == 422 and "too large" in big.json()["detail"].lower()
    monkeypatch.delenv("MOSAERA_MAX_AUDIO_MB")

    # 422 over the duration limit — checked before consuming segments.
    monkeypatch.setattr("mosaera_api.routes.voice.ENGINE", _ready_engine("x", duration=500.0))
    long = c.post("/api/transcribe", files={"audio": ("v.webm", b"xx", "audio/webm")})
    assert long.status_code == 422 and "too long" in long.json()["detail"].lower()


def test_engine_error_states(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    config = VoiceConfig.from_env()

    # Model that explodes on decode → calm 422, not a raw library error.
    eng = _ready_engine()
    assert eng._model is not None

    class _Boom:
        def transcribe(self, *a: Any, **k: Any) -> Any:
            raise RuntimeError("codec exploded")

    eng._model = _Boom()
    with pytest.raises(TranscriptionError) as exc:
        eng.transcribe(b"bytes", config)
    assert exc.value.status_code == 422
    assert "Could not read the audio" in exc.value.reason

    # A concurrently-loading engine reports preparing via 503.
    fresh = WhisperEngine()
    fresh._lock.acquire()
    with pytest.raises(TranscriptionError) as busy:
        fresh.transcribe(b"bytes", config)
    assert busy.value.status_code == 503
    assert "being prepared" in busy.value.reason
    fresh._lock.release()


def test_voice_config_env_parsing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    monkeypatch.setenv("MOSAERA_WHISPER_MODEL", "small")
    monkeypatch.setenv("MOSAERA_MAX_AUDIO_SECONDS", "60")
    monkeypatch.setenv("MOSAERA_WHISPER_MODEL_CACHE", str(tmp_path / "custom-cache"))
    c = VoiceConfig.from_env()
    assert c.model == "small" and c.max_audio_seconds == 60
    assert c.cache_dir == tmp_path / "custom-cache"
    monkeypatch.delenv("MOSAERA_WHISPER_MODEL_CACHE")
    assert VoiceConfig.from_env().cache_dir == tmp_path / "models" / "whisper"
