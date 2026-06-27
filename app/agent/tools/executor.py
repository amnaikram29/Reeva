from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.models.appointment import Appointment
from app.services.appointment_service import book_appointment, check_slot_available
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ProcessTurnResult:
    text: str
    escalate: bool = False
    escalation_reason: str = ""
    end_call: bool = False


async def execute_tool(
    name: str,
    args: dict[str, Any],
    settings,
    call_sid: str = "",
    caller_number: str = "",
) -> str:
    """
    Returns "__ESCALATE__" for escalate_to_human; returns "" for answer_faq when no
    match is found — both signal to the provider that escalation is needed.
    """
    from app.agent.prompt import build_faq, lookup_faq

    faq = build_faq(settings)

    if name == "check_availability":
        available = await check_slot_available(args["date"], args["time"])
        if available:
            return f"We have availability on {args['date']} at {args['time']}."
        return "I'm sorry, we have no availability at that time. Can I suggest another slot?"

    if name == "book_appointment":
        appt = Appointment(
            call_sid=call_sid or "unknown",
            caller_name=args["name"],
            caller_phone=args.get("phone", caller_number),
            service=args["service"],
            date=args["date"],
            time=args["time"],
        )
        success = await book_appointment(appt)
        if success:
            logger.info("appointment_booked", call_sid=call_sid, summary=appt.friendly_summary())
            return (
                f"Perfect, I've booked your {args['service']} for "
                f"{args['date']} at {args['time']}. "
                f"You'll receive an SMS confirmation shortly."
            )
        return "I'm sorry, that slot was just taken. Let me check another time for you."

    if name == "answer_faq":
        return lookup_faq(args["question"], faq)  # "" = no match → provider escalates

    if name == "escalate_to_human":
        return "__ESCALATE__"

    return "I couldn't process that request."
