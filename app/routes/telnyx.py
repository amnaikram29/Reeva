from __future__ import annotations

import asyncio
import base64
import json
from typing import Optional

from fastapi import APIRouter, Request, Response, WebSocket, WebSocketDisconnect

from app.config import get_settings
from app.exceptions import ClaudeError, DeepgramError, ElevenLabsError, TelnyxError
from app.services import telnyx_service
from app.agent import process_turn
from app.services.appointment_service import list_appointments
from app.services.call_session import (
    create_session,
    delete_session,
    get_session,
    save_session,
)
from app.services.deepgram_service import DeepgramService
from app.services.elevenlabs_service import ElevenLabsService
from app.utils.logger import get_logger

router = APIRouter(prefix="/telnyx", tags=["telnyx"])
logger = get_logger(__name__)

_FALLBACK_TEXT = "I'm sorry, I didn't catch that. Could you repeat that please?"


# ─── Helpers ──────────────────────────────────────────────────────────────────


async def _validate_telnyx(request: Request) -> bool:
    """
    In production, Telnyx signs webhooks with Ed25519 using the public key
    found in Mission Control → API Keys → Webhook signing. Set TELNYX_PUBLIC_KEY
    and implement full verification here before going to prod.
    """
    settings = get_settings()
    if settings.debug:
        return True
    sig = request.headers.get("telnyx-signature-ed25519", "")
    ts = request.headers.get("telnyx-timestamp", "")
    if not sig or not ts:
        return False
    # Full Ed25519 verification: verify sig over f"{ts}|{body}" using settings.telnyx_public_key
    return True


async def _send_audio_chunks(websocket: WebSocket, chunks: list[str]) -> None:
    for chunk in chunks:
        await websocket.send_json({"event": "media", "media": {"payload": chunk}})


async def _stream_tts(
    websocket: WebSocket,
    text: str,
    fallback_audio: list[str],
) -> None:
    try:
        async for chunk in ElevenLabsService().synthesize(text):
            await websocket.send_json({"event": "media", "media": {"payload": chunk}})
    except ElevenLabsError as exc:
        logger.error("tts_failed", error=str(exc))
        await _send_audio_chunks(websocket, fallback_audio)


async def _handle_call_end(call_control_id: str, caller_number: str) -> None:
    try:
        all_appts = await list_appointments()
        call_appts = [a for a in all_appts if a.call_sid == call_control_id]
        if not call_appts:
            return
        settings = get_settings()
        appt = call_appts[-1]
        body = (
            f"Your {appt.service} appointment is confirmed for "
            f"{appt.date} at {appt.time}. "
            f"Confirmation: {appt.id[:8].upper()}. "
            f"Thank you for choosing {settings.business_name}!"
        )
        await telnyx_service.send_sms(caller_number, body)
    except TelnyxError as exc:
        logger.error("appointment_sms_failed", call_control_id=call_control_id, error=str(exc))
    except Exception as exc:
        logger.error("call_end_cleanup_error", call_control_id=call_control_id, error=str(exc))


# ─── Webhook endpoint ─────────────────────────────────────────────────────────


@router.post("/webhook")
async def telnyx_webhook(request: Request) -> Response:
    """
    Receives all Telnyx call-control events (JSON, not form-encoded).
    Drives the call lifecycle: initiated → answered → streaming → hangup.
    """
    if not await _validate_telnyx(request):
        logger.warning("invalid_telnyx_signature")
        return Response(status_code=403)

    body = await request.json()
    data = body.get("data", {})
    event_type = data.get("event_type", "")
    payload = data.get("payload", {})
    call_control_id: str = payload.get("call_control_id", "")

    logger.info("telnyx_event", event_type=event_type, call_control_id=call_control_id)

    if event_type == "call.initiated":
        caller = payload.get("from", "unknown")
        await create_session(call_sid=call_control_id, caller_number=caller)
        try:
            await telnyx_service.answer_call(call_control_id)
        except TelnyxError as exc:
            logger.error("telnyx_answer_failed", error=str(exc))

    elif event_type == "call.answered":
        settings = get_settings()
        # Derive the WebSocket URL from BASE_URL (same public host, different scheme)
        ws_url = (
            settings.base_url
            .replace("https://", "wss://")
            .replace("http://", "ws://")
            .rstrip("/")
        )
        stream_url = f"{ws_url}/telnyx/stream"
        try:
            await telnyx_service.start_streaming(call_control_id, stream_url)
        except TelnyxError as exc:
            logger.error("telnyx_start_streaming_failed", error=str(exc))

    elif event_type == "call.hangup":
        await delete_session(call_control_id)

    # Telnyx requires a 200 OK — the body is ignored
    return Response(status_code=200)


# ─── WebSocket endpoint ───────────────────────────────────────────────────────


