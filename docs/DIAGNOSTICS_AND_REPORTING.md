# CamHUB Diagnostics & Troubleshooting Export Report

Dokumentasi arsitektur, spesifikasi teknis, mekanisme keamanan, dan panduan penggunaan sistem **Diagnostics & Export Report** pada CamHUB.

---

## 1. 📋 Ringkasan & Tujuan

Fitur **Diagnostics & Export Report** dirancang untuk mempermudah troubleshooting teknis pada kamera CCTV, adapter decoder (V380 / O-Kam), FFmpeg, komputasi AI lokal, dan layanan backend CamHUB tanpa membocorkan data pribadi atau kredensial sensitif.

Sistem ini menyediakan diagnosis sekali klik (*one-click diagnosis*) dari antarmuka web dashboard maupun REST API, menghasilkan arsip terkompresi ZIP yang memuat laporan markdown yang mudah dibaca teknisi, file JSON telemetri terstruktur, serta manifest integritas dengan *checksum* SHA-256.

---

## 2. 🛡️ Keamanan, Sanitasi & Batasan Privasi

Sesuai dengan kriteria keamanan privasi dan audit threat model:

1. **Redaksi Kredensial Menyeluruh (Zero-Leakage Guarantee)**:
   - **Password RTSP**: Pola `rtsp://<user>:<password>@<host>` disamarkan otomatis menjadi `rtsp://<user>:***@<host>`.
   - **Argumen CLI**: Parameter `--password <secret>` atau `-p <secret>` diredaksi menjadi `--password [REDACTED]`.
   - **Bot Token**: Token Telegram atau Bearer API token disamarkan menjadi `[BOT_TOKEN_REDACTED]`.
   - **Struktur Objek Konfigurasi**: Field kunci dengan nama `password`, `pwd`, `secret`, `token`, `key`, `auth`, `cred` disanitasi secara rekursif.
2. **Tidak Ada Media Pribadi**:
   - File rekaman video (`.mp4`) dan gambar snapshot (`.jpg`) **tidak dimasukkan ke dalam arsip ZIP secara default** guna menjaga privasi privasi ruangan dan penghuni.
3. **Pencegahan Command Injection & Eksekusi Arbitrer**:
   - Sistem **hanya mengizinkan perintah sistem yang terdaftar dalam whitelist ketat**:
     - `python --version` (atau `sys.version`)
     - `ffmpeg -version` (hanya baris pertama versi)
     - `dotnet --version`
   - Setiap perintah memiliki batas waktu eksekusi ketat (*timeout* 3.0 detik).
4. **Pembatasan Ukuran & Rentang Log**:
   - Log buffer dibatasi maksimal **500 baris terbaru** atau 500 KB untuk mencegah kehabisan memori (*Out-Of-Memory*).
   - Ukuran maksimal bundle ZIP dibatasi maksimal **10 MB** (rata-rata bundle teks/JSON hanya ~7 KB).
5. **Otorisasi Berbasis Peran (Admin Role Protection)**:
   - Endpoint pembuatan (`POST /api/diagnostics/generate`) dan penghapusan (`DELETE /api/diagnostics`) dilindungi otorisasi admin (`X-CamHub-Role: admin` atau loopback lokal tanpa role viewer). Pengguna dengan peran `viewer` ditolak dengan status **HTTP 403 Forbidden**.

---

## 3. 📦 Struktur & Spesifikasi Diagnostic Bundle (.zip)

Setiap bundle diekspor dengan format nama `camhub_diagnostics_YYYYMMDD_HHMMSS.zip` dan memuat 8 berkas:

| Nama Berkas | Format | Deskripsi |
| :--- | :---: | :--- |
| `manifest.json` | JSON | Metadata bundle, versi generator, timestamp, hostname host, total berkas, dan hash SHA-256 tiap berkas |
| `diagnostics_summary.md` | Markdown | Laporan ringkas yang dapat langsung dibaca teknisi, memuat matriks kesehatan kamera, kapasitas disk, dan rekomendasi perbaikan |
| `system_info.json` | JSON | Versi CamHUB, runtime Python, compiler, versi FFmpeg, versi .NET, arsitektur CPU, dan safe environment variables |
| `services_status.json` | JSON | Status proses supervisor kamera, circuit breaker, health telemetry (FPS, latency, reconnects), status storage, dan motion/AI |
| `ports_status.json` | JSON | Hasil uji konektivitas TCP non-blocking untuk port dashboard (3000), HTTP port kamera, dan port RTSP |
| `sanitized_config.json` | JSON | File konfigurasi `services_config.json` yang seluruh password dan kredensialnya sudah diredaksi 100% |
| `recent_errors.json` | JSON | Agregasi kegagalan kamera, circuit breaker tripped, frame frozen, dan peringatan storage |
| `recent_logs.txt` | Text | Riwayat log event dan panggilan API terkini (maksimal 500 baris) |

