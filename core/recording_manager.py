"""
CamHub Local Recording & Playback Manager
Manages local video segment recording using FFmpeg with zero-transcode pass-through (-c:v copy),
canonical metadata indexing, unified retention policy delegation, disk space protection,
and verified safe file deletion.
"""

import os
import sys
import time
import glob
import shutil
import threading
import subprocess
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

from core.media_index import (
    sanitize_path,
    get_index_lock,
    read_json_index,
    atomic_write_json_index,
    to_rel_posix_path,
    resolve_camera_identity,
    normalize_recording_entry,
    safe_remove_media_file,
)
from core.storage_manager import CamHubStorageManager

# CamHUB project root directory (parent of core/)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_RECORDINGS_DIR = os.path.join(BASE_DIR, "recordings")

DEFAULT_RECORDING_CONFIG = {
    "enabled": True,
    "storagePath": "recordings",
    "segmentDurationSeconds": 60,
    "retentionDays": 7,
    "maxStorageGb": 20.0,
    "minDiskFreeGb": 5.0,
    "preferredSource": "rtsp",
    "autoRecordCameras": [],
}


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
            "freeBytes": free,
        }
    except Exception as e:
        return {
            "totalGb": 0.0,
            "usedGb": 0.0,
            "freeGb": 0.0,
            "totalBytes": 0,
            "usedBytes": 0,
            "freeBytes": 0,
            "error": str(e),
        }


class RecordingSession:
    """Manages an active FFmpeg recording process for a camera."""

    def __init__(
        self,
        camera_id: str,
        stream_url: str,
        storage_dir: str,
        mode: str = "continuous",
        segment_dur: int = 60,
        duration_limit: int = 0,
    ):
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
        self.session_dir = os.path.join(self.storage_dir, self.camera_id, self.current_day)
        self.session_prefix: Optional[str] = None
        self.active_file_path: Optional[str] = None

    def is_active(self) -> bool:
        if not self.running:
            return False
        if self.process is not None and self.process.poll() is not None:
            return False
        return True

    def get_active_segment_paths(self) -> List[str]:
        """Return the concrete segment file path(s) currently being written by this active session."""
        if not self.is_active():
            return []

        protected: List[str] = []
        if self.active_file_path:
            protected.append(self.active_file_path)

        if self.session_prefix and os.path.isdir(self.session_dir):
            pattern = os.path.join(self.session_dir, f"{self.session_prefix}*.mp4")
            matches = [p for p in glob.glob(pattern) if os.path.isfile(p)]
            if matches:
                matches.sort(key=lambda p: (os.path.getmtime(p), p))
                # Always protect the newest segment being written by FFmpeg, plus any segment
                # touched within the last 5 seconds during segment rotation.
                now = time.time()
                protected.append(matches[-1])
                for m_path in matches[:-1]:
                    try:
                        if (now - os.path.getmtime(m_path)) <= 5.0:
                            protected.append(m_path)
                    except OSError:
                        pass
            else:
                protected.append(self.session_dir)
        elif not protected and os.path.isdir(self.session_dir):
            # Fallback if session started externally/mocked without session_prefix:
            # protect newest MP4 in session_dir or session_dir if none exists yet.
            matches = [p for p in glob.glob(os.path.join(self.session_dir, "*.mp4")) if os.path.isfile(p)]
            if matches:
                matches.sort(key=lambda p: (os.path.getmtime(p), p))
                protected.append(matches[-1])
            else:
                protected.append(self.session_dir)

        return protected

    def start(self) -> tuple[bool, str]:
        self.current_day = datetime.now().strftime("%Y-%m-%d")
        self.session_dir = os.path.join(self.storage_dir, self.camera_id, self.current_day)
        os.makedirs(self.session_dir, exist_ok=True)

        prefix = "motion" if self.mode == "motion" else "rec"
        start_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_prefix = f"{self.camera_id}_{prefix}_{start_ts}_seg"
        pattern = os.path.join(self.session_dir, f"{self.session_prefix}%03d.mp4")

        is_rtsp = self.stream_url.lower().startswith("rtsp://")

        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "warning"]
        if is_rtsp:
            cmd.extend(["-rtsp_transport", "tcp", "-timeout", "5000000"])
        else:
            cmd.extend(["-timeout", "5000000"])
        cmd.extend(["-i", self.stream_url])

        if self.duration_limit > 0:
            cmd.extend(["-t", str(self.duration_limit)])

        if is_rtsp:
            cmd.extend(["-c:v", "copy"])
        else:
            cmd.extend([
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-tune",
                "zerolatency",
                "-pix_fmt",
                "yuv420p",
            ])

        cmd.extend([
            "-an",
            "-f",
            "segment",
            "-segment_time",
            str(self.segment_duration),
            "-reset_timestamps",
            "1",
            "-segment_format",
            "mp4",
            "-movflags",
            "+faststart",
            pattern,
        ])

        try:
            self.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
            )
            self.pid = self.process.pid
            self.running = True

            time.sleep(0.3)
            ret = self.process.poll()
            if ret is not None:
                err_msg = ""
                try:
                    err_msg = self.process.stderr.read().decode("utf-8", errors="ignore").strip()
                except Exception:
                    pass
                self.running = False
                self.process = None
                return False, f"FFmpeg failed to start (exit code {ret}): {err_msg[:200]}"

            return True, f"Started recording for {self.camera_id} (PID {self.pid})"
        except Exception as e:
            return False, str(e)

    def stop(self):
        self.running = False
        if self.process:
            try:
                if self.process.stdin:
                    try:
                        self.process.stdin.write(b"q\n")
                        self.process.stdin.flush()
                        self.process.wait(timeout=2.0)
                    except Exception:
                        pass

                if self.process and self.process.poll() is None:
                    if sys.platform == "win32":
                        subprocess.run(
                            ["taskkill", "/F", "/T", "/PID", str(self.process.pid)],
                            capture_output=True,
                        )
                    else:
                        self.process.terminate()
                        try:
                            self.process.wait(timeout=1.0)
                        except Exception:
                            self.process.kill()
            except Exception:
                pass
            finally:
                for stream_attr in ("stdin", "stdout", "stderr"):
                    st = getattr(self.process, stream_attr, None)
                    if st:
                        try:
                            st.close()
                        except Exception:
                            pass
            self.process = None
            self.pid = None


