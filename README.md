# CamHub — Unified Camera Monitor

A local-first, privacy-focused dashboard for viewing mixed-brand IP cameras via local streaming adapters (such as `V380Decoder`). CamHub runs completely within your Local Area Network (LAN), never transmits camera credentials over the internet, and does not require third-party cloud accounts.

---

## 📷 Integrated Cameras

### 1. V380 Pro — Kamera 1 (Utama / Indoor)
- **Device Protocol:** LAN P2P decoded locally via `V380Decoder`
- **Decoder HTTP Port:** `8080`
- **Live Stream (MJPEG):** `http://192.168.100.11:8080/stream.mjpg`
- **Snapshot Endpoint:** `http://192.168.100.11:8080/snapshot`

### 2. V380 Pro — Garasi
- **Device IP:** `192.168.100.4` (Device ID: `97357757`)
- **Decoder HTTP Port:** `8081`
- **Live Stream (MJPEG):** `http://192.168.100.11:8081/stream.mjpg`
- **Snapshot Endpoint:** `http://192.168.100.11:8081/snapshot`

### 3. O-Kam Pro / VStarcam — Kamera 3
- **Device IP:** `192.168.100.6`
- **Native RTSP Port:** `10554` (Lens 1) & `10555` (Lens 2)
- **Local Adapter:** `okam_adapter.py`
- **Decoder HTTP Port:** `8082`
- **Live Stream (MJPEG):** `http://192.168.100.11:8082/stream.mjpg`
- **Snapshot Endpoint:** `http://192.168.100.11:8082/snapshot`
- **Telemetry Metrics:** `http://192.168.100.11:8082/api/metrics`

---

## 🚀 How to Run CamHub

### Step 1: Ensure Local Decoders are Running

Both cameras require their respective local decoder instances to remain running in PowerShell/Terminal windows on this laptop:

#### Start Decoder for Kamera 1 (Port 8080):
```powershell
cd "$HOME\V380Decoder-Latest"

$user1 = Read-Host "Username kamera 1"
$secure1 = Read-Host "Password kamera 1" -AsSecureString
$ptr1 = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure1)
$pass1 = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr1)

dotnet run --no-build -- `
  --id 124095217 `
  --username $user1 `
  --password $pass1 `
  --ip 192.168.100.24 `
  --port 8800 `
  --source lan `
  --output rtsp `
  --quality sd `
  --enable-api `
  --http-port 8080 `
  --rtsp-port 8554 `
  --debug

[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr1)
Remove-Variable pass1, secure1, user1 -ErrorAction SilentlyContinue
```

#### Start Decoder for Kamera 2 — Garasi (Port 8081):
```powershell
cd "$HOME\V380Decoder-Fork"

$user2 = Read-Host "Username kamera 2"
$secure2 = Read-Host "Password kamera 2" -AsSecureString
$ptr2 = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure2)
$pass2 = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr2)

dotnet run --no-build -- `
  --id 97357757 `
  --username $user2 `
  --password $pass2 `
  --source cloud `
  --output rtsp `
  --quality sd `
  --enable-api `
  --http-port 8081 `
  --rtsp-port 8555 `
  --debug

[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr2)
Remove-Variable pass2, secure2, user2 -ErrorAction SilentlyContinue
```

#### Start Adapter for Kamera 3 — O-Kam Pro (Port 8082):
```powershell
cd "C:\DaffaP\Project df\CamHUB"

# Jalankan adapter RTSP-to-MJPEG untuk O-Kam Pro
python okam_adapter.py --port 8082 --rtsp "rtsp://admin:Danendra07.@192.168.100.6:10554/tcp/av0_0"
```

### Step 2: Serve the Dashboard

Open PowerShell in this project folder (`C:\DaffaP\Project df\CamHUB`):

```powershell
python -m http.server 3000
```

### Step 3: Open in Browser

Open Google Chrome or any modern browser and navigate to:
```
http://127.0.0.1:3000
```
*(or `http://localhost:3000`)*

---

## 🔍 How to Test Both Cameras from the Dashboard

1. **Check Camera 2 (Garasi):**
   - With the port 8081 decoder running, the second card will immediately show the green `● LIVE · Connected` status badge, display a `● LIVE` overlay indicator, and render the live video feed.
2. **Check Camera 1 (Kamera 1):**
   - If the port 8080 decoder is not yet running, the card will display `● No Signal / Offline` and a clear diagnostic message: *"Cannot reach local decoder on port :8080"*.
   - Start the decoder on port 8080 in a terminal.
   - Click **"↻ Retry Connection"** on the card or **"↻ Refresh feeds"** in the top navigation bar.
   - The card will transition to `Connecting…` and then directly to `Live · Connected`.
3. **Check Camera 3 (O Kam Pro):**
   - Displays `Not Configured` with a prompt to set up when its protocol is verified.
   - Click **"⚙ Configure"** to set its stream URL whenever ready.

---

## 🔒 Security Best Practices

- **Zero Credentials Stored:** CamHub never stores or logs camera usernames or passwords. Passwords are used only in local decoder terminal flags.
- **LAN-Only Streaming:** All streams operate strictly within your private subnet (`192.168.100.x`).
- **No Internet Port Forwarding:** Do not expose ports 8080, 8081, or RTSP ports to the public internet. For remote access, use a secure VPN such as WireGuard or Tailscale.
- **Mixed Content Avoidance:** CamHub is served via local HTTP (`http://127.0.0.1:3000`), allowing standard browsers to load local HTTP MJPEG streams seamlessly without mixed-content blocks.
