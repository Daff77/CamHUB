"""
CamHub Motion Detection & Event Timeline Engine
Lightweight, vectorized background subtraction with noise filtering, lighting change suppression,
detection zones (ROI), snapshot capture, event metadata indexing, and retention management.
"""

import os
import io
import sys
import time
import json
import glob
import shutil
import threading
import uuid
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime
from urllib.request import Request, urlopen
import numpy as np
from PIL import Image

# CamHUB project root directory (parent of core/)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_EVENTS_DIR = os.path.join(BASE_DIR, "events")

DEFAULT_MOTION_CONFIG = {
    "enabled": True,
    "samplingIntervalSeconds": 0.5,   # 2 fps sampling
    "analysisWidth": 320,
    "analysisHeight": 180,
    "motionThreshold": 25.0,          # Pixel intensity delta
    "minMotionAreaPercent": 1.5,      # 1.5% of frame
    "maxMotionAreaPercent": 65.0,     # Above 65% is global lighting switch
    "cooldownSeconds": 15.0,          # Cooldown between saved events
    "minEventDurationSeconds": 0.6,   # Sustained motion confirmation
    "retentionDays": 7,
    "maxStorageMb": 1000.0,
    "cameras": {}                     # Per-camera threshold overrides
}

def sanitize_path(base_dir: str, target_path: str) -> str:
    """Ensure target path is strictly within base directory (prevents path traversal)."""
    abs_base = os.path.abspath(base_dir)
    abs_target = os.path.abspath(target_path)
    if os.path.commonpath([abs_base, abs_target]) != abs_base:
        raise ValueError("Access denied: path traversal detected")
    return abs_target

