# CamHUB — Backlog Fitur Terurut (Post-Audit Roadmap)

Dokumen ini memuat daftar fitur lanjutan yang direkomendasikan setelah penyelesaian audit keamanan, penyatuan skema indeks media, perbaikan identitas kamera, dan penguatan retention/playback pada 18 November 2026.

> **Catatan Scope**: Autentikasi dan otorisasi berbasis sesi/token (`core/auth_manager.py`) telah diimplementasikan. Ketujuh fitur pada backlog di bawah ini didokumentasikan secara terurut berdasarkan prioritas operasional dan siap dikerjakan pada iterasi berikutnya.

---

## Ringkasan Urutan Prioritas

| Urutan | Prioritas | Fitur | Fokus Utama |
| :---: | :---: | :--- | :--- |
| 1 | P1 | Timeline rekaman dengan penanda gap | Visibilitas kontinuitas rekaman & deteksi jeda arsip |
| 2 | P1 | Klip event dengan pre-roll dan post-roll | Konteks video utuh sebelum & sesudah pemicu gerakan/AI |
| 3 | P1 | Peringatan feed live tetapi recorder berhenti | Deteksi dini kegagalan perekaman diam-diam (*silent recording drop*) |
| 4 | P2 | Audit log aktivitas pengguna | Akuntabilitas operasi admin, PTZ, konfigurasi, dan penghapusan |
| 5 | P2 | Export bukti kejadian beserta timestamp dan checksum | Integritas forensik klip/snapshot saat diekspor |
| 6 | P2 | Editor zona dan jadwal deteksi | Kontrol visual ROI dan jadwal aktif deteksi per kamera |
| 7 | P3 | Quiet hours dan eskalasi notifikasi | Pengurangan *alert fatigue* dan eskalasi insiden kritis |

---

## Detail Backlog Fitur

### 1. Timeline Rekaman dengan Penanda Gap (Prioritas 1)

- **Manfaat**:
  - Memudahkan operator dan viewer menelusuri rekaman sepanjang hari per kamera dalam satu bilah waktu (*scrubber* 24 jam) tanpa harus membuka segmen MP4 satu per satu.
  - Menampilkan secara eksplisit rentang waktu ketika rekaman terputus (*gap*), kamera offline, atau segmen korup sehingga operator segera mengetahui ada tidaknya celah arsip.
- **Dependensi**:
  - Skema indeks rekaman kanonik (`recordings_index.json` melalui `core/media_index.py` & `core/recording_manager.py`) dengan atribut `cameraId`, `date`, `startTime`, `endTime`, `durationSeconds`, dan `status`.
  - Endpoint streaming `GET /api/recordings/stream` dengan dukungan HTTP 206 Range (`server.py`).
- **Acceptance Criteria**:
  1. Endpoint API mengembalikan daftar blok rekaman berurutan dan daftar *gap* (interval kosong > toleransi rotasi segmen, mis. > 3 detik) per `cameraId` dan tanggal (`YYYY-MM-DD`).
  2. Kamera `okam_1`, `okam_2`, `okam_3`, `v380-1`, dan `v380-2` memiliki jalur timeline masing-masing yang terpisah.
  3. Klik pada titik waktu di timeline langsung memutar segmen yang sesuai pada offset detik yang tepat dan otomatis berlanjut ke segmen berikutnya.
  4. Area *gap* dan segmen berstatus `corrupt` diberi penanda visual berbeda serta menampilkan durasi dan penyebab (jika tercatat) saat di-*hover*.

---

### 2. Klip Event dengan Pre-Roll dan Post-Roll (Prioritas 1)

- **Manfaat**:
  - Menyimpan konteks beberapa detik **sebelum** pemicu gerakan/deteksi AI (*pre-roll*) dan beberapa detik **sesudah** gerakan berakhir (*post-roll*), sehingga awal kejadian tidak terpotong oleh waktu inisialisasi proses FFmpeg baru.
  - Menghubungkan setiap entri pada tab **Events & AI** langsung ke klip video kejadian terkait.
- **Dependensi**:
  - `MotionDetectorService` (`core/motion_detector.py`) sebagai penghasil sinyal event & skor gerakan/AI.
  - Ring buffer segmen pendek di memori/disk sementara atau ekstraksi lintas segmen dari `RecordingManager` (`core/recording_manager.py`).
  - `CamHubStorageManager` (`core/storage_manager.py`) untuk perlindungan file klip dan perhitungan kuota retention.
