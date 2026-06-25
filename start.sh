#!/usr/bin/env bash
# start.sh — Reeva AI Voice Receptionist — Mac/Linux launcher
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

fail() {
    echo -e "\n${RED}ERROR — Step $1 failed: $2${NC}" >&2
    exit 1
}

# ─── Step 1: Check Docker Desktop ────────────────────────────────────────────
echo -n "Checking Docker Desktop... "
docker info > /dev/null 2>&1 || {
    echo -e "\n${RED}Docker Desktop is not running. Please open it manually, then re-run this script.${NC}"
    exit 1
}
echo -e "${GREEN}OK${NC}"

# ─── Step 2: Start the stack ─────────────────────────────────────────────────
echo "Starting stack (docker compose up -d --build)..."
docker compose up -d --build || fail "2" "docker compose up failed"

# ─── Step 3: Wait for redis + app to be healthy (60s timeout) ────────────────
echo "Waiting for containers to be healthy (timeout: 60s)..."
ALL_HEALTHY=false
ELAPSED=0
while [ "$ELAPSED" -lt 60 ]; do
    sleep 2
    ELAPSED=$((ELAPSED + 2))

    REDIS_ID=$(docker compose ps -q redis 2>/dev/null || true)
    APP_ID=$(docker compose ps -q app 2>/dev/null || true)
    [ -z "$REDIS_ID" ] || [ -z "$APP_ID" ] && continue

    REDIS_HEALTH=$(docker inspect --format '{{.State.Health.Status}}' "$REDIS_ID" 2>/dev/null || echo "unknown")
    APP_HEALTH=$(docker inspect --format '{{.State.Health.Status}}' "$APP_ID" 2>/dev/null || echo "unknown")

    echo "  redis=$REDIS_HEALTH  app=$APP_HEALTH"

    if [ "$REDIS_HEALTH" = "healthy" ] && [ "$APP_HEALTH" = "healthy" ]; then
        ALL_HEALTHY=true
        break
    fi
done
[ "$ALL_HEALTHY" = "true" ] || fail "3" "containers not healthy after 60s. Run: docker compose logs"

# ─── Step 4: Poll ngrok for the https tunnel (30s timeout) ───────────────────
echo "Waiting for ngrok tunnel (timeout: 30s)..."
NGROK_URL=""
for _ in $(seq 1 15); do
    sleep 2
    NGROK_URL=$(python3 - <<'EOF'
import urllib.request, json, sys
try:
    data = json.loads(urllib.request.urlopen("http://localhost:4040/api/tunnels", timeout=2).read())
    urls = [t["public_url"] for t in data.get("tunnels", []) if t["public_url"].startswith("https://")]
    print(urls[0] if urls else "", end="")
except Exception:
    print("", end="")
EOF
)
    [ -n "$NGROK_URL" ] && break
done
[ -n "$NGROK_URL" ] || fail "4" "ngrok https tunnel not found after 30s. Run: docker compose logs ngrok"

# Read Telnyx phone number from .env
TELNYX_NUMBER=$(grep -m1 '^TELNYX_PHONE_NUMBER=' .env 2>/dev/null | cut -d= -f2 || true)

# ─── Step 5: Summary ─────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}============================================${NC}"
echo -e "${GREEN}${BOLD}ALL SERVICES RUNNING${NC}"
echo ""
echo "Redis:     healthy"
echo "App:       running on http://localhost:8000"
echo "Ngrok URL: $NGROK_URL"
echo ""
echo -e "${YELLOW}--> Update Telnyx webhook to:${NC}"
echo -e "${YELLOW}    $NGROK_URL/telnyx/webhook${NC}"
if [ -n "$TELNYX_NUMBER" ]; then
    echo ""
    echo -e "${YELLOW}--> Then call: $TELNYX_NUMBER${NC}"
fi
echo -e "${CYAN}============================================${NC}"
echo ""

# ─── Step 6: Tail app logs ───────────────────────────────────────────────────
echo "Tailing app logs (Ctrl+C to stop)..."
docker compose logs -f app
