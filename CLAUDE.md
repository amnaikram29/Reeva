# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run dev server (with hot reload)
make dev
# or: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Run prod server (4 workers)
make prod

# Lint
make lint
# or: ruff check app/

# Start full stack (Redis + app + ngrok) — requires Docker Desktop running
.\start.ps1          # Windows
./start.sh           # Mac/Linux

# Tear down Docker stack
docker compose down
```

## Architecture Overview

Reeva is a real-time AI voice receptionist. The call flow is:

1. **Telnyx** receives an inbound call and POST the `call.initiated` event to `/telnyx/webhook`
2. The webhook answers the call and then (on `call.answered`) instructs Telnyx to open a media stream WebSocket to `/telnyx/stream`
3. The WebSocket (`app/routes/telnyx.py`) runs a bidirectional audio pipeline:
   - Inbound μ-law audio from Telnyx → **Deepgram** (`DeepgramService`) — streaming STT
   - Transcripts land in an `asyncio.Queue` and are consumed by a background processor task
   - Each transcript → **AI agent** (`process_turn` in `app/services/ai_agent.py`) — tool-use agent
   - Agent response text → **ElevenLabs** (`ElevenLabsService`) — streaming TTS back to Telnyx
4. On hangup, an SMS confirmation is sent via `telnyx_service.send_sms` if an appointment was booked during the call

### AI Agent (`app/services/ai_agent.py`)

The agent is provider-agnostic. `AI_PROVIDER=claude` (default) uses `ClaudeProvider`; `AI_PROVIDER=openai` uses `OpenAIProvider`. Both implement the same `process_turn(messages, call_sid, caller_number) → ProcessTurnResult` interface. A single singleton is created at startup via `get_ai_provider()`.

The canonical tool list (`TOOLS`) is defined once and each provider's `_convert_tools()` translates it to its native API format. Tools available to the agent:
- `check_availability` — checks Redis for slot conflicts
- `book_appointment` — atomically reserves a slot with Redis `SET NX`
- `answer_faq` — keyword-matches a hardcoded FAQ dict
- `escalate_to_human` — triggers a Telnyx warm-transfer to `TELNYX_HUMAN_AGENT_NUMBER`

The agent runs up to 3 tool-call iterations before giving up. `escalate_to_human` always short-circuits the loop immediately.

### Session State (`app/services/call_session.py`)

`CallSession` (Pydantic model) is persisted to Redis as JSON under the key `session:{call_control_id}` with a TTL of `SESSION_TTL_SECONDS`. Tool calls are executed in-flight and **not** persisted — only the human/assistant text turns are stored in `session.conversation`.

### Appointment Storage (`app/services/appointment_service.py`)

All appointments live in Redis:
- Slot lock: `slots:{date}:{time}` key with `SET NX` (atomic, prevents double-booking)
- Appointment data: `appointments:all` hash keyed by appointment UUID

### Configuration (`app/config.py`)

All settings come from `.env` via `pydantic-settings`. The singleton `get_settings()` is cached globally. `BUSINESS_HOURS` must be a valid JSON string (validated at startup). `BASE_URL` must be the public-facing URL (ngrok in dev); it is rewritten to `wss://` to derive the WebSocket URL that Telnyx is told to connect to.

### Logging (`app/utils/logger.py`)

Structured logging throughout — every log call uses keyword args (e.g., `logger.info("event_name", key=value)`). In production (`DEBUG=false`), `/docs` is disabled.

### Webhook Signature Verification (`app/routes/telnyx.py`)

`_validate_telnyx()` is a stub — in `DEBUG=true` it always returns `True`. For production, implement Ed25519 verification over `f"{timestamp}|{body}"` using `TELNYX_PUBLIC_KEY`.

## Environment Setup

Copy `.env.example` to `.env` and fill in all values. Key non-obvious fields:
- `BASE_URL` — the ngrok HTTPS URL printed by `start.ps1`/`start.sh` (changes each run with free ngrok)
- `BUSINESS_HOURS` — must be a JSON string (see `.env.example` for the exact format)
- `TELNYX_PUBLIC_KEY` — optional in dev (`DEBUG=true`), required for webhook verification in prod
- `ELEVENLABS_VOICE_ID` — find in ElevenLabs dashboard under Voices
