# CamHUB Architecture & Directory Structure

CamHUB is a modular, high-performance, real-time multi-camera management and telemetry platform. This document outlines the project's file architecture, module responsibilities, and data flow.

---

## 📁 Directory Structure Overview

```
CamHUB/
│
├── core/                         # Backend Python engine & microservices
│   ├── __init__.py               # Core package exports and service facades
│   ├── auto_recovery.py          # Process supervision, crash recovery, circuit breaker
│   ├── health_monitor.py         # Multi-signal health check, zombie & freeze detection
│   ├── motion_detector.py        # OpenCV motion analysis worker & snapshot manager
│   ├── recording_manager.py      # Local segmentation, disk quota & retention manager
│   └── okam_adapter.py           # Multi-threaded RTSP-to-MJPEG protocol adapter
│
├── web/                          # Frontend SPA dashboard assets
│   ├── index.html                # Single-page dashboard interface
│   ├── app.js                    # Web UI state management, digital zoom, charts & telemetry
│   └── styles.css                # Responsive stylesheet & dark/light theme tokens
│
├── config/                       # Application configuration
│   └── services_config.json      # Camera profiles, network ports, thresholds & cmds
│
├── docs/                         # Technical documentation & architecture
│   ├── ARCHITECTURE.md           # This architecture and directory layout guide
│   └── DESIGN.md                 # Design decisions & requirements specification
│
├── tests/                        # Automated unit test suite (32 unit tests)
│   ├── __init__.py               # Test discovery environment setup
│   ├── test_auto_recovery.py     # Supervisor state transitions & recovery tests
│   ├── test_health_monitor.py    # Health signals, freeze checks & sanitization tests
│   ├── test_local_recording.py   # Segment rotation, retention & HTTP 206 tests
│   └── test_motion_detection.py  # Motion scoring, static filters & cooldown tests
│
├── events/                       # Motion detection snapshot storage
│   ├── <camera_id>/<date>/       # Organized by camera and date
│   ├── events_index.json         # Searchable event timeline metadata index
│   └── .gitkeep
│
├── recordings/                   # Video recordings storage
│   ├── <camera_id>/<date>/       # Organized by camera and date (.mp4 segments)
│   ├── recordings_index.json     # Recording metadata index
│   └── .gitkeep
│
├── server.py                     # Primary host application, HTTP static server & REST API
├── okam_adapter.py               # Root CLI wrapper for backward compatibility
├── README.md                     # Project overview and quickstart guide
└── .gitignore                    # Git exclusions
```

---

## 🧩 Module Breakdown

### 1. `core/` (Backend Services)
- **`auto_recovery.py`**: State machine (`STOPPED`, `STARTING`, `RUNNING`, `STOPPING`, `RESTARTING`, `FAILED`) supervising child processes. Manages exponential backoff, circuit breaking, stable run resets, and clean process tree termination without orphan processes.
- **`health_monitor.py`**: Non-blocking concurrent health checker tracking TCP ports, HTTP telemetry, frame freshness, frozen frame hashing, and degraded FPS detection.
- **`motion_detector.py`**: Background analytics worker analyzing video snapshots using OpenCV / PIL image differencing, contour detection, sudden lighting suppression, and timeline persistence.
- **`recording_manager.py`**: Direct-stream or re-encoded segment recorder using FFmpeg. Implements automated segment rotation, disk space safeguards, and retention policy purging.
- **`okam_adapter.py`**: Dedicated RTSP-to-MJPEG/Snapshot adapter for O-Kam Pro / VStarcam cameras with multi-client thread pooling.

### 2. `web/` (Frontend Application)
- **`index.html`**: Semantic layout supporting 2-column, auto-dense, and 1-column layouts, live monitoring grid, analytics drawer, event timeline, and recording playback.
- **`app.js`**: Client-side single page app featuring:
  - Interactive Digital Zoom & Pan (1.0x to 5.0x with smooth drag & mouse wheel).
  - Live sparkline FPS graphing and pipeline bottleneck diagnostics.
  - Camera multi-select filter with real-time health indicator badges.
  - Recording playback scrubber with HTTP 206 range seeking.
- **`styles.css`**: Hardware-accelerated CSS with CSS custom properties for dark & light themes.

### 3. `config/` (Configuration)
- **`services_config.json`**: Centralized configuration defining camera parameters, launch commands, health thresholds, auto-recovery limits, recording retention, and motion sensitivity.

### 4. `server.py` (Host Server)
- Serves frontend assets from `web/` with strict anti-caching headers (`Cache-Control: no-cache, no-store, must-revalidate`).
- Provides unified REST APIs (`/api/services`, `/api/health`, `/api/recovery`, `/api/recordings`, `/api/events`).
- Supports video streaming with HTTP 206 Partial Content.
