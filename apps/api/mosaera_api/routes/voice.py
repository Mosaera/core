"""Voice transcription routes (in-memory only, never persisted).

Zero shared app state — the transcription engine is a module-level singleton in
``mosaera_api.transcribe``. Tests patch ``mosaera_api.routes.voice.ENGINE``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Form, HTTPException, UploadFile

from mosaera_api.transcribe import ENGINE, TranscriptionError, VoiceConfig, voice_status


def make_voice_router() -> APIRouter:
    api = APIRouter()

    @api.get("/transcribe/status")
    def transcribe_status() -> dict[str, Any]:
        return voice_status()

    @api.post("/transcribe")
    async def transcribe(audio: UploadFile, language: str | None = Form(None)) -> dict[str, Any]:
        config = VoiceConfig.from_env()
        if not config.enabled:
            raise HTTPException(
                status_code=403, detail="Voice input is not enabled on this instance"
            )
        data = await audio.read()
        try:
            # In-memory end to end (guardrail 7): the bytes are decoded from a
            # buffer and garbage-collected after this response.
            return ENGINE.transcribe(data, config, language=language)
        except TranscriptionError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.reason) from exc

    return api
