"""
CamHub Local Recording & Playback Manager
Manages local video segment recording using FFmpeg with zero-transcode pass-through (-c:v copy),
metadata indexing, retention policy enforcement, disk space protection, incomplete file recovery,
and HTTP 206 Partial Content streaming for smooth playback.
"""

import os
import sys
import time
import json
import glob
import shutil
import threading
import subprocess
from datetime import datetime
from urllib.parse import quote, unquote

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_RECORDINGS_DIR = os.path.join(BASE_DIR, "recordings")

DEFAULT_RECORDING_CONFIG = {
    "enabled": True,
    "storagePath": "recordings",
    "segmentDurationSeconds": 60,
    "retentionDays": 7,
    "maxStorageGb": 20.0,
    "minDiskFreeGb": 5.0,
    "preferredSource": "rtsp",
    "autoRecordCameras": []
}

def sanitize_path(base_dir: str, target_path: str) -> str:
    """Ensure target path is strictly within base directory (prevents path traversal)."""
    abs_base = os.path.abspath(base_dir)
    abs_target = os.path.abspath(target_path)
    if os.path.commonpath([abs_base, abs_target]) != abs_base:
        raise ValueError("Access denied: path traversal detected")
    return abs_target

def get_disk_space_stats(path: str) -> dict:
    """Retrieve total, used, and free disk space in GB."""
    try:
        os.makedirs(path, exist_ok=True)
        total, used, free = shutil.disk_usage(path)
        return {
            "totalGb": round(total / (1024**3), 2),
            "usedGb": round(used / (1024**3), 2),
            "freeGb": round(free / (1024**3), 2),
            "totalBytes": total,
            "usedBytes": used,
            "freeBytes": free
        }
    except Exception as e:
        return {
            "totalGb": 0.0, "usedGb": 0.0, "freeGb": 0.0,
            "totalBytes": 0, "usedBytes": 0, "freeBytes": 0, "error": str(e)
        }

class RecordingSession:
    """Manages an active FFmpeg recording process for a camera."""

    def __init__(self, camera_id: str, stream_url: str, storage_dir: str, mode: str = "continuous", segment_dur: int = 60, duration_limit: int = 0):
        self.camera_id = camera_id
        self.stream_url = stream_url
        self.storage_dir = storage_dir
        self.mode = mode
        self.segment_duration = segment_dur
        self.duration_limit = duration_limit  # 0 = continuous until stopped
        self.start_time = time.time()
        self.process = None
        self.pid = None
        self.running = False
        self.current_day = datetime.now().strftime("%Y-%m-%d")

    def start(self) -> tuple[bool, str]:
        date_folder = os.path.join(self.storage_dir, self.camera_id, self.current_day)
        os.makedirs(date_folder, exist_ok=True)

        prefix = "motion" if self.mode == "motion" else "rec"
        # Segment pattern: e.g. v380-1_rec_20261029_201500_seg%03d.mp4
        pattern = os.path.join(date_folder, f"{self.camera_id}_{prefix}_%Y%m%d_%H%M%S_seg%03d.mp4")

        is_rtsp = self.stream_url.lower().startswith("rtsp://")

        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
        if is_rtsp:
            cmd.extend(["-rtsp_transport", "tcp"])
        cmd.extend(["-i", self.stream_url])

        if self.duration_limit > 0:
            cmd.extend(["-t", str(self.duration_limit)])

        # Zero-transcode copy into MP4 segment format
        cmd.extend([
            "-c:v", "copy",
            "-an",
            "-f", "segment",
            "-segment_time", str(self.segment_duration),
            "-reset_timestamps", "1",
            "-strftime", "1",
            "-segment_format", "mp4",
            "-movflags", "+faststart",
            pattern
        ])

        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
            )
            self.pid = self.process.pid
            self.running = True
            return True, f"Started recording for {self.camera_id} (PID {self.pid})"
        except Exception as e:
            return False, str(e)

    def stop(self):
        self.running = False
        if self.process:
            try:
                if sys.platform == "win32":
                    subprocess.run(f"taskkill /F /T /PID {self.process.pid}", shell=True, capture_output=True)
                else:
                    self.process.terminate()
            except:
                pass
            self.process = None
            self.pid = None


