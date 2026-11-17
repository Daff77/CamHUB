"""
CamHub Storage Manager
Comprehensive disk space monitoring, growth trend forecasting, multi-tier threshold alerts (80%, 90%, 95%),
single unified retention enforcement with dry-run support, active recording/playback file protection,
and idempotent self-healing index reconciliation using the canonical media metadata schema.
"""

import os
import time
import glob
import shutil
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple, Set

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

# Base project directory
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULT_STORAGE_CONFIG = {
    "enabled": True,
    "checkIntervalSeconds": 60.0,
    "warningThresholdPercent": 80.0,
    "criticalThresholdPercent": 90.0,
    "emergencyThresholdPercent": 95.0,
    "minDiskFreeGb": 5.0,
    "retention": {
        "recordings": {
            "maxAgeDays": 7,
            "maxStorageGb": 20.0,
            "protectActiveRecordings": True,
            "protectActivePlayback": True,
        },
        "events": {
            "maxAgeDays": 7,
            "maxStorageMb": 1000.0,
        },
        "tempFiles": {
            "maxAgeHours": 2.0,
        },
    },
    "cameras": {},
}


def get_disk_usage_stats(path: str = ".") -> Dict[str, Any]:
    """Retrieve filesystem disk usage metrics."""
    try:
        total, used, free = shutil.disk_usage(path)
        used_pct = round((used / total) * 100.0, 1) if total > 0 else 0.0
        free_pct = round((free / total) * 100.0, 1) if total > 0 else 0.0
        return {
            "totalBytes": total,
            "usedBytes": used,
            "freeBytes": free,
            "totalGb": round(total / (1024**3), 2),
            "usedGb": round(used / (1024**3), 2),
            "freeGb": round(free / (1024**3), 2),
            "usedPercent": used_pct,
            "freePercent": free_pct,
        }
    except Exception as e:
        return {
            "error": str(e),
            "totalBytes": 0,
            "usedBytes": 0,
            "freeBytes": 0,
            "totalGb": 0.0,
            "usedGb": 0.0,
            "freeGb": 0.0,
            "usedPercent": 0.0,
            "freePercent": 0.0,
        }


class PlaybackLockManager:
    """
    Tracks active playback/download sessions and prevents active files from being pruned.
    Supports both time-bounded leases (for HTTP 206 Range scrubbing) and active stream refcounts
    (so slow or long downloads remain locked for the entire transfer duration).
    """

    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = os.path.abspath(base_dir) if base_dir else None
        self._locks: Dict[str, float] = {}          # caller_key -> expiration_time
        self._norm_locks: Dict[str, float] = {}     # canonical_key -> expiration_time
        self._active_streams: Dict[str, int] = {}   # canonical_key -> open transfer count
        self._stream_keys: Dict[str, str] = {}      # canonical_key -> display caller_key
        self._lock = threading.RLock()

    def _canonical_key(self, file_key: str) -> str:
        if not file_key:
            return ""
        raw = file_key.strip()
        if self.base_dir:
            candidate = raw if os.path.isabs(raw) else os.path.join(self.base_dir, raw)
            return os.path.normcase(os.path.realpath(os.path.abspath(candidate)))
        if os.path.isabs(raw):
            return os.path.normcase(os.path.realpath(os.path.abspath(raw)))
        return raw.replace("\\", "/").lstrip("./")

    def acquire(self, file_key: str, lease_seconds: float = 300.0) -> None:
        if not file_key:
            return
        exp = time.time() + max(0.01, float(lease_seconds))
        ckey = self._canonical_key(file_key)
        with self._lock:
            self._locks[file_key] = max(exp, self._locks.get(file_key, 0.0))
            if ckey:
                self._norm_locks[ckey] = max(exp, self._norm_locks.get(ckey, 0.0))

    def renew(self, file_key: str, lease_seconds: float = 300.0) -> None:
        self.acquire(file_key, lease_seconds=lease_seconds)

    def begin_transfer(self, file_key: str, lease_seconds: float = 300.0) -> str:
        """Mark an active HTTP stream/download transfer in progress and acquire a lease."""
        ckey = self._canonical_key(file_key)
        with self._lock:
            self.acquire(file_key, lease_seconds=lease_seconds)
            if ckey:
                self._active_streams[ckey] = self._active_streams.get(ckey, 0) + 1
                self._stream_keys[ckey] = file_key
        return ckey

    def end_transfer(self, file_key: str, grace_lease_seconds: float = 60.0) -> None:
        """Complete an active transfer, preserving a short grace lease for HTML5 video Range seeks."""
        ckey = self._canonical_key(file_key)
        with self._lock:
            if ckey and ckey in self._active_streams:
                remaining = self._active_streams[ckey] - 1
                if remaining <= 0:
                    self._active_streams.pop(ckey, None)
                    self._stream_keys.pop(ckey, None)
                else:
                    self._active_streams[ckey] = remaining
            if grace_lease_seconds > 0:
                exp = time.time() + float(grace_lease_seconds)
                self._locks[file_key] = max(exp, self._locks.get(file_key, 0.0))
                if ckey:
                    self._norm_locks[ckey] = max(exp, self._norm_locks.get(ckey, 0.0))

    def release(self, file_key: str) -> None:
        ckey = self._canonical_key(file_key)
        with self._lock:
            self._locks.pop(file_key, None)
            if ckey:
                self._norm_locks.pop(ckey, None)
                self._active_streams.pop(ckey, None)
                self._stream_keys.pop(ckey, None)
                # Also remove any alias keys that normalize to the same canonical path
                stale_aliases = [k for k in self._locks if self._canonical_key(k) == ckey]
                for k in stale_aliases:
                    self._locks.pop(k, None)

    def _prune_expired_locked(self, now: float) -> None:
        self._locks = {k: exp for k, exp in self._locks.items() if exp > now}
        self._norm_locks = {k: exp for k, exp in self._norm_locks.items() if exp > now}

    def is_locked(self, file_key: str) -> bool:
        if not file_key:
            return False
        now = time.time()
        ckey = self._canonical_key(file_key)
        with self._lock:
            self._prune_expired_locked(now)
            if ckey and self._active_streams.get(ckey, 0) > 0:
                return True
            if file_key in self._locks:
                return True
            if ckey and ckey in self._norm_locks:
                return True
            return False

    def is_path_locked(self, full_path: str = "", rel_path: str = "", item_id: str = "") -> bool:
        """Check lock status across full path, relative path, and segment ID."""
        for candidate in (full_path, rel_path, item_id):
            if candidate and self.is_locked(candidate):
                return True
        return False

    def get_active_locks(self) -> List[str]:
        now = time.time()
        with self._lock:
            self._prune_expired_locked(now)
            result = list(self._locks.keys())
            for ckey, cnt in self._active_streams.items():
                if cnt > 0:
                    disp = self._stream_keys.get(ckey, ckey)
                    if disp not in result:
                        result.append(disp)
            return result


