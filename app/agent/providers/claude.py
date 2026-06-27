from __future__ import annotations

from typing import Any

from app.agent.prompt import build_system_prompt
from app.agent.tools import TOOLS, ProcessTurnResult, execute_tool
from app.utils.logger import get_logger

logger = get_logger(__name__)


class ClaudeProvider:
    def __init__(self, settings):
        from anthropic import AsyncAnthropic
        self.client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        self.settings = settings
        self.model = settings.claude_model

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
