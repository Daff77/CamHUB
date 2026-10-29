"""
CamHub Smart Health Monitor
Monitors camera stream health, detects zombie servers, frozen frames, degraded FPS,
and maintains robust state transitions (HEALTHY, DEGRADED, OFFLINE, RECOVERING, UNKNOWN).
"""

import os
import sys
import time
import json
import socket
import hashlib
import threading
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from concurrent.futures import ThreadPoolExecutor, as_completed
from enum import Enum
import re

class CameraHealthState(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    OFFLINE = "OFFLINE"
    RECOVERING = "RECOVERING"
    UNKNOWN = "UNKNOWN"

DEFAULT_THRESHOLDS = {
    "pollIntervalSeconds": 3.0,
    "httpTimeoutSeconds": 1.5,
    "minFpsHealthy": 5.0,
    "minFpsDegraded": 0.5,
    "frameFreshnessTimeoutSec": 4.5,
    "frozenFrameThresholdSec": 8.0,
    "maxReconnectsDegraded": 2,
    "recoveryStabilitySeconds": 6.0,
    "consecutiveFailuresForOffline": 2
}

def sanitize_sensitive_data(text: str) -> str:
    """Mask credentials and passwords from text and URLs."""
    if not text:
        return ""
    # Mask URL credentials: http://user:pass@host -> http://user:***@host
    text = re.sub(r'://([^:]+):([^@]+)@', r'://\1:***@', text)
    # Mask CLI arguments: --password Secret123 -> --password ***
    text = re.sub(r'(--password\s+)[^\s]+', r'\1***', text, flags=re.IGNORECASE)
    return text

def is_port_listening(port: int, host: str = "127.0.0.1", timeout: float = 0.4) -> bool:
    """Non-blocking TCP socket check."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            return s.connect_ex((host, port)) == 0
    except:
        return False

class CameraHealthTracker:
    """Tracks state and history for a single camera stream."""

    def __init__(self, camera_id: str, name: str, port: int, thresholds: dict = None):
        self.camera_id = camera_id
        self.name = name
        self.port = port
        self.thresholds = dict(DEFAULT_THRESHOLDS)
        if thresholds:
            self.thresholds.update(thresholds)

        now = time.time()
        self.state = CameraHealthState.UNKNOWN
        self.previous_state = CameraHealthState.UNKNOWN
        self.state_entered_at = now
        self.last_checked = now
        self.last_healthy_at = 0.0
        self.incident_started_at = None
        self.recovery_started_at = None
        self.reason = "Initializing health monitoring"

        # Signal trackers
        self.consecutive_failures = 0
        self.consecutive_successes = 0
        self.last_total_frames = -1
        self.last_frame_advance_time = now
        self.last_snapshot_hash = None
        self.snapshot_hash_streak_time = now
        self.last_reconnect_count = 0
        self.last_decode_errors = 0

        # Latest raw metrics
        self.latest_metrics = {
            "fps": 0.0,
            "targetFps": 15.0,
            "latencyMs": 0.0,
            "totalFrames": 0,
            "frameAgeSeconds": 0.0,
            "queueDepth": 0,
            "reconnectCount": 0,
            "decodeErrors": 0,
            "cpuUsagePercent": 0.0,
            "memoryUsageMb": 0.0,
            "activeFfmpegCount": 0
        }

        self.latest_checks = {
            "portListening": False,
            "metricsResponding": False,
            "feedAlive": False,
            "streamFrozen": False,
            "fpsAdequate": False
        }

    def _transition_to(self, new_state: CameraHealthState, reason: str, now: float):
        if self.state != new_state:
            self.previous_state = self.state
            self.state = new_state
            self.state_entered_at = now

            if new_state == CameraHealthState.HEALTHY:
                self.incident_started_at = None
                self.recovery_started_at = None
                self.last_healthy_at = now
            elif new_state in (CameraHealthState.DEGRADED, CameraHealthState.OFFLINE):
                if self.incident_started_at is None:
                    self.incident_started_at = now
                self.recovery_started_at = None
            elif new_state == CameraHealthState.RECOVERING:
                if self.recovery_started_at is None:
                    self.recovery_started_at = now

        self.reason = reason

    def evaluate(self, metrics_data: dict, snapshot_bytes: bytes, port_open: bool, now: float = None):
        if now is None:
            now = time.time()

        self.last_checked = now
        min_fps_healthy = self.thresholds.get("minFpsHealthy", 5.0)
        min_fps_degraded = self.thresholds.get("minFpsDegraded", 0.5)
        freshness_timeout = self.thresholds.get("frameFreshnessTimeoutSec", 4.5)
        frozen_timeout = self.thresholds.get("frozenFrameThresholdSec", 8.0)
        max_reconnects = self.thresholds.get("maxReconnectsDegraded", 2)
        recovery_stability = self.thresholds.get("recoveryStabilitySeconds", 6.0)
        offline_debounce = self.thresholds.get("consecutiveFailuresForOffline", 2)

        self.latest_checks["portListening"] = port_open

        # 1. Critical failure: Port is closed / Process is unreachable
        if not port_open:
            self.consecutive_failures += 1
            self.consecutive_successes = 0
            self.latest_checks["metricsResponding"] = False
            self.latest_checks["feedAlive"] = False
            self.latest_checks["fpsAdequate"] = False
            self.latest_checks["streamFrozen"] = False

            if self.consecutive_failures >= offline_debounce or self.state == CameraHealthState.OFFLINE:
                self._transition_to(
                    CameraHealthState.OFFLINE,
                    f"Port {self.port} closed. Decoder service is offline or not running.",
                    now
                )
            else:
                self._transition_to(
                    CameraHealthState.DEGRADED,
                    f"Port {self.port} connection refused. Waiting for confirmation...",
                    now
                )
            return

        # 2. Port is open, check metrics response
        if metrics_data is None:
            self.consecutive_failures += 1
            self.consecutive_successes = 0
            self.latest_checks["metricsResponding"] = False
            self.latest_checks["feedAlive"] = False
            self.latest_checks["fpsAdequate"] = False

            # Port is open, but HTTP metrics endpoint is not responding = Zombie / Hung process
            self._transition_to(
                CameraHealthState.DEGRADED,
                f"Port {self.port} is open, but HTTP endpoint timed out. Adapter is hanging or deadlocked.",
                now
            )
            return

        self.latest_checks["metricsResponding"] = True
        self.consecutive_failures = 0

        # Extract telemetry
        stages = metrics_data.get("stages", {})
        latency_info = metrics_data.get("latency", {})
        health_info = metrics_data.get("health", {})

        src_fps = float(stages.get("sourceFps") or metrics_data.get("sourceFps") or 0.0)
        target_fps = float(stages.get("cameraDeclaredFps") or 15.0)
        lat_ms = float(latency_info.get("decodeLatencyMs") or metrics_data.get("xcodeLatencyMs") or 0.0)
        total_frames = int(metrics_data.get("totalSourceFrames") or 0)
        q_depth = int(health_info.get("queueDepth") or 0)
        reconnects = int(health_info.get("reconnectCount") or 0)
        dec_errors = int(health_info.get("decodingErrors") or 0)

        # Track frame advance (Zombie Video Detection)
        if total_frames > self.last_total_frames and self.last_total_frames != -1:
            self.last_frame_advance_time = now
        elif self.last_total_frames == -1 and total_frames > 0:
            self.last_frame_advance_time = now

        frame_age = max(0.0, now - self.last_frame_advance_time)
        self.last_total_frames = total_frames

        # Track frame frozen / identical snapshot hash
        is_frozen = False
        if snapshot_bytes and len(snapshot_bytes) > 100:
            snap_hash = hashlib.md5(snapshot_bytes).hexdigest()
            if snap_hash == self.last_snapshot_hash:
                streak = now - self.snapshot_hash_streak_time
                # Only flag frozen if frame advance is ALSO stalled to avoid static scene false positives!
                if streak >= frozen_timeout and frame_age >= (frozen_timeout * 0.75):
                    is_frozen = True
            else:
                self.last_snapshot_hash = snap_hash
                self.snapshot_hash_streak_time = now
        elif frame_age >= frozen_timeout and total_frames > 0:
            is_frozen = True

        self.latest_checks["streamFrozen"] = is_frozen
        feed_alive = frame_age < freshness_timeout and (total_frames > 0 or src_fps > 0)
        self.latest_checks["feedAlive"] = feed_alive
        fps_adequate = src_fps >= min_fps_healthy
        self.latest_checks["fpsAdequate"] = fps_adequate

        # Reconnect burst check
        reconnect_delta = max(0, reconnects - self.last_reconnect_count)
        self.last_reconnect_count = reconnects
        self.last_decode_errors = dec_errors

        # Store latest metrics
        self.latest_metrics = {
            "fps": round(src_fps, 1),
            "targetFps": round(target_fps, 1),
            "latencyMs": round(lat_ms, 1),
            "totalFrames": total_frames,
            "frameAgeSeconds": round(frame_age, 1),
            "queueDepth": q_depth,
            "reconnectCount": reconnects,
            "decodeErrors": dec_errors,
            "cpuUsagePercent": health_info.get("cpuUsagePercent", 0.0),
            "memoryUsageMb": health_info.get("memoryUsageMb", 0.0),
            "activeFfmpegCount": health_info.get("activeFfmpegCount", 0)
        }

        # 3. State Decision Logic
        # Condition A: Stream is completely stalled / 0 frames for longer than offline threshold
        if total_frames > 0 and frame_age > (freshness_timeout * 3):
            self.consecutive_successes = 0
            self._transition_to(
                CameraHealthState.OFFLINE,
                f"Stream stalled. Port {self.port} listening, but no frames received for {round(frame_age, 1)}s.",
                now
            )
            return

        # Condition B: Frozen frame detected
        if is_frozen:
            self.consecutive_successes = 0
            self._transition_to(
                CameraHealthState.DEGRADED,
                f"Video frozen. Snapshot and frame counter static for {round(now - self.snapshot_hash_streak_time, 1)}s.",
                now
            )
            return

        # Condition C: Frequent reconnects
        if reconnect_delta >= max_reconnects:
            self.consecutive_successes = 0
            self._transition_to(
                CameraHealthState.DEGRADED,
                f"Unstable LAN transport. {reconnect_delta} reconnects detected recently.",
                now
            )
            return

        # Condition D: Low / Degraded FPS
        if src_fps < min_fps_healthy:
            self.consecutive_successes = 0
            if src_fps < min_fps_degraded:
                self._transition_to(
                    CameraHealthState.DEGRADED,
                    f"Critically low framerate ({src_fps} fps). Expected >= {min_fps_healthy} fps.",
                    now
                )
            else:
                self._transition_to(
                    CameraHealthState.DEGRADED,
                    f"Reduced framerate ({src_fps} fps). Target is {target_fps} fps.",
                    now
                )
            return

        # Condition E: Excessive Latency / Queue
        if lat_ms > 2500.0 or q_depth >= 15:
            self.consecutive_successes = 0
            self._transition_to(
                CameraHealthState.DEGRADED,
                f"High pipeline backlog. Latency {round(lat_ms)}ms, queue depth {q_depth} frames.",
                now
            )
            return

        # Condition F: Healthy metrics observed
        self.consecutive_successes += 1

        if self.state in (CameraHealthState.OFFLINE, CameraHealthState.DEGRADED):
            # Begin recovery period
            self._transition_to(
                CameraHealthState.RECOVERING,
                f"Stream resumed at {src_fps} fps. Verifying stability ({recovery_stability}s window)...",
                now
            )
        elif self.state == CameraHealthState.RECOVERING:
            dur = now - (self.recovery_started_at or now)
            if dur >= recovery_stability:
                self._transition_to(
                    CameraHealthState.HEALTHY,
                    f"Stream healthy and stable at {src_fps} fps, latency {round(lat_ms)}ms.",
                    now
                )
            else:
                self.reason = f"Stream recovering at {src_fps} fps ({round(dur, 1)}s / {recovery_stability}s)..."
        elif self.state in (CameraHealthState.HEALTHY, CameraHealthState.UNKNOWN):
            self._transition_to(
                CameraHealthState.HEALTHY,
                f"Stream healthy at {src_fps} fps, latency {round(lat_ms)}ms, queue {q_depth}.",
                now
            )

    def to_dict(self) -> dict:
        now = time.time()
        incident_dur = round(now - self.incident_started_at, 1) if self.incident_started_at else 0.0
        state_dur = round(now - self.state_entered_at, 1)

        return {
            "id": self.camera_id,
            "name": self.name,
            "port": self.port,
            "status": self.state.value,
            "previousStatus": self.previous_state.value,
            "reason": self.reason,
            "lastChecked": int(self.last_checked * 1000),
            "lastHealthy": int(self.last_healthy_at * 1000) if self.last_healthy_at > 0 else None,
            "stateDurationSeconds": state_dur,
            "incidentDurationSeconds": incident_dur,
            "metrics": dict(self.latest_metrics),
            "checks": dict(self.latest_checks)
        }


class CameraHealthMonitor:
    """Non-blocking background manager for all camera health checks."""

    def __init__(self, config_provider, global_thresholds: dict = None):
        self.config_provider = config_provider
        self.global_thresholds = dict(DEFAULT_THRESHOLDS)
        if global_thresholds:
            self.global_thresholds.update(global_thresholds)

        self.trackers = {}
        self.lock = threading.Lock()
        self.running = False
        self.worker_thread = None
        self.executor = ThreadPoolExecutor(max_workers=6, thread_name_prefix="HealthCheckWorker")

    def start(self):
        with self.lock:
            if self.running:
                return
            self.running = True
            self.worker_thread = threading.Thread(target=self._run_loop, daemon=True, name="HealthMonitorLoop")
            self.worker_thread.start()
            print("[HEALTH] Smart Health Monitor started.", flush=True)

    def stop(self):
        with self.lock:
            self.running = False
        if self.executor:
            self.executor.shutdown(wait=False)

    def _sync_cameras(self):
        cfg = self.config_provider()
        thresholds_cfg = cfg.get("healthMonitor", {})
        cameras = cfg.get("cameras", [])

        with self.lock:
            active_ids = set()
            for cam in cameras:
                cid = cam.get("id")
                port = cam.get("port")
                name = cam.get("name", cid)
                active_ids.add(cid)

                # Merge global and per-camera thresholds
                merged_thresh = dict(self.global_thresholds)
                merged_thresh.update(thresholds_cfg)
                if "healthThresholds" in cam:
                    merged_thresh.update(cam["healthThresholds"])

                if cid not in self.trackers:
                    self.trackers[cid] = CameraHealthTracker(cid, name, port, merged_thresh)
                else:
                    self.trackers[cid].port = port
                    self.trackers[cid].thresholds = merged_thresh

            # Remove deleted cameras
            to_remove = [cid for cid in self.trackers if cid not in active_ids]
            for cid in to_remove:
                del self.trackers[cid]

    def _check_single_camera(self, tracker: CameraHealthTracker):
        port = tracker.port
        timeout = tracker.thresholds.get("httpTimeoutSeconds", 1.5)

        # 1. Port Check
        port_open = is_port_listening(port, timeout=0.4)
        if not port_open:
            with self.lock:
                tracker.evaluate(None, None, False)
            return

        # 2. HTTP Metrics fetch (non-blocking with timeout)
        metrics_data = None
        metrics_url = f"http://127.0.0.1:{port}/api/metrics"
        try:
            req = Request(metrics_url, headers={"User-Agent": "CamHub-HealthMonitor/1.0"})
            with urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    body = resp.read()
                    metrics_data = json.loads(body.decode("utf-8"))
        except:
            metrics_data = None

        # 3. Snapshot fetch (sample for frozen frame detection if metrics returned 0 fps or periodically)
        snapshot_bytes = None
        if metrics_data:
            fps = float(metrics_data.get("sourceFps") or 0.0)
            if fps < 3.0:
                try:
                    snap_url = f"http://127.0.0.1:{port}/snapshot"
                    s_req = Request(snap_url, headers={"User-Agent": "CamHub-HealthMonitor/1.0"})
                    with urlopen(s_req, timeout=1.0) as s_resp:
                        if s_resp.status == 200:
                            snapshot_bytes = s_resp.read()
                except:
                    snapshot_bytes = None

        with self.lock:
            tracker.evaluate(metrics_data, snapshot_bytes, True)

    def _run_loop(self):
        while self.running:
            try:
                self._sync_cameras()
                with self.lock:
                    trackers_list = list(self.trackers.values())

                if trackers_list:
                    futures = [self.executor.submit(self._check_single_camera, t) for t in trackers_list]
                    # Wait up to 3 seconds for all checks to finish
                    for f in as_completed(futures, timeout=3.0):
                        try:
                            f.result()
                        except:
                            pass

                interval = self.global_thresholds.get("pollIntervalSeconds", 3.0)
                time.sleep(interval)
            except Exception as e:
                time.sleep(2.0)

    def get_camera_health(self, camera_id: str) -> dict:
        with self.lock:
            tracker = self.trackers.get(camera_id)
            if tracker:
                return tracker.to_dict()
        return None

    def get_all_health(self) -> dict:
        now = time.time()
        with self.lock:
            trackers_list = [t.to_dict() for t in self.trackers.values()]

        summary = {
            "total": len(trackers_list),
            "healthy": sum(1 for t in trackers_list if t["status"] == CameraHealthState.HEALTHY.value),
            "degraded": sum(1 for t in trackers_list if t["status"] == CameraHealthState.DEGRADED.value),
            "offline": sum(1 for t in trackers_list if t["status"] == CameraHealthState.OFFLINE.value),
            "recovering": sum(1 for t in trackers_list if t["status"] == CameraHealthState.RECOVERING.value),
            "unknown": sum(1 for t in trackers_list if t["status"] == CameraHealthState.UNKNOWN.value)
        }

        # Overall fleet status
        if summary["offline"] > 0:
            fleet_status = CameraHealthState.DEGRADED.value if summary["healthy"] > 0 else CameraHealthState.OFFLINE.value
        elif summary["degraded"] > 0:
            fleet_status = CameraHealthState.DEGRADED.value
        elif summary["recovering"] > 0:
            fleet_status = CameraHealthState.RECOVERING.value
        elif summary["healthy"] == summary["total"] and summary["total"] > 0:
            fleet_status = CameraHealthState.HEALTHY.value
        else:
            fleet_status = CameraHealthState.UNKNOWN.value

        cameras_map = {t["id"]: t for t in trackers_list}

        return {
            "status": fleet_status,
            "timestamp": int(now * 1000),
            "summary": summary,
            "cameras": cameras_map
        }
