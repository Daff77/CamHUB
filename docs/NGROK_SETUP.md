# Panduan Konfigurasi & Menjalankan CamHUB via Ngrok

Dokumen ini menjelaskan cara mengakses dashboard dan seluruh live stream CCTV CamHUB dari luar jaringan (internet / smartphone) menggunakan **Ngrok** secara aman, tanpa gangguan *Mixed Content* (HTTPS vs HTTP), dan hanya memerlukan **1 tunnel port (port 3000)**.

---

## 🎯 Mengapa Membutuhkan Reverse Proxy Built-in?

Secara default di jaringan lokal (LAN):
- Server CamHUB berjalan di port `3000`.
- Kamera 1 (V380) berjalan di port `8080`.
- Kamera 2 (V380) berjalan di port `8081`.
- Kamera 3 (O-Kam) berjalan di port `8082`.

Jika dibuka melalui Ngrok (`https://xxxx.ngrok-free.app`), browser modern (Chrome, Edge, Safari) akan memblokir feed video karena **Mixed Content** (halaman HTTPS tidak boleh memuat feed `http://...:8080`). Selain itu, Ngrok free tier hanya memberikan 1 tunnel publik.

### Solusi CamHUB Built-in Reverse Proxy
Backend CamHUB ([`server.py`](file:///c:/DaffaP/Project%20df/CamHUB/server.py)) menyediakan endpoint proxy internal:
- Live Stream: `/proxy/stream/<camera_id>` (contoh: `/proxy/stream/v380-1`)
- Snapshot: `/proxy/snapshot/<camera_id>`
- Telemetry Metrics: `/proxy/metrics/<camera_id>`

Ketika dashboard dibuka via Ngrok (`https://...`):
- Frontend [`app.js`](file:///c:/DaffaP/Project%20df/CamHUB/web/app.js) **otomatis beralih ke proxy mode**.
- Seluruh 3 kamera, snapshot, dan metrik FPS dialirkan langsung melalui URL HTTPS Ngrok yang sama.
- Tidak ada port decoder yang perlu di-forward ke internet.

---

## 🚀 Langkah Menjalankan via Ngrok

### Langkah 1: Pasang Authtoken Ngrok (Hanya Sekali)
Jika Anda belum mendaftarkan authtoken Ngrok gratis:
1. Buka [https://dashboard.ngrok.com/signup](https://dashboard.ngrok.com/signup) dan buat akun gratis.
2. Salin AuthToken Anda dari dashboard Ngrok.
3. Buka PowerShell dan jalankan:
   ```powershell
   ngrok config add-authtoken <TOKEN_ANDA>
   ```

---

### Langkah 2: Jalankan Ngrok Tunnel

Pilih salah satu cara di bawah ini:

#### Cara A: Menggunakan Script Otomatis (Direkomendasikan)
Cukup jalankan script PowerShell:
```powershell
.\start_ngrok.ps1
```
Atau klik ganda file **`start_ngrok.bat`** di Windows Explorer. Script ini akan otomatis mendeteksi server CamHUB dan membuka tunnel port 3000.

#### Cara B: Menggunakan File Konfigurasi `ngrok.yml`
```powershell
ngrok start --config "config\ngrok.yml" camhub
```

#### Cara C: Perintah Manual Langsung
```powershell
ngrok http 3000 --host-header="localhost:3000"
```

---

### Langkah 3: Buka Link Ngrok di Browser / HP
Di jendela terminal Ngrok, Anda akan melihat baris:
```
Forwarding   https://a1b2-c3d4.ngrok-free.app -> http://localhost:3000
```
Buka link `https://...ngrok-free.app` tersebut di browser HP atau laptop di luar rumah:
- Dashboard CamHUB langsung terbuka.
- Semua 3 feed kamera langsung tampil via streaming HTTPS proxy.
- Header `ngrok-skip-browser-warning: 1` telah terpasang otomatis sehingga request API tidak terhalang halaman interstitial Ngrok.

---

## 🔒 Tips Keamanan (Opsional)

Agar link Ngrok tidak bisa diakses sembarang orang, Anda dapat mengaktifkan **HTTP Basic Auth** pada tunnel:

```powershell
ngrok http 3000 --basic-auth "admin:PasswordKameraRahasia123"
```
Dengan opsi ini, setiap pengguna yang membuka link Ngrok wajib memasukkan username dan password terlebih dahulu.

---

## 🛠️ File Terkait
- [`start_ngrok.ps1`](file:///c:/DaffaP/Project%20df/CamHUB/start_ngrok.ps1) — Script launcher otomatis
- [`start_ngrok.bat`](file:///c:/DaffaP/Project%20df/CamHUB/start_ngrok.bat) — Batch file shortcut Windows
- [`config/ngrok.yml`](file:///c:/DaffaP/Project%20df/CamHUB/config/ngrok.yml) — File konfigurasi ngrok v2/v3
- [`server.py`](file:///c:/DaffaP/Project%20df/CamHUB/server.py) — Endpoint reverse proxy `/proxy/stream/<id>`
- [`web/app.js`](file:///c:/DaffaP/Project%20df/CamHUB/web/app.js) — Deteksi HTTPS/Ngrok otomatis
