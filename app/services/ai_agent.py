from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional, Union

from app.config import get_settings
from app.exceptions import ClaudeError
from app.models.appointment import Appointment
from app.models.session import CallSession
from app.services.appointment_service import book_appointment, check_slot_available
from app.services.business_hours import hours_summary, is_open, next_open_day
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ─── Shared result type ───────────────────────────────────────────────────────

@dataclass
class ProcessTurnResult:
    text: str
    escalate: bool = False
    escalation_reason: str = ""
    end_call: bool = False


# ─── Public response type (unchanged — keeps calls.py unmodified) ─────────────

class AgentResponse:
    def __init__(
        self,
        text: str,
        transfer: bool = False,
        end_call: bool = False,
        transfer_number: Optional[str] = None,
    ):
        self.text = text
        self.transfer = transfer
        self.end_call = end_call
        self.transfer_number = transfer_number


# ─── Canonical tool list ──────────────────────────────────────────────────────
# Defined once; each provider's _convert_tools() maps to its native format.

TOOLS: list[dict[str, Any]] = [
    {
        "name": "check_availability",
        "description": "Check available appointment slots for a given date and time.",
        "parameters": {
            "date": {"type": "string", "description": "Requested date e.g. 'Monday' or '2024-06-10'"},
            "time": {"type": "string", "description": "Requested time e.g. '2pm' or '14:00'"},
        },
        "required": ["date", "time"],
    },
    {
        "name": "book_appointment",
        "description": "Book a confirmed appointment after the caller agrees to the slot.",
        "parameters": {
            "name":    {"type": "string", "description": "Caller full name"},
            "phone":   {"type": "string", "description": "Caller phone number"},
            "date":    {"type": "string", "description": "Confirmed date"},
            "time":    {"type": "string", "description": "Confirmed time"},
            "service": {"type": "string", "description": "Service being booked e.g. 'cleaning'"},
        },
        "required": ["name", "phone", "date", "time", "service"],
    },
    {
        "name": "answer_faq",
        "description": "Answer a frequently asked question about the business.",
        "parameters": {
            "question": {"type": "string", "description": "The caller's question verbatim"},
        },
        "required": ["question"],
    },
    {
        "name": "escalate_to_human",
        "description": (
            "Transfer to a human agent when the issue is complex, urgent, "
            "or the caller is distressed."
        ),
        "parameters": {
            "reason": {"type": "string", "description": "Brief reason for escalation"},
        },
        "required": ["reason"],
    },
]


# ─── System prompt ────────────────────────────────────────────────────────────

def build_system_prompt(settings) -> str:
    open_status = "OPEN" if is_open() else "CLOSED"
    next_day = next_open_day()
    next_info = f" Next open: {next_day}." if next_day else ""
    services = ", ".join(settings.services_list())

    return f"""You are a professional phone receptionist for {settings.business_name}.
Keep every response under 2 sentences — this is a phone call.
Never mention you are an AI unless directly asked.
If asked directly say: "I'm the virtual receptionist for {settings.business_name}."
Business status: {open_status}.{next_info}
Business hours: {settings.business_hours}
Address: {settings.business_address}
Services offered: {services}
Always confirm appointment details before booking.
For any emergency or urgent medical issue, use escalate_to_human immediately.
If you cannot resolve the issue, escalate — never end the call abruptly.
Speak naturally — no bullet points, no markdown, no lists."""


# ─── FAQ ──────────────────────────────────────────────────────────────────────

def build_faq(settings) -> dict[str, str]:
    address_line = (
        f"We are located at {settings.business_address}."
        if settings.business_address
        else "Please check our website or Google Maps for our address."
    )
    return {
        "hours":        f"We are open {settings.business_hours}.",
        "location":     address_line,
        "parking":      "We have free parking available on site.",
        "insurance":    "We accept most major insurance plans. Please call us to confirm yours.",
        "cancellation": "Please give us at least 24 hours notice to cancel or reschedule.",
        "pricing":      "Pricing depends on the service. We would be happy to give you a quote.",
        "emergency":    "For emergencies please come in immediately or call emergency services.",
    }


def lookup_faq(question: str, faq: dict[str, str]) -> str:
    q = question.lower()
    for key, answer in faq.items():
        if key in q:
            return answer
    return ""  # empty string = no match found


# ─── Shared tool executor ─────────────────────────────────────────────────────

async def execute_tool(
    name: str,
    args: dict[str, Any],
    settings,
    call_sid: str = "",
    caller_number: str = "",
) -> str:
    """
    Execute a canonical tool call and return a plain-text result string.
    Returns "__ESCALATE__" for escalate_to_human; returns "" for answer_faq
    when no match is found (caller should interpret both as escalation signals).
    """
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
        answer = lookup_faq(args["question"], faq)
        if answer:
            return answer
        return ""  # empty = no match → caller escalates

    if name == "escalate_to_human":
        return "__ESCALATE__"

    return "I couldn't process that request."


# ─── Claude provider ──────────────────────────────────────────────────────────

