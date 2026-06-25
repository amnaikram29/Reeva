# start.ps1 -- Reeva AI Voice Receptionist -- Windows launcher

function Fail {
    param([string]$Step, [string]$Reason)
    Write-Host ""
    Write-Host "ERROR -- Step $Step failed: $Reason" -ForegroundColor Red
    exit 1
}

# --- Step 1: Check Docker Desktop -------------------------------------------
Write-Host "Checking Docker Desktop..." -NoNewline
docker info 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Docker Desktop is not running. Please open it manually, then re-run this script." -ForegroundColor Red
    exit 1
}
Write-Host " OK" -ForegroundColor Green

# --- Step 2: Start the stack -------------------------------------------------
Write-Host "Starting stack (docker compose up -d --build)..."
docker compose up -d --build
if ($LASTEXITCODE -ne 0) { Fail "2" "docker compose up failed" }

# --- Step 3: Wait for redis + app to be healthy (60s timeout) ----------------
Write-Host "Waiting for containers to be healthy (timeout: 60s)..."
$allHealthy = $false
$elapsed = 0
while ($elapsed -lt 60) {
    Start-Sleep -Seconds 2
    $elapsed += 2

    $redisId = (docker compose ps -q redis 2>$null | Out-String).Trim()
    $appId   = (docker compose ps -q app   2>$null | Out-String).Trim()
    if (-not $redisId -or -not $appId) { continue }

    $redisHealth = (docker inspect --format '{{.State.Health.Status}}' $redisId 2>$null | Out-String).Trim()
    $appHealth   = (docker inspect --format '{{.State.Health.Status}}' $appId   2>$null | Out-String).Trim()

    Write-Host "  redis=$redisHealth  app=$appHealth"

    if ($redisHealth -eq "healthy" -and $appHealth -eq "healthy") {
        $allHealthy = $true
        break
    }
}
if (-not $allHealthy) { Fail "3" "containers not healthy after 60s. Run: docker compose logs" }

# --- Step 4: Poll ngrok for the https tunnel (30s timeout) ------------------
Write-Host "Waiting for ngrok tunnel (timeout: 30s)..."
$ngrokUrl = ""
for ($i = 0; $i -lt 15; $i++) {
    Start-Sleep -Seconds 2
    try {
        $r      = Invoke-RestMethod -Uri "http://localhost:4040/api/tunnels" -ErrorAction Stop
        $tunnel = $r.tunnels | Where-Object { $_.public_url -like "https://*" } | Select-Object -First 1
        if ($tunnel) { $ngrokUrl = $tunnel.public_url; break }
    } catch {}
}
if (-not $ngrokUrl) { Fail "4" "ngrok https tunnel not found after 30s. Run: docker compose logs ngrok" }

# Read Telnyx phone number from .env for display
$telnyxNumber = ""
try {
    $match = Select-String -Path ".env" -Pattern "^TELNYX_PHONE_NUMBER=(.+)" | Select-Object -First 1
    if ($match) { $telnyxNumber = $match.Matches[0].Groups[1].Value.Trim() }
} catch {}

# --- Step 5: Summary ---------------------------------------------------------
Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "ALL SERVICES RUNNING" -ForegroundColor Green
Write-Host ""
Write-Host "Redis:     healthy"
Write-Host "App:       running on http://localhost:8000"
Write-Host "Ngrok URL: $ngrokUrl"
Write-Host ""
Write-Host "--> Update Telnyx webhook to:" -ForegroundColor Yellow
Write-Host "    $ngrokUrl/telnyx/webhook" -ForegroundColor Yellow
if ($telnyxNumber) {
    Write-Host ""
    Write-Host "--> Then call: $telnyxNumber" -ForegroundColor Yellow
}
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# --- Step 6: Tail app logs ---------------------------------------------------
Write-Host "Tailing app logs (Ctrl+C to stop)..."
docker compose logs -f app
