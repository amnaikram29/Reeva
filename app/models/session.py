from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class AppointmentDraft(BaseModel):
    caller_name: Optional[str] = None
    caller_phone: Optional[str] = None
    service: Optional[str] = None
    preferred_date: Optional[str] = None
    preferred_time: Optional[str] = None
    notes: Optional[str] = None


class CallSession(BaseModel):
    call_sid: str
    caller_number: str
    conversation: list[Message] = Field(default_factory=list)
    appointment_draft: Optional[AppointmentDraft] = None
    escalated: bool = False
    call_ended: bool = False
    gather_attempt: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def add_message(self, role: Literal["user", "assistant"], content: str) -> None:
        self.conversation.append(Message(role=role, content=content))
        self.updated_at = datetime.utcnow()

    def to_anthropic_messages(self) -> list[dict[str, Any]]:
        """Returns only the text turns — tool calls are managed in-flight, not persisted."""
        return [{"role": m.role, "content": m.content} for m in self.conversation]
