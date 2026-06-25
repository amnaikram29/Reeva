# Reeva — AI Voice Receptionist

A production-grade AI voice receptionist backend. When someone calls your Telnyx number, Reeva answers, understands natural speech, books appointments, transfers to a human when needed, and sends an SMS confirmation — all in real time.

## Stack

| Layer | Technology |
|-------|------------|
| Telephony | [Telnyx](https://telnyx.com) — inbound calls, media streaming, SMS |
| Speech-to-text | [Deepgram](https://deepgram.com) Nova-2 — streaming, real-time |
| AI brain | [Claude](https://anthropic.com) (`claude-sonnet-4-6`) or OpenAI GPT-4o — tool-use agent |
| Text-to-speech | [ElevenLabs](https://elevenlabs.io) — streaming, low-latency |
| Session state | [Redis](https://redis.io) — call sessions + atomic appointment slot locking |
| Web framework | [FastAPI](https://fastapi.tiangolo.com) + uvicorn |
| Tunnel (dev) | [ngrok](https://ngrok.com) — exposes local port to Telnyx |

## Quick Start

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and **already running** (cannot be started from a script)
- API keys for: Telnyx, Deepgram, ElevenLabs, Anthropic (and/or OpenAI)
- A free [ngrok](https://ngrok.com) account — copy your authtoken from the dashboard

### Steps

**1. Copy and fill in your environment file**

```bash
cp .env.example .env
```

Open `.env` and fill in every value, including `NGROK_AUTHTOKEN`.

**2. Open Docker Desktop**

Must be running before the next step. There is no way to start it from a script.

**3. Start the full stack**

```powershell
# Windows
.\start.ps1
```

```bash
# Mac / Linux
chmod +x start.sh
./start.sh
```

The script builds the images, waits for every service to be healthy, polls for the ngrok tunnel, then prints a summary like this:

```
============================================
ALL SERVICES RUNNING

Redis:     healthy
App:       running on http://localhost:8000
Ngrok URL: https://xxxx-xx-xx-xx-xx.ngrok-free.app

--> Update Telnyx webhook to:
    https://xxxx-xx-xx-xx-xx.ngrok-free.app/telnyx/webhook

--> Then call: +1XXXXXXXXXX
============================================
```

**4. Wire the webhook in Telnyx**

In [Telnyx Mission Control](https://portal.telnyx.com):

> **Voice API Application → your app → Inbound Settings → Webhook URL**

Paste the ngrok URL printed by the script, appending `/telnyx/webhook`:

```
https://xxxx-xx-xx-xx-xx.ngrok-free.app/telnyx/webhook
```

**5. Call the number**

Dial the Telnyx number shown in the summary and speak to Reeva.

### Stopping the stack

```powershell
# Windows
docker compose down
```

```bash
# Mac / Linux
make down
```

## API

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/telnyx/webhook` | Telnyx call-control events (answer, hangup, etc.) |
| `WS` | `/telnyx/stream` | Real-time media stream (Deepgram → Claude → ElevenLabs) |
| `GET` | `/appointments/` | List all booked appointments |
| `GET` | `/appointments/{id}` | Get a single appointment |
| `DELETE` | `/appointments/{id}` | Cancel an appointment |
| `GET` | `/health` | Redis + Deepgram connectivity check |

## Project Structure

```
app/
├── routes/
│   ├── telnyx.py            # Webhook + WebSocket media stream
│   ├── appointments.py      # Appointment REST API
│   └── health.py
├── services/
│   ├── telnyx_service.py    # Telnyx Call Control REST calls
│   ├── ai_agent.py          # Claude / OpenAI tool-use agent
│   ├── deepgram_service.py  # Streaming STT
│   ├── elevenlabs_service.py# Streaming TTS
│   ├── appointment_service.py
│   └── call_session.py      # Redis session management
├── models/
├── utils/
├── config.py                # All env vars via pydantic-settings
├── exceptions.py
└── main.py
Dockerfile
docker-compose.yml           # redis + app + ngrok
start.ps1                    # Windows one-command launcher
start.sh                     # Mac/Linux one-command launcher
```