- **Acceptance Criteria**:
  1. Konfigurasi per kamera mendukung `preRollSeconds` (mis. default 5 detik) dan `postRollSeconds` (mis. default 10 detik).
  2. Ketika event gerakan/AI terkonfirmasi, sistem menghasilkan atau menautkan klip MP4 yang mencakup minimal `preRollSeconds` sebelum timestamp pemicu hingga `postRollSeconds` setelah gerakan reda.
  3. Pergerakan beruntun dalam jendela *post-roll* digabungkan menjadi satu klip berkelanjutan tanpa duplikasi proses perekam.
  4. Objek metadata di `events_index.json` menyimpan referensi `clipRecordingId` / `clipPath` yang dapat diputar oleh peran `viewer` maupun `admin`.

---

### 3. Peringatan Feed Live tetapi Recorder Berhenti (Prioritas 1)

- **Manfaat**:
  - Mencegah skenario berbahaya di mana tampilan *Live View* di layar terlihat normal (`HEALTHY`), tetapi proses perekam latar belakang berhenti menulis ke disk akibat kegagalan FFmpeg, disk penuh, atau sesi macet.
- **Dependensi**:
  - `CameraHealthMonitor` (`core/health_monitor.py`) untuk status kelayakan feed live (`status == HEALTHY` / `fps > 0`).
  - `RecordingManager` (`core/recording_manager.py`) untuk status sesi aktif, waktu segmen valid terakhir (`endTime`), dan status ruang disk.
  - `NotificationCenter` (`core/notification_center.py`) untuk pengiriman peringatan sistem.
- **Acceptance Criteria**:
  1. API status kamera membedakan empat indikator secara eksplisit: status feed live, status sesi recorder, timestamp segmen valid terakhir, dan sisa ruang disk.
  2. Jika sebuah kamera yang dikonfigurasi merekam memiliki feed live sehat selama lebih dari ambang batas (mis. 90 detik) tanpa pembaruan file segmen atau dengan sesi recorder mati, sistem mengubah status kelengkapan rekaman kamera tersebut menjadi `RECORDING_STALLED` / `STOPPED`.
  3. Dashboard dan kartu kamera menampilkan badge peringatan yang jelas ketika video live aktif tetapi perekaman berhenti.
  4. `NotificationCenter` mencatat alert kategori `recording_stopped` dengan mekanisme *cooldown* agar tidak membanjiri daftar notifikasi.

---

### 4. Audit Log Aktivitas Pengguna (Prioritas 2)

- **Manfaat**:
  - Menyediakan jejak akuntabilitas keamanan (*non-repudiation*) untuk seluruh aksi sensitif seperti login/logout, kegagalan autentikasi, pergerakan PTZ, start/stop kamera, pemicuan cleanup retention, perubahan konfigurasi, dan penghapusan rekaman/event.
- **Dependensi**:
  - `AuthManager` (`core/auth_manager.py`) untuk identitas prinsipal terverifikasi (`username`, `role`, `authType`) dan IP klien (`_client_key()`).
  - Utilitas sanitasi rahasia (`sanitize_sensitive_data` / `CamHubDiagnosticsService`) agar password dan token tidak pernah tertulis ke log.
- **Acceptance Criteria**:
  1. Seluruh operasi mutasi (`POST`, `PUT`, `PATCH`, `DELETE`) serta percobaan login/otorisasi gagal (`401`/`403`) dicatat secara append-only dalam format JSON Lines (`logs/audit.jsonl`) dengan penulisan sinkron aman-thread.
  2. Setiap baris audit memuat `timestamp`, `username` (atau `anonymous`), `role`, `clientIp`, `method`, `path`, `targetId` (mis. `cameraId` / `recordingId`), `statusCode`, dan `outcome`.
  3. Tidak ada password, token sesi, token bootstrap, bot token Telegram, atau kredensial RTSP yang pernah muncul di file audit log.
  4. Endpoint baca riwayat audit (`GET /api/audit`) hanya dapat diakses oleh peran `admin` dan disertakan (dalam kondisi tersanitasi) pada bundel ekspor diagnostik.

---

### 5. Export Bukti Kejadian beserta Timestamp dan Checksum (Prioritas 2)

- **Manfaat**:
  - Memungkinkan pemilik/admin mengekspor paket bukti kejadian yang utuh dan dapat diverifikasi keasliannya (belum dimodifikasi sejak diekspor) untuk dokumentasi insiden keamanan.
