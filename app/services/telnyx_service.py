from __future__ import annotations

import httpx

from app.config import get_settings
from app.exceptions import TelnyxError
from app.utils.logger import get_logger

logger = get_logger(__name__)

_BASE = "https://api.telnyx.com/v2"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {get_settings().telnyx_api_key}",
        "Content-Type": "application/json",
    }


async def answer_call(call_control_id: str) -> None:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{_BASE}/calls/{call_control_id}/actions/answer",
            headers=_headers(),
        )
    if r.status_code not in (200, 201, 202):
        raise TelnyxError(f"answer_call failed ({r.status_code}): {r.text}")
    logger.info("telnyx_call_answered", call_control_id=call_control_id)


async def start_streaming(call_control_id: str, stream_url: str) -> None:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{_BASE}/calls/{call_control_id}/actions/streaming_start",
            headers=_headers(),
            json={"stream_url": stream_url, "stream_track": "inbound_track"},
        )
    if r.status_code not in (200, 201, 202):
        raise TelnyxError(f"start_streaming failed ({r.status_code}): {r.text}")
    logger.info("telnyx_streaming_started", call_control_id=call_control_id, stream_url=stream_url)


async def transfer_call(call_control_id: str, to_number: str) -> None:
    settings = get_settings()
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{_BASE}/calls/{call_control_id}/actions/transfer",
            headers=_headers(),
            json={"to": to_number, "from": settings.telnyx_phone_number},
        )
    if r.status_code not in (200, 201, 202):
        raise TelnyxError(f"transfer_call failed ({r.status_code}): {r.text}")
    logger.info("telnyx_warm_transfer_initiated", call_control_id=call_control_id, to=to_number)


async def hangup_call(call_control_id: str) -> None:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{_BASE}/calls/{call_control_id}/actions/hangup",
            headers=_headers(),
        )
    if r.status_code not in (200, 201, 202):
        logger.warning("telnyx_hangup_unexpected_status", status=r.status_code, call_control_id=call_control_id)
    else:
        logger.info("telnyx_hangup", call_control_id=call_control_id)


async def send_sms(to_number: str, message: str) -> None:
    settings = get_settings()
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{_BASE}/messages",
            headers=_headers(),
            json={
                "from": settings.telnyx_phone_number,
                "to": to_number,
                "text": message,
            },
        )
    if r.status_code not in (200, 201, 202):
        raise TelnyxError(f"send_sms to {to_number} failed ({r.status_code}): {r.text}")
    logger.info("telnyx_sms_sent", to=to_number)
