"""Server-side voice transcription (MR 4C) — local faster-whisper, CPU.

Raw audio NEVER touches disk (guardrail 7): the upload is decoded straight
from an in-memory buffer (faster-whisper accepts file-like objects via PyAV)
and the buffer is discarded after the response. The model itself downloads
lazily into the cache dir on first use, with an explicit state machine the UI
reflects honestly (guardrails 1-2): disabled | not_ready | preparing | ready |
failed. Server-side limits are authoritative (guardrail 8).
"""

from __future__ import annotations

import io
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mosaera_core.config import Settings


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass
class VoiceConfig:
    enabled: bool
    prefer: str  # browser_first | whisper_first
    model: str
    device: str
    cache_dir: Path
    max_audio_seconds: int
    max_audio_mb: int

    @classmethod
    def from_env(cls) -> VoiceConfig:
        cache = _env("MOSAERA_WHISPER_MODEL_CACHE", "")
        prefer = _env("MOSAERA_VOICE_PREFER", "browser_first")
        if prefer not in ("browser_first", "whisper_first"):
            prefer = "browser_first"
        return cls(
            enabled=_env("MOSAERA_ENABLE_TRANSCRIPTION", "true").lower() != "false",
            prefer=prefer,
            model=_env("MOSAERA_WHISPER_MODEL", "base"),
            device=_env("MOSAERA_WHISPER_DEVICE", "cpu"),
            cache_dir=Path(cache) if cache else Settings.from_env().home / "models" / "whisper",
            max_audio_seconds=int(_env("MOSAERA_MAX_AUDIO_SECONDS", "120")),
            max_audio_mb=int(_env("MOSAERA_MAX_AUDIO_MB", "25")),
        )


class TranscriptionError(Exception):
    """User-facing transcription failure (limits, invalid audio)."""

    def __init__(self, reason: str, status_code: int = 422):
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code


class WhisperEngine:
    """Thread-safe lazy loader around one faster-whisper model instance."""

    def __init__(self) -> None:
        self._model: Any = None
        self._lock = threading.Lock()
        self._state = "not_ready"  # not_ready | preparing | ready | failed
        self._error = ""

    @property
    def state(self) -> str:
        return self._state

    def _load(self, config: VoiceConfig) -> Any:
        # First call downloads ~145MB into the cache dir; the API reports
        # "preparing" to concurrent requests so the UI can say so honestly.
        if self._model is not None:
            return self._model
        if not self._lock.acquire(blocking=False):
            raise TranscriptionError(
                "Voice model is being prepared. This can take a few minutes the first time.",
                status_code=503,
            )
        try:
            if self._model is not None:
                return self._model
            self._state = "preparing"
            from faster_whisper import WhisperModel

            config.cache_dir.mkdir(parents=True, exist_ok=True)
            self._model = WhisperModel(
                config.model, device=config.device, download_root=str(config.cache_dir)
            )
            self._state = "ready"
            return self._model
        except Exception as exc:
            self._state = "failed"
            self._error = str(exc)[:300]
            raise TranscriptionError(
                "Voice transcription is unavailable on this instance.", status_code=503
            ) from exc
        finally:
            self._lock.release()

    def transcribe(
        self, audio: bytes, config: VoiceConfig, language: str | None = None
    ) -> dict[str, Any]:
        """Transcribe in-memory audio bytes; never writes to disk (guardrail 7)."""
        if len(audio) == 0:
            raise TranscriptionError("No audio received.")
        if len(audio) > config.max_audio_mb * 1024 * 1024:
            raise TranscriptionError(f"Audio too large (limit {config.max_audio_mb} MB).")
        model = self._load(config)
        try:
            segments, info = model.transcribe(io.BytesIO(audio), language=language)
        except Exception as exc:
            raise TranscriptionError("Could not read the audio recording.") from exc
        duration = float(getattr(info, "duration", 0.0) or 0.0)
        if duration > config.max_audio_seconds:
            # info is available before segments are consumed — abort without
            # spending compute on an over-limit recording (guardrail 8).
            raise TranscriptionError(
                f"Recording too long (limit {config.max_audio_seconds} seconds)."
            )
        text = " ".join(s.text.strip() for s in segments).strip()
        return {
            "text": text,
            "duration_seconds": round(duration, 2),
            "model": config.model,
            "language": getattr(info, "language", language) or "",
        }


# Module-level engine: one model per process, shared across requests.
ENGINE = WhisperEngine()


def voice_status(engine: WhisperEngine | None = None) -> dict[str, Any]:
    """Source of truth for the mic UI (guardrail 1)."""
    config = VoiceConfig.from_env()
    eng = engine or ENGINE
    state = "disabled" if not config.enabled else eng.state
    return {
        "enabled": config.enabled,
        "state": state,
        "model": config.model,
        "prefer": config.prefer,
    }
