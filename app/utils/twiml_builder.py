from __future__ import annotations

from twilio.twiml.voice_response import Connect, Dial, Stream, VoiceResponse


def incoming_call_response(websocket_url: str) -> str:
    """
    Returns TwiML that immediately opens a bidirectional media stream to
    websocket_url. No greeting audio — the agent speaks via the WebSocket.
    track=inbound_track captures caller audio only (we send TTS back explicitly).
    """
    vr = VoiceResponse()
    connect = Connect()
    connect.stream(url=websocket_url, track="inbound_track")
    vr.append(connect)
    return str(vr)


def transfer_call_response(to_number: str) -> str:
    """Returns TwiML that dials to_number with a 30-second ring timeout."""
    vr = VoiceResponse()
    dial = Dial(
        timeout=30,
        action="/calls/status",
        record="record-from-answer-dual",
    )
    dial.number(to_number)
    vr.append(dial)
    return str(vr)
