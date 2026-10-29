"""
Unit tests for CamHUB Motion Detection & Event Timeline (Agent 5).
Validates static scene suppression, motion detection & bounding box accuracy,
lighting switch filter, cooldown enforcement, retention purge, and path traversal safety.
"""

import os
import io
import time
import shutil
import tempfile
import unittest
from datetime import datetime
from PIL import Image, ImageDraw

from motion_detector import (
    CameraMotionTracker,
    MotionDetectorService,
    sanitize_path,
    DEFAULT_MOTION_CONFIG
)

def create_synthetic_frame(width=320, height=180, base_color=80, box=None) -> bytes:
    """Generates synthetic JPEG bytes with optional highlighted moving box."""
    img = Image.new("L", (width, height), color=base_color)
    if box:
        draw = ImageDraw.Draw(img)
        draw.rectangle(box, fill=230)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return buf.getvalue()


class TestMotionDetection(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="camhub_motion_test_")
        self.config = {
            "enabled": True,
            "samplingIntervalSeconds": 0.1,
            "analysisWidth": 320,
            "analysisHeight": 180,
            "motionThreshold": 25.0,
            "minMotionAreaPercent": 2.0,
            "maxMotionAreaPercent": 65.0,
            "cooldownSeconds": 10.0,
            "minEventDurationSeconds": 0.4,
            "retentionDays": 3,
            "maxStorageMb": 5.0
        }

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_static_scene_no_motion(self):
        """Identical or near-identical frames should never trigger a motion event."""
        tracker = CameraMotionTracker("cam-1", "Camera 1", "http://fake/snapshot", self.config)
        static_frame = create_synthetic_frame(base_color=100)

        t0 = 1000.0
        # Initialize background model
        is_evt, data = tracker.evaluate_frame(static_frame, now=t0)
        self.assertFalse(is_evt)
        self.assertIsNone(data)
        self.assertIsNotNone(tracker.background_model)

        # 10 consecutive identical frames
        for step in range(1, 11):
            is_evt, data = tracker.evaluate_frame(static_frame, now=t0 + step * 0.1)
            self.assertFalse(is_evt)
            self.assertIsNone(data)
            self.assertEqual(tracker.current_score, 0.0)
            self.assertEqual(tracker.last_state, "idle")

    def test_moving_object_detects_event_and_bounding_box(self):
        """A persistent moving object should trigger a confirmed event with bounding box."""
        tracker = CameraMotionTracker("cam-1", "Camera 1", "http://fake/snapshot", self.config)
        empty_frame = create_synthetic_frame(base_color=50)

        t0 = 1000.0
        # Initial frame to learn background
        tracker.evaluate_frame(empty_frame, now=t0)

        # Moving box covering ~10% of frame: (40, 30) to (140, 110)
        # Area: 100 x 80 = 8000 pixels / (320*180 = 57600) ~ 13.8%
        box_coords = [40, 30, 140, 110]
        motion_frame = create_synthetic_frame(base_color=50, box=box_coords)

        # Frame 1 of motion: duration = 0.0s (< min 0.4s) -> detecting state
        is_evt1, data1 = tracker.evaluate_frame(motion_frame, now=t0 + 0.1)
        self.assertFalse(is_evt1)
        self.assertEqual(tracker.last_state, "detecting")
        self.assertGreater(tracker.current_score, 5.0)

        # Frame 2: duration = 0.2s (< min 0.4s) -> detecting state
        is_evt2, data2 = tracker.evaluate_frame(motion_frame, now=t0 + 0.3)
        self.assertFalse(is_evt2)

        # Frame 3: duration = 0.5s (>= min 0.4s) -> event confirmed!
        is_evt3, data3 = tracker.evaluate_frame(motion_frame, now=t0 + 0.6)
        self.assertTrue(is_evt3)
        self.assertIsNotNone(data3)
        self.assertEqual(data3["cameraId"], "cam-1")
        self.assertGreater(data3["score"], 5.0)

        # Bounding box verification (normalized 0.0 - 1.0)
        bbox = data3["boundingBox"]
        self.assertAlmostEqual(bbox["x"], 40 / 320, delta=0.05)
        self.assertAlmostEqual(bbox["y"], 30 / 180, delta=0.05)
        self.assertAlmostEqual(bbox["width"], 100 / 320, delta=0.05)
        self.assertAlmostEqual(bbox["height"], 80 / 180, delta=0.05)

    def test_global_lighting_change_suppression(self):
        """Sudden brightness change across > 65% of frame should adapt background, not trigger event."""
        tracker = CameraMotionTracker("cam-1", "Camera 1", "http://fake/snapshot", self.config)
        dark_room = create_synthetic_frame(base_color=20)
        bright_room = create_synthetic_frame(base_color=200)

        t0 = 1000.0
        # Background initialized to dark
        tracker.evaluate_frame(dark_room, now=t0)

        # Suddenly room lights turn on (100% of frame changes by 180 delta)
        is_evt, data = tracker.evaluate_frame(bright_room, now=t0 + 0.5)
        self.assertFalse(is_evt)
        self.assertIsNone(data)
        self.assertEqual(tracker.last_state, "lighting_change")
        self.assertGreater(tracker.current_score, 65.0)

        # Subsequent bright frame should be evaluated against new bright background -> 0% diff
        is_evt2, data2 = tracker.evaluate_frame(bright_room, now=t0 + 0.7)
        self.assertFalse(is_evt2)
        self.assertEqual(tracker.current_score, 0.0)

    def test_cooldown_timer_prevents_duplicate_events(self):
        """Once an event fires, motion within cooldown period should be suppressed."""
        tracker = CameraMotionTracker("cam-1", "Camera 1", "http://fake/snapshot", self.config)
        empty_frame = create_synthetic_frame(base_color=50)
        motion_frame = create_synthetic_frame(base_color=50, box=[50, 50, 150, 150])

        t0 = 1000.0
        tracker.evaluate_frame(empty_frame, now=t0)

        # Trigger first event
        tracker.evaluate_frame(motion_frame, now=t0 + 0.1)
        is_evt1, _ = tracker.evaluate_frame(motion_frame, now=t0 + 0.6)
        self.assertTrue(is_evt1)

        # Motion continues at t0 + 2.0s (within 10s cooldown)
        is_evt2, _ = tracker.evaluate_frame(motion_frame, now=t0 + 2.0)
        self.assertFalse(is_evt2)
        self.assertEqual(tracker.last_state, "cooldown")

        # After cooldown passes (t0 + 12.0s)
        is_evt3, _ = tracker.evaluate_frame(motion_frame, now=t0 + 12.0)
        self.assertTrue(is_evt3)

    def test_retention_policy_age_and_capacity(self):
        """Expired events or exceeding max storage should be pruned safely."""
        config_provider = lambda: {
            "cameras": [{"id": "cam-test", "name": "Test Cam", "port": 8080}],
            "motionDetection": {
                "retentionDays": 2,
                "maxStorageMb": 0.001  # ~1 KB capacity to force capacity purge
            }
        }
        service = MotionDetectorService(config_provider, base_dir=self.temp_dir)
        now = time.time()

        # Add 3 mock events
        # Event 1: 5 days old (should be purged by age)
        old_time = now - (5 * 86400)
        service._record_event({
            "cameraId": "cam-test",
            "cameraName": "Test Cam",
            "score": 15.0,
            "boundingBox": {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2},
            "durationSeconds": 1.0,
            "originalWidth": 320,
            "originalHeight": 180,
            "timestamp": int(old_time * 1000),
            "isoTime": datetime.fromtimestamp(old_time).strftime("%Y-%m-%d %H:%M:%S")
        }, b"X" * 2000)

        # Event 2: recent but will be pruned by capacity
        recent_1 = now - 50
        service._record_event({
            "cameraId": "cam-test",
            "cameraName": "Test Cam",
            "score": 25.0,
            "boundingBox": {"x": 0.2, "y": 0.2, "width": 0.2, "height": 0.2},
            "durationSeconds": 1.2,
            "originalWidth": 320,
            "originalHeight": 180,
            "timestamp": int(recent_1 * 1000),
            "isoTime": datetime.fromtimestamp(recent_1).strftime("%Y-%m-%d %H:%M:%S")
        }, b"Y" * 2000)

        # Event 3: newest
        recent_2 = now - 10
        service._record_event({
            "cameraId": "cam-test",
            "cameraName": "Test Cam",
            "score": 35.0,
            "boundingBox": {"x": 0.3, "y": 0.3, "width": 0.2, "height": 0.2},
            "durationSeconds": 1.5,
            "originalWidth": 320,
            "originalHeight": 180,
            "timestamp": int(recent_2 * 1000),
            "isoTime": datetime.fromtimestamp(recent_2).strftime("%Y-%m-%d %H:%M:%S")
        }, b"Z" * 500)

        self.assertEqual(len(service.index), 3)

        # Run retention enforcement
        service.enforce_retention_policy()

        # Event 1 (old) should be purged by age.
        # Total capacity is set to 1KB, Event 2 is 2KB, so Event 2 is also purged.
        # Only Event 3 (500 bytes < 1024 bytes) survives.
        self.assertEqual(len(service.index), 1)
        remaining = list(service.index.values())[0]
        self.assertEqual(remaining["score"], 35.0)

    def test_sanitize_path_prevents_traversal(self):
        """Sanitize path must deny directory traversal attempts."""
        safe = sanitize_path(self.temp_dir, os.path.join(self.temp_dir, "events", "img.jpg"))
        self.assertTrue(safe.startswith(os.path.abspath(self.temp_dir)))

        with self.assertRaises(ValueError):
            sanitize_path(self.temp_dir, os.path.join(self.temp_dir, "..", "..", "Windows", "System32"))

    def test_api_list_and_delete_event(self):
        """List events with filtering and delete event cleanly."""
        config_provider = lambda: {"cameras": [], "motionDetection": {}}
        service = MotionDetectorService(config_provider, base_dir=self.temp_dir)
        now = time.time()

        service._record_event({
            "cameraId": "cam-a",
            "cameraName": "Camera A",
            "score": 10.0,
            "boundingBox": {"x": 0, "y": 0, "width": 0.5, "height": 0.5},
            "durationSeconds": 1.0,
            "originalWidth": 320,
            "originalHeight": 180,
            "timestamp": int(now * 1000),
            "isoTime": datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S")
        }, b"DATA_A")

        service._record_event({
            "cameraId": "cam-b",
            "cameraName": "Camera B",
            "score": 45.0,
            "boundingBox": {"x": 0.1, "y": 0.1, "width": 0.3, "height": 0.3},
            "durationSeconds": 2.0,
            "originalWidth": 320,
            "originalHeight": 180,
            "timestamp": int((now + 1) * 1000),
            "isoTime": datetime.fromtimestamp(now + 1).strftime("%Y-%m-%d %H:%M:%S")
        }, b"DATA_B")

        # Filter by camera
        items_a = service.list_events(camera_id="cam-a")
        self.assertEqual(len(items_a), 1)
        self.assertEqual(items_a[0]["cameraId"], "cam-a")

        # Filter by min_score
        items_high = service.list_events(min_score=30.0)
        self.assertEqual(len(items_high), 1)
        self.assertEqual(items_high[0]["cameraId"], "cam-b")

        # Delete event
        evt_to_del = items_high[0]["id"]
        ok, msg = service.delete_event(evt_to_del)
        self.assertTrue(ok)
        self.assertEqual(len(service.list_events()), 1)


if __name__ == "__main__":
    unittest.main()
