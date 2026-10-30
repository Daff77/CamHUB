"""
CamHub Storage Manager
Comprehensive disk space monitoring, growth trend forecasting, multi-tier threshold alerts (80%, 90%, 95%),
configurable retention enforcement with dry-run support, active recording/playback file protection,
and self-healing index reconciliation for corrupted, orphaned, and temporary files.
"""

import os
import io
import sys
import time
import json
import glob
import shutil
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple

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
            "protectActivePlayback": True
        },
        "events": {
            "maxAgeDays": 7,
            "maxStorageMb": 1000.0
        },
        "tempFiles": {
            "maxAgeHours": 2.0
        }
    },
    "cameras": {}
}

# Fix true/false for python defaults
DEFAULT_STORAGE_CONFIG["retention"]["recordings"]["protectActiveRecordings"] = True
DEFAULT_STORAGE_CONFIG["retention"]["recordings"]["protectActivePlayback"] = True


def sanitize_path(base_dir: str, target_path: str) -> str:
    """Ensure target path is strictly within base directory (prevents path traversal)."""
    abs_base = os.path.abspath(base_dir)
    abs_target = os.path.abspath(target_path)
    if os.path.commonpath([abs_base, abs_target]) != abs_base:
        raise ValueError("Access denied: path traversal detected")
    return abs_target


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
            "freePercent": free_pct
        }
    except Exception as e:
        return {
            "error": str(e),
            "totalBytes": 0, "usedBytes": 0, "freeBytes": 0,
            "totalGb": 0.0, "usedGb": 0.0, "freeGb": 0.0,
            "usedPercent": 0.0, "freePercent": 0.0
        }


class PlaybackLockManager:
    """Tracks active playback sessions and prevents active files from being pruned."""

    def __init__(self):
        self._locks = {}  # filepath/id -> expiration_time
        self._lock = threading.Lock()

    def acquire(self, file_key: str, lease_seconds: float = 300.0) -> None:
        with self._lock:
            self._locks[file_key] = time.time() + lease_seconds

    def release(self, file_key: str) -> None:
        with self._lock:
            self._locks.pop(file_key, None)

    def is_locked(self, file_key: str) -> bool:
        with self._lock:
            exp = self._locks.get(file_key)
            if exp is None:
                return False
            if time.time() > exp:
                del self._locks[file_key]
                return False
            return True

    def get_active_locks(self) -> List[str]:
        with self._lock:
            now = time.time()
            valid = [k for k, exp in self._locks.items() if exp > now]
            # prune expired
            self._locks = {k: exp for k, exp in self._locks.items() if exp > now}
            return valid


