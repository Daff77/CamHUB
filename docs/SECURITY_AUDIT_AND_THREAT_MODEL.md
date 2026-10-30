# CamHUB Security Audit & Threat Model Report (AGENT 7)

**Dokumen**: Laporan Audit Keamanan, Model Ancaman (Threat Model), dan Rencana Migrasi Keamanan  
**Target Proyek**: CamHUB Central CCTV Monitoring & Edge Analytics Platform  
**Status**: Fase 1 — Audit & Analisis Risiko Sebelum Implementasi  
**Tanggal**: 30 Oktober 2026  

---

## 1. Ringkasan Eksekutif (Executive Summary)

CamHUB adalah platform pengawasan CCTV dan analitik berbasis web yang menghubungkan decoder kamera V380, O-Kam Pro, engine motion detection, perekaman lokal, dan inferensi AI DirectML. Saat ini, CamHUB berjalan pada server HTTP internal (`server.py`) port 3000 dan dapat diekspos melalui Ngrok atau jaringan lokal.

Hasil audit mendalam menunjukkan bahwa seluruh endpoint CamHUB saat ini **belum memiliki lapisan autentikasi, otorisasi peran (RBAC), atau proteksi CSRF/CORS**. Siapa pun yang dapat menjangkau port 3000 (baik via LAN, Wi-Fi bersama, tunnel Ngrok, atau serangan Cross-Origin dari browser) dapat mematikan seluruh proses kamera, menghapus rekaman video dan snapshot dari disk, serta melihat seluruh tayangan kamera tanpa batasan.

Laporan ini menyajikan analisis ancaman komprehensif (STRIDE), audit seluruh endpoint, temuan kritis, serta usulan rancangan pengamanan bertahap yang **tidak memutus akses lokal yang sedang berjalan**.

---

## 2. Model Ancaman (Threat Model — STRIDE Framework)

```mermaid
graph TD
    Attacker[External / Malicious Actor]
    WebBrowser[Victim Browser on Malicious Site]
    Ngrok[Ngrok Tunnel / Public URL]
    LAN[Local Network / Wi-Fi Shared]
    
    Attacker -->|Direct Request| Ngrok
    Attacker -->|Direct Request| LAN
    WebBrowser -->|CSRF / CORS Attack| LAN
    
    subgraph CamHUB System Boundary
        Server[CamHUB server.py :3000]
        Config[(config/services_config.json)]
        Decoders[Camera Decoders :8080-8082]
        Storage[(Recordings & Events Storage)]
        AI[DirectML AI Engine]
    end
    
    Ngrok --> Server
    LAN --> Server
    Server --> Config
    Server --> Decoders
    Server --> Storage
    Server --> AI
```

| Kategori Ancaman (STRIDE) | Deskripsi Risiko pada CamHUB | Tingkat Keparahan |
| :--- | :--- | :--- |
| **Spoofing (Penyamaran)** | Tidak ada sistem login atau verifikasi identitas. Siapa pun dianggap sebagai pengguna sah yang memiliki kontrol absolut. | **CRITICAL** |
| **Tampering (Manipulasi)** | Siapa pun dapat menghapus file MP4 rekaman (`DELETE /api/recordings`), menghapus event snapshot (`DELETE /api/events`), atau mereset status supervisor. | **HIGH** |
| **Repudiation (Penyangkalan)** | Tidak ada audit log untuk aksi login, penghentian proses kamera, perubahan konfigurasi, atau penghapusan bukti rekaman. | **MEDIUM** |
| **Information Disclosure (Kebocoran Data)** | Password kamera disimpan plaintext di `config/services_config.json`. Live stream, snapshot, rekaman, dan riwayat pergerakan dapat diakses bebas. | **HIGH** |
| **Denial of Service (DoS)** | Endpoint `/api/services/stop-all` dapat dipanggil seketika untuk mematikan seluruh CCTV. Endpoint `/api/ai/benchmark` dapat dipanggil berulang kali untuk membebani CPU/GPU. Tidak ada rate limiting atau batas request size. | **HIGH** |
| **Elevation of Privilege (Eskalasi Akses)** | Tidak ada pemisahan antara pengguna biasa yang hanya ingin melihat stream (**Viewer**) dengan pengelola sistem (**Admin**). | **HIGH** |

---

