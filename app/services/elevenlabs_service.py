from __future__ import annotations

import asyncio
import base64
from typing import AsyncGenerator

from elevenlabs.client import AsyncElevenLabs

from app.config import get_settings
from app.exceptions import ElevenLabsError
from app.utils.logger import get_logger

logger = get_logger(__name__)


class ElevenLabsService:
    """
    Streams TTS audio from ElevenLabs and yields base64-encoded mulaw chunks.

    Output format ulaw_8000 is telephone-native (G.711 μ-law) — Telnyx accepts it directly.
    Chunks are yielded as they arrive so the caller hears audio immediately.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._client = AsyncElevenLabs(api_key=settings.elevenlabs_api_key)
        self._voice_id = settings.elevenlabs_voice_id

    async def synthesize(self, text: str) -> AsyncGenerator[str, None]:
        """
        Yields base64-encoded ulaw_8000 audio chunks suitable for sending
        directly into a Telnyx media stream WebSocket message.
        """
        try:
            logger.info("elevenlabs_synthesizing", chars=len(text))
            audio_stream = self._client.text_to_speech.convert_as_stream(
                voice_id=self._voice_id,
                text=text,
                model_id="eleven_turbo_v2",
                output_format="ulaw_8000",
                optimize_streaming_latency=4,
            )
            # convert_as_stream returns an AsyncIterator[bytes]
            # Handle both coroutine (older SDK builds) and async iterator
            if asyncio.iscoroutine(audio_stream):
                audio_stream = await audio_stream

            async for chunk in audio_stream:
                if isinstance(chunk, bytes) and chunk:
                    yield base64.b64encode(chunk).decode("utf-8")

        except ElevenLabsError:
            raise
        except Exception as exc:
            logger.error("elevenlabs_synthesis_failed", error=str(exc), text_preview=text[:60])
            raise ElevenLabsError(f"ElevenLabs synthesis failed: {exc}") from exc