class CamHubStorageManager:
    """
    Central storage supervisor for CamHUB.
    Monitors host storage, forecasts capacity depletion, enforces the single unified retention policy,
    cleans corrupted/temporary files, reconciles indices idempotently, and protects active files.
    """

    def __init__(
        self,
        config_provider,
        base_dir: str = None,
        recording_manager=None,
        motion_service=None,
    ):
        self.config_provider = config_provider
        self.base_dir = os.path.abspath(base_dir or BASE_DIR)
        self.recordings_dir = os.path.join(self.base_dir, "recordings")
        self.events_dir = os.path.join(self.base_dir, "events")
        self.playback_locks = PlaybackLockManager(base_dir=self.base_dir)
        self.recording_manager = recording_manager
        self.motion_service = motion_service

        self.lock = threading.RLock()
        self.running = False
        self.worker_thread = None

        # Growth trend tracking (rolling window of time -> total CamHub bytes)
        self.history = []  # list of (timestamp, camhub_bytes, free_bytes)
        self.last_check_time = 0.0

        # Current alert status
        self.alert_level = "NORMAL"
        self.alert_message = "Storage operating within healthy parameters."

    def attach_managers(self, recording_manager=None, motion_service=None) -> None:
        if recording_manager is not None:
            self.recording_manager = recording_manager
            if getattr(recording_manager, "storage_dir", None):
                self.recordings_dir = recording_manager.storage_dir
        if motion_service is not None:
            self.motion_service = motion_service
            if getattr(motion_service, "storage_dir", None):
                self.events_dir = motion_service.storage_dir

    def _configured_camera_ids(self) -> List[str]:
        full_cfg = self.config_provider() or {}
        ids = []
        for cam in full_cfg.get("cameras", []):
            cid = cam.get("id")
            if cid:
                ids.append(cid)
        return ids

    def get_config(self) -> Dict[str, Any]:
        """Merge user config with defaults, unifying storageManagement and recording retention settings."""
        full_cfg = self.config_provider() or {}
        rec_cfg = full_cfg.get("recording", {})
        evt_cfg = full_cfg.get("motionDetection", {})
        user_cfg = full_cfg.get("storageManagement", {})

        merged_rec_ret = dict(DEFAULT_STORAGE_CONFIG["retention"]["recordings"])
        if "retentionDays" in rec_cfg:
            merged_rec_ret["maxAgeDays"] = rec_cfg["retentionDays"]
        if "maxStorageGb" in rec_cfg:
            merged_rec_ret["maxStorageGb"] = rec_cfg["maxStorageGb"]

        merged_evt_ret = dict(DEFAULT_STORAGE_CONFIG["retention"]["events"])
        if "retentionDays" in evt_cfg:
            merged_evt_ret["maxAgeDays"] = evt_cfg["retentionDays"]
        if "maxStorageMb" in evt_cfg:
            merged_evt_ret["maxStorageMb"] = evt_cfg["maxStorageMb"]

        merged_temp_ret = dict(DEFAULT_STORAGE_CONFIG["retention"]["tempFiles"])

        user_ret = user_cfg.get("retention", {})
        if isinstance(user_ret.get("recordings"), dict):
            merged_rec_ret.update(user_ret["recordings"])
        if isinstance(user_ret.get("events"), dict):
            merged_evt_ret.update(user_ret["events"])
        if isinstance(user_ret.get("tempFiles"), dict):
            merged_temp_ret.update(user_ret["tempFiles"])

        cfg = dict(DEFAULT_STORAGE_CONFIG)
        for k, v in user_cfg.items():
            if k != "retention":
                cfg[k] = v
        cfg["retention"] = {
            "recordings": merged_rec_ret,
            "events": merged_evt_ret,
            "tempFiles": merged_temp_ret,
        }
        return cfg

    def start(self):
        """Start the background maintenance worker."""
        with self.lock:
            if self.running:
                return
            self.running = True
            self.worker_thread = threading.Thread(
                target=self._maintenance_loop,
                name="CamHub-StorageWorker",
                daemon=True,
            )
            self.worker_thread.start()
            print(f"[STORAGE] Storage Manager active. Monitoring volume: {self.base_dir}", flush=True)

    def stop(self):
        """Stop background worker cleanly."""
        with self.lock:
            self.running = False

    def scan_location(self, target_dir: str, extension: str) -> Dict[str, Any]:
        """
        Scan a data directory (e.g. recordings or events) for file count, sizes,
        camera breakdowns, and date ranges.
        """
        if not os.path.exists(target_dir):
            return {
                "fileCount": 0,
                "totalBytes": 0,
                "totalMb": 0.0,
                "totalGb": 0.0,
                "cameras": {},
                "oldestTimestamp": None,
                "newestTimestamp": None,
            }

        total_bytes = 0
        file_count = 0
        cam_breakdown = {}
        oldest_time = None
        newest_time = None
        known_cids = self._configured_camera_ids()

        pattern = os.path.join(target_dir, "**", f"*{extension}")
        for filepath in glob.iglob(pattern, recursive=True):
            try:
                st = os.stat(filepath)
                sz = st.st_size
                mtime = st.st_mtime

                total_bytes += sz
                file_count += 1

                if oldest_time is None or mtime < oldest_time:
                    oldest_time = mtime
                if newest_time is None or mtime > newest_time:
                    newest_time = mtime

                cam_id, _, _ = resolve_camera_identity(
                    filepath,
                    base_dir=self.base_dir,
                    storage_dir=target_dir,
                    configured_camera_ids=known_cids,
                )

                if cam_id not in cam_breakdown:
                    cam_breakdown[cam_id] = {"count": 0, "bytes": 0, "mb": 0.0}
                cam_breakdown[cam_id]["count"] += 1
                cam_breakdown[cam_id]["bytes"] += sz
                cam_breakdown[cam_id]["mb"] = round(cam_breakdown[cam_id]["bytes"] / (1024 * 1024), 2)
            except OSError:
                continue

        return {
            "fileCount": file_count,
            "totalBytes": total_bytes,
            "totalMb": round(total_bytes / (1024 * 1024), 2),
            "totalGb": round(total_bytes / (1024**3), 3),
            "cameras": cam_breakdown,
            "oldestTime": datetime.fromtimestamp(oldest_time).isoformat() if oldest_time else None,
            "newestTime": datetime.fromtimestamp(newest_time).isoformat() if newest_time else None,
        }

    def scan_temp_and_corrupt(self) -> Dict[str, Any]:
        """Scan for temporary files (.tmp, .part) and 0-byte corrupted files."""
        temp_files = []
        corrupted_files = []
        total_temp_bytes = 0

        for root in [self.recordings_dir, self.events_dir]:
            if not os.path.exists(root):
                continue
            for entry in glob.iglob(os.path.join(root, "**", "*"), recursive=True):
                if not os.path.isfile(entry):
                    continue
                filename = os.path.basename(entry)
                if ".idxtmp." in filename:
                    continue
                try:
                    st = os.stat(entry)
                    sz = st.st_size
                    mtime = st.st_mtime
                    age_hours = (time.time() - mtime) / 3600.0

                    if ".tmp" in filename or filename.endswith(".part"):
                        temp_files.append({
                            "path": os.path.relpath(entry, self.base_dir).replace("\\", "/"),
                            "sizeBytes": sz,
                            "ageHours": round(age_hours, 1),
                        })
                        total_temp_bytes += sz
                    elif sz == 0 and age_hours > 0.16:
                        if filename.endswith(".mp4") or filename.endswith(".jpg"):
                            corrupted_files.append({
                                "path": os.path.relpath(entry, self.base_dir).replace("\\", "/"),
                                "reason": "0-byte empty file",
                                "ageHours": round(age_hours, 1),
                            })
                except OSError:
                    continue

        return {
            "tempFilesCount": len(temp_files),
            "tempTotalBytes": total_temp_bytes,
            "tempTotalMb": round(total_temp_bytes / (1024 * 1024), 2),
            "tempFiles": temp_files,
            "corruptedFilesCount": len(corrupted_files),
            "corruptedFiles": corrupted_files,
        }

    def get_storage_overview(self) -> Dict[str, Any]:
        """Comprehensive storage audit overview and metrics."""
        disk = get_disk_usage_stats(self.base_dir)
        rec = self.scan_location(self.recordings_dir, ".mp4")
        evt = self.scan_location(self.events_dir, ".jpg")
        temp = self.scan_temp_and_corrupt()

        camhub_bytes = rec["totalBytes"] + evt["totalBytes"] + temp["tempTotalBytes"]
        camhub_mb = round(camhub_bytes / (1024 * 1024), 2)
        camhub_gb = round(camhub_bytes / (1024**3), 3)

        now = time.time()
        with self.lock:
            self.history.append((now, camhub_bytes, disk.get("freeBytes", 0)))
            cutoff = now - 86400
            self.history = [h for h in self.history if h[0] >= cutoff]

        growth_rate_mb_per_hour = self._calculate_growth_rate_mb_hour()
        time_remaining = self._estimate_time_remaining(disk.get("freeBytes", 0), growth_rate_mb_per_hour)

        cfg = self.get_config()
        warn_pct = cfg.get("warningThresholdPercent", 80.0)
        crit_pct = cfg.get("criticalThresholdPercent", 90.0)
        emerg_pct = cfg.get("emergencyThresholdPercent", 95.0)
        min_free_gb = cfg.get("minDiskFreeGb", 5.0)

        used_pct = disk.get("usedPercent", 0.0)
        free_gb = disk.get("freeGb", 0.0)

        alert_level = "NORMAL"
        alert_msg = "Storage operating within healthy parameters."

        if used_pct >= emerg_pct or free_gb < (min_free_gb / 2.0):
            alert_level = "EMERGENCY"
            alert_msg = f"EMERGENCY: Disk usage at {used_pct}% ({free_gb} GB free). Recordings risk immediate termination."
        elif used_pct >= crit_pct or free_gb < min_free_gb:
            alert_level = "CRITICAL"
            alert_msg = f"CRITICAL: Disk usage at {used_pct}% ({free_gb} GB free). Proactive retention purge recommended."
        elif used_pct >= warn_pct:
            alert_level = "WARNING"
            alert_msg = f"WARNING: Disk usage exceeds {warn_pct}% (currently {used_pct}%, {free_gb} GB free)."

        with self.lock:
            self.alert_level = alert_level
            self.alert_message = alert_msg

        return {
            "timestamp": int(now * 1000),
            "disk": disk,
            "camhub": {
                "totalBytes": camhub_bytes,
                "totalMb": camhub_mb,
                "totalGb": camhub_gb,
                "percentOfDiskUsed": round((camhub_bytes / max(1, disk.get("usedBytes", 1))) * 100.0, 2),
            },
            "recordings": rec,
            "events": evt,
            "tempAndCorrupt": temp,
            "forecasting": {
                "growthRateMbPerHour": growth_rate_mb_per_hour,
                "growthRateGbPerDay": round((growth_rate_mb_per_hour * 24) / 1024, 2),
                "estimatedHoursRemaining": time_remaining.get("hoursRemaining"),
                "estimatedDaysRemaining": time_remaining.get("daysRemaining"),
                "depletionForecastDate": time_remaining.get("depletionDate"),
                "status": time_remaining.get("status"),
            },
            "alerts": {
                "level": alert_level,
                "message": alert_msg,
                "thresholds": {
                    "warningPercent": warn_pct,
                    "criticalPercent": crit_pct,
                    "emergencyPercent": emerg_pct,
                    "minFreeGb": min_free_gb,
                },
            },
            "activePlaybackLocks": self.playback_locks.get_active_locks(),
        }

    def _calculate_growth_rate_mb_hour(self) -> float:
        with self.lock:
            if len(self.history) < 2:
                return 45.0

            first_t, first_b, _ = self.history[0]
            last_t, last_b, _ = self.history[-1]
            elapsed_sec = last_t - first_t

            if elapsed_sec < 60:
                return 45.0

            delta_bytes = max(0, last_b - first_b)
            rate_bytes_sec = delta_bytes / elapsed_sec
            mb_hour = round((rate_bytes_sec * 3600.0) / (1024 * 1024), 2)
            return max(5.0, mb_hour)

    def _estimate_time_remaining(self, free_bytes: int, growth_rate_mb_hour: float) -> Dict[str, Any]:
        if free_bytes <= 0 or growth_rate_mb_hour <= 0:
            return {"hoursRemaining": 0, "daysRemaining": 0, "depletionDate": None, "status": "Depleted"}

        free_mb = free_bytes / (1024 * 1024)
        hours = round(free_mb / growth_rate_mb_hour, 1)
        days = round(hours / 24.0, 1)

        depletion_date = None
        if hours < 87600:
            depletion_dt = datetime.now() + timedelta(hours=hours)
            depletion_date = depletion_dt.strftime("%Y-%m-%d %H:%M")

        status = "Comfortable"
        if days < 2:
            status = "Imminent"
        elif days < 7:
            status = "Warning"

        return {
            "hoursRemaining": hours,
            "daysRemaining": days,
            "depletionDate": depletion_date,
            "status": status,
        }

    def _collect_active_recording_targets(
        self, explicit_active_files: Optional[List[str]] = None
    ) -> Tuple[Set[str], Set[str], Set[str]]:
        """
        Gather normalized active recording file paths, active session directories (if a directory was supplied),
        and active camera IDs from both explicit caller arguments and any attached RecordingManager.
        """
        active_files_norm: Set[str] = set()
        active_dirs_norm: Set[str] = set()
        active_cam_ids: Set[str] = set()

        raw_candidates: List[str] = list(explicit_active_files or [])
        if self.recording_manager is not None:
            try:
                raw_candidates.extend(self.recording_manager.get_active_recording_paths())
                active_cam_ids.update(self.recording_manager.get_active_camera_ids())
            except Exception:
                pass

        for entry in raw_candidates:
            if not entry or not isinstance(entry, str):
                continue
            abs_p = (
                os.path.realpath(os.path.abspath(entry))
                if os.path.isabs(entry)
                else os.path.realpath(os.path.abspath(os.path.join(self.base_dir, entry)))
            )
            norm_p = os.path.normcase(abs_p)
            if os.path.isdir(abs_p) or not os.path.splitext(abs_p)[1]:
                active_dirs_norm.add(norm_p)
            else:
                active_files_norm.add(norm_p)

        return active_files_norm, active_dirs_norm, active_cam_ids

    def is_file_protected(
        self,
        full_path: str,
        rel_path: str = "",
        item: Optional[Dict[str, Any]] = None,
        active_recording_files: Optional[List[str]] = None,
        protect_recordings: bool = True,
        protect_playback: bool = True,
    ) -> bool:
        """Check whether a recording/media file is protected by active recording or playback/download lock."""
        item_id = (item or {}).get("id") or ""
        if protect_playback and self.playback_locks.is_path_locked(full_path, rel_path, item_id):
            return True

        if protect_recordings:
            active_files, active_dirs, active_cids = self._collect_active_recording_targets(active_recording_files)
            norm_full = os.path.normcase(os.path.realpath(os.path.abspath(full_path)))
            if norm_full in active_files:
                return True
            for d in active_dirs:
                try:
                    if os.path.normcase(os.path.commonpath([d, norm_full])) == d:
                        return True
                except ValueError:
                    continue
            if item and item.get("status") == "recording":
                if not active_cids or item.get("cameraId") in active_cids:
                    return True

        return False

    def _load_normalized_recordings_index(self, rec_index_file: str) -> Tuple[Dict[str, Dict[str, Any]], bool]:
        """Load and migrate recordings_index.json (or attached RecordingManager index) under index lock."""
        known_cids = self._configured_camera_ids()
        if self.recording_manager is not None:
            return self.recording_manager.get_synchronized_index_copy(), False

        raw_index = read_json_index(rec_index_file)
        normalized: Dict[str, Dict[str, Any]] = {}
        migrated = False
        for seg_id, raw_item in raw_index.items():
            entry, changed = normalize_recording_entry(
                seg_id,
                raw_item,
                base_dir=self.base_dir,
                storage_dir=self.recordings_dir,
                configured_camera_ids=known_cids,
            )
            if entry is not None:
                normalized[entry["id"]] = entry
                if changed or entry["id"] != seg_id:
                    migrated = True
            else:
                migrated = True
        return normalized, migrated

    def _persist_recordings_index(self, rec_index_file: str, rec_index: Dict[str, Dict[str, Any]]) -> None:
        if self.recording_manager is not None:
            self.recording_manager.replace_synchronized_index(rec_index)
        else:
            atomic_write_json_index(rec_index_file, rec_index)

    def evaluate_retention(
        self,
        dry_run: bool = True,
        active_recording_files: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Single unified retention policy engine for recordings, events, and temporary/corrupted files.
        - Protects active recording segments and active playback/download files on ALL cleanup paths.
        - Removes metadata ONLY after physical file deletion succeeds or file is confirmed absent.
        - Accurately reports partial failures when OS refuses deletion of a file.
        """
        cfg = self.get_config()
        rec_ret = cfg.get("retention", {}).get("recordings", {})
        evt_ret = cfg.get("retention", {}).get("events", {})
        temp_ret = cfg.get("retention", {}).get("tempFiles", {})

        protect_rec = bool(rec_ret.get("protectActiveRecordings", True))
        protect_play = bool(rec_ret.get("protectActivePlayback", True))
        active_files_norm, active_dirs_norm, active_cids = self._collect_active_recording_targets(active_recording_files)

        def _rec_is_protected(full_p: str, rel_p: str, rec_item: Optional[Dict[str, Any]] = None) -> bool:
            item_id = (rec_item or {}).get("id") or ""
            if protect_play and self.playback_locks.is_path_locked(full_p, rel_p, item_id):
                return True
            if protect_rec:
                norm_full = os.path.normcase(os.path.realpath(os.path.abspath(full_p)))
                if norm_full in active_files_norm:
                    return True
                for d in active_dirs_norm:
                    try:
                        if os.path.normcase(os.path.commonpath([d, norm_full])) == d:
                            return True
                    except ValueError:
                        continue
                if rec_item and rec_item.get("status") == "recording":
                    if not active_cids or rec_item.get("cameraId") in active_cids:
                        return True
            return False

        now = time.time()
        files_to_delete: List[Dict[str, Any]] = []
        bytes_to_free = 0
        protected_skipped_count = 0

        rec_index_file = os.path.join(self.recordings_dir, "recordings_index.json")
        evt_index_file = os.path.join(self.events_dir, "events_index.json")

        rec_lock = get_index_lock(rec_index_file)
        evt_lock = get_index_lock(evt_index_file)

        with rec_lock, evt_lock:
            # -------------------------------------------------------------
            # 1. Recordings Retention (Age & Storage Cap)
            # -------------------------------------------------------------
            rec_index, migrated = self._load_normalized_recordings_index(rec_index_file)
            if migrated and not dry_run:
                self._persist_recordings_index(rec_index_file, rec_index)

            max_rec_age_sec = float(rec_ret.get("maxAgeDays", 7)) * 86400.0
            max_rec_bytes = float(rec_ret.get("maxStorageGb", 20.0)) * (1024**3)

            rec_items = list(rec_index.values())
            rec_items.sort(key=lambda x: x.get("startTime", 0))
            queued_rec_ids: Set[str] = set()

            for item in rec_items:
                rel_path = item.get("filePath", "")
                if not rel_path:
                    continue
                full = os.path.join(self.base_dir, rel_path)
                sz = int(item.get("fileSizeBytes", 0) or 0)
                start_sec = float(item.get("startTime", 0) or 0) / 1000.0

                if (now - start_sec) > max_rec_age_sec:
                    if _rec_is_protected(full, rel_path, item):
                        protected_skipped_count += 1
                        continue
                    files_to_delete.append({
                        "type": "recording",
                        "id": item.get("id"),
                        "path": rel_path,
                        "filePath": rel_path,
                        "fullPath": full,
                        "sizeBytes": sz,
                        "reason": f"Exceeded max age of {rec_ret.get('maxAgeDays')} days",
                    })
                    queued_rec_ids.add(item["id"])
                    bytes_to_free += sz

            remaining_rec_bytes = sum(int(i.get("fileSizeBytes", 0) or 0) for i in rec_items) - sum(
                f["sizeBytes"] for f in files_to_delete if f["type"] == "recording"
            )
            if remaining_rec_bytes > max_rec_bytes:
                for item in rec_items:
                    if item.get("id") in queued_rec_ids:
                        continue
                    rel_path = item.get("filePath", "")
                    if not rel_path:
                        continue
                    full = os.path.join(self.base_dir, rel_path)
                    if _rec_is_protected(full, rel_path, item):
                        protected_skipped_count += 1
                        continue

                    sz = int(item.get("fileSizeBytes", 0) or 0)
                    files_to_delete.append({
                        "type": "recording",
                        "id": item.get("id"),
                        "path": rel_path,
                        "filePath": rel_path,
                        "fullPath": full,
                        "sizeBytes": sz,
                        "reason": f"Exceeded quota of {rec_ret.get('maxStorageGb')} GB",
                    })
                    queued_rec_ids.add(item["id"])
                    bytes_to_free += sz
                    remaining_rec_bytes -= sz
                    if remaining_rec_bytes <= max_rec_bytes:
                        break

            # -------------------------------------------------------------
            # 2. Events Retention (Age & Storage Cap)
            # -------------------------------------------------------------
            if self.motion_service is not None:
                self.motion_service.load_index()
                with self.motion_service.lock:
                    evt_index = dict(self.motion_service.index)
            else:
                evt_index = read_json_index(evt_index_file)

            max_evt_age_sec = float(evt_ret.get("maxAgeDays", 7)) * 86400.0
            max_evt_bytes = float(evt_ret.get("maxStorageMb", 1000.0)) * (1024 * 1024)

            evt_items = [e for e in evt_index.values() if isinstance(e, dict)]
            evt_items.sort(key=lambda x: x.get("timestamp", 0))
            queued_evt_ids: Set[str] = set()

            for item in evt_items:
                rel_path = item.get("snapshotPath", "")
                if not rel_path:
                    continue
                full = os.path.join(self.base_dir, rel_path) if not os.path.isabs(rel_path) else rel_path
                sz = int(item.get("fileSizeBytes", 0) or 0)
                ts_sec = float(item.get("timestamp", 0) or 0) / 1000.0

                if (now - ts_sec) > max_evt_age_sec:
                    files_to_delete.append({
                        "type": "event",
                        "id": item.get("id"),
                        "path": rel_path,
                        "fullPath": full,
                        "sizeBytes": sz,
                        "reason": f"Exceeded max age of {evt_ret.get('maxAgeDays')} days",
                    })
                    queued_evt_ids.add(item.get("id"))
                    bytes_to_free += sz

            remaining_evt_bytes = sum(int(i.get("fileSizeBytes", 0) or 0) for i in evt_items) - sum(
                f["sizeBytes"] for f in files_to_delete if f["type"] == "event"
            )
            if remaining_evt_bytes > max_evt_bytes:
                for item in evt_items:
                    if item.get("id") in queued_evt_ids:
                        continue
                    rel_path = item.get("snapshotPath", "")
                    if not rel_path:
                        continue
                    full = os.path.join(self.base_dir, rel_path) if not os.path.isabs(rel_path) else rel_path
                    sz = int(item.get("fileSizeBytes", 0) or 0)
                    files_to_delete.append({
                        "type": "event",
                        "id": item.get("id"),
                        "path": rel_path,
                        "fullPath": full,
                        "sizeBytes": sz,
                        "reason": f"Exceeded quota of {evt_ret.get('maxStorageMb')} MB",
                    })
                    queued_evt_ids.add(item.get("id"))
                    bytes_to_free += sz
                    remaining_evt_bytes -= sz
                    if remaining_evt_bytes <= max_evt_bytes:
                        break

            # -------------------------------------------------------------
            # 3. Temporary & Corrupted Files Purge
            # -------------------------------------------------------------
            temp_scan = self.scan_temp_and_corrupt()
            max_temp_age = float(temp_ret.get("maxAgeHours", 2.0))
            already_queued_paths = {f["path"] for f in files_to_delete}

            for t_file in temp_scan.get("tempFiles", []):
                if t_file["ageHours"] >= max_temp_age and t_file["path"] not in already_queued_paths:
                    full = os.path.join(self.base_dir, t_file["path"])
                    if _rec_is_protected(full, t_file["path"], None):
                        protected_skipped_count += 1
                        continue
                    files_to_delete.append({
                        "type": "temp",
                        "id": None,
                        "path": t_file["path"],
                        "fullPath": full,
                        "sizeBytes": t_file["sizeBytes"],
                        "reason": f"Temporary file older than {max_temp_age} hours",
                    })
                    already_queued_paths.add(t_file["path"])
                    bytes_to_free += t_file["sizeBytes"]

            for c_file in temp_scan.get("corruptedFiles", []):
                if c_file["path"] not in already_queued_paths:
                    full = os.path.join(self.base_dir, c_file["path"])
                    if _rec_is_protected(full, c_file["path"], None):
                        protected_skipped_count += 1
                        continue
                    files_to_delete.append({
                        "type": "corrupted",
                        "id": None,
                        "path": c_file["path"],
                        "fullPath": full,
                        "sizeBytes": 0,
                        "reason": "Corrupted/Empty 0-byte file",
                    })
                    already_queued_paths.add(c_file["path"])

            # -------------------------------------------------------------
            # Execution (if dry_run is False)
            # -------------------------------------------------------------
            deleted_count = 0
            bytes_freed = 0
            deleted_rec_ids: Set[str] = set()
            deleted_evt_ids: Set[str] = set()
            failed_deletions: List[Dict[str, Any]] = []

            if not dry_run:
                for target in files_to_delete:
                    rel_p = target["path"]
                    full = target["fullPath"]

                    # Re-verify lock right before deletion to prevent race with newly opened playback/recording
                    if target["type"] in ("recording", "temp", "corrupted"):
                        rec_item = rec_index.get(target["id"]) if target["id"] else None
                        if _rec_is_protected(full, rel_p, rec_item):
                            protected_skipped_count += 1
                            continue

                    allowed_root = (
                        self.events_dir
                        if rel_p.replace("\\", "/").startswith("events/")
                        else self.recordings_dir
                    )
                    can_unindex, physically_deleted, err = safe_remove_media_file(
                        self.base_dir, allowed_root, rel_p
                    )

                    if can_unindex:
                        if physically_deleted:
                            deleted_count += 1
                            bytes_freed += int(target.get("sizeBytes", 0) or 0)
                        if target["type"] == "recording" and target["id"]:
                            deleted_rec_ids.add(target["id"])
                        elif target["type"] == "event" and target["id"]:
                            deleted_evt_ids.add(target["id"])
                    else:
                        failed_deletions.append({
                            "id": target.get("id"),
                            "type": target.get("type"),
                            "path": rel_p,
                            "error": err or "Unknown file deletion failure",
                        })

                if deleted_rec_ids:
                    for rid in deleted_rec_ids:
                        rec_index.pop(rid, None)
                    self._persist_recordings_index(rec_index_file, rec_index)

                if deleted_evt_ids:
                    for eid in deleted_evt_ids:
                        evt_index.pop(eid, None)
                    if self.motion_service is not None:
                        with self.motion_service.lock:
                            for eid in deleted_evt_ids:
                                self.motion_service.index.pop(eid, None)
                        self.motion_service.save_index()
                    else:
                        atomic_write_json_index(evt_index_file, evt_index)

        has_failures = len(failed_deletions) > 0
        partial_failure = has_failures and (deleted_count > 0 or len(deleted_rec_ids) > 0 or len(deleted_evt_ids) > 0)
        status_str = (
            "dry_run"
            if dry_run
            else ("ok" if not has_failures else ("partial" if partial_failure else "failed"))
        )

        return {
            "success": not has_failures,
            "partialFailure": partial_failure if not dry_run else False,
            "status": status_str,
            "dryRun": dry_run,
            "itemsEvaluated": len(files_to_delete),
            "filesToDeleteCount": len(files_to_delete),
            "filesDeletedCount": deleted_count if not dry_run else 0,
            "failedCount": len(failed_deletions) if not dry_run else 0,
            "failedFiles": failed_deletions if not dry_run else [],
            "protectedSkippedCount": protected_skipped_count,
            "bytesToFree": bytes_to_free,
            "bytesFreed": bytes_freed if not dry_run else 0,
            "mbToFree": round(bytes_to_free / (1024 * 1024), 2),
            "files": files_to_delete,
            "recordings_purged": (
                sorted(deleted_rec_ids)
                if not dry_run
                else [f["id"] for f in files_to_delete if f["type"] == "recording" and f.get("id")]
            ),
        }

    def reconcile_and_repair_index(self) -> Dict[str, Any]:
        """
        Idempotent self-healing index reconciliation using the unified canonical schema:
        1. Migrates legacy schema entries (path/filename -> filePath/fileName) and repairs cameraId from directory path.
        2. Removes ghost index records whose physical files are missing on disk.
        3. Discovers unindexed physical files on disk without duplicating or clobbering existing entries.
        """
        results = {
            "recordingsReconciled": 0,
            "recordingsGhostPurged": 0,
            "recordingsMigrated": 0,
            "eventsReconciled": 0,
            "eventsGhostPurged": 0,
            "eventsMigrated": 0,
        }
        known_cids = self._configured_camera_ids()

        # 1. Reconcile Recordings
        rec_index_file = os.path.join(self.recordings_dir, "recordings_index.json")
        rec_lock = get_index_lock(rec_index_file)
        with rec_lock:
            raw_rec = (
                self.recording_manager.get_raw_or_synced_index()
                if self.recording_manager is not None
                else read_json_index(rec_index_file)
            )
            rec_index: Dict[str, Dict[str, Any]] = {}

            for rid, raw_item in list(raw_rec.items()):
                entry, changed = normalize_recording_entry(
                    rid,
                    raw_item,
                    base_dir=self.base_dir,
                    storage_dir=self.recordings_dir,
                    configured_camera_ids=known_cids,
                )
                if entry is None:
                    results["recordingsGhostPurged"] += 1
                    continue

                full = os.path.join(self.base_dir, entry["filePath"])
                if not os.path.isfile(full):
                    results["recordingsGhostPurged"] += 1
                    continue

                if changed or entry["id"] != rid:
                    results["recordingsMigrated"] += 1

                # Keep size accurate if file grew
                try:
                    st = os.stat(full)
                    if entry.get("fileSizeBytes") != st.st_size:
                        entry["fileSizeBytes"] = st.st_size
                except OSError:
                    pass

                rec_index[entry["id"]] = entry

            indexed_paths = {item["filePath"]: seg_id for seg_id, item in rec_index.items()}

            if os.path.exists(self.recordings_dir):
                for mp4 in sorted(glob.iglob(os.path.join(self.recordings_dir, "**", "*.mp4"), recursive=True)):
                    if not os.path.isfile(mp4):
                        continue
                    try:
                        rel = to_rel_posix_path(self.base_dir, mp4)
                    except ValueError:
                        continue
                    if not rel or rel in indexed_paths:
                        continue

                    try:
                        st = os.stat(mp4)
                        filename = os.path.basename(mp4)
                        seg_id = os.path.splitext(filename)[0]
                        if seg_id in rec_index:
                            # Disambiguate if two different camera folders share a filename stem
                            cid_tmp, _, _ = resolve_camera_identity(
                                rel, self.base_dir, self.recordings_dir, configured_camera_ids=known_cids
                            )
                            seg_id = f"{cid_tmp}_{seg_id}"

                        cid, _, date_str = resolve_camera_identity(
                            rel,
                            base_dir=self.base_dir,
                            storage_dir=self.recordings_dir,
                            configured_camera_ids=known_cids,
                        )
                        if not date_str:
                            date_str = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d")

                        ctime_ms = int(st.st_ctime * 1000)
                        mtime_ms = max(ctime_ms, int(st.st_mtime * 1000))
                        mode = "motion" if "motion" in filename.lower() else "continuous"

                        rec_index[seg_id] = {
                            "id": seg_id,
                            "cameraId": cid,
                            "date": date_str,
                            "fileName": filename,
                            "filePath": rel,
                            "fileSizeBytes": st.st_size,
                            "startTime": ctime_ms,
                            "endTime": mtime_ms,
                            "durationSeconds": round(max(0.0, (mtime_ms - ctime_ms) / 1000.0), 1),
                            "status": "completed" if st.st_size > 1024 else ("corrupt" if st.st_size == 0 else "completed"),
                            "mode": mode,
                            "format": "mp4",
                        }
                        indexed_paths[rel] = seg_id
                        results["recordingsReconciled"] += 1
                    except OSError:
                        continue

            self._persist_recordings_index(rec_index_file, rec_index)

        # 2. Reconcile Events
        evt_index_file = os.path.join(self.events_dir, "events_index.json")
        evt_lock = get_index_lock(evt_index_file)
        with evt_lock:
            if self.motion_service is not None:
                self.motion_service.load_index()
                with self.motion_service.lock:
                    raw_evt = dict(self.motion_service.index)
            else:
                raw_evt = read_json_index(evt_index_file)

            evt_index: Dict[str, Dict[str, Any]] = {}
            for eid, item in list(raw_evt.items()):
                if not isinstance(item, dict):
                    results["eventsGhostPurged"] += 1
                    continue
                raw_snap = item.get("snapshotPath", "")
                try:
                    rel = to_rel_posix_path(self.base_dir, raw_snap) if raw_snap else ""
                except ValueError:
                    rel = ""
                if not rel:
                    results["eventsGhostPurged"] += 1
                    continue
                full = os.path.join(self.base_dir, rel)
                if not os.path.isfile(full):
                    results["eventsGhostPurged"] += 1
                    continue

                updated_item = dict(item)
                cid, dir_cid, date_str = resolve_camera_identity(
                    rel,
                    base_dir=self.base_dir,
                    storage_dir=self.events_dir,
                    configured_camera_ids=known_cids,
                    existing_camera_id=updated_item.get("cameraId"),
                )
                if dir_cid and updated_item.get("cameraId") != dir_cid:
                    updated_item["cameraId"] = dir_cid
                    results["eventsMigrated"] += 1
                elif not updated_item.get("cameraId"):
                    updated_item["cameraId"] = cid
                    results["eventsMigrated"] += 1

                if updated_item.get("snapshotPath") != rel:
                    updated_item["snapshotPath"] = rel
                    results["eventsMigrated"] += 1
                if date_str and not updated_item.get("date"):
                    updated_item["date"] = date_str

                entry_eid = str(updated_item.get("id") or eid)
                updated_item["id"] = entry_eid
                evt_index[entry_eid] = updated_item

            indexed_snaps = {item["snapshotPath"]: eid for eid, item in evt_index.items()}

            if os.path.exists(self.events_dir):
                for jpg in sorted(glob.iglob(os.path.join(self.events_dir, "**", "*.jpg"), recursive=True)):
                    if not os.path.isfile(jpg):
                        continue
                    try:
                        rel = to_rel_posix_path(self.base_dir, jpg)
                    except ValueError:
                        continue
                    if not rel or rel in indexed_snaps:
                        continue
                    try:
                        st = os.stat(jpg)
                        fname = os.path.splitext(os.path.basename(jpg))[0]
                        cid, _, date_str = resolve_camera_identity(
                            rel,
                            base_dir=self.base_dir,
                            storage_dir=self.events_dir,
                            configured_camera_ids=known_cids,
                        )
                        if not date_str:
                            date_str = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d")

                        evt_index[fname] = {
                            "id": fname,
                            "cameraId": cid,
                            "cameraName": cid,
                            "score": 10.0,
                            "timestamp": int(st.st_mtime * 1000),
                            "isoTime": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                            "date": date_str,
                            "durationSeconds": 1.0,
                            "boundingBox": {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0},
                            "snapshotPath": rel,
                            "fileSizeBytes": st.st_size,
                            "status": "completed",
                        }
                        indexed_snaps[rel] = fname
                        results["eventsReconciled"] += 1
                    except OSError:
                        continue

            if self.motion_service is not None:
                with self.motion_service.lock:
                    self.motion_service.index = dict(evt_index)
                self.motion_service.save_index()
            else:
                atomic_write_json_index(evt_index_file, evt_index)

        return results

    def _maintenance_loop(self):
        """Continuous background loop for storage safeguard and retention checks."""
        while self.running:
            try:
                cfg = self.get_config()
                interval = cfg.get("checkIntervalSeconds", 60.0)

                overview = self.get_storage_overview()
                alert_level = overview["alerts"]["level"]

                if alert_level in ("CRITICAL", "EMERGENCY"):
                    print(
                        f"[STORAGE] Triggering automated retention purge due to {alert_level} storage alert.",
                        flush=True,
                    )
                    self.evaluate_retention(dry_run=False)

                time.sleep(interval)
            except Exception:
                time.sleep(10.0)
