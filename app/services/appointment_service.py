from __future__ import annotations

from typing import Optional

from app.models.appointment import Appointment
from app.services.call_session import get_redis
from app.utils.logger import get_logger

logger = get_logger(__name__)

_APPTS_HASH = "appointments:all"
_SLOTS_PREFIX = "slots:"


def _slot_key(date: str, time_str: str) -> str:
    return f"{_SLOTS_PREFIX}{date}:{time_str}"


async def check_slot_available(date: str, time_str: str) -> bool:
    r = await get_redis()
    return not await r.exists(_slot_key(date, time_str))


async def book_appointment(appt: Appointment) -> bool:
    r = await get_redis()
    slot = _slot_key(appt.date, appt.time)

    # Atomic: SET NX ensures only one booking per slot even under concurrency
    booked = await r.set(slot, appt.id, nx=True, ex=60 * 60 * 24 * 90)
    if not booked:
        logger.warning("slot_already_taken", date=appt.date, time=appt.time)
        return False

    await r.hset(_APPTS_HASH, appt.id, appt.model_dump_json())
    logger.info("appointment_booked", appt_id=appt.id, service=appt.service, date=appt.date, time=appt.time)
    return True


async def get_appointment(appt_id: str) -> Optional[Appointment]:
    r = await get_redis()
    raw = await r.hget(_APPTS_HASH, appt_id)
    if raw is None:
        return None
    return Appointment.model_validate_json(raw)


async def list_appointments() -> list[Appointment]:
    r = await get_redis()
    all_raw = await r.hgetall(_APPTS_HASH)
    appts = [Appointment.model_validate_json(v) for v in all_raw.values()]
    return sorted(appts, key=lambda a: (a.date, a.time))


async def cancel_appointment(appt_id: str) -> bool:
    r = await get_redis()
    appt = await get_appointment(appt_id)
    if appt is None:
        return False
    await r.hdel(_APPTS_HASH, appt_id)
    await r.delete(_slot_key(appt.date, appt.time))
    logger.info("appointment_cancelled", appt_id=appt_id)
    return True
