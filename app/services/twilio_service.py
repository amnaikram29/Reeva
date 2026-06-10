from __future__ import annotations

from twilio.rest import Client

from app.config import get_settings
from app.exceptions import TwilioError
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _client() -> Client:
    s = get_settings()
    return Client(s.twilio_account_sid, s.twilio_auth_token)


async def send_sms(to_number: str, message: str) -> None:
    """Send an SMS from the business Twilio number."""
    settings = get_settings()
    try:
        msg = _client().messages.create(
            to=to_number,
            from_=settings.twilio_phone_number,
            body=message,
        )
        logger.info("sms_sent", to=to_number, sid=msg.sid)
    except Exception as exc:
        logger.error("sms_failed", to=to_number, error=str(exc))
        raise TwilioError(f"SMS to {to_number} failed: {exc}") from exc


async def warm_transfer(call_sid: str, to_number: str) -> None:
    """
    Update the live call with transfer TwiML, redirecting the caller to
    to_number immediately without hanging up first.
    """
    from app.utils.twiml_builder import transfer_call_response

    try:
        _client().calls(call_sid).update(twiml=transfer_call_response(to_number))
        logger.info("warm_transfer_initiated", call_sid=call_sid, to=to_number)
    except Exception as exc:
        logger.error("warm_transfer_failed", call_sid=call_sid, to=to_number, error=str(exc))
        raise TwilioError(f"Warm transfer for {call_sid} failed: {exc}") from exc
