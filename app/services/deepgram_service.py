from __future__ import annotations

from typing import Awaitable, Callable, Optional

try:
    import audioop  # built-in on Python <= 3.12
except ModuleNotFoundError:
    from audioop_lts import audioop  # type: ignore[no-redef]  # Python 3.13+

from deepgram import DeepgramClient, LiveOptions, LiveTranscriptionEvents

from app.config import get_settings
from app.exceptions import DeepgramError
from app.utils.logger import get_logger

logger = get_logger(__name__)

TranscriptCallback = Callable[[str], Awaitable[None]]


class DeepgramService:
    """
    Manages a single Deepgram AsyncLive STT connection for one call.

    Converts telephone μ-law/8000 audio to linear16 PCM before forwarding —
    Deepgram does not accept mulaw directly on the streaming endpoint.
    Only fires transcript_callback on is_final=True results.
    """

    def __init__(self, transcript_callback: TranscriptCallback) -> None:
        self._callback = transcript_callback
        self._connection = None
        self._connected = False

    async def connect(self) -> None:
        settings = get_settings()
        try:
            client = DeepgramClient(api_key=settings.deepgram_api_key)
            self._connection = client.listen.asynclive.v("1")

            self._connection.on(LiveTranscriptionEvents.Transcript, self._on_transcript)
            self._connection.on(LiveTranscriptionEvents.Error, self._on_error)
            self._connection.on(LiveTranscriptionEvents.Close, self._on_close)

            options = LiveOptions(
                model="nova-2",
                language="en-US",
                encoding="linear16",
                sample_rate=8000,
                channels=1,
                punctuate=True,
                endpointing=300,
            )

            started = await self._connection.start(options)
            if not started:
                raise DeepgramError("Deepgram connection returned False on start()")

            self._connected = True
            logger.info("deepgram_connected")

        except DeepgramError:
            raise
        except Exception as exc:
            logger.error("deepgram_connect_failed", error=str(exc))
            raise DeepgramError(f"Failed to connect to Deepgram: {exc}") from exc

    async def send_audio(self, mulaw_bytes: bytes) -> None:
        if not self._connected or self._connection is None:
            return
        try:
            # ulaw2lin(data, sample_width=2) → 16-bit linear PCM
            pcm_bytes = audioop.ulaw2lin(mulaw_bytes, 2)
            await self._connection.send(pcm_bytes)
        except Exception as exc:
            logger.error("deepgram_send_failed", error=str(exc))
            raise DeepgramError(f"Failed to send audio to Deepgram: {exc}") from exc

    async def disconnect(self) -> None:
        if self._connection is None:
            return
        try:
            await self._connection.finish()
            logger.info("deepgram_disconnected")
        except Exception as exc:
            logger.error("deepgram_disconnect_error", error=str(exc))
        finally:
            self._connected = False
            self._connection = None

    async def _on_transcript(self, _connection, result, **kwargs) -> None:
        try:
            alternatives = result.channel.alternatives
            if not alternatives:
                return
            transcript = alternatives[0].transcript.strip()
            if result.is_final and transcript:
                logger.info("deepgram_final_transcript", text=transcript[:120])
                await self._callback(transcript)
        except Exception as exc:
            logger.error("deepgram_transcript_parse_error", error=str(exc))

    async def _on_error(self, _connection, error, **kwargs) -> None:
        logger.error("deepgram_error", error=str(error))

    async def _on_close(self, _connection, close, **kwargs) -> None:
        self._connected = False
        logger.info("deepgram_connection_closed")
