from __future__ import annotations

from typing import Optional

import redis.asyncio as aioredis

from app.config import get_settings
from app.models.session import CallSession
from app.utils.logger import get_logger

logger = get_logger(__name__)

_redis: Optional[aioredis.Redis] = None


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        settings = get_settings()
        _redis = await aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis


def _key(call_sid: str) -> str:
    return f"session:{call_sid}"


async def create_session(call_sid: str, caller_number: str) -> CallSession:
    session = CallSession(call_sid=call_sid, caller_number=caller_number)
    await save_session(session)
    logger.info("session_created", call_sid=call_sid, caller=caller_number)
    return session


async def get_session(call_sid: str) -> Optional[CallSession]:
    r = await get_redis()
    raw = await r.get(_key(call_sid))
    if raw is None:
        return None
    return CallSession.model_validate_json(raw)


async def save_session(session: CallSession) -> None:
    r = await get_redis()
    settings = get_settings()
    await r.setex(
        _key(session.call_sid),
        settings.session_ttl_seconds,
        session.model_dump_json(),
    )


async def delete_session(call_sid: str) -> None:
    r = await get_redis()
    await r.delete(_key(call_sid))
    logger.info("session_deleted", call_sid=call_sid)


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
