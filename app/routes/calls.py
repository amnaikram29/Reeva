from __future__ import annotations

import asyncio
import base64
import json
from typing import Optional

from fastapi import APIRouter, Form, Request, Response, WebSocket, WebSocketDisconnect
from twilio.request_validator import RequestValidator

from app.config import get_settings
from app.exceptions import ClaudeError, DeepgramError, ElevenLabsError, TwilioError
from app.services import twilio_service
from app.services.ai_agent import process_turn
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
from app.utils.twiml_builder import incoming_call_response

router = APIRouter(prefix="/calls", tags=["calls"])
logger = get_logger(__name__)

_FALLBACK_TEXT = "I'm sorry, I didn't catch that. Could you repeat that please?"


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _xml(content: str) -> Response:
    return Response(content=content, media_type="text/xml")


async def _validate_twilio(request: Request, params: dict) -> bool:
    settings = get_settings()
    if settings.debug:
        return True
    validator = RequestValidator(settings.twilio_auth_token)
    signature = request.headers.get("X-Twilio-Signature", "")
    return validator.validate(str(request.url), params, signature)


async def _send_audio_chunks(
    websocket: WebSocket,
    stream_sid: str,
    chunks: list[str],
) -> None:
    """Send a pre-built list of base64 mulaw chunks over the media stream."""
    for chunk in chunks:
        await websocket.send_json({
            "event": "media",
            "streamSid": stream_sid,
            "media": {"payload": chunk},
        })


async def _stream_tts(
    websocket: WebSocket,
    stream_sid: str,
    text: str,
    fallback_audio: list[str],
) -> None:
    """Synthesize text with ElevenLabs and stream chunks to the caller."""
    try:
        svc = ElevenLabsService()
        async for chunk in svc.synthesize(text):
            await websocket.send_json({
                "event": "media",
                "streamSid": stream_sid,
                "media": {"payload": chunk},
            })
    except ElevenLabsError as exc:
        logger.error("tts_failed", error=str(exc))
        await _send_audio_chunks(websocket, stream_sid, fallback_audio)


async def _handle_call_end(call_sid: str, caller_number: str) -> None:
    """Send appointment confirmation SMS if a booking occurred during this call."""
    try:
        all_appts = await list_appointments()
        call_appts = [a for a in all_appts if a.call_sid == call_sid]
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
        await twilio_service.send_sms(caller_number, body)
    except TwilioError as exc:
        logger.error("appointment_sms_failed", call_sid=call_sid, error=str(exc))
    except Exception as exc:
        logger.error("call_end_cleanup_error", call_sid=call_sid, error=str(exc))


# ─── HTTP endpoint ────────────────────────────────────────────────────────────


@router.post("/incoming")
async def incoming_call(
    request: Request,
    CallSid: str = Form(...),
    From: str = Form(...),
    To: str = Form(...),
):
    """
    Twilio calls this when a call arrives. We respond with TwiML that opens
    a media stream WebSocket — the WebSocket handler drives the conversation.
    """
    params = {"CallSid": CallSid, "From": From, "To": To}
    if not await _validate_twilio(request, params):
        logger.warning("invalid_twilio_signature", call_sid=CallSid)
        return Response(status_code=403)

    logger.info("call_incoming", call_sid=CallSid, from_number=From)

    # Create session now so the WebSocket handler can retrieve caller_number
    await create_session(call_sid=CallSid, caller_number=From)

    host = request.headers.get("host", "")
    scheme = "wss" if request.url.scheme == "https" else "ws"
    websocket_url = f"{scheme}://{host}/calls/stream"

    return _xml(incoming_call_response(websocket_url))


@router.post("/status")
async def call_status(CallSid: str = Form(...), CallStatus: str = Form(...)):
    logger.info("call_status_update", call_sid=CallSid, status=CallStatus)
    if CallStatus in ("completed", "failed", "busy", "no-answer", "canceled"):
        await delete_session(CallSid)
    return Response(status_code=204)


# ─── WebSocket endpoint ───────────────────────────────────────────────────────