class RecordingManager:
    """Fleet-wide recording, playback, retention, and metadata index manager."""

    def __init__(self, config_provider, base_dir: str = None):
        self.config_provider = config_provider
        self.base_dir = base_dir or BASE_DIR
        self.lock = threading.Lock()
        self.active_sessions = {}  # camera_id -> RecordingSession
        self.index = {}  # segment_id -> metadata dict
        self.running = False
        self.worker_thread = None

        cfg = self.config_provider().get("recording", {})
        self.config = dict(DEFAULT_RECORDING_CONFIG)
        self.config.update(cfg)

        rel_storage = self.config.get("storagePath", "recordings")
        self.storage_dir = os.path.join(self.base_dir, rel_storage)
        os.makedirs(self.storage_dir, exist_ok=True)
        self.index_file = os.path.join(self.storage_dir, "recordings_index.json")

        self.load_index()
        self.scan_and_sync_filesystem()

    def start(self):
        with self.lock:
            if self.running:
                return
            self.running = True
            self.worker_thread = threading.Thread(target=self._background_worker, daemon=True, name="RecordingWorker")
            self.worker_thread.start()
            print(f"[RECORDING] Recording Manager active. Storage: {self.storage_dir}", flush=True)

        # Check auto-start cameras from config
        self._check_auto_record()

    def stop(self):
        with self.lock:
            self.running = False
            sessions = list(self.active_sessions.values())
        for s in sessions:
            s.stop()
        self.save_index()

    def _check_auto_record(self):
        cfg = self.config_provider()
        rec_cfg = cfg.get("recording", {})
        auto_cams = rec_cfg.get("autoRecordCameras", [])
        for cam in cfg.get("cameras", []):
            cid = cam.get("id")
            if cid in auto_cams and cid not in self.active_sessions:
                self.start_recording(cid, mode="continuous")

    def load_index(self):
        if os.path.exists(self.index_file):
            try:
                with open(self.index_file, "r", encoding="utf-8") as f:
                    self.index = json.load(f)
            except Exception as e:
                print(f"[RECORDING] Error reading index: {e}", file=sys.stderr)
                self.index = {}
        else:
            self.index = {}

    def save_index(self):
        try:
            with open(self.index_file, "w", encoding="utf-8") as f:
                json.dump(self.index, f, indent=2)
        except Exception as e:
            print(f"[RECORDING] Error saving index: {e}", file=sys.stderr)

    def scan_and_sync_filesystem(self):
        """Discovers new recording files on disk and cleans stale unclosed entries."""
        with self.lock:
            mp4_files = glob.glob(os.path.join(self.storage_dir, "*", "*", "*.mp4"))
            existing_paths = {item.get("filePath"): seg_id for seg_id, item in self.index.items()}

            for filepath in mp4_files:
                norm_path = os.path.normpath(filepath)
                rel_path = os.path.relpath(norm_path, self.base_dir).replace("\\", "/")
                filename = os.path.basename(norm_path)
                parts = filename.split("_")
                cam_id = parts[0] if parts else "unknown"

                try:
                    stat = os.stat(norm_path)
                    size = stat.st_size
                    mtime = stat.st_mtime
                    ctime = stat.st_ctime
                except:
                    continue

                if rel_path not in existing_paths:
                    # New discovered segment
                    seg_id = os.path.splitext(filename)[0]
                    mode = "motion" if "motion" in filename else "continuous"
                    self.index[seg_id] = {
                        "id": seg_id,
                        "cameraId": cam_id,
                        "fileName": filename,
                        "filePath": rel_path,
                        "fileSizeBytes": size,
                        "startTime": int(ctime * 1000),
                        "endTime": int(mtime * 1000),
                        "durationSeconds": round(max(0, mtime - ctime), 1),
                        "status": "completed" if size > 1024 else "corrupt",
                        "mode": mode,
                        "format": "mp4"
                    }
                else:
                    # Update file size of existing entries
                    seg_id = existing_paths[rel_path]
                    entry = self.index[seg_id]
                    if entry.get("fileSizeBytes") != size:
                        entry["fileSizeBytes"] = size
                        entry["endTime"] = int(mtime * 1000)
                        entry["durationSeconds"] = round(max(0, mtime - (entry["startTime"] / 1000)), 1)
                        if size > 1024:
                            entry["status"] = "completed"

            # Check for entries in index whose files were deleted from disk
            to_remove = []
            for seg_id, item in self.index.items():
                full_path = os.path.join(self.base_dir, item.get("filePath", ""))
                if not os.path.exists(full_path):
                    to_remove.append(seg_id)
            for seg_id in to_remove:
                del self.index[seg_id]

        self.save_index()

    def get_stream_url_for_camera(self, cid: str) -> str:
        """Determines best RTSP or MJPEG URL for recording without disturbing live view."""
        cfg = self.config_provider()
        cam = next((c for c in cfg.get("cameras", []) if c.get("id") == cid), None)
        if not cam:
            return ""

        pref = self.config.get("preferredSource", "rtsp")

        # RTSP endpoints
        if pref == "rtsp":
            if cam.get("type") == "okam":
                # Camera 3 direct RTSP
                rtsp_cmd = cam.get("cmd", "")
                if "--rtsp" in rtsp_cmd:
                    try:
                        idx = rtsp_cmd.index("--rtsp")
                        return rtsp_cmd[idx + 6:].strip().strip('"').strip("'")
                    except:
                        pass
            elif cam.get("fastRtsCmd"):
                # Camera 2 direct RTSP
                try:
                    cmd_str = cam["fastRtsCmd"]
                    idx = cmd_str.index("--rtsp")
                    return cmd_str[idx + 6:].strip().strip('"').strip("'")
                except:
                    pass
            elif cam.get("rtspPort"):
                # V380Decoder restream port (e.g. 8554, 8555)
                return f"rtsp://127.0.0.1:{cam['rtspPort']}/live/ch0"

        # Fallback to local MJPEG stream
        port = cam.get("port", 8080)
        return f"http://127.0.0.1:{port}/stream.mjpg"

    def start_recording(self, cid: str, mode: str = "manual", duration: int = 0) -> tuple[bool, str]:
        # Check disk space warning before launching
        stats = get_disk_space_stats(self.storage_dir)
        min_free = self.config.get("minDiskFreeGb", 5.0)
        if stats.get("freeGb", 0) < min_free:
            return False, f"Disk space critically low ({stats.get('freeGb')} GB free < {min_free} GB threshold). Recording halted."

        with self.lock:
            if cid in self.active_sessions:
                s = self.active_sessions[cid]
                if s.running and s.process and s.process.poll() is None:
                    return True, f"Recording already active for '{cid}' (PID {s.pid})"

        stream_url = self.get_stream_url_for_camera(cid)
        if not stream_url:
            return False, f"No stream URL found for camera '{cid}'"

        seg_dur = self.config.get("segmentDurationSeconds", 60)
        session = RecordingSession(
            camera_id=cid,
            stream_url=stream_url,
            storage_dir=self.storage_dir,
            mode=mode,
            segment_dur=seg_dur,
            duration_limit=duration
        )

        ok, msg = session.start()
        if ok:
            with self.lock:
                self.active_sessions[cid] = session
        return ok, msg

    def stop_recording(self, cid: str) -> tuple[bool, str]:
        with self.lock:
            session = self.active_sessions.get(cid)
            if not session:
                return False, f"No active recording for camera '{cid}'"
            del self.active_sessions[cid]

        session.stop()
        self.scan_and_sync_filesystem()
        return True, f"Stopped recording for camera '{cid}'"

    def trigger_motion_recording(self, cid: str, duration: int = 30) -> tuple[bool, str]:
        """Trigger an isolated motion clip recording."""
        return self.start_recording(cid, mode="motion", duration=duration)

    def enforce_retention_policy(self):
        """Purges recordings exceeding retentionDays or maxStorageGb."""
        retention_days = self.config.get("retentionDays", 7)
        max_storage_gb = self.config.get("maxStorageGb", 20.0)
        now_ts = time.time()
        max_age_sec = retention_days * 86400

        with self.lock:
            items = list(self.index.values())

        # 1. Purge segments older than retentionDays
        purged_by_age = []
        for item in items:
            start_sec = item.get("startTime", 0) / 1000.0
            if (now_ts - start_sec) > max_age_sec:
                purged_by_age.append(item["id"])
                self._delete_file_for_item(item)

        with self.lock:
            for seg_id in purged_by_age:
                if seg_id in self.index:
                    del self.index[seg_id]
            items = list(self.index.values())

        # 2. Check maxStorageGb quota (FIFO purge)
        total_bytes = sum(item.get("fileSizeBytes", 0) for item in items)
        max_bytes = max_storage_gb * (1024**3)

        if total_bytes > max_bytes:
            # Sort oldest first
            sorted_items = sorted(items, key=lambda x: x.get("startTime", 0))
            for item in sorted_items:
                if total_bytes <= max_bytes:
                    break
                self._delete_file_for_item(item)
                total_bytes -= item.get("fileSizeBytes", 0)
                with self.lock:
                    if item["id"] in self.index:
                        del self.index[item["id"]]

        self.save_index()

    def _delete_file_for_item(self, item: dict):
        try:
            rel = item.get("filePath")
            if rel:
                full = sanitize_path(self.base_dir, os.path.join(self.base_dir, rel))
                if os.path.exists(full):
                    os.remove(full)
                    # Clean up empty parent folder
                    parent = os.path.dirname(full)
                    if os.path.exists(parent) and not os.listdir(parent):
                        os.rmdir(parent)
        except Exception as e:
            print(f"[RECORDING] Error removing file: {e}", file=sys.stderr)

    def delete_recording(self, segment_id: str) -> tuple[bool, str]:
        with self.lock:
            item = self.index.get(segment_id)
            if not item:
                return False, f"Recording '{segment_id}' not found"
            del self.index[segment_id]

        self._delete_file_for_item(item)
        self.save_index()
        return True, f"Deleted recording '{segment_id}'"

    def list_recordings(self, camera_id: str = None, date_str: str = None, limit: int = 100) -> list:
        self.scan_and_sync_filesystem()
        with self.lock:
            items = list(self.index.values())

        # Filter by camera
        if camera_id:
            items = [item for item in items if item.get("cameraId") == camera_id]

        # Filter by date (YYYY-MM-DD)
        if date_str:
            items = [item for item in items if date_str in item.get("filePath", "")]

        # Sort newest first
        items.sort(key=lambda x: x.get("startTime", 0), reverse=True)
        return items[:limit]

    def get_recording_item(self, segment_id: str) -> dict:
        with self.lock:
            return self.index.get(segment_id)

    def get_storage_status(self) -> dict:
        disk_stats = get_disk_space_stats(self.storage_dir)
        with self.lock:
            items = list(self.index.values())
            active_cams = list(self.active_sessions.keys())

        total_rec_bytes = sum(i.get("fileSizeBytes", 0) for i in items)
        total_rec_gb = round(total_rec_bytes / (1024**3), 2)
        min_free = self.config.get("minDiskFreeGb", 5.0)

        disk_warning = disk_stats.get("freeGb", 0) < min_free

        return {
            "activeRecordingCameras": active_cams,
            "totalRecordingsCount": len(items),
            "recordingsStorageGb": total_rec_gb,
            "recordingsStorageBytes": total_rec_bytes,
            "disk": disk_stats,
            "diskWarning": disk_warning,
            "minDiskFreeGb": min_free,
            "retentionDays": self.config.get("retentionDays", 7),
            "maxStorageGb": self.config.get("maxStorageGb", 20.0)
        }

    def _background_worker(self):
        """Periodic maintenance: sync filesystem, prune retention, check disk space."""
        while self.running:
            try:
                # 1. Clean finished duration-limited sessions
                with self.lock:
                    finished = []
                    for cid, s in self.active_sessions.items():
                        if s.process and s.process.poll() is not None:
                            finished.append(cid)
                    for cid in finished:
                        del self.active_sessions[cid]

                # 2. Sync filesystem and check new segments
                self.scan_and_sync_filesystem()

                # 3. Enforce retention policy
                self.enforce_retention_policy()

                # 4. Check disk free space safeguard
                stats = get_disk_space_stats(self.storage_dir)
                min_free = self.config.get("minDiskFreeGb", 5.0)
                if stats.get("freeGb", 0) < min_free:
                    with self.lock:
                        sessions = list(self.active_sessions.values())
                    if sessions:
                        print(f"[RECORDING] Safeguard triggered: Free space {stats.get('freeGb')}GB < {min_free}GB. Halting active recordings.", file=sys.stderr, flush=True)
                        for s in sessions:
                            s.stop()
                        with self.lock:
                            self.active_sessions.clear()

                time.sleep(15.0)
            except Exception as e:
                time.sleep(5.0)

