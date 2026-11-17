"""
Unified Media Metadata Schema, Camera Identity Resolution, Atomic Index Store & Verified File Deletion
Shared single source of truth for RecordingManager, CamHubStorageManager, MotionDetectorService, and server playback APIs.
"""

import os
import re
import json
import time
import threading
from datetime import datetime
from typing import Dict, Any, Optional, Tuple, Iterable

_LOCKS_GUARD = threading.Lock()
_INDEX_LOCKS: Dict[str, threading.RLock] = {}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SEG_PREFIX_RE = re.compile(r"^(.+?)_(?:rec|motion)_\d{8}_\d{6}(?:_seg\d+)?$", re.IGNORECASE)


def sanitize_path(base_dir: str, target_path: str) -> str:
    """Ensure target path is strictly within base directory (prevents path traversal)."""
    abs_base = os.path.realpath(os.path.abspath(base_dir))
    abs_target = os.path.realpath(os.path.abspath(target_path))
    try:
        common = os.path.commonpath([abs_base, abs_target])
    except ValueError:
        raise ValueError("Access denied: path traversal across drives detected")
    if os.path.normcase(common) != os.path.normcase(abs_base):
        raise ValueError("Access denied: path traversal detected")
    return os.path.abspath(target_path)


def get_index_lock(index_file: str) -> threading.RLock:
    """Return a process-wide reentrant lock keyed by canonical index file path."""
    key = os.path.normcase(os.path.realpath(os.path.abspath(index_file)))
    with _LOCKS_GUARD:
        lock = _INDEX_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _INDEX_LOCKS[key] = lock
        return lock


def read_json_index(index_file: str) -> Dict[str, Any]:
    """Thread-safe read of a JSON dictionary index file."""
    lock = get_index_lock(index_file)
    with lock:
        if not os.path.exists(index_file):
            return {}
        try:
            with open(index_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    return {}
                loaded = json.loads(content)
                return loaded if isinstance(loaded, dict) else {}
        except Exception:
            return {}


def atomic_write_json_index(index_file: str, data: Dict[str, Any]) -> None:
    """Thread-safe atomic write to a JSON index file via temp file + fsync + os.replace."""
    lock = get_index_lock(index_file)
    with lock:
        parent = os.path.dirname(os.path.abspath(index_file))
        os.makedirs(parent, exist_ok=True)
        # Use .idxtmp suffix so storage temp-file scanner (.tmp / .part) never touches live index writes
        tmp_file = f"{index_file}.idxtmp.{os.getpid()}.{threading.get_ident()}"
        try:
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())

            last_err = None
            for _ in range(5):
                try:
                    os.replace(tmp_file, index_file)
                    last_err = None
                    break
                except OSError as e:
                    last_err = e
                    time.sleep(0.03)
            if last_err is not None:
                raise last_err
        finally:
            if os.path.exists(tmp_file):
                try:
                    os.remove(tmp_file)
                except OSError:
                    pass


def to_rel_posix_path(base_dir: str, path_value: str) -> str:
    """Normalize a relative or absolute path inside base_dir into a relative POSIX path."""
    if not path_value or not isinstance(path_value, str):
        return ""
    cleaned = path_value.strip()
    if not cleaned:
        return ""
    candidate = cleaned if os.path.isabs(cleaned) else os.path.join(base_dir, cleaned)
    abs_checked = sanitize_path(base_dir, candidate)
    rel = os.path.relpath(abs_checked, os.path.abspath(base_dir)).replace("\\", "/")
    if rel in (".", ""):
        return ""
    return rel