@router.websocket("/stream")
async def telnyx_stream(websocket: WebSocket) -> None:
    """
    Telnyx media stream pipeline:
      Telnyx μ-law audio → Deepgram STT → Claude agent → ElevenLabs TTS → Telnyx

    Telnyx opens this WebSocket after streaming_start is called. Key differences
    from the Twilio handler: no streamSid, and the clear event has no extra fields.
    """
    await websocket.accept()

    call_control_id: Optional[str] = None
    deepgram_svc: Optional[DeepgramService] = None

    fallback_audio: list[str] = getattr(websocket.app.state, "fallback_audio", [])
    transcript_queue: asyncio.Queue[Optional[str]] = asyncio.Queue()

    async def on_transcript(text: str) -> None:
        await transcript_queue.put(text)

    async def process_transcript_queue() -> None:
        while True:
            text = await transcript_queue.get()
            if text is None:
                break

            current_session = await get_session(call_control_id) if call_control_id else None
            if current_session is None:
                logger.warning("session_missing_during_turn", call_control_id=call_control_id)
                await _send_audio_chunks(websocket, fallback_audio)
                continue

            try:
                # Interrupt any in-progress playback before responding
                await websocket.send_json({"event": "clear"})

                agent_resp = await process_turn(current_session, text)
                await save_session(current_session)

                if agent_resp.transfer:
                    settings = get_settings()
                    logger.info("escalating_to_human", call_control_id=call_control_id)
                    try:
                        await telnyx_service.transfer_call(
                            call_control_id, settings.telnyx_human_agent_number
                        )
                    except TelnyxError as exc:
                        logger.error("warm_transfer_error", error=str(exc))
                    return

                await _stream_tts(websocket, agent_resp.text, fallback_audio)

            except ClaudeError as exc:
                logger.error("claude_turn_error", call_control_id=call_control_id, error=str(exc))
                await _send_audio_chunks(websocket, fallback_audio)
            except DeepgramError as exc:
                logger.error("deepgram_turn_error", call_control_id=call_control_id, error=str(exc))
                await _send_audio_chunks(websocket, fallback_audio)
            except ElevenLabsError as exc:
                logger.error("elevenlabs_turn_error", call_control_id=call_control_id, error=str(exc))
                await _send_audio_chunks(websocket, fallback_audio)
            except Exception as exc:
                logger.error("unexpected_turn_error", call_control_id=call_control_id, error=str(exc))
                await _send_audio_chunks(websocket, fallback_audio)

    processor_task = asyncio.create_task(process_transcript_queue())

    try:
        async for raw_msg in websocket.iter_text():
            msg = json.loads(raw_msg)
            event = msg.get("event")

            if event == "connected":
                logger.info("telnyx_ws_connected")

            elif event == "start":
                start = msg["start"]
                call_control_id = start["call_control_id"]
                caller = start.get("from", start.get("from_number", "unknown"))

                session = await get_session(call_control_id)
                if session is None:
                    logger.warning("session_not_found_on_start", call_control_id=call_control_id)
                    session = await create_session(call_control_id, caller)

                deepgram_svc = DeepgramService(on_transcript)
                try:
                    await deepgram_svc.connect()
                except DeepgramError as exc:
                    logger.error("deepgram_connect_error_on_start", error=str(exc))
                    deepgram_svc = None

                logger.info(
                    "telnyx_stream_started",
                    call_control_id=call_control_id,
                    caller=session.caller_number,
                )

                greeting = (
                    f"Thank you for calling {get_settings().business_name}. "
                    "How can I help you today?"
                )
                await _stream_tts(websocket, greeting, fallback_audio)

            elif event == "media":
                if deepgram_svc is not None:
                    audio_bytes = base64.b64decode(msg["media"]["payload"])
                    try:
                        await deepgram_svc.send_audio(audio_bytes)
                    except DeepgramError as exc:
                        logger.error("deepgram_send_error", error=str(exc))

            elif event == "stop":
                logger.info("telnyx_stream_stopped", call_control_id=call_control_id)
                if deepgram_svc is not None:
                    await deepgram_svc.disconnect()
                    deepgram_svc = None

                if call_control_id:
                    final_session = await get_session(call_control_id)
                    caller_number = final_session.caller_number if final_session else "unknown"
                    if final_session:
                        await save_session(final_session)
                    await _handle_call_end(call_control_id, caller_number)

    except WebSocketDisconnect:
        logger.info("telnyx_websocket_disconnected", call_control_id=call_control_id)
    except Exception as exc:
        logger.error("telnyx_websocket_loop_error", call_control_id=call_control_id, error=str(exc))
    finally:
        await transcript_queue.put(None)
        try:
            await asyncio.wait_for(processor_task, timeout=5.0)
        except asyncio.TimeoutError:
            processor_task.cancel()

        if deepgram_svc is not None:
            await deepgram_svc.disconnect()

        if call_control_id:
            final_session = await get_session(call_control_id)
            if final_session:
                await save_session(final_session)