class CamHubStorageManager:
    """
    Central storage supervisor for CamHUB.
    Monitors host storage, forecasts capacity depletion, enforces retention policies,
    cleans corrupted/temporary files, and protects active files.
    """

    def __init__(self, config_provider, base_dir: str = None):
        self.config_provider = config_provider
        self.base_dir = base_dir or BASE_DIR
        self.recordings_dir = os.path.join(self.base_dir, "recordings")
        self.events_dir = os.path.join(self.base_dir, "events")
        self.playback_locks = PlaybackLockManager()

        self.lock = threading.RLock()
        self.running = False
        self.worker_thread = None

        # Growth trend tracking (rolling window of time -> total CamHub bytes)
        self.history = []  # list of (timestamp, camhub_bytes, free_bytes)
        self.last_check_time = 0.0

        # Current alert status
        self.alert_level = "NORMAL"
        self.alert_message = "Storage operating within healthy parameters."

    def get_config(self) -> Dict[str, Any]:
        """Merge user config with defaults."""
        full_cfg = self.config_provider()
        cfg = dict(DEFAULT_STORAGE_CONFIG)
        user_cfg = full_cfg.get("storageManagement", {})
        cfg.update(user_cfg)
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
                daemon=True
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
                "newestTimestamp": None
            }

        total_bytes = 0
        file_count = 0
        cam_breakdown = {}
        oldest_time = None
        newest_time = None

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

                # Determine camera ID from path: target_dir/<camera_id>/...
                rel = os.path.relpath(filepath, target_dir)
                parts = rel.replace("\\", "/").split("/")
                cam_id = parts[0] if len(parts) > 1 else "root"

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
            "newestTime": datetime.fromtimestamp(newest_time).isoformat() if newest_time else None
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
                try:
                    st = os.stat(entry)
                    sz = st.st_size
                    mtime = st.st_mtime
                    age_hours = (time.time() - mtime) / 3600.0

                    # Temporary files
                    if ".tmp" in filename or filename.endswith(".part"):
                        temp_files.append({
                            "path": os.path.relpath(entry, self.base_dir).replace("\\", "/"),
                            "sizeBytes": sz,
                            "ageHours": round(age_hours, 1)
                        })
                        total_temp_bytes += sz

                    # 0-byte corrupted video or image files older than 10 minutes
                    elif sz == 0 and age_hours > 0.16:
                        if filename.endswith(".mp4") or filename.endswith(".jpg"):
                            corrupted_files.append({
                                "path": os.path.relpath(entry, self.base_dir).replace("\\", "/"),
                                "reason": "0-byte empty file",
                                "ageHours": round(age_hours, 1)
                            })
                except OSError:
                    continue

        return {
            "tempFilesCount": len(temp_files),
            "tempTotalBytes": total_temp_bytes,
            "tempTotalMb": round(total_temp_bytes / (1024 * 1024), 2),
            "tempFiles": temp_files,
            "corruptedFilesCount": len(corrupted_files),
            "corruptedFiles": corrupted_files
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

        # Update growth history
        now = time.time()
        with self.lock:
            self.history.append((now, camhub_bytes, disk.get("freeBytes", 0)))
            # Keep history for rolling 24 hours
            cutoff = now - 86400
            self.history = [h for h in self.history if h[0] >= cutoff]

        # Calculate growth rate and remaining time estimate
        growth_rate_mb_per_hour = self._calculate_growth_rate_mb_hour()
        time_remaining = self._estimate_time_remaining(disk.get("freeBytes", 0), growth_rate_mb_per_hour)

        # Evaluate threshold alerts
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
                "percentOfDiskUsed": round((camhub_bytes / max(1, disk.get("usedBytes", 1))) * 100.0, 2)
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
                "status": time_remaining.get("status")
            },
            "alerts": {
                "level": alert_level,
                "message": alert_msg,
                "thresholds": {
                    "warningPercent": warn_pct,
                    "criticalPercent": crit_pct,
                    "emergencyPercent": emerg_pct,
                    "minFreeGb": min_free_gb
                }
            },
            "activePlaybackLocks": self.playback_locks.get_active_locks()
        }

    def _calculate_growth_rate_mb_hour(self) -> float:
        """Estimate hourly data addition rate based on recent history."""
        with self.lock:
            if len(self.history) < 2:
                # Default baseline: ~50 MB/hour for active CCTV motion & snapshots
                return 45.0

            first_t, first_b, _ = self.history[0]
            last_t, last_b, _ = self.history[-1]
            elapsed_sec = last_t - first_t

            if elapsed_sec < 60:
                return 45.0

            delta_bytes = max(0, last_b - first_b)
            rate_bytes_sec = delta_bytes / elapsed_sec
            mb_hour = round((rate_bytes_sec * 3600.0) / (1024 * 1024), 2)
            return max(5.0, mb_hour)  # minimum baseline 5 MB/hr

    def _estimate_time_remaining(self, free_bytes: int, growth_rate_mb_hour: float) -> Dict[str, Any]:
        """Estimate hours and days until disk is depleted."""
        if free_bytes <= 0 or growth_rate_mb_hour <= 0:
            return {"hoursRemaining": 0, "daysRemaining": 0, "depletionDate": None, "status": "Depleted"}

        free_mb = free_bytes / (1024 * 1024)
        hours = round(free_mb / growth_rate_mb_hour, 1)
        days = round(hours / 24.0, 1)

        depletion_date = None
        if hours < 87600:  # within 10 years
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
            "status": status
        }

    def evaluate_retention(
        self,
        dry_run: bool = True,
        active_recording_files: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Evaluate retention policy for both recordings and events.
        If dry_run=True, lists files that WOULD be deleted without modifying disk.
        If dry_run=False, safely purges files and updates indices.
        """
        cfg = self.get_config()
        rec_ret = cfg.get("retention", {}).get("recordings", {})
        evt_ret = cfg.get("retention", {}).get("events", {})
        temp_ret = cfg.get("retention", {}).get("tempFiles", {})

        now = time.time()
        active_recs = set(active_recording_files or [])
        locked_playback = set(self.playback_locks.get_active_locks())

        files_to_delete = []
        bytes_to_free = 0

        # -------------------------------------------------------------
        # 1. Recordings Retention (Age & Storage Cap)
        # -------------------------------------------------------------
        rec_index_file = os.path.join(self.recordings_dir, "recordings_index.json")
        rec_index = {}
        if os.path.exists(rec_index_file):
            try:
                with open(rec_index_file, "r", encoding="utf-8") as f:
                    rec_index = json.load(f)
            except Exception:
                rec_index = {}

        max_rec_age_sec = rec_ret.get("maxAgeDays", 7) * 86400
        max_rec_bytes = rec_ret.get("maxStorageGb", 20.0) * (1024**3)

        rec_items = list(rec_index.values())
        rec_items.sort(key=lambda x: x.get("startTime", 0))

        # Check age
        for item in rec_items:
            path = item.get("path", "")
            full = os.path.join(self.base_dir, path) if not os.path.isabs(path) else path
            sz = item.get("fileSizeBytes", 0)
            start_sec = item.get("startTime", 0) / 1000.0

            # Protect active recording or active playback
            if full in active_recs or path in active_recs:
                continue
            if full in locked_playback or path in locked_playback:
                continue

            if (now - start_sec) > max_rec_age_sec:
                files_to_delete.append({
                    "type": "recording",
                    "id": item.get("id"),
                    "path": path,
                    "fullPath": full,
                    "sizeBytes": sz,
                    "reason": f"Exceeded max age of {rec_ret.get('maxAgeDays')} days"
                })
                bytes_to_free += sz

        # Check max storage bytes
        remaining_rec_bytes = sum(i.get("fileSizeBytes", 0) for i in rec_items) - sum(f["sizeBytes"] for f in files_to_delete if f["type"] == "recording")
        if remaining_rec_bytes > max_rec_bytes:
            for item in rec_items:
                path = item.get("path", "")
                full = os.path.join(self.base_dir, path) if not os.path.isabs(path) else path
                if any(f["path"] == path for f in files_to_delete):
                    continue
                if full in active_recs or path in active_recs or full in locked_playback or path in locked_playback:
                    continue

                sz = item.get("fileSizeBytes", 0)
                files_to_delete.append({
                    "type": "recording",
                    "id": item.get("id"),
                    "path": path,
                    "fullPath": full,
                    "sizeBytes": sz,
                    "reason": f"Exceeded quota of {rec_ret.get('maxStorageGb')} GB"
                })
                bytes_to_free += sz
                remaining_rec_bytes -= sz
                if remaining_rec_bytes <= max_rec_bytes:
                    break

        # -------------------------------------------------------------
        # 2. Events Retention (Age & Storage Cap)
        # -------------------------------------------------------------
        evt_index_file = os.path.join(self.events_dir, "events_index.json")
        evt_index = {}
        if os.path.exists(evt_index_file):
            try:
                with open(evt_index_file, "r", encoding="utf-8") as f:
                    evt_index = json.load(f)
            except Exception:
                evt_index = {}

        max_evt_age_sec = evt_ret.get("maxAgeDays", 7) * 86400
        max_evt_bytes = evt_ret.get("maxStorageMb", 1000.0) * (1024 * 1024)

        evt_items = list(evt_index.values())
        evt_items.sort(key=lambda x: x.get("timestamp", 0))

        # Check age
        for item in evt_items:
            path = item.get("snapshotPath", "")
            full = os.path.join(self.base_dir, path) if not os.path.isabs(path) else path
            sz = item.get("fileSizeBytes", 0)
            ts_sec = item.get("timestamp", 0) / 1000.0

            if (now - ts_sec) > max_evt_age_sec:
                files_to_delete.append({
                    "type": "event",
                    "id": item.get("id"),
                    "path": path,
                    "fullPath": full,
                    "sizeBytes": sz,
                    "reason": f"Exceeded max age of {evt_ret.get('maxAgeDays')} days"
                })
                bytes_to_free += sz

        # Check max storage MB
        remaining_evt_bytes = sum(i.get("fileSizeBytes", 0) for i in evt_items) - sum(f["sizeBytes"] for f in files_to_delete if f["type"] == "event")
        if remaining_evt_bytes > max_evt_bytes:
            for item in evt_items:
                path = item.get("snapshotPath", "")
                full = os.path.join(self.base_dir, path) if not os.path.isabs(path) else path
                if any(f["path"] == path for f in files_to_delete):
                    continue

                sz = item.get("fileSizeBytes", 0)
                files_to_delete.append({
                    "type": "event",
                    "id": item.get("id"),
                    "path": path,
                    "fullPath": full,
                    "sizeBytes": sz,
                    "reason": f"Exceeded quota of {evt_ret.get('maxStorageMb')} MB"
                })
                bytes_to_free += sz
                remaining_evt_bytes -= sz
                if remaining_evt_bytes <= max_evt_bytes:
                    break

        # -------------------------------------------------------------
        # 3. Temporary & Corrupted Files Purge
        # -------------------------------------------------------------
        temp_scan = self.scan_temp_and_corrupt()
        max_temp_age = temp_ret.get("maxAgeHours", 2.0)
        for t_file in temp_scan.get("tempFiles", []):
            if t_file["ageHours"] >= max_temp_age:
                full = os.path.join(self.base_dir, t_file["path"])
                files_to_delete.append({
                    "type": "temp",
                    "id": None,
                    "path": t_file["path"],
                    "fullPath": full,
                    "sizeBytes": t_file["sizeBytes"],
                    "reason": f"Temporary file older than {max_temp_age} hours"
                })
                bytes_to_free += t_file["sizeBytes"]

        for c_file in temp_scan.get("corruptedFiles", []):
            full = os.path.join(self.base_dir, c_file["path"])
            files_to_delete.append({
                "type": "corrupted",
                "id": None,
                "path": c_file["path"],
                "fullPath": full,
                "sizeBytes": 0,
                "reason": "Corrupted/Empty 0-byte file"
            })

        # -------------------------------------------------------------
        # Execution (if dry_run is False)
        # -------------------------------------------------------------
        deleted_count = 0
        if not dry_run:
            deleted_rec_ids = set()
            deleted_evt_ids = set()

            for target in files_to_delete:
                full = target["fullPath"]
                try:
                    # Security check: must reside inside base_dir
                    sanitize_path(self.base_dir, full)
                    if os.path.exists(full):
                        os.remove(full)
                        deleted_count += 1
                        # Clean empty parent folder
                        parent = os.path.dirname(full)
                        if os.path.exists(parent) and not os.listdir(parent):
                            os.rmdir(parent)
                except Exception as del_err:
                    print(f"[STORAGE] Failed to delete file {full}: {del_err}", file=sys.stderr)

                if target["type"] == "recording" and target["id"]:
                    deleted_rec_ids.add(target["id"])
                elif target["type"] == "event" and target["id"]:
                    deleted_evt_ids.add(target["id"])

            # Update indices
            if deleted_rec_ids and os.path.exists(rec_index_file):
                try:
                    for rid in deleted_rec_ids:
                        rec_index.pop(rid, None)
                    with open(rec_index_file, "w", encoding="utf-8") as f:
                        json.dump(rec_index, f, indent=2)
                except Exception as idx_err:
                    print(f"[STORAGE] Error updating recording index: {idx_err}", file=sys.stderr)

            if deleted_evt_ids and os.path.exists(evt_index_file):
                try:
                    for eid in deleted_evt_ids:
                        evt_index.pop(eid, None)
                    with open(evt_index_file, "w", encoding="utf-8") as f:
                        json.dump(evt_index, f, indent=2)
                except Exception as idx_err:
                    print(f"[STORAGE] Error updating events index: {idx_err}", file=sys.stderr)

        return {
            "dryRun": dry_run,
            "itemsEvaluated": len(files_to_delete),
            "filesToDeleteCount": len(files_to_delete),
            "filesDeletedCount": deleted_count if not dry_run else 0,
            "bytesToFree": bytes_to_free,
            "mbToFree": round(bytes_to_free / (1024 * 1024), 2),
            "files": files_to_delete
        }

    def reconcile_and_repair_index(self) -> Dict[str, Any]:
        """
        Self-healing index reconciliation:
        1. Finds files on disk missing from index -> adds them.
        2. Finds index records missing physical files on disk -> removes ghost records.
        """
        results = {
            "recordingsReconciled": 0,
            "recordingsGhostPurged": 0,
            "eventsReconciled": 0,
            "eventsGhostPurged": 0
        }

        # 1. Reconcile Recordings
        rec_index_file = os.path.join(self.recordings_dir, "recordings_index.json")
        rec_index = {}
        if os.path.exists(rec_index_file):
            try:
                with open(rec_index_file, "r", encoding="utf-8") as f:
                    rec_index = json.load(f)
            except Exception:
                rec_index = {}

        # Remove ghost entries
        for rid, item in list(rec_index.items()):
            rel = item.get("path", "")
            full = os.path.join(self.base_dir, rel)
            if not os.path.exists(full):
                del rec_index[rid]
                results["recordingsGhostPurged"] += 1

        # Scan physical files missing from index
        for mp4 in glob.iglob(os.path.join(self.recordings_dir, "**", "*.mp4"), recursive=True):
            rel = os.path.relpath(mp4, self.base_dir).replace("\\", "/")
            existing = any(item.get("path") == rel for item in rec_index.values())
            if not existing:
                try:
                    st = os.stat(mp4)
                    fname = os.path.splitext(os.path.basename(mp4))[0]
                    parts = rel.split("/")
                    cid = parts[1] if len(parts) > 2 else "unknown"
                    date_str = parts[2] if len(parts) > 3 else datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d")

                    rec_index[fname] = {
                        "id": fname,
                        "cameraId": cid,
                        "date": date_str,
                        "filename": os.path.basename(mp4),
                        "path": rel,
                        "fileSizeBytes": st.st_size,
                        "startTime": int(st.st_mtime * 1000),
                        "durationSeconds": 60.0,
                        "status": "completed"
                    }
                    results["recordingsReconciled"] += 1
                except OSError:
                    pass

        try:
            with open(rec_index_file, "w", encoding="utf-8") as f:
                json.dump(rec_index, f, indent=2)
        except Exception:
            pass

        # 2. Reconcile Events
        evt_index_file = os.path.join(self.events_dir, "events_index.json")
        evt_index = {}
        if os.path.exists(evt_index_file):
            try:
                with open(evt_index_file, "r", encoding="utf-8") as f:
                    evt_index = json.load(f)
            except Exception:
                evt_index = {}

        # Remove ghost events
        for eid, item in list(evt_index.items()):
            rel = item.get("snapshotPath", "")
            full = os.path.join(self.base_dir, rel)
            if not os.path.exists(full):
                del evt_index[eid]
                results["eventsGhostPurged"] += 1

        # Scan physical jpgs missing from index
        for jpg in glob.iglob(os.path.join(self.events_dir, "**", "*.jpg"), recursive=True):
            rel = os.path.relpath(jpg, self.base_dir).replace("\\", "/")
            existing = any(item.get("snapshotPath") == rel for item in evt_index.values())
            if not existing:
                try:
                    st = os.stat(jpg)
                    fname = os.path.splitext(os.path.basename(jpg))[0]
                    parts = rel.split("/")
                    cid = parts[1] if len(parts) > 2 else "unknown"
                    date_str = parts[2] if len(parts) > 3 else datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d")

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
                        "status": "completed"
                    }
                    results["eventsReconciled"] += 1
                except OSError:
                    pass

        try:
            with open(evt_index_file, "w", encoding="utf-8") as f:
                json.dump(evt_index, f, indent=2)
        except Exception:
            pass

        return results

    def _maintenance_loop(self):
        """Continuous background loop for storage safeguard and retention checks."""
        while self.running:
            try:
                cfg = self.get_config()
                interval = cfg.get("checkIntervalSeconds", 60.0)

                # Check disk stats
                overview = self.get_storage_overview()
                alert_level = overview["alerts"]["level"]

                # If Emergency or Critical, trigger automated purge
                if alert_level in ("CRITICAL", "EMERGENCY"):
                    print(f"[STORAGE] Triggering automated retention purge due to {alert_level} storage alert.", flush=True)
                    self.evaluate_retention(dry_run=False)

                time.sleep(interval)
            except Exception as e:
                time.sleep(10.0)