class RecordingManager:
    """Fleet-wide recording, playback, unified retention delegation, and canonical metadata index manager."""

    def __init__(self, config_provider, base_dir: str = None, storage_manager: Optional[CamHubStorageManager] = None):
        self.config_provider = config_provider
        self.base_dir = os.path.abspath(base_dir or BASE_DIR)
        self.active_sessions: Dict[str, RecordingSession] = {}
        self.index: Dict[str, Dict[str, Any]] = {}
        self.running = False
        self.worker_thread = None
        self._index_mtime: float = 0.0

        cfg = (self.config_provider() or {}).get("recording", {})
        self.config = dict(DEFAULT_RECORDING_CONFIG)
        self.config.update(cfg)

        rel_storage = self.config.get("storagePath", "recordings")
        self.storage_dir = os.path.abspath(os.path.join(self.base_dir, rel_storage))
        os.makedirs(self.storage_dir, exist_ok=True)
        self.index_file = os.path.join(self.storage_dir, "recordings_index.json")
        self.lock = get_index_lock(self.index_file)

        if storage_manager is not None:
            self.storage_manager = storage_manager
            self.storage_manager.attach_managers(recording_manager=self)
        else:
            self.storage_manager = CamHubStorageManager(
                self.config_provider,
                base_dir=self.base_dir,
                recording_manager=self,
            )

        self.load_index()
        self.scan_and_sync_filesystem()

    def _configured_camera_ids(self) -> List[str]:
        cfg = self.config_provider() or {}
        return [c.get("id") for c in cfg.get("cameras", []) if c.get("id")]

    def start(self):
        with self.lock:
            if self.running:
                return
            self.running = True
            self.worker_thread = threading.Thread(target=self._background_worker, daemon=True, name="RecordingWorker")
            self.worker_thread.start()
            print(f"[RECORDING] Recording Manager active. Storage: {self.storage_dir}", flush=True)

        self._check_auto_record()

    def stop(self):
        with self.lock:
            self.running = False
            sessions = list(self.active_sessions.values())
            self.active_sessions.clear()
        for s in sessions:
            s.stop()
        self.save_index()

    def _check_auto_record(self):
        cfg = self.config_provider() or {}
        rec_cfg = cfg.get("recording", {})
        auto_cams = rec_cfg.get("autoRecordCameras", [])
        for cam in cfg.get("cameras", []):
            cid = cam.get("id")
            if cid in auto_cams and cid not in self.active_sessions:
                self.start_recording(cid, mode="continuous")

    def _get_disk_index_mtime(self) -> float:
        try:
            return os.path.getmtime(self.index_file) if os.path.exists(self.index_file) else 0.0
        except OSError:
            return 0.0

    def _normalize_in_memory_locked(self) -> bool:
        known_cids = self._configured_camera_ids()
        normalized: Dict[str, Dict[str, Any]] = {}
        changed_any = False
        for seg_id, raw_item in list(self.index.items()):
            entry, changed = normalize_recording_entry(
                seg_id,
                raw_item,
                base_dir=self.base_dir,
                storage_dir=self.storage_dir,
                configured_camera_ids=known_cids,
            )
            if entry is not None:
                normalized[entry["id"]] = entry
                if changed or entry["id"] != seg_id:
                    changed_any = True
            else:
                changed_any = True
        self.index = normalized
        return changed_any

    def _sync_from_disk_if_changed_locked(self) -> None:
        disk_mtime = self._get_disk_index_mtime()
        if disk_mtime > 0 and disk_mtime != self._index_mtime:
            self.load_index()
        else:
            self._normalize_in_memory_locked()

    def load_index(self):
        with self.lock:
            if os.path.exists(self.index_file):
                raw = read_json_index(self.index_file)
                self.index = raw
                migrated = self._normalize_in_memory_locked()
                self._index_mtime = self._get_disk_index_mtime()
                if migrated:
                    self.save_index()
            else:
                self.index = {}
                self._index_mtime = 0.0

    def save_index(self):
        with self.lock:
            self._normalize_in_memory_locked()
            try:
                atomic_write_json_index(self.index_file, self.index)
                self._index_mtime = self._get_disk_index_mtime()
            except Exception as e:
                print(f"[RECORDING] Error saving index: {e}", file=sys.stderr)

    def get_raw_or_synced_index(self) -> Dict[str, Dict[str, Any]]:
        """Used by CamHubStorageManager during reconciliation to respect external disk changes or memory updates."""
        with self.lock:
            disk_mtime = self._get_disk_index_mtime()
            if disk_mtime > 0 and disk_mtime != self._index_mtime:
                return read_json_index(self.index_file)
            return dict(self.index)

    def get_synchronized_index_copy(self) -> Dict[str, Dict[str, Any]]:
        with self.lock:
            self._sync_from_disk_if_changed_locked()
            return {k: dict(v) for k, v in self.index.items()}

    def replace_synchronized_index(self, new_index: Dict[str, Dict[str, Any]]) -> None:
        with self.lock:
            self.index = {k: dict(v) for k, v in new_index.items()}
            self._normalize_in_memory_locked()
            atomic_write_json_index(self.index_file, self.index)
            self._index_mtime = self._get_disk_index_mtime()

    def get_active_camera_ids(self) -> List[str]:
        with self.lock:
            return [cid for cid, s in self.active_sessions.items() if s.is_active()]

    def get_active_recording_paths(self) -> List[str]:
        """Return concrete file paths of segments currently being recorded across all active sessions."""
        paths: List[str] = []
        with self.lock:
            sessions = list(self.active_sessions.values())
        for s in sessions:
            paths.extend(s.get_active_segment_paths())
        return paths

    def _find_session_for_file_locked(self, norm_path: str) -> Tuple[Optional[RecordingSession], bool]:
        norm_cmp = os.path.normcase(os.path.realpath(norm_path))
        for s in self.active_sessions.values():
            if not s.is_active():
                continue
            active_segs = {
                os.path.normcase(os.path.realpath(os.path.abspath(p)))
                for p in s.get_active_segment_paths()
                if os.path.isfile(p)
            }
            if norm_cmp in active_segs:
                return s, True
            cam_dir = os.path.normcase(os.path.realpath(os.path.abspath(os.path.join(s.storage_dir, s.camera_id))))
            try:
                if os.path.normcase(os.path.commonpath([cam_dir, norm_cmp])) == cam_dir:
                    return s, False
            except ValueError:
                continue
        return None, False

    def scan_and_sync_filesystem(self):
        """Discovers recording files on disk, repairs camera identities, and cleans stale ghost entries."""
        with self.lock:
            self._sync_from_disk_if_changed_locked()
            known_cids = self._configured_camera_ids()

            mp4_files = sorted(glob.iglob(os.path.join(self.storage_dir, "**", "*.mp4"), recursive=True))
            existing_paths = {item.get("filePath"): seg_id for seg_id, item in self.index.items() if item.get("filePath")}

            for filepath in mp4_files:
                if not os.path.isfile(filepath):
                    continue
                norm_path = os.path.normpath(filepath)
                try:
                    rel_path = to_rel_posix_path(self.base_dir, norm_path)
                except ValueError:
                    continue
                if not rel_path:
                    continue

                filename = os.path.basename(norm_path)
                session, is_active_seg = self._find_session_for_file_locked(norm_path)
                session_cid = session.camera_id if session else None

                cam_id, authoritative_dir_cid, date_str = resolve_camera_identity(
                    rel_path,
                    base_dir=self.base_dir,
                    storage_dir=self.storage_dir,
                    session_camera_id=session_cid,
                    configured_camera_ids=known_cids,
                )

                try:
                    stat = os.stat(norm_path)
                    size = stat.st_size
                    mtime = stat.st_mtime
                    ctime = stat.st_ctime
                except OSError:
                    continue

                if not date_str:
                    date_str = datetime.fromtimestamp(ctime).strftime("%Y-%m-%d")

                if rel_path not in existing_paths:
                    seg_id = os.path.splitext(filename)[0]
                    if seg_id in self.index and self.index[seg_id].get("filePath") != rel_path:
                        seg_id = f"{cam_id}_{seg_id}"

                    mode = (
                        session.mode
                        if session
                        else ("motion" if "motion" in filename.lower() else "continuous")
                    )
                    status = (
                        "recording"
                        if is_active_seg
                        else ("completed" if size > 1024 else "corrupt")
                    )
                    self.index[seg_id] = {
                        "id": seg_id,
                        "cameraId": cam_id,
                        "date": date_str,
                        "fileName": filename,
                        "filePath": rel_path,
                        "fileSizeBytes": size,
                        "startTime": int(ctime * 1000),
                        "endTime": int(max(ctime, mtime) * 1000),
                        "durationSeconds": round(max(0.0, mtime - ctime), 1),
                        "status": status,
                        "mode": mode,
                        "format": "mp4",
                    }
                    existing_paths[rel_path] = seg_id
                else:
                    seg_id = existing_paths[rel_path]
                    entry = self.index[seg_id]
                    if authoritative_dir_cid and entry.get("cameraId") != authoritative_dir_cid:
                        entry["cameraId"] = authoritative_dir_cid
                    if not entry.get("date") and date_str:
                        entry["date"] = date_str
                    if entry.get("fileSizeBytes") != size:
                        entry["fileSizeBytes"] = size
                        entry["endTime"] = int(max(entry.get("startTime", 0) / 1000.0, mtime) * 1000)
                        entry["durationSeconds"] = round(max(0.0, mtime - (entry["startTime"] / 1000.0)), 1)
                    if is_active_seg:
                        entry["status"] = "recording"
                    elif entry.get("status") == "recording" or size > 1024:
                        entry["status"] = "completed" if size > 1024 else entry.get("status", "completed")

            # Remove entries whose physical files were deleted from disk
            to_remove = []
            for seg_id, item in self.index.items():
                rel_p = item.get("filePath", "")
                if not rel_p:
                    to_remove.append(seg_id)
                    continue
                full_path = os.path.join(self.base_dir, rel_p)
                if not os.path.isfile(full_path):
                    to_remove.append(seg_id)
            for seg_id in to_remove:
                del self.index[seg_id]

            self.save_index()

    def get_stream_url_for_camera(self, cid: str) -> str:
        """Determines best RTSP or MJPEG URL for recording without disturbing live view."""
        cfg = self.config_provider() or {}
        cam = next((c for c in cfg.get("cameras", []) if c.get("id") == cid or cid in c.get("aliases", [])), None)
        if not cam:
            return ""

        canonical_cid = cam.get("id", cid)
        pref = self.config.get("preferredSource", "rtsp")

        if pref == "rtsp":
            rtsp_port = cam.get("rtspPort")
            if rtsp_port:
                return f"rtsp://127.0.0.1:{rtsp_port}/live/ch0"

            if cam.get("rtspUrl"):
                return cam["rtspUrl"]

            if cam.get("type") == "okam":
                rtsp_cmd = cam.get("cmd", "")
                if "--rtsp" in rtsp_cmd:
                    try:
                        idx = rtsp_cmd.index("--rtsp")
                        return rtsp_cmd[idx + 6:].strip().strip('"').strip("'")
                    except Exception:
                        pass
            elif cam.get("fastRtsCmd"):
                try:
                    cmd_str = cam["fastRtsCmd"]
                    if "--rtsp" in cmd_str:
                        idx = cmd_str.index("--rtsp")
                        return cmd_str[idx + 6:].strip().strip('"').strip("'")
                except Exception:
                    pass

        port = cam.get("port", 8080)
        stream_path = cam.get("streamPath") or (
            f"/api/cameras/{canonical_cid}/stream.mjpg" if cam.get("type") == "okam" else "/stream.mjpg"
        )
        return f"http://127.0.0.1:{port}{stream_path}"

    def start_recording(self, cid: str, mode: str = "manual", duration: int = 0) -> tuple[bool, str]:
        stats = get_disk_space_stats(self.storage_dir)
        min_free = self.config.get("minDiskFreeGb", 5.0)
        if stats.get("freeGb", 0) < min_free:
            return (
                False,
                f"Disk space critically low ({stats.get('freeGb')} GB free < {min_free} GB threshold). Recording halted.",
            )

        cfg = self.config_provider() or {}
        cam = next((c for c in cfg.get("cameras", []) if c.get("id") == cid or cid in c.get("aliases", [])), None)
        if cam and cam.get("id"):
            cid = cam["id"]

        with self.lock:
            if cid in self.active_sessions:
                s = self.active_sessions[cid]
                if s.is_active():
                    return True, f"Recording already active for '{cid}' (PID {s.pid})"
                else:
                    del self.active_sessions[cid]

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
            duration_limit=duration,
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

    def enforce_retention_policy(self) -> Dict[str, Any]:
        """
        Delegates to CamHubStorageManager.evaluate_retention(dry_run=False) so that all retention
        enforcement flows through a single unified policy engine with active recording & playback protection.
        """
        return self.storage_manager.evaluate_retention(dry_run=False)

    def delete_recording(self, segment_id: str) -> tuple[bool, str]:
        """
        Safely delete a recording segment:
          1. Rejects deletion if protected by active recording or active playback/download lock.
          2. Deletes physical file first via verified safe helper.
          3. Removes metadata ONLY after physical file deletion succeeds or file is confirmed absent.
        """
        with self.lock:
            self._sync_from_disk_if_changed_locked()
            item = self.index.get(segment_id)
            if not item:
                return False, f"Recording '{segment_id}' not found"

            rel_path = item.get("filePath") or item.get("path") or ""
            if not rel_path:
                return False, f"Recording '{segment_id}' has an invalid empty file path"

            full_path = os.path.join(self.base_dir, rel_path)
            if self.storage_manager.is_file_protected(full_path, rel_path, item):
                return False, f"Recording '{segment_id}' is protected by an active recording or playback lock"

            can_unindex, _, err = safe_remove_media_file(self.base_dir, self.storage_dir, rel_path)
            if not can_unindex:
                return False, f"Failed to delete recording file for '{segment_id}': {err}"

            del self.index[segment_id]
            self.save_index()
            return True, f"Deleted recording '{segment_id}'"

    def list_recordings(self, camera_id: str = None, date_str: str = None, limit: int = 100) -> list:
        self.scan_and_sync_filesystem()
        with self.lock:
            items = list(self.index.values())

        if camera_id:
            items = [item for item in items if item.get("cameraId") == camera_id]

        if date_str:
            items = [
                item
                for item in items
                if item.get("date") == date_str or date_str in item.get("filePath", "")
            ]

        items.sort(key=lambda x: x.get("startTime", 0), reverse=True)
        return items[:limit]

    def get_recording_item(self, segment_id: str) -> Optional[dict]:
        with self.lock:
            self._sync_from_disk_if_changed_locked()
            item = self.index.get(segment_id)
            return dict(item) if item else None

    def get_storage_status(self) -> dict:
        disk_stats = get_disk_space_stats(self.storage_dir)
        with self.lock:
            self._sync_from_disk_if_changed_locked()
            items = list(self.index.values())
            active_cams = [cid for cid, s in self.active_sessions.items() if s.is_active()]

        total_rec_bytes = sum(int(i.get("fileSizeBytes", 0) or 0) for i in items)
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
            "maxStorageGb": self.config.get("maxStorageGb", 20.0),
        }

    def _background_worker(self):
        """Periodic maintenance: sync filesystem, enforce unified retention, check disk space."""
        while self.running:
            try:
                with self.lock:
                    finished = [cid for cid, s in self.active_sessions.items() if not s.is_active()]
                    for cid in finished:
                        self.active_sessions[cid].stop()
                        del self.active_sessions[cid]

                self.scan_and_sync_filesystem()
                self.enforce_retention_policy()

                stats = get_disk_space_stats(self.storage_dir)
                min_free = self.config.get("minDiskFreeGb", 5.0)
                if stats.get("freeGb", 0) < min_free:
                    with self.lock:
                        sessions = list(self.active_sessions.values())
                        self.active_sessions.clear()
                    if sessions:
                        print(
                            f"[RECORDING] Safeguard triggered: Free space {stats.get('freeGb')}GB < {min_free}GB. Halting active recordings.",
                            file=sys.stderr,
                            flush=True,
                        )
                        for s in sessions:
                            s.stop()

                time.sleep(15.0)
            except Exception:
                time.sleep(5.0)