## 3. Klasifikasi & Audit Endpoint CamHUB

Audit terhadap seluruh endpoint yang terdaftar di [`server.py`](file:///c:/DaffaP/Project%20df/CamHUB/server.py):

| HTTP Method & Endpoint | Kategori Aksi | Tingkat Risiko | Hak Akses yang Diusulkan |
| :--- | :--- | :---: | :---: |
| `POST /api/services/start-all` | Memulai semua proses kamera di host | **CRITICAL** | **Admin Only** |
| `POST /api/services/stop-all` | Mematikan paksa semua proses CCTV | **CRITICAL** | **Admin Only** |
| `POST /api/services/restart-all` | Me-restart seluruh decoder kamera | **CRITICAL** | **Admin Only** |
| `POST /api/services/start` | Menjalankan child process kamera tertentu | **HIGH** | **Admin Only** |
| `POST /api/services/stop` | Mematikan child process kamera tertentu | **HIGH** | **Admin Only** |
| `POST /api/services/restart` | Me-restart child process kamera tertentu | **HIGH** | **Admin Only** |
| `POST /api/recovery/reset` | Mereset circuit breaker & restart kamera | **HIGH** | **Admin Only** |
| `POST /api/recordings/start` | Menjalankan proses FFmpeg untuk merekam | **HIGH** | **Admin Only** |
| `POST /api/recordings/stop` | Menghentikan proses perekaman FFmpeg | **HIGH** | **Admin Only** |
| `DELETE /api/recordings` | Menghapus permanen file rekaman video di disk | **CRITICAL** | **Admin Only** |
| `DELETE /api/events` | Menghapus file snapshot & event index di disk | **HIGH** | **Admin Only** |
| `POST /api/ai/benchmark` | Menjalankan uji beban komputasi GPU & CPU | **MEDIUM** | **Admin Only** |
| `POST /api/ai/enrich` | Memicu analisis ulang AI pada snapshot | **LOW** | **Viewer / Admin** |
| `POST /api/ai/detect` | Menjalankan deteksi langsung pada snapshot | **LOW** | **Viewer / Admin** |
| `GET /api/services/status` | Melihat status proses & health telemetry | **LOW** | **Viewer / Admin** |
| `GET /api/recordings` | Melihat daftar arsip rekaman video | **MEDIUM** | **Viewer / Admin** |
| `GET /api/recordings/stream` | Memutar streaming video arsip rekaman (HTTP 206) | **HIGH** (Privasi) | **Viewer / Admin** |
| `GET /api/recordings/download`| Mengunduh file video mentah | **HIGH** (Privasi) | **Viewer / Admin** |
| `GET /api/events` | Melihat riwayat event motion & deteksi AI | **MEDIUM** | **Viewer / Admin** |
| `GET /api/events/snapshot` | Melihat gambar snapshot aktivitas | **HIGH** (Privasi) | **Viewer / Admin** |
| `GET /proxy/stream/*` | Live stream MJPEG kamera | **HIGH** (Privasi) | **Viewer / Admin** |
| `GET /proxy/snapshot/*` | Live snapshot instan kamera | **HIGH** (Privasi) | **Viewer / Admin** |
| `GET /api/health/*` | Health check & diagnostik metrik | **LOW** | **Viewer / Admin** |
| `GET /api/ai/status` | Status engine AI & provider | **LOW** | **Viewer / Admin** |
| `GET /*` (HTML, JS, CSS) | Asset antarmuka web dashboard | **PUBLIC** | **Semua (Login UI)** |

---

## 4. Temuan Kritis (Critical Security Findings)

### Temuan 1: Wildcard CORS Mengizinkan Serangan Lintas Situs (CSRF / Cross-Origin Hijacking)
- **Lokasi**: [`server.py` baris 200](file:///c:/DaffaP/Project%20df/CamHUB/server.py#L200)
- **Kondisi**: Header dikirimkan secara global tanpa validasi Origin:
  ```python
  self.send_header("Access-Control-Allow-Origin", "*")
  self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
  self.send_header("Access-Control-Allow-Headers", "*")
  ```
- **Dampak**: Jika pengguna membuka tab browser ke situs web berbahaya saat CamHUB sedang berjalan, JavaScript situs tersebut dapat mengirimkan request HTTP POST ke `http://127.0.0.1:3000/api/services/stop-all` atau mengambil foto snapshot CCTV rumah secara diam-diam.
- **Rekomendasi**: Batasi CORS hanya untuk origin yang diizinkan (same-origin, localhost, domain ngrok resmi, atau VPN domain yang dikonfigurasi). Tolak wildcard origin pada endpoint mutasi (`POST`/`DELETE`) dan data sensitif.

---

### Temuan 2: Tidak Ada Lapisan Autentikasi dan Pembagian Peran (RBAC)
- **Lokasi**: [`server.py`](file:///c:/DaffaP/Project%20df/CamHUB/server.py)
- **Kondisi**: Tidak ada mekanisme login, token, API key, ataupun session cookie.
- **Dampak**: Siapa pun yang memiliki URL Ngrok atau IP lokal memiliki kontrol penuh setara Super Admin.
- **Rekomendasi**: Implementasikan autentikasi ringan berbasis token/session dengan 2 peran minimal:
  1. **Admin**: Hak penuh (konfigurasi, kontrol kamera, start/stop, penghapusan rekaman).
  2. **Viewer**: Hak baca terbatas (hanya memantau live stream, riwayat event, dan playback tanpa tombol kontrol/delete).

---

### Temuan 3: Kredensial Kamera Tersimpan Plaintext di File Konfigurasi
- **Lokasi**: [`config/services_config.json`](file:///c:/DaffaP/Project%20df/CamHUB/config/services_config.json)
- **Kondisi**: Password kamera RTSP dan akun V380 tertulis secara mentah di dalam file JSON:
  ```json
  "--password Danendra07."
  "rtsp://admin:Danendra07.@192.168.100.6:10554/tcp/av0_0"
  ```
- **Dampak**: Jika file konfigurasi terbaca, kredensial fisik perangkat kamera langsung terekspos.
- **Rekomendasi**: Redaksi kredensial dari respons API, sembunyikan dari UI Viewer, serta sediakan enkripsi lokal atau environment variable injection untuk kredensial kamera.

---

### Temuan 4: Potensi Command Injection pada Eksekusi Shell
- **Lokasi**: [`server.py` baris 60-67](file:///c:/DaffaP/Project%20df/CamHUB/server.py#L60-L67), [`core/auto_recovery.py` baris 50](file:///c:/DaffaP/Project%20df/CamHUB/core/auto_recovery.py#L50)
- **Kondisi**:
  ```python
  subprocess.run(f"taskkill /F /T /PID {pid}", shell=True)
  cmd = f'powershell -NoProfile -Command "(Get-NetTCPConnection -LocalPort {port} ...).OwningProcess"'
  subprocess.check_output(cmd, shell=True)
  ```
- **Dampak**: Pemanggilan `shell=True` dengan string formatting membuka celah injeksi jika parameter tidak berupa integer yang tervalidasi ketat.
- **Rekomendasi**: Ubah eksekusi proses menjadi `shell=False` dengan argumen berbentuk list: `subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)])`.

---

### Temuan 5: Ketiadaan Rate Limiting dan Batas Ukuran Request (DoS Vector)
- **Lokasi**: [`server.py`](file:///c:/DaffaP/Project%20df/CamHUB/server.py)
- **Kondisi**: Server HTTP Python `ThreadingHTTPServer` menerima request tanpa batasan kecepatan (rate limit) dan tanpa batas ukuran payload request body.
- **Dampak**: Brute force login, memory exhaustion via payload besar, atau saturasi thread server.
- **Rekomendasi**: Terapkan in-memory sliding-window rate limiter (misalnya: max 10 failed login attempts per minute, max 60 API requests/sec) dan batasi ukuran request body maksimum 2 MB.

---

### Temuan 6: Ketiadaan Audit Trail (Security Log)
- **Kondisi**: Tidak ada pencatatan terstruktur terhadap aktivitas penting seperti kapan login terjadi, siapa yang menghentikan kamera, kapan rekaman dihapus, atau dari IP mana request berasal.
- **Rekomendasi**: Buat `core/audit_logger.py` yang mencatat setiap event keamanan ke file `logs/security_audit.log` berformat JSONL terproteksi.

---

## 5. Rencana Arsitektur Pengamanan (Non-Breaking Migration)

Agar penambahan sistem keamanan **TIDAK memutus akses lokal yang sedang berjalan**, strategi implementasi dirancang sebagai berikut:

```mermaid
flowchart TD
    Req[Incoming HTTP Request] --> RateLimit{Rate Limit Check}
    RateLimit -->|Exceeded| Res429[429 Too Many Requests]
    RateLimit -->|OK| StaticCheck{Is Static Asset or Login?}
    
    StaticCheck -->|Yes| ServeStatic[Serve Asset / Login Page]
    StaticCheck -->|No| AuthCheck{Auth Header / Cookie Present?}
    
    AuthCheck -->|No| LocalBypass{Local Dev Bypass Enabled & Client is Loopback?}
    LocalBypass -->|Yes| AssignLocalAdmin[Assign Local Session with Audit Log]
    LocalBypass -->|No| Res401[401 Unauthorized / Redirect to Login]
    
    AuthCheck -->|Yes| VerifyToken{Verify Token Signature & Expiry}
    VerifyToken -->|Invalid| Res401
    VerifyToken -->|Valid| RoleCheck{Endpoint Requires Admin?}
    
    RoleCheck -->|Yes & Role == Viewer| Res403[403 Forbidden: Admin Only]
    RoleCheck -->|Pass| ExecHandler[Execute Endpoint Handler]
    
    ExecHandler --> AuditLog[Write to Audit Log]
```

### Mekanisme Autentikasi yang Diusulkan:
1. **Lightweight Secure Session Token / HMAC**:
   - Token ditandatangani menggunakan kunci rahasia yang disimpan lokal di host (`config/security.key` dengan izin `0600`).
   - Masa berlaku token terkonfigurasi (default: 7 hari).
   - Mendukung header `Authorization: Bearer <token>` (untuk API / cURL) serta cookie HTTP `camhub_session` (`HttpOnly`, `SameSite=Lax`).
2. **Kredensial Default & Bootstrap Awal**:
   - Sistem menyediakan akun default terpisah:
     - **Admin**: username `admin` (dapat diatur password-nya pada setup pertama atau file config).
     - **Viewer**: username `viewer` (password terpisah, hanya untuk melihat live feed & arsip).
   - Password disimpan menggunakan hashing kuat salt-based (PBKDF2-HMAC-SHA256, 100.000 iterasi) tanpa dependency eksternal tambahan.
3. **Pencegahan Terkunci (Local Loopback Grace Mechanism)**:
   - Request dari `127.0.0.1` / `localhost` dapat dikonfigurasi dengan mode transisi (*permissive transition mode*) sehingga pengembang tidak terkunci jika belum mengatur password.
   - Sediakan tombol dan instruksi *Emergency Reset*.

---

## 6. Prosedur Rollback (Langkah Pemulihan Darurat)

Jika terjadi kendala saat atau setelah pengamanan diterapkan:
1. **Bypass Mode via Argumen CLI**:
   Server dapat dijalankan dengan flag darurat `--no-auth`:
   ```powershell
   python server.py --port 3000 --no-auth
   ```
2. **Reset Kredensial**:
   Script reset darurat `scripts/reset_security.py` akan disediakan untuk mereset password admin kembali ke default dalam hitungan detik dari terminal host lokal.
3. **Git Revert**:
   Perubahan keamanan dilakukan dalam commit mandiri yang dapat di-revert secara instan jika diperlukan:
   ```powershell
   git revert HEAD
   ```

---

## 7. Rekomendasi Remote Access (VPN vs Port Forwarding)

1. **JANGAN membuka port kamera atau port CamHUB langsung ke internet via port forwarding router**:
   - Port forwarding rentan terhadap scanning otomatis oleh botnet Shodan / Censys.
2. **Opsi Rekomendasi 1 — Tailscale / WireGuard (Zero Trust Mesh VPN)**:
   - Aman, terenkripsi end-to-end, tanpa perlu membuka port router publik (NAT traversal otomatis).
   - CamHUB hanya dapat diakses oleh perangkat yang berada di dalam Tailnet pemilik.
3. **Opsi Rekomendasi 2 — Reverse Proxy dengan HTTPS (Caddy / Nginx / Cloudflare Tunnel / Ngrok Auth)**:
   - Jika perlu diakses publik via browser tanpa VPN, gunakan reverse proxy yang menerapkan HTTPS / TLS dan Basic Auth di layer proxy.