---

## 4. 🌐 Dokumentasi REST API

### 1. `GET /api/diagnostics/summary`
Mengambil ringkasan diagnostik instan tanpa membuat file ZIP di disk. Cocok untuk widget visual dashboard.
- **Header**: `X-CamHub-Role: admin` (atau loopback lokal)
- **Status Response**: `200 OK`
```json
{
  "overallStatus": "HEALTHY",
  "issueCount": 0,
  "software": {
    "app": "CamHUB 1.0.0",
    "python": { "version": "3.10.11" },
    "ffmpeg": { "installed": true, "version": "ffmpeg version 9.0.1..." },
    "dotnet": { "installed": true, "version": "10.0.403" }
  },
  "ports": {
    "dashboard": { "port": 3000, "status": "OPEN", "latencyMs": 1.2 },
    "cameras": { ... }
  },
  "bundles": [ ... ]
}
```

### 2. `POST /api/diagnostics/generate`
Membuat file ZIP bundle diagnostik baru di direktori `diagnostics/`.
- **Hak Akses**: Admin Only
- **Status Response**: `200 OK`
```json
{
  "success": true,
  "filename": "camhub_diagnostics_20261031_013519.zip",
  "filePath": "C:\\DaffaP\\Project df\\CamHUB\\diagnostics\\camhub_diagnostics_20261031_013519.zip",
  "sizeBytes": 6584,
  "sha256": "1b44ff1f3b2ebe02055794db4b86eb01da4ec2ba3852285fa795d92a9aac9fd4",
  "durationMs": 1771.1,
  "downloadUrl": "/api/diagnostics/download?file=camhub_diagnostics_20261031_013519.zip",
  "manifest": { ... }
}
```

### 3. `GET /api/diagnostics/download?file=<filename>`
Mengunduh berkas ZIP diagnostik hasil generate. Dilengkapi sanitasi path untuk mencegah *directory traversal attacks*.
- **Content-Type**: `application/zip`
- **Content-Disposition**: `attachment; filename="camhub_diagnostics_....zip"`

### 4. `GET /api/diagnostics/list`
Melihat daftar berkas laporan diagnostik yang tersimpan di host beserta ukuran dan tanggal pembuatannya.

### 5. `DELETE /api/diagnostics?file=<filename>`
Menghapus berkas ZIP diagnostik lama dari disk host.
- **Hak Akses**: Admin Only

---

## 5. 🖥️ Antarmuka Pengguna (UI Walkthrough)

1. **Tombol Header Dashboard**:
   - Di baris atas dashboard, tersedia tombol **Diagnostics** (ikon kunci pas) dan tombol **Notification Center** (ikon lonceng dengan *unread count badge*).
2. **Modal Diagnostik**:
   - Menampilkan status sistem seketika: versi software, status host, dan matriks port TCP dengan indikator visual hijau (*OPEN*) atau merah (*CLOSED*).
   - Tombol **Generate Diagnostic Bundle (ZIP)** dengan indikator progres pemrosesan dan status.
   - Kartu hasil unduhan langsung dengan nama berkas, ukuran, dan checksum SHA-256.
   - Tabel riwayat laporan diagnostik sebelumnya dengan tombol unduh dan hapus.

---

## 6. 🧪 Hasil Pengujian Otomatis

Modul diuji secara menyeluruh melalui [`tests/test_diagnostics.py`](file:///c:/DaffaP/Project%20df/CamHUB/tests/test_diagnostics.py):
1. `test_sanitize_string`: Memastikan sanitasi URL RTSP, argumen CLI `--password`, dan bot token Telegram.
2. `test_sanitize_value_dict_recursive`: Memastikan sanitasi rekursif pada struktur JSON bersarang.
3. `test_software_versions`: Memverifikasi pendeteksian runtime Python, .NET, dan FFmpeg.
4. `test_system_resources`: Memverifikasi telemetri OS, CPU cores, PID, dan disk space.
5. `test_check_ports`: Memverifikasi pengecekan port TCP dashboard dan kamera.
6. `test_bundle_creation_and_zero_credential_leak`: Memastikan arsip ZIP valid dan **sama sekali tidak memuat kredensial fisik atau password**.
7. `test_bundle_creation_resilience_when_camera_offline`: Memastikan pembuatan bundle tetap sukses bahkan saat kamera mengalami status **OFFLINE** atau **FAILED**.
8. `test_list_and_delete_bundles`: Memastikan pengelolaan dan penghapusan bundle berjalan aman.

Seluruh **66/66 unit test** di seluruh proyek CamHUB lulus dengan tingkat keberhasilan **100%**.

