from __future__ import annotations

from typing import Optional, Union

from app.agent.providers import ClaudeProvider, OpenAIProvider
from app.config import get_settings
from app.exceptions import ClaudeError
from app.models.session import CallSession
from app.utils.logger import get_logger

logger = get_logger(__name__)


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


_provider_instance: Optional[Union[ClaudeProvider, OpenAIProvider]] = None


def get_ai_provider() -> Union[ClaudeProvider, OpenAIProvider]:
    global _provider_instance
    if _provider_instance is None:
        settings = get_settings()
        _provider_instance = (
            OpenAIProvider(settings)
            if settings.ai_provider == "openai"
            else ClaudeProvider(settings)
        )
    return _provider_instance


async def process_turn(session: CallSession, user_input: str) -> AgentResponse:
    settings = get_settings()
    session.add_message("user", user_input)
    messages = session.to_anthropic_messages()

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
