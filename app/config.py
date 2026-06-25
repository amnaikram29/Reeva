from __future__ import annotations

import json
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Server
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    debug: bool = False
    base_url: str = Field(..., description="Public base URL that Telnyx posts webhooks to")

    # Anthropic
    anthropic_api_key: str
    claude_model: str = "claude-sonnet-4-6"

    # Redis
    redis_url: str = "redis://localhost:6379"
    session_ttl_seconds: int = 3600

    # Business
    business_name: str
    business_phone_number: str
    business_address: str = ""
    business_timezone: str = "America/Chicago"
    business_hours: str = Field(
        ...,
        description='JSON map: day → {"open":"HH:MM","close":"HH:MM"} or null',
    )
    business_services: str = Field(
        ..., description="Comma-separated list of services offered"
    )

    # Deepgram STT
    deepgram_api_key: str

    # ElevenLabs TTS
    elevenlabs_api_key: str
    elevenlabs_voice_id: str

    # Telnyx
    telnyx_api_key: str = ""
    telnyx_phone_number: str = ""
    telnyx_public_key: str = ""  # Ed25519 public key for webhook signature verification
    telnyx_human_agent_number: str = ""

    # AI provider selection
    ai_provider: str = "claude"    # "claude" | "openai"
    openai_api_key: str = ""       # only required when ai_provider=openai
    openai_model: str = "gpt-4o"

    @field_validator("ai_provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        allowed = {"claude", "openai"}
        if v not in allowed:
            raise ValueError(f"AI_PROVIDER must be one of {allowed}, got '{v}'")
        return v

    @field_validator("business_hours")
    @classmethod
    def validate_hours_json(cls, v: str) -> str:
        try:
            json.loads(v)
        except json.JSONDecodeError as exc:
            raise ValueError(f"BUSINESS_HOURS must be valid JSON: {exc}") from exc
        return v

    def parsed_hours(self) -> dict:
        return json.loads(self.business_hours)

    def services_list(self) -> list[str]:
        return [s.strip() for s in self.business_services.split(",") if s.strip()]


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
