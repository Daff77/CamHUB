# CamHUB Storage Manager & Retention Policy Guide (AGENT 8)

Dokumentasi arsitektur penyimpanan, kebijakan retensi bertingkat, pemantauan disk, peramalan kapasitas (*forecasting*), dan rekonsiliasi indeks pada CamHUB.

---

## 1. Ringkasan & Tujuan
Modul **CamHUB Storage Manager** ([`core/storage_manager.py`](file:///c:/DaffaP/Project%20df/CamHUB/core/storage_manager.py)) bertugas mengelola seluruh aset data lokal secara terukur, otomatis, dan dapat diprediksi tanpa risiko menghapus data aktif atau file di luar direktori CamHUB.

### Karakteristik & Batasan Keamanan:
- **Scope Containment**: Proteksi path traversal ketat (`sanitize_path`), operasi penghapusan dibatasi hanya pada direktori data `recordings/` dan `events/`.
- **Dry-Run Validation**: Sebelum pembersihan dilakukan, sistem menyediakan mode simulasi (`dryRun=true`) untuk memvalidasi daftar file dan jumlah byte yang akan terhapus.
- **Active File Protection**:
  - File yang sedang aktif direkam oleh FFmpeg (`active_sessions`) diproteksi dari pembersihan.
  - File yang sedang diputar di pemutar web atau diunduh diproteksi melalui lease lock otomatis ([`PlaybackLockManager`](file:///c:/DaffaP/Project%20df/CamHUB/core/storage_manager.py)).
- **Dynamic Threshold Alerts**: Ambang peringatan kapasitas disk bertingkat: **80% (WARNING)**, **90% (CRITICAL)**, dan **95% (EMERGENCY)**.
- **Self-Healing Index**: Pemulihan otomatis jika server mengalami crash mendadak atau file fisik tidak sinkron dengan file indeks.

---

## 2. Struktur Tata Letak Penyimpanan (Storage Layout)

```
c:\DaffaP\Project df\CamHUB\
├── recordings/                      # Direktori rekaman video MP4
│   ├── <camera_id>/
│   │   └── YYYY-MM-DD/
│   │       ├── <cam>_rec_YYYYMMDD_HHMMSS_seg000.mp4
│   │       └── <cam>_motion_YYYYMMDD_HHMMSS_seg000.mp4
│   └── recordings_index.json       # Metadata indeks rekaman MP4
│
├── events/                          # Direktori snapshot deteksi gerakan & AI
│   ├── <camera_id>/
│   │   └── YYYY-MM-DD/
│   │       └── evt_<cam>_YYYYMMDD_HHMMSS_xxxxxx.jpg
│   └── events_index.json           # Metadata indeks snapshot & bounding box
│
└── config/
    └── services_config.json        # Konfigurasi retensi & kuota penyimpanan
```

---

## 3. Ambang Peringatan Kapasitas Disk (Threshold Alerting)

Sistem memantau volume disk host secara berkala:

| Level Alert | Ambang Kapasitas | Ambang Sisa | Tindakan Sistem |
| :--- | :---: | :---: | :--- |
| **NORMAL** | Digunakan < 80% | Free > 5.0 GB | Operasi normal, logging berkala. |
| **WARNING** | **≥ 80.0% Digunakan** | Free ≤ 76.5 GB | Status pill kuning pada dashboard, notifikasi tren penipisan ruang. |
| **CRITICAL** | **≥ 90.0% Digunakan** | Free < 5.0 GB | Status pill oranye, memicu pembersihan retensi agresif pada data lampau. |
| **EMERGENCY**| **≥ 95.0% Digunakan** | Free < 2.5 GB | Status pill merah berkedip, menghentikan perekaman aktif non-esensial untuk melindungi stabilitas sistem operasi host. |

> [!NOTE]
> Pada mesin host saat ini (kapasitas 476.19 GB, digunakan 399.75 GB / **83.9%**), sistem secara akurat mengaktifkan status **WARNING** dengan estimasi sisa 72.5 hari pada tingkat pertumbuhan rata-rata 45 MB/jam.

---

## 4. Kebijakan Retensi & Formula Peramalan Kapasitas

### 4.1 Kebijakan Retensi Terpisah Berdasarkan Tipe Data
Dikonfigurasi pada [`config/services_config.json`](file:///c:/DaffaP/Project%20df/CamHUB/config/services_config.json):
```json
"storageManagement": {
  "enabled": true,
  "checkIntervalSeconds": 60.0,
  "warningThresholdPercent": 80.0,
  "criticalThresholdPercent": 90.0,
  "emergencyThresholdPercent": 95.0,
  "minDiskFreeGb": 5.0,
  "retention": {
    "recordings": {
      "maxAgeDays": 7,
      "maxStorageGb": 20.0,
      "protectActiveRecordings": true,
      "protectActivePlayback": true
    },
    "events": {
      "maxAgeDays": 7,
      "maxStorageMb": 1000.0
    },
    "tempFiles": {
      "maxAgeHours": 2.0
    }
  }
}
```

### 4.2 Formula Estimasi Waktu Tersisa (*Depletion Forecasting*)
$$Laju\ Pertumbuhan\ (MB/jam) = \frac{\Delta\ Byte\ Data\ CamHUB}{\Delta\ Waktu\ (detik)} \times 3600 \div 1024^2$$

$$Estimasi\ Jam\ Tersisa = \frac{Ruang\ Kosong\ Disk\ (MB)}{Laju\ Pertumbuhan\ (MB/jam)}$$

$$Estimasi\ Hari\ Tersisa = \frac{Estimasi\ Jam\ Tersisa}{24}$$

---

## 5. Rekonsiliasi & Self-Healing Index

Jika metadata mengalami desinkronisasi (misalnya crash listrik saat file sedang ditulis):
1. **Pembersihan Entri Hantu (Ghost Records)**:  
   Jika indeks memuat rekaman atau event yang file fisiknya sudah dihapus manual dari disk, entri tersebut dibersihkan secara otomatis.
2. **Rekonstruksi File Tak Terindeks (Orphaned Files)**:  
   File `.mp4` atau `.jpg` yang ada di disk namun belum masuk ke dalam indeks akan diinspeksi header dan timestamp-nya, lalu didaftarkan ulang ke metadata indeks.
3. **Pembersihan File Sampah & Sementara**:  
   File dengan ekstensi `.tmp` atau `.part` yang berumur lebih dari 2 jam serta file 0-byte kosong dibersihkan secara otomatis.

---

## 6. Dokumentasi REST API

### 1. `GET /api/storage/status`
Mengembalikan status kapasitas disk, ukuran total CamHUB, rincian per kamera, estimasi sisa waktu, dan level alert.
```json
{
  "disk": {
    "totalGb": 476.19,
    "usedGb": 399.75,
    "freeGb": 76.44,
    "usedPercent": 83.9
  },
  "camhub": {
    "totalMb": 12.2,
    "totalGb": 0.012
  },
  "recordings": {
    "fileCount": 0,
    "totalMb": 0.0
  },
  "events": {
    "fileCount": 50,
    "totalMb": 12.2,
    "cameras": {
      "okam-3": {"count": 30, "mb": 5.17},
      "v380-1": {"count": 20, "mb": 7.04}
    }
  },
  "forecasting": {
    "growthRateMbPerHour": 45.0,
    "estimatedDaysRemaining": 72.5,
    "status": "Comfortable"
  },
  "alerts": {
    "level": "WARNING",
    "message": "WARNING: Disk usage exceeds 80.0% (currently 83.9%, 76.44 GB free)."
  }
}
```

### 2. `POST /api/storage/cleanup?dryRun=true`
Menjalankan simulasi (*dry-run*) kebijakan retensi tanpa menghapus file fisik di disk.
```json
{
  "dryRun": true,
  "filesToDeleteCount": 0,
  "filesDeletedCount": 0,
  "mbToFree": 0.0,
  "files": []
}
```
*Ganti `dryRun=false` untuk eksekusi pembersihan nyata.*

### 3. `POST /api/storage/reindex`
Memicu rekonsiliasi dan perbaikan mandiri antara disk fisik dan database JSON indeks.

### 4. `GET /api/storage/report`
Mengembalikan laporan ringkas diagnostik teks yang siap ditampilkan ke administrator.

---

## 7. Hasil Pengujian Unit & Verifikasi

Pengujian dilakukan dengan 9 test case komprehensif di [`tests/test_storage_manager.py`](file:///c:/DaffaP/Project%20df/CamHUB/tests/test_storage_manager.py):
- Verifikasi pencegahan path traversal.
- Pengujian ambang batas disk 80%, 90%, 95%.
- Pengujian simulasi *dry-run* vs eksekusi nyata.
- Pengujian proteksi file yang sedang direkam atau diputar (*playback lock lease*).
- Pengujian rekonsiliasi entri hantu dan file fisik tanpa metadata.
- **Hasil**: 51/51 unit test di seluruh proyek lulus (**100% pass rate**).