@router.websocket("/stream")
async def call_stream(websocket: WebSocket):
    """
    Core real-time pipeline:
      Twilio mulaw audio → Deepgram STT → Claude agent → ElevenLabs TTS → Twilio
    One WebSocket connection per call. All state lives in the CallSession.
    """
    await websocket.accept()

    call_sid: Optional[str] = None
    stream_sid: Optional[str] = None
    deepgram_svc: Optional[DeepgramService] = None

    # Pre-cached fallback audio from app startup
    fallback_audio: list[str] = getattr(websocket.app.state, "fallback_audio", [])

    # asyncio.Queue decouples the Deepgram callback (fires externally) from the
    # WebSocket send loop, preventing concurrent writes on the same socket.
    transcript_queue: asyncio.Queue[Optional[str]] = asyncio.Queue()

    async def on_transcript(text: str) -> None:
        await transcript_queue.put(text)

    async def process_transcript_queue() -> None:
        """
        Background task: consume transcripts, run the Claude agent, synthesize
        audio with ElevenLabs, and stream the result back through the WebSocket.
        One turn at a time — if a new transcript arrives mid-synthesis, we clear
        Twilio's playback buffer before starting the next response.
        """
        while True:
            text = await transcript_queue.get()
            if text is None:  # shutdown sentinel
                break

            if stream_sid is None:
                continue

            # Retrieve fresh session each turn (avoids stale state across turns)
            current_session = await get_session(call_sid) if call_sid else None
            if current_session is None:
                logger.warning("session_missing_during_turn", call_sid=call_sid)
                await _send_audio_chunks(websocket, stream_sid, fallback_audio)
                continue

            try:
                # Interrupt any in-progress playback before responding
                await websocket.send_json({"event": "clear", "streamSid": stream_sid})

                agent_resp = await process_turn(current_session, text)
                await save_session(current_session)

                if agent_resp.transfer:
                    settings = get_settings()
                    logger.info("escalating_to_human", call_sid=call_sid)
                    try:
                        await twilio_service.warm_transfer(
                            call_sid, settings.twilio_human_agent_number
                        )
                    except TwilioError as exc:
                        logger.error("warm_transfer_error", error=str(exc))
                    return  # stop processing; Twilio is redirecting the call

                await _stream_tts(websocket, stream_sid, agent_resp.text, fallback_audio)

            except ClaudeError as exc:
                logger.error("claude_turn_error", call_sid=call_sid, error=str(exc))
                await _send_audio_chunks(websocket, stream_sid, fallback_audio)
            except DeepgramError as exc:
                logger.error("deepgram_turn_error", call_sid=call_sid, error=str(exc))
                await _send_audio_chunks(websocket, stream_sid, fallback_audio)
            except ElevenLabsError as exc:
                logger.error("elevenlabs_turn_error", call_sid=call_sid, error=str(exc))
                await _send_audio_chunks(websocket, stream_sid, fallback_audio)
            except Exception as exc:
                logger.error("unexpected_turn_error", call_sid=call_sid, error=str(exc))
                await _send_audio_chunks(websocket, stream_sid, fallback_audio)

    processor_task = asyncio.create_task(process_transcript_queue())

    try:
        async for raw_msg in websocket.iter_text():
            msg = json.loads(raw_msg)
            event = msg.get("event")

            if event == "connected":
                logger.info("twilio_ws_connected")

            elif event == "start":
                call_sid = msg["start"]["callSid"]
                stream_sid = msg["start"]["streamSid"]

                # Session was created in POST /calls/incoming — retrieve it
                session = await get_session(call_sid)
                if session is None:
                    logger.warning("session_not_found_on_start", call_sid=call_sid)
                    session = await create_session(call_sid, "unknown")

                deepgram_svc = DeepgramService(on_transcript)
                try:
                    await deepgram_svc.connect()
                except DeepgramError as exc:
                    logger.error("deepgram_connect_error_on_start", error=str(exc))
                    deepgram_svc = None

                logger.info(
                    "stream_started",
                    call_sid=call_sid,
                    stream_sid=stream_sid,
                    caller=session.caller_number,
                )

                # Greet the caller — synthesize the opening line
                greeting = (
                    f"Thank you for calling {get_settings().business_name}. "
                    "How can I help you today?"
                )
                if stream_sid:
                    await _stream_tts(websocket, stream_sid, greeting, fallback_audio)

            elif event == "media":
                if deepgram_svc is not None:
                    payload = msg["media"]["payload"]
                    audio_bytes = base64.b64decode(payload)
                    try:
                        await deepgram_svc.send_audio(audio_bytes)
                    except DeepgramError as exc:
                        logger.error("deepgram_send_error", error=str(exc))

            elif event == "stop":
                logger.info("stream_stopped", call_sid=call_sid)
                if deepgram_svc is not None:
                    await deepgram_svc.disconnect()
                    deepgram_svc = None

                # Final session save + appointment SMS
                if call_sid:
                    final_session = await get_session(call_sid)
                    caller_number = final_session.caller_number if final_session else "unknown"
                    await save_session(final_session) if final_session else None
                    await _handle_call_end(call_sid, caller_number)

    except WebSocketDisconnect:
        logger.info("websocket_disconnected", call_sid=call_sid)
    except Exception as exc:
        logger.error("websocket_loop_error", call_sid=call_sid, error=str(exc))
    finally:
        # Signal processor to exit, then wait for it to drain
        await transcript_queue.put(None)
        try:
            await asyncio.wait_for(processor_task, timeout=5.0)
        except asyncio.TimeoutError:
            processor_task.cancel()

        if deepgram_svc is not None:
            await deepgram_svc.disconnect()

        if call_sid:
            final_session = await get_session(call_sid)
            if final_session:
                await save_session(final_session)
