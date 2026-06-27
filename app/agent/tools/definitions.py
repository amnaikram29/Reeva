from __future__ import annotations

from typing import Any

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
