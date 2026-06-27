from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routes import appointments, health, telnyx
from app.services.call_session import close_redis
from app.utils.logger import configure_logging, get_logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(debug=settings.debug)
    logger = get_logger("startup")
    logger.info(
        "server_starting",
        business=settings.business_name,
        host=settings.app_host,
        port=settings.app_port,
        base_url=settings.base_url,
    )

    # Force provider instantiation at startup — bad API key fails here, not on first call
    from app.agent import get_ai_provider
    get_ai_provider()
    logger.info("ai_provider_ready", provider=get_settings().ai_provider)

    # Pre-synthesize fallback audio so the first error response is instant
    from app.services.elevenlabs_service import ElevenLabsService
    _FALLBACK = "I'm sorry, I didn't catch that. Could you repeat that please?"
    try:
        chunks: list[str] = []
        async for chunk in ElevenLabsService().synthesize(_FALLBACK):
            chunks.append(chunk)
        app.state.fallback_audio = chunks
        logger.info("fallback_audio_cached", chunks=len(chunks))
    except Exception as exc:
        logger.warning("fallback_audio_cache_failed", error=str(exc))
        app.state.fallback_audio = []

    yield
    await close_redis()
    get_logger("shutdown").info("server_stopped")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=f"{settings.business_name} — AI Voice Receptionist",
        description="Inbound call handler powered by Claude + Telnyx",
        version="1.0.0",
        docs_url="/docs" if settings.debug else None,
        redoc_url=None,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(telnyx.router)
    app.include_router(appointments.router)

    return app


app = create_app()
