from __future__ import annotations

import json
from typing import Any

from app.agent.prompt import build_system_prompt
from app.agent.tools import TOOLS, ProcessTurnResult, execute_tool
from app.utils.logger import get_logger

logger = get_logger(__name__)


class OpenAIProvider:
    def __init__(self, settings):
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.settings = settings
        self.model = settings.openai_model

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