def resolve_camera_identity(
    rel_or_full_path: str,
    base_dir: str,
    storage_dir: str,
    session_camera_id: Optional[str] = None,
    configured_camera_ids: Optional[Iterable[str]] = None,
    existing_camera_id: Optional[str] = None,
) -> Tuple[str, Optional[str], Optional[str]]:
    """
    Resolve (camera_id, authoritative_dir_camera_id, date_str) for a media file.
    Priority:
      1. Active recording session camera_id (authoritative)
      2. Directory structure under storage_dir: <storage_dir>/<camera_id>/[<YYYY-MM-DD>/]<file>
         Preserves full IDs containing underscores such as okam_1, okam_2, okam_3.
      3. Configured camera ID prefix or '<camera_id>_(rec|motion)_YYYYMMDD_HHMMSS' pattern
      4. Existing metadata camera_id (if not truncated) or filename fallback
    """
    dir_cam_id: Optional[str] = None
    date_str: Optional[str] = None

    if rel_or_full_path:
        abs_file = (
            os.path.abspath(rel_or_full_path)
            if os.path.isabs(rel_or_full_path)
            else os.path.abspath(os.path.join(base_dir, rel_or_full_path))
        )
        abs_storage = os.path.abspath(storage_dir)
        try:
            if os.path.normcase(os.path.commonpath([abs_storage, abs_file])) == os.path.normcase(abs_storage):
                rel_to_storage = os.path.relpath(abs_file, abs_storage).replace("\\", "/")
                parts = [p for p in rel_to_storage.split("/") if p and p != "."]
                if len(parts) >= 2:
                    # parts[0] is camera directory (e.g. 'okam_1', 'okam_2', 'okam_3', 'v380-1')
                    if not _DATE_RE.match(parts[0]):
                        dir_cam_id = parts[0]
                        if len(parts) >= 3 and _DATE_RE.match(parts[1]):
                            date_str = parts[1]
                    else:
                        date_str = parts[0]
        except ValueError:
            pass

    if session_camera_id:
        return session_camera_id, dir_cam_id or session_camera_id, date_str

    if dir_cam_id:
        return dir_cam_id, dir_cam_id, date_str

    filename = os.path.basename(rel_or_full_path or "")
    stem = os.path.splitext(filename)[0]

    # Match against known configured camera IDs (longest first so 'okam_10' beats 'okam_1')
    if configured_camera_ids and stem:
        for cid in sorted((c for c in configured_camera_ids if c), key=len, reverse=True):
            if stem == cid or stem.startswith(f"{cid}_"):
                return cid, None, date_str

    # Match segment naming pattern '<camera_id>_rec_YYYYMMDD_HHMMSS...'
    m = _SEG_PREFIX_RE.match(stem)
    if m:
        return m.group(1), None, date_str

    if existing_camera_id and existing_camera_id not in ("unknown", "root"):
        return existing_camera_id, None, date_str

    if stem:
        return stem.split("_")[0], None, date_str

    return "unknown", None, date_str


