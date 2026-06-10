from __future__ import annotations

from datetime import datetime, time
from typing import Optional

import pytz

from app.config import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

_DAY_MAP = {
    0: "monday",
    1: "tuesday",
    2: "wednesday",
    3: "thursday",
    4: "friday",
    5: "saturday",
    6: "sunday",
}


def _parse_time(t: str) -> time:
    h, m = t.split(":")
    return time(int(h), int(m))


def is_open(now: Optional[datetime] = None) -> bool:
    settings = get_settings()
    hours = settings.parsed_hours()

    if now is None:
        local_tz = pytz.timezone(settings.business_timezone)
        now = datetime.now(local_tz)

    day_name = _DAY_MAP[now.weekday()]
    day_hours = hours.get(day_name)

    if not day_hours:
        return False

    open_time = _parse_time(day_hours["open"])
    close_time = _parse_time(day_hours["close"])
    current_time = now.time().replace(second=0, microsecond=0)
    return open_time <= current_time < close_time


def hours_summary() -> str:
    settings = get_settings()
    hours = settings.parsed_hours()
    lines = []
    for day, schedule in hours.items():
        if schedule:
            lines.append(f"  {day.capitalize()}: {schedule['open']} – {schedule['close']}")
        else:
            lines.append(f"  {day.capitalize()}: Closed")
    return "\n".join(lines)


def next_open_day() -> Optional[str]:
    """Return the name of the next day the business is open, or None."""
    settings = get_settings()
    hours = settings.parsed_hours()
    local_tz = pytz.timezone(settings.business_timezone)
    now = datetime.now(local_tz)

    for delta in range(1, 8):
        candidate = (now.weekday() + delta) % 7
        day_name = _DAY_MAP[candidate]
        if hours.get(day_name):
            return day_name.capitalize()
    return None