- **Dependensi**:
  - Indeks rekaman kanonik (`core/recording_manager.py`), indeks event (`core/motion_detector.py`), dan `PlaybackLockManager` (`core/storage_manager.py`).
  - `AuthManager` (`core/auth_manager.py`) untuk membatasi pembuatan paket ekspor pada pengguna berizin dan mencatat identitas pengekspor.
- **Acceptance Criteria**:
  1. Pengguna berizin (`admin`) dapat memilih `cameraId` dan rentang waktu (`startTime`–`endTime`) atau kumpulan `eventId` untuk diekspor menjadi satu arsip `.zip`.
  2. Selama proses pengemasan berlangsung, seluruh file MP4/JPEG sumber dilindungi oleh `PlaybackLockManager` agar tidak terhapus oleh retention otomatis.
  3. Arsip `.zip` berisi klip video MP4, snapshot JPEG terkait, serta file `manifest.json` yang mencantumkan identitas kamera, rentang waktu UTC & lokal, waktu ekspor, akun pengekspor, ukuran byte, dan hash `SHA-256` untuk setiap file di dalam bundel.
  4. Manifest tidak membocorkan URL RTSP mentah atau kredensial internal server.

---

### 6. Editor Zona dan Jadwal Deteksi (Prioritas 2)

- **Manfaat**:
  - Mengurangi positif palsu (*false alarm*) dari pepohonan, jalan umum, atau perubahan lampu dengan menggambar zona deteksi (*Region of Interest* / poligon/kotak) langsung di atas pratinjau kamera serta menjadwalkan jam aktif deteksi (mis. malam hari atau jam tutup).
- **Dependensi**:
  - Dukungan filter ROI yang sudah tersedia di `CameraMotionTracker` (`core/motion_detector.py`) dan `LocalObjectDetector` (`core/ai_detector.py`).
  - Endpoint snapshot kamera (`GET /api/cameras/{id}/snapshot`) sebagai latar kanvas editor dan otorisasi `admin` (`POST /api/cameras/config`).
- **Acceptance Criteria**:
  1. UI menyediakan kanvas visual di atas snapshot kamera terpilih untuk menambah, mengubah ukuran, dan menghapus zona deteksi ternormalisasi (`0.0`–`1.0`) serta mengatur sensitivitas/threshold per zona.
  2. Konfigurasi mendukung jadwal aktif per hari & jam (mis. `22:00–06:00` atau `24/7`) per kamera (`v380-1`, `v380-2`, `okam_1`, `okam_2`, `okam_3` secara independen).
  3. Perubahan zona dan jadwal hanya dapat disimpan oleh `admin` (`403` untuk `viewer`), divalidasi skemanya di server, disimpan secara atomik, dan langsung diterapkan ke `MotionDetectorService` tanpa me-restart server.

---

### 7. Quiet Hours dan Eskalasi Notifikasi (Prioritas 3)

- **Manfaat**:
  - Mencegah gangguan notifikasi berulang untuk kejadian berprioritas rendah pada jam istirahat (*quiet hours*), sambil memastikan insiden kritis (seperti kamera offline berkepanjangan atau disk hampir penuh) tetap dieskalasi tepat waktu.
- **Dependensi**:
  - `NotificationCenter` (`core/notification_center.py`), `CameraHealthMonitor` (`core/health_monitor.py`), dan `CamHubStorageManager` (`core/storage_manager.py`).
- **Acceptance Criteria**:
  1. Admin dapat mengatur jadwal *quiet hours* (rentang jam, hari aktif, dan zona waktu) serta memilih tingkat keparahan yang dibisukan sementara (mis. `info` dan `warning` ditahan di aplikasi, sedangkan `critical` tetap dikirim ke Telegram).
  2. Kejadian serupa yang berulang dalam jendela waktu singkat dikelompokkan (*digest/batching*) agar tidak mengirim puluhan pesan terpisah.
  3. Jika kamera berstatus `OFFLINE` atau disk berstatus `CRITICAL`/`EMERGENCY` melampaui durasi eskalasi yang dikonfigurasi (mis. > 10 menit belum di-*acknowledge*), sistem menaikkan prioritas dan mengirim notifikasi eskalasi meskipun sedang berada dalam *quiet hours*.
  4. Seluruh notifikasi yang tertahan selama *quiet hours* tetap tersimpan di riwayat aplikasi dan dapat ditinjau kapan saja.