def normalize_recording_entry(
    seg_id: str,
    raw: Dict[str, Any],
    base_dir: str,
    storage_dir: str,
    configured_camera_ids: Optional[Iterable[str]] = None,
) -> Tuple[Optional[Dict[str, Any]], bool]:
    """
    Normalize and migrate a recording index entry into the canonical schema:
      id, cameraId, date, fileName, filePath, fileSizeBytes, startTime, endTime,
      durationSeconds, status, mode, format (+ any extra custom keys preserved).
    Returns (normalized_entry_or_None_if_invalid, changed_flag).
    """
    if not isinstance(raw, dict):
        return None, True

    changed = False
    raw_path = raw.get("filePath") or raw.get("path") or ""
    try:
        rel_path = to_rel_posix_path(base_dir, raw_path) if raw_path else ""
    except ValueError:
        return None, True

    if not rel_path:
        return None, True

    if "path" in raw or raw.get("filePath") != rel_path:
        changed = True

    file_name = raw.get("fileName") or raw.get("filename") or os.path.basename(rel_path)
    if "filename" in raw or raw.get("fileName") != file_name:
        changed = True

    existing_cid = raw.get("cameraId")
    resolved_cid, authoritative_dir_cid, path_date = resolve_camera_identity(
        rel_path,
        base_dir=base_dir,
        storage_dir=storage_dir,
        configured_camera_ids=configured_camera_ids,
        existing_camera_id=existing_cid,
    )
    # If directory clearly establishes camera identity, repair stale/truncated cameraId (e.g. 'okam' -> 'okam_1')
    final_cid = authoritative_dir_cid or existing_cid or resolved_cid
    if existing_cid in (None, "", "unknown", "root"):
        final_cid = resolved_cid
    elif authoritative_dir_cid and existing_cid != authoritative_dir_cid:
        final_cid = authoritative_dir_cid

    if raw.get("cameraId") != final_cid:
        changed = True

    entry_id = str(raw.get("id") or seg_id or os.path.splitext(file_name)[0])
    if raw.get("id") != entry_id:
        changed = True

    # Inspect physical file only if metadata fields are missing
    abs_file = os.path.join(base_dir, rel_path)
    stat_res = None
    if any(k not in raw for k in ("fileSizeBytes", "startTime", "endTime")):
        try:
            if os.path.isfile(abs_file):
                stat_res = os.stat(abs_file)
        except OSError:
            stat_res = None

    size_bytes = raw.get("fileSizeBytes")
    if size_bytes is None:
        size_bytes = int(stat_res.st_size) if stat_res else 0
        changed = True
    else:
        size_bytes = int(size_bytes)

    start_time = raw.get("startTime")
    if start_time is None:
        start_time = int((stat_res.st_ctime if stat_res else time.time()) * 1000)
        changed = True
    else:
        start_time = int(start_time)

    end_time = raw.get("endTime")
    if end_time is None:
        if stat_res:
            end_time = max(start_time, int(stat_res.st_mtime * 1000))
        else:
            dur_guess = float(raw.get("durationSeconds", 0.0) or 0.0)
            end_time = start_time + int(dur_guess * 1000)
        changed = True
    else:
        end_time = int(end_time)

    duration_sec = raw.get("durationSeconds")
    if duration_sec is None:
        duration_sec = round(max(0.0, (end_time - start_time) / 1000.0), 1)
        changed = True
    else:
        duration_sec = float(duration_sec)

    date_val = raw.get("date") or path_date
    if not date_val:
        try:
            date_val = datetime.fromtimestamp(start_time / 1000.0).strftime("%Y-%m-%d")
        except Exception:
            date_val = datetime.now().strftime("%Y-%m-%d")
    if raw.get("date") != date_val:
        changed = True

    status = raw.get("status")
    if not status:
        status = "completed" if size_bytes > 0 else "corrupt"
        changed = True

    mode = raw.get("mode")
    if not mode:
        mode = "motion" if "motion" in file_name.lower() else "continuous"
        changed = True

    fmt = raw.get("format") or "mp4"
    if raw.get("format") != fmt:
        changed = True

    # Preserve any additional custom keys while removing legacy duplicate keys ('path', 'filename')
    normalized: Dict[str, Any] = {}
    for k, v in raw.items():
        if k not in ("path", "filename"):
            normalized[k] = v

    normalized.update({
        "id": entry_id,
        "cameraId": final_cid,
        "date": date_val,
        "fileName": file_name,
        "filePath": rel_path,
        "fileSizeBytes": size_bytes,
        "startTime": start_time,
        "endTime": end_time,
        "durationSeconds": duration_sec,
        "status": status,
        "mode": mode,
        "format": fmt,
    })

    return normalized, changed


def safe_remove_media_file(
    base_dir: str,
    allowed_root: str,
    rel_or_full_path: str,
) -> Tuple[bool, bool, Optional[str]]:
    """
    Safely delete a media file inside allowed_root.
    Returns (can_remove_metadata, physically_deleted, error_message):
      - (True, True, None)   : File existed and was deleted from disk.
      - (True, False, None)  : File was already absent on disk (safe to remove stale metadata).
      - (False, False, err)  : Deletion failed or path was invalid/directory (DO NOT remove metadata).
    """
    if not rel_or_full_path or not isinstance(rel_or_full_path, str) or not rel_or_full_path.strip():
        return False, False, "Empty file path"

    candidate = (
        rel_or_full_path
        if os.path.isabs(rel_or_full_path)
        else os.path.join(base_dir, rel_or_full_path)
    )
    try:
        abs_root = sanitize_path(base_dir, allowed_root)
        abs_target = sanitize_path(abs_root, candidate)
    except ValueError as ve:
        return False, False, str(ve)

    if os.path.normcase(abs_target) == os.path.normcase(abs_root):
        return False, False, "Refusing to delete storage root directory"

    if not os.path.exists(abs_target):
        return True, False, None

    if os.path.isdir(abs_target):
        return False, False, f"Target path is a directory, not a file: {abs_target}"

    try:
        os.remove(abs_target)
    except FileNotFoundError:
        return True, False, None
    except OSError as e:
        return False, False, str(e)

    # Verify file is truly gone
    if os.path.exists(abs_target):
        return False, False, f"File still exists after os.remove: {abs_target}"

    # Prune empty date folder (never prune allowed_root itself)
    parent = os.path.dirname(abs_target)
    try:
        if (
            os.path.isdir(parent)
            and os.path.normcase(parent) != os.path.normcase(abs_root)
            and os.path.normcase(os.path.commonpath([abs_root, parent])) == os.path.normcase(abs_root)
            and not os.listdir(parent)
        ):
            os.rmdir(parent)
    except OSError:
        pass

    return True, True, None
