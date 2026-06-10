from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class Appointment(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    call_sid: str
    caller_name: str
    caller_phone: str
    service: str
    date: str   # ISO "YYYY-MM-DD"
    time: str   # 24h "HH:MM"
    notes: Optional[str] = None
    status: str = "confirmed"
    created_at: datetime = Field(default_factory=datetime.utcnow)

    def friendly_summary(self) -> str:
        return f"{self.service} for {self.caller_name} on {self.date} at {self.time}"
