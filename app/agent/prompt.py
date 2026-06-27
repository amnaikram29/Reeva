from __future__ import annotations

from app.services.business_hours import is_open, next_open_day


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
    return ""