class CameraMotionTracker:
    """Tracks running background model and evaluates motion for a single camera."""

    def __init__(self, camera_id: str, name: str, snapshot_url: str, config: dict):
        self.camera_id = camera_id
        self.name = name
        self.snapshot_url = snapshot_url
        self.config = config

        self.background_model = None
        self.last_sample_time = 0.0
        self.last_event_time = 0.0
        self.motion_start_time = None
        self.is_motion_sustained = False

        # Performance metrics
        self.processed_frames = 0
        self.last_proc_duration_ms = 0.0
        self.current_score = 0.0
        self.last_state = "idle"  # idle, detecting, cooldown

    def evaluate_frame(self, jpeg_bytes: bytes, now: float = None) -> tuple[bool, dict]:
        """
        Process a single snapshot frame.
        Returns (is_event_confirmed, event_data_or_none)
        """
        if now is None:
            now = time.time()

        t_start = time.perf_counter()
        self.last_sample_time = now
        self.processed_frames += 1

        w = self.config.get("analysisWidth", 320)
        h = self.config.get("analysisHeight", 180)
        thresh = self.config.get("motionThreshold", 25.0)
        min_pct = self.config.get("minMotionAreaPercent", 1.5)
        max_pct = self.config.get("maxMotionAreaPercent", 65.0)
        cooldown = self.config.get("cooldownSeconds", 15.0)
        min_dur = self.config.get("minEventDurationSeconds", 0.6)
        roi = self.config.get("roi")  # optional [x1, y1, x2, y2] in 0.0-1.0

        try:
            # 1. Decode & Downscale
            img = Image.open(io.BytesIO(jpeg_bytes)).convert("L")
            orig_w, orig_h = img.size
            if img.size != (w, h):
                img = img.resize((w, h), Image.Resampling.BILINEAR)
            arr = np.asarray(img, dtype=np.float32)
        except Exception:
            return False, None

        # 2. Initialize or Update Adaptive Background Model
        if self.background_model is None:
            self.background_model = arr.copy()
            self.last_proc_duration_ms = (time.perf_counter() - t_start) * 1000
            return False, None

        # 3. Vectorized Absolute Difference
        delta = np.abs(arr - self.background_model)

        # 4. Optional Region of Interest (ROI) Mask
        if roi and len(roi) == 4:
            x1 = int(roi[0] * w)
            y1 = int(roi[1] * h)
            x2 = int(roi[2] * w)
            y2 = int(roi[3] * h)
            roi_delta = delta[y1:y2, x1:x2]
            total_eval_pixels = (x2 - x1) * (y2 - y1)
            motion_mask = roi_delta > thresh
        else:
            total_eval_pixels = w * h
            motion_mask = delta > thresh

        motion_pixels = int(np.sum(motion_mask))
        score_pct = round((motion_pixels / max(1, total_eval_pixels)) * 100.0, 2)
        self.current_score = score_pct

        # 5. Global Lighting Change Filter (e.g. lights turned on/off)
        if score_pct > max_pct:
            # Fast adapt background without generating false positive event!
            self.background_model = arr.copy()
            self.motion_start_time = None
            self.last_state = "lighting_change"
            self.last_proc_duration_ms = (time.perf_counter() - t_start) * 1000
            return False, None

        # 6. Motion Threshold Evaluation
        has_motion = score_pct >= min_pct

        if has_motion:
            # Compute bounding box of motion
            y_indices, x_indices = np.where(motion_mask)
            if len(x_indices) > 0 and len(y_indices) > 0:
                bx_min = round(float(np.min(x_indices)) / w, 3)
                by_min = round(float(np.min(y_indices)) / h, 3)
                bx_max = round(float(np.max(x_indices)) / w, 3)
                by_max = round(float(np.max(y_indices)) / h, 3)
                bbox = {
                    "x": bx_min,
                    "y": by_min,
                    "width": round(bx_max - bx_min, 3),
                    "height": round(by_max - by_min, 3)
                }
            else:
                bbox = {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0}

            if self.motion_start_time is None:
                self.motion_start_time = now

            duration_so_far = now - self.motion_start_time
            in_cooldown = (now - self.last_event_time) < cooldown

            if duration_so_far >= min_dur and not in_cooldown:
                # Event confirmed!
                self.last_event_time = now
                self.last_state = "event_triggered"
                # Update background model with learning rate 0.2
                self.background_model = (0.2 * arr) + (0.8 * self.background_model)
                self.last_proc_duration_ms = (time.perf_counter() - t_start) * 1000

                event_data = {
                    "cameraId": self.camera_id,
                    "cameraName": self.name,
                    "score": score_pct,
                    "boundingBox": bbox,
                    "durationSeconds": round(duration_so_far, 1),
                    "originalWidth": orig_w,
                    "originalHeight": orig_h,
                    "timestamp": int(now * 1000),
                    "isoTime": datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S")
                }
                return True, event_data
            else:
                self.last_state = "cooldown" if in_cooldown else "detecting"
        else:
            self.motion_start_time = None
            self.last_state = "idle"
            # Background running average update (slow adaptation)
            self.background_model = (0.05 * arr) + (0.95 * self.background_model)

        self.last_proc_duration_ms = (time.perf_counter() - t_start) * 1000
        return False, None