class ClaudeProvider:
    def __init__(self, settings):
        from anthropic import AsyncAnthropic
        self.client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        self.settings = settings
        self.model = settings.claude_model  # defaults to "claude-sonnet-4-6" via config

    def _convert_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": t["name"],
                "description": t["description"],
                "input_schema": {
                    "type": "object",
                    "properties": t["parameters"],
                    "required": t["required"],
                },
            }
            for t in TOOLS
        ]

    async def process_turn(
        self,
        messages: list[dict[str, Any]],
        call_sid: str = "",
        caller_number: str = "",
    ) -> ProcessTurnResult:
        system = build_system_prompt(self.settings)
        tools = self._convert_tools()
        history = list(messages)

        for _ in range(3):
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=300,
                system=system,
                tools=tools,
                messages=history,
            )

            if response.stop_reason == "end_turn":
                text = next(
                    (b.text for b in response.content if hasattr(b, "text") and b.text),
                    "",
                )
                return ProcessTurnResult(text=text)

            if response.stop_reason == "tool_use":
                history.append({"role": "assistant", "content": response.content})
                tool_results: list[dict[str, Any]] = []

                for block in response.content:
                    if not hasattr(block, "type") or block.type != "tool_use":
                        continue

                    if block.name == "escalate_to_human":
                        return ProcessTurnResult(
                            text="",
                            escalate=True,
                            escalation_reason=block.input.get("reason", ""),
                        )

                    result = await execute_tool(
                        block.name, block.input, self.settings, call_sid, caller_number
                    )

                    if result == "" and block.name == "answer_faq":
                        return ProcessTurnResult(
                            text="",
                            escalate=True,
                            escalation_reason="FAQ lookup failed — no matching answer",
                        )

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

                history.append({"role": "user", "content": tool_results})
                continue

            logger.warning("unexpected_claude_stop_reason", reason=response.stop_reason)
            break

        return ProcessTurnResult(text="Let me get someone to help you with that.")


# ─── OpenAI provider ──────────────────────────────────────────────────────────

class OpenAIProvider:
    def __init__(self, settings):
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.settings = settings
        self.model = settings.openai_model  # defaults to "gpt-4o" via config

    def _convert_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": {
                        "type": "object",
                        "properties": t["parameters"],
                        "required": t["required"],
                    },
                },
            }
            for t in TOOLS
        ]

    async def process_turn(
        self,
        messages: list[dict[str, Any]],
        call_sid: str = "",
        caller_number: str = "",
    ) -> ProcessTurnResult:
        system = build_system_prompt(self.settings)
        tools = self._convert_tools()
        # OpenAI: system message lives inside the messages array
        history: list[Any] = [{"role": "system", "content": system}] + list(messages)

        for _ in range(3):
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=history,
                tools=tools,
                tool_choice="auto",
                temperature=0.3,
                max_tokens=300,
            )

            choice = response.choices[0]

            if choice.finish_reason == "stop":
                return ProcessTurnResult(text=choice.message.content or "")

            if choice.finish_reason == "tool_calls":
                history.append(choice.message)

                for tool_call in choice.message.tool_calls:
                    name = tool_call.function.name
                    args = json.loads(tool_call.function.arguments)

                    if name == "escalate_to_human":
                        return ProcessTurnResult(
                            text="",
                            escalate=True,
                            escalation_reason=args.get("reason", ""),
                        )

                    result = await execute_tool(
                        name, args, self.settings, call_sid, caller_number
                    )

                    if result == "" and name == "answer_faq":
                        return ProcessTurnResult(
                            text="",
                            escalate=True,
                            escalation_reason="FAQ lookup failed — no matching answer",
                        )

                    history.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result,
                    })

                continue

            logger.warning("unexpected_openai_finish_reason", reason=choice.finish_reason)
            break

        return ProcessTurnResult(text="Let me get someone to help you with that.")


# ─── Factory ──────────────────────────────────────────────────────────────────

_provider_instance: Optional[Union[ClaudeProvider, OpenAIProvider]] = None


def get_ai_provider() -> Union[ClaudeProvider, OpenAIProvider]:
    global _provider_instance
    if _provider_instance is None:
        settings = get_settings()
        if settings.ai_provider == "openai":
            _provider_instance = OpenAIProvider(settings)
        else:
            _provider_instance = ClaudeProvider(settings)
    return _provider_instance


# ─── Public entry point ───────────────────────────────────────────────────────
# Signature is UNCHANGED — calls.py is not modified.

async def process_turn(session: CallSession, user_input: str) -> AgentResponse:
    """
    Run one conversational turn through the configured AI provider.
    Session message history is read and updated in-place; caller saves to Redis.
    Tool calls happen in-flight and are not persisted to the session.
    """
    settings = get_settings()
    session.add_message("user", user_input)
    messages = session.to_anthropic_messages()  # plain role/content dicts — compatible with both providers

    provider = get_ai_provider()
    try:
        result = await provider.process_turn(
            messages,
            call_sid=session.call_sid,
            caller_number=session.caller_number,
        )
    except Exception as exc:
        logger.error(
            "ai_provider_error",
            provider=settings.ai_provider,
            call_sid=session.call_sid,
            error=str(exc),
        )
        raise ClaudeError(str(exc)) from exc

    if result.escalate:
        session.escalated = True
        logger.info(
            "escalating_to_human",
            call_sid=session.call_sid,
            reason=result.escalation_reason,
        )
        return AgentResponse(
            text="One moment please, I'm connecting you now.",
            transfer=True,
            transfer_number=settings.business_phone_number,
        )

    session.add_message("assistant", result.text)
    return AgentResponse(text=result.text, end_call=result.end_call)
