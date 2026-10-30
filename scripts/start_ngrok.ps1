<#
.SYNOPSIS
  CamHUB Ngrok Tunnel Launcher
.DESCRIPTION
  Launches an Ngrok public HTTPS tunnel to CamHUB (port 3000).
  All 3 camera feeds, snapshots, and telemetry are routed through CamHUB's
  built-in reverse proxy (/proxy/stream/<camera_id>), allowing full remote
  monitoring over a single HTTPS URL without Mixed Content errors.
#>

[CmdletBinding()]
param(
  [int]$Port = 3000,
  [string]$Authtoken = ""
)

$ErrorActionPreference = "Continue"

$projectRoot = Split-Path $PSScriptRoot -Parent
if (-not (Test-Path (Join-Path $projectRoot "server.py"))) {
  $projectRoot = $PSScriptRoot
}

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "            CamHUB Ngrok Tunnel Launcher          " -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Check if ngrok is installed
$ngrokCmd = Get-Command ngrok -ErrorAction SilentlyContinue
if (-not $ngrokCmd) {
  Write-Host "[ERROR] 'ngrok' is not installed or not in your system PATH." -ForegroundColor Red
  Write-Host "To install ngrok on Windows:" -ForegroundColor Yellow
  Write-Host "  winget install ngrok" -ForegroundColor White
  Write-Host "  or download from: https://ngrok.com/download" -ForegroundColor White
  Write-Host ""
  Read-Host "Press Enter to exit..."
  exit 1
}

# 2. Configure authtoken if passed as parameter
if ($Authtoken) {
  Write-Host "[SETUP] Configuring ngrok authtoken..." -ForegroundColor Gray
  & ngrok config add-authtoken $Authtoken
  if ($LASTEXITCODE -ne 0) {
    Write-Host "[WARNING] Failed to set authtoken. Continuing anyway..." -ForegroundColor Yellow
  }
}

# 3. Check if CamHUB server is running on port 3000
$tcp = Test-NetConnection -ComputerName 127.0.0.1 -Port $Port -InformationLevel Quiet -WarningAction SilentlyContinue
if (-not $tcp) {
  Write-Host "[INFO] CamHUB server is not detected on port $Port." -ForegroundColor Yellow
  Write-Host "[INFO] Starting CamHUB host server in background..." -ForegroundColor Gray
  Start-Process python -ArgumentList "-u server.py --port $Port" -WorkingDirectory $projectRoot -WindowStyle Minimized
  Start-Sleep -Seconds 2
} else {
  Write-Host "[OK] CamHUB server is active on http://127.0.0.1:$Port" -ForegroundColor Green
}

Write-Host ""
Write-Host "--------------------------------------------------" -ForegroundColor DarkGray
Write-Host " [1] Single HTTPS URL covers Dashboard + All Feeds" -ForegroundColor Green
Write-Host " [2] Built-in Reverse Proxy (/proxy/stream/<id>)  " -ForegroundColor Green
Write-Host " [3] No Mixed Content errors on mobile or desktop " -ForegroundColor Green
Write-Host "--------------------------------------------------" -ForegroundColor DarkGray
Write-Host ""
Write-Host "Starting Ngrok tunnel..." -ForegroundColor Cyan
Write-Host "Press Ctrl + C anytime in this window to stop." -ForegroundColor DarkGray
Write-Host ""

# 4. Launch ngrok
$configPath = Join-Path $projectRoot "config\ngrok.yml"
if (Test-Path $configPath) {
  & ngrok start --config $configPath camhub
} else {
  & ngrok http $Port --host-header="localhost:$Port"
}