class MotionDetectorService:
    """Fleet-wide motion detection supervisor, event indexer, and retention service."""

    def __init__(self, config_provider, base_dir: str = None):
        self.config_provider = config_provider
        self.base_dir = base_dir or BASE_DIR
        self.lock = threading.RLock()
        self.trackers = {}
        self.running = False
        self.worker_thread = None

        cfg = self.config_provider().get("motionDetection", {})
        self.config = dict(DEFAULT_MOTION_CONFIG)
        self.config.update(cfg)

        self.storage_dir = os.path.join(self.base_dir, "events")
        os.makedirs(self.storage_dir, exist_ok=True)
        self.index_file = os.path.join(self.storage_dir, "events_index.json")

        self.index = {}  # event_id -> event dict
        self.load_index()

        # Service metrics
        self.analytics_fps = 0.0
        self.last_fps_calc_time = time.time()
        self.frame_counter = 0

        # Local AI Object Detection Engine (Decoupled background worker)
        self.ai_detector = None
        self.ai_worker = None
        self._init_ai()

    def _init_ai(self):
        """Initialize decoupled AI object detector with DirectML/CPU fallback."""
        try:
            from core.ai_detector import LocalObjectDetector, AIObjectDetectorWorker
            full_cfg = self.config_provider()
            ai_cfg = full_cfg.get("aiDetection", {})
            if ai_cfg.get("enabled", True):
                provider = ai_cfg.get("provider", "auto")
                model_path = ai_cfg.get("modelPath")
                if model_path and not os.path.isabs(model_path):
                    model_path = os.path.join(self.base_dir, model_path)
                conf = ai_cfg.get("confidenceThreshold", 0.40)
                nms = ai_cfg.get("nmsThreshold", 0.45)
                targets = ai_cfg.get("targetClasses", ["person", "car", "motorcycle", "animal"])
                max_fps = ai_cfg.get("maxInferenceFps", 2.0)

                self.ai_detector = LocalObjectDetector(
                    model_path=model_path,
                    provider=provider,
                    confidence_threshold=conf,
                    nms_threshold=nms,
                    target_classes=targets
                )
                self.ai_worker = AIObjectDetectorWorker(self.ai_detector, max_fps=max_fps)
                self.ai_worker.start()
                print(f"[MOTION] Local AI Object Detection active with provider: {self.ai_detector.active_provider}", flush=True)
        except Exception as e:
            print(f"[MOTION] AI initialization warning: {e}", file=sys.stderr)

    def _get_camera_ai_config(self, camera_id: str) -> dict:
        """Resolve per-camera AI overrides from config."""
        full_cfg = self.config_provider()
        ai_cfg = full_cfg.get("aiDetection", {})
        cam_overrides = ai_cfg.get("cameras", {}).get(camera_id, {})

        # Also check camera object directly in "cameras" list
        cams = full_cfg.get("cameras", [])
        cam_obj = next((c for c in cams if c.get("id") == camera_id), {})
        inline_overrides = cam_obj.get("aiDetection", {})

        merged = {
            "enabled": ai_cfg.get("enabled", True),
            "confidenceThreshold": ai_cfg.get("confidenceThreshold", 0.40),
            "targetClasses": ai_cfg.get("targetClasses", ["person", "car", "motorcycle", "animal"]),
            "roi": cam_obj.get("roi") or cam_overrides.get("roi")
        }
        merged.update(cam_overrides)
        merged.update(inline_overrides)
        return merged

    def _on_ai_detection(self, detections: list, metadata: dict):
        """Asynchronous callback executed by AIWorkerThread when inference completes."""
        evt_id = metadata.get("event_id")
        if not evt_id:
            return

        with self.lock:
            if evt_id in self.index:
                evt = self.index[evt_id]
                evt["detectedObjects"] = detections
                if detections:
                    # Pick highest confidence detection or prioritize person/car
                    sorted_dets = sorted(detections, key=lambda d: d.get("confidence", 0.0), reverse=True)
                    evt["primaryClass"] = sorted_dets[0]["class"]
                    evt["primaryCategory"] = sorted_dets[0]["category"]
                    evt["primaryConfidence"] = sorted_dets[0]["confidence"]
                    # If high confidence, refine bounding box with the primary object's bounding box
                    if sorted_dets[0]["confidence"] >= 0.40:
                        evt["boundingBox"] = sorted_dets[0]["box"]
                else:
                    evt["primaryClass"] = None
                    evt["primaryCategory"] = None
                    evt["primaryConfidence"] = None
        self.save_index()

    def start(self):
        with self.lock:
            if self.running:
                return
            self.running = True
            self._sync_trackers()
            self.worker_thread = threading.Thread(target=self._run_loop, daemon=True, name="MotionWorker")
            self.worker_thread.start()
            print(f"[MOTION] Motion Detection & Event Timeline active. Storage: {self.storage_dir}", flush=True)

    def stop(self):
        with self.lock:
            self.running = False
        if self.ai_worker:
            self.ai_worker.stop()
        self.save_index()

    def load_index(self):
        if os.path.exists(self.index_file):
            try:
                with open(self.index_file, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        self.index = json.loads(content)
            except Exception as e:
                print(f"[MOTION] Error reading event index: {e}", file=sys.stderr)
        else:
            if not self.index:
                self.index = {}

    def save_index(self):
        with self.lock:
            try:
                tmp_file = f"{self.index_file}.tmp.{os.getpid()}"
                with open(tmp_file, "w", encoding="utf-8") as f:
                    json.dump(self.index, f, indent=2)
                for _ in range(3):
                    try:
                        os.replace(tmp_file, self.index_file)
                        break
                    except OSError:
                        time.sleep(0.05)
                else:
                    with open(self.index_file, "w", encoding="utf-8") as f:
                        json.dump(self.index, f, indent=2)
                    if os.path.exists(tmp_file):
                        try:
                            os.remove(tmp_file)
                        except:
                            pass
            except Exception as e:
                print(f"[MOTION] Error saving event index: {e}", file=sys.stderr)

    def _sync_trackers(self):
        cfg = self.config_provider()
        global_motion_cfg = cfg.get("motionDetection", {})
        cameras = cfg.get("cameras", [])

        with self.lock:
            active_ids = set()
            for cam in cameras:
                cid = cam.get("id")
                name = cam.get("name", cid)
                port = cam.get("port", 8080)
                snapshot_url = f"http://127.0.0.1:{port}/snapshot"
                active_ids.add(cid)

                merged_cfg = dict(DEFAULT_MOTION_CONFIG)
                merged_cfg.update(global_motion_cfg)
                if "motionDetection" in cam:
                    merged_cfg.update(cam["motionDetection"])

                if cid not in self.trackers:
                    self.trackers[cid] = CameraMotionTracker(cid, name, snapshot_url, merged_cfg)
                else:
                    self.trackers[cid].snapshot_url = snapshot_url
                    self.trackers[cid].config = merged_cfg

            # Remove deleted
            to_remove = [cid for cid in self.trackers if cid not in active_ids]
            for cid in to_remove:
                del self.trackers[cid]

    def _fetch_snapshot(self, url: str) -> bytes:
        try:
            req = Request(url, headers={"User-Agent": "CamHub-MotionDetector/1.0"})
            with urlopen(req, timeout=0.8) as resp:
                if resp.status == 200:
                    return resp.read()
        except:
            return None

    def _record_event(self, event_data: dict, snapshot_bytes: bytes):
        cid = event_data["cameraId"]
        now_sec = (event_data["timestamp"] / 1000.0) if "timestamp" in event_data else time.time()
        date_str = datetime.fromtimestamp(now_sec).strftime("%Y-%m-%d")
        time_slug = datetime.fromtimestamp(now_sec).strftime("%Y%m%d_%H%M%S")
        evt_id = f"evt_{cid}_{time_slug}_{uuid.uuid4().hex[:6]}"

        # Folder structure: events/<camera_id>/YYYY-MM-DD/<event_id>.jpg
        date_folder = os.path.join(self.storage_dir, cid, date_str)
        os.makedirs(date_folder, exist_ok=True)
        img_filename = f"{evt_id}.jpg"
        img_path = os.path.join(date_folder, img_filename)

        try:
            with open(img_path, "wb") as f:
                f.write(snapshot_bytes)
            size = len(snapshot_bytes)
        except Exception as e:
            print(f"[MOTION] Failed to write snapshot: {e}", file=sys.stderr)
            return

        rel_path = os.path.relpath(img_path, self.base_dir).replace("\\", "/")

        event_record = {
            "id": evt_id,
            "cameraId": cid,
            "cameraName": event_data["cameraName"],
            "score": event_data["score"],
            "timestamp": event_data["timestamp"],
            "isoTime": event_data["isoTime"],
            "date": date_str,
            "durationSeconds": event_data["durationSeconds"],
            "boundingBox": event_data["boundingBox"],
            "snapshotPath": rel_path,
            "fileSizeBytes": size,
            "detectedObjects": [],
            "primaryClass": None,
            "primaryCategory": None,
            "primaryConfidence": None,
            "status": "completed"
        }

        with self.lock:
            self.index[evt_id] = event_record
        self.save_index()
        print(f"[MOTION] Event captured: {evt_id} ({event_data['cameraName']}, score: {event_data['score']}%)", flush=True)

        # Dispatch non-blocking to decoupled AI Object Detection Worker
        if self.ai_worker and self.ai_worker.running:
            cam_ai = self._get_camera_ai_config(cid)
            if cam_ai.get("enabled", True):
                self.ai_worker.submit_frame(snapshot_bytes, {
                    "event_id": evt_id,
                    "cameraId": cid,
                    "confidenceThreshold": cam_ai.get("confidenceThreshold"),
                    "targetClasses": cam_ai.get("targetClasses"),
                    "roi": cam_ai.get("roi"),
                    "callback": self._on_ai_detection
                })

    def _run_loop(self):
        while self.running:
            t_loop = time.time()
            try:
                self._sync_trackers()
                with self.lock:
                    trackers_list = list(self.trackers.values())

                for tracker in trackers_list:
                    # Non-blocking snapshot fetch
                    jpeg_bytes = self._fetch_snapshot(tracker.snapshot_url)
                    if jpeg_bytes and len(jpeg_bytes) > 200:
                        self.frame_counter += 1
                        is_event, event_data = tracker.evaluate_frame(jpeg_bytes)
                        if is_event and event_data:
                            self._record_event(event_data, jpeg_bytes)

                # Calc analytics FPS
                elapsed = time.time() - self.last_fps_calc_time
                if elapsed >= 2.0:
                    self.analytics_fps = round(self.frame_counter / elapsed, 1)
                    self.frame_counter = 0
                    self.last_fps_calc_time = time.time()

                # Retention purge check every 60s
                if int(t_loop) % 60 == 0:
                    self.enforce_retention_policy()

                # Sleep to maintain sampling interval
                interval = self.config.get("samplingIntervalSeconds", 0.5)
                time.sleep(interval)
            except Exception as e:
                time.sleep(1.0)

    def enforce_retention_policy(self):
        """Purges event snapshots older than retentionDays or exceeding maxStorageMb."""
        retention_days = self.config.get("retentionDays", 7)
        max_storage_mb = self.config.get("maxStorageMb", 1000.0)
        now_ts = time.time()
        max_age_sec = retention_days * 86400

        with self.lock:
            items = list(self.index.values())

        purged_ids = []
        for item in items:
            start_sec = item.get("timestamp", 0) / 1000.0
            if (now_ts - start_sec) > max_age_sec:
                purged_ids.append(item["id"])
                self._delete_snapshot_file(item)

        with self.lock:
            for eid in purged_ids:
                if eid in self.index:
                    del self.index[eid]
            items = list(self.index.values())

        # Check max storage MB
        total_bytes = sum(i.get("fileSizeBytes", 0) for i in items)
        max_bytes = max_storage_mb * (1024 * 1024)

        if total_bytes > max_bytes:
            # Sort oldest first
            sorted_items = sorted(items, key=lambda x: x.get("timestamp", 0))
            for item in sorted_items:
                if total_bytes <= max_bytes:
                    break
                self._delete_snapshot_file(item)
                total_bytes -= item.get("fileSizeBytes", 0)
                with self.lock:
                    if item["id"] in self.index:
                        del self.index[item["id"]]

        self.save_index()

    def _delete_snapshot_file(self, item: dict):
        try:
            rel = item.get("snapshotPath")
            if rel:
                full = sanitize_path(self.base_dir, os.path.join(self.base_dir, rel))
                if os.path.exists(full):
                    os.remove(full)
                    parent = os.path.dirname(full)
                    if os.path.exists(parent) and not os.listdir(parent):
                        os.rmdir(parent)
        except:
            pass

    def delete_event(self, event_id: str) -> tuple[bool, str]:
        with self.lock:
            item = self.index.get(event_id)
            if not item:
                return False, f"Event '{event_id}' not found"
            del self.index[event_id]

        self._delete_snapshot_file(item)
        self.save_index()
        return True, f"Deleted event '{event_id}'"

    def enrich_event_with_ai(self, event_id: str) -> Optional[dict]:
        """Run on-demand AI detection on an existing event's snapshot and update index."""
        evt = self.get_event(event_id)
        if not evt:
            return None
        rel_path = evt.get("snapshotPath")
        if not rel_path:
            return None
        full_path = sanitize_path(self.base_dir, os.path.join(self.base_dir, rel_path))
        if not os.path.exists(full_path):
            return None

        if not self.ai_detector:
            return evt

        cam_ai = self._get_camera_ai_config(evt.get("cameraId", ""))
        dets = self.ai_detector.detect(
            full_path,
            conf_threshold=cam_ai.get("confidenceThreshold"),
            target_classes=cam_ai.get("targetClasses"),
            roi=cam_ai.get("roi")
        )
        self._on_ai_detection(dets, {"event_id": event_id})
        return self.get_event(event_id)

    def list_events(
        self,
        camera_id: str = None,
        date_str: str = None,
        min_score: float = None,
        limit: int = 100,
        object_class: str = None,
        category: str = None
    ) -> list:
        self.load_index()
        with self.lock:
            items = list(self.index.values())

        if camera_id:
            items = [i for i in items if i.get("cameraId") == camera_id]
        if date_str:
            items = [i for i in items if i.get("date") == date_str]
        if min_score is not None:
            items = [i for i in items if i.get("score", 0) >= min_score]
        if object_class:
            obj_lower = object_class.lower()
            items = [i for i in items if (i.get("primaryClass") or "").lower() == obj_lower or any(d.get("class", "").lower() == obj_lower for d in i.get("detectedObjects", []))]
        if category:
            cat_lower = category.lower()
            items = [i for i in items if (i.get("primaryCategory") or "").lower() == cat_lower or any(d.get("category", "").lower() == cat_lower for d in i.get("detectedObjects", []))]

        items.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        return items[:limit]

    def get_event(self, event_id: str) -> dict:
        self.load_index()
        with self.lock:
            return self.index.get(event_id)

    def get_stats(self) -> dict:
        self.load_index()
        with self.lock:
            items = list(self.index.values())
            trackers_info = {}
            for cid, t in self.trackers.items():
                trackers_info[cid] = {
                    "score": t.current_score,
                    "state": t.last_state,
                    "latencyMs": round(t.last_proc_duration_ms, 1),
                    "framesAnalyzed": t.processed_frames
                }

        today_str = datetime.now().strftime("%Y-%m-%d")
        today_count = sum(1 for i in items if i.get("date") == today_str)
        total_size_mb = round(sum(i.get("fileSizeBytes", 0) for i in items) / (1024 * 1024), 2)

        ai_metrics = self.ai_worker.get_metrics() if self.ai_worker else {
            "activeProvider": "disabled",
            "isMock": False,
            "totalInferences": 0,
            "droppedFrames": 0,
            "lastLatencyMs": 0.0,
            "inferenceFps": 0.0
        }

        return {
            "analyticsFps": self.analytics_fps,
            "totalEvents": len(items),
            "eventsToday": today_count,
            "storageMb": total_size_mb,
            "maxStorageMb": self.config.get("maxStorageMb", 1000.0),
            "retentionDays": self.config.get("retentionDays", 7),
            "ai": ai_metrics,
            "trackers": trackers_info
        }
