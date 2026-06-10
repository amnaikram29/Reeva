from __future__ import annotations

import asyncio

import httpx
import redis.asyncio as aioredis
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.services.business_hours import is_open, next_open_day

router = APIRouter(tags=["health"])


@router.get("/")
async def root():
    settings = get_settings()
    return {"service": f"{settings.business_name} Voice Receptionist", "version": "1.0.0"}


async def _check_redis(url: str) -> bool:
    try:
        r = await aioredis.from_url(url, decode_responses=True)
        await r.ping()
        await r.aclose()
        return True
    except Exception:
        return False


async def _check_deepgram(api_key: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                "https://api.deepgram.com/v1/projects",
                headers={"Authorization": f"Token {api_key}"},
            )
            return resp.status_code == 200
    except Exception:
        return False


@router.get("/health")
async def health_check():
    settings = get_settings()

    redis_ok, deepgram_ok = await asyncio.gather(
        _check_redis(settings.redis_url),
        _check_deepgram(settings.deepgram_api_key),
    )

    overall_ok = redis_ok and deepgram_ok
    open_now = is_open()

    return JSONResponse(
        status_code=200 if overall_ok else 503,
        content={
            "status": "healthy" if overall_ok else "degraded",
            "redis": "connected" if redis_ok else "disconnected",
            "deepgram": "reachable" if deepgram_ok else "unreachable",
            "business": settings.business_name,
            "business_open": open_now,
            "next_open_day": None if open_now else next_open_day(),
            "twilio_number": settings.twilio_phone_number,
        },
    )
