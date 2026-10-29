"""
Unit tests for CamHub Smart Health Monitor
Tests state transitions: HEALTHY, DEGRADED, OFFLINE, RECOVERING, UNKNOWN
Tests frozen frame detection, low FPS, reconnect bursts, recovery stabilization,
and sensitive data sanitization.
"""

import os
import sys
import time
import unittest

# Ensure core and root directories are in sys.path
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CORE_DIR = os.path.join(ROOT_DIR, "core")
for p in (ROOT_DIR, CORE_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from core.health_monitor import (
        CameraHealthState,
        CameraHealthTracker,
        CameraHealthMonitor,
        sanitize_sensitive_data,
        DEFAULT_THRESHOLDS
    )
except ImportError:
    from health_monitor import (
        CameraHealthState,
        CameraHealthTracker,
        CameraHealthMonitor,
        sanitize_sensitive_data,
        DEFAULT_THRESHOLDS
    )

class TestSmartHealthMonitor(unittest.TestCase):

    def setUp(self):
        self.thresholds = dict(DEFAULT_THRESHOLDS)
        self.thresholds.update({
            "minFpsHealthy": 5.0,
            "minFpsDegraded": 0.5,
            "frameFreshnessTimeoutSec": 4.0,
            "frozenFrameThresholdSec": 6.0,
            "maxReconnectsDegraded": 2,
            "recoveryStabilitySeconds": 4.0,
            "consecutiveFailuresForOffline": 2
        })
        self.tracker = CameraHealthTracker("cam-test", "Test Camera", 8080, self.thresholds)

    def test_initial_state_is_unknown(self):
        self.assertEqual(self.tracker.state, CameraHealthState.UNKNOWN)
        d = self.tracker.to_dict()
        self.assertEqual(d["status"], "UNKNOWN")

    def test_transition_to_healthy_on_good_metrics(self):
        now = 1000.0
        metrics = {
            "sourceFps": 12.0,
            "totalSourceFrames": 100,
            "latency": {"decodeLatencyMs": 25.0},
            "stages": {"sourceFps": 12.0, "cameraDeclaredFps": 15.0},
            "health": {"queueDepth": 0, "reconnectCount": 0, "decodingErrors": 0}
        }
        self.tracker.evaluate(metrics, b"fake-frame-1", port_open=True, now=now)
        self.assertEqual(self.tracker.state, CameraHealthState.HEALTHY)
        self.assertTrue(self.tracker.latest_checks["fpsAdequate"])
        self.assertTrue(self.tracker.latest_checks["feedAlive"])
        self.assertFalse(self.tracker.latest_checks["streamFrozen"])

    def test_transition_to_degraded_on_low_fps(self):
        now = 1000.0
        # Start healthy
        self.tracker.evaluate({
            "sourceFps": 12.0,
            "totalSourceFrames": 100,
            "stages": {"sourceFps": 12.0}
        }, b"fake-frame-1", port_open=True, now=now)
        self.assertEqual(self.tracker.state, CameraHealthState.HEALTHY)

        # Drop to low FPS (2.0 fps < minFpsHealthy 5.0)
        now += 3.0
        self.tracker.evaluate({
            "sourceFps": 2.0,
            "totalSourceFrames": 106,
            "stages": {"sourceFps": 2.0}
        }, b"fake-frame-2", port_open=True, now=now)

        self.assertEqual(self.tracker.state, CameraHealthState.DEGRADED)
        self.assertIn("Reduced framerate", self.tracker.reason)
        self.assertIsNotNone(self.tracker.incident_started_at)

    def test_transition_to_degraded_on_reconnect_burst(self):
        now = 1000.0
        # Start healthy
        self.tracker.evaluate({
            "sourceFps": 12.0,
            "totalSourceFrames": 100,
            "health": {"reconnectCount": 0}
        }, b"frame-a", port_open=True, now=now)

        # 3 reconnects burst (maxReconnectsDegraded = 2)
        now += 3.0
        self.tracker.evaluate({
            "sourceFps": 12.0,
            "totalSourceFrames": 136,
            "health": {"reconnectCount": 3}
        }, b"frame-b", port_open=True, now=now)

        self.assertEqual(self.tracker.state, CameraHealthState.DEGRADED)
        self.assertIn("reconnects detected", self.tracker.reason)

    def test_frozen_frame_detection(self):
        now = 1000.0
        frame_bytes = b"identical-frozen-frame-content-1234567890" * 10
        # Frame 1
        self.tracker.evaluate({
            "sourceFps": 0.0,
            "totalSourceFrames": 50
        }, frame_bytes, port_open=True, now=now)

        # Frame 2 at +3s (same hash, totalSourceFrames still 50)
        now += 3.0
        self.tracker.evaluate({
            "sourceFps": 0.0,
            "totalSourceFrames": 50
        }, frame_bytes, port_open=True, now=now)

        # Frame 3 at +7s (> frozenFrameThresholdSec 6.0)
        now += 4.0
        self.tracker.evaluate({
            "sourceFps": 0.0,
            "totalSourceFrames": 50
        }, frame_bytes, port_open=True, now=now)

        self.assertEqual(self.tracker.state, CameraHealthState.DEGRADED)
        self.assertTrue(self.tracker.latest_checks["streamFrozen"])
        self.assertIn("Video frozen", self.tracker.reason)

    def test_no_false_positive_on_static_scene_when_frames_advance(self):
        """When scene is static at night but camera continues advancing frame counter, do NOT flag frozen."""
        now = 1000.0
        static_frame_bytes = b"black-room-static-frame-1234567890" * 10
        # Initialize
        self.tracker.evaluate({
            "sourceFps": 10.0,
            "totalSourceFrames": 100
        }, static_frame_bytes, port_open=True, now=now)

        # Even 10s later with exact same byte payload, frames are steadily advancing (100 -> 200)
        now += 10.0
        self.tracker.evaluate({
            "sourceFps": 10.0,
            "totalSourceFrames": 200
        }, static_frame_bytes, port_open=True, now=now)

        self.assertFalse(self.tracker.latest_checks["streamFrozen"])
        self.assertEqual(self.tracker.state, CameraHealthState.HEALTHY)

    def test_offline_on_port_closed_with_debounce(self):
        now = 1000.0
        # Start healthy
        self.tracker.evaluate({"sourceFps": 12.0, "totalSourceFrames": 100}, b"f", port_open=True, now=now)

        # First port closed check (debounces to DEGRADED on failure 1)
        now += 3.0
        self.tracker.evaluate(None, None, port_open=False, now=now)
        self.assertEqual(self.tracker.state, CameraHealthState.DEGRADED)

        # Second consecutive failure -> OFFLINE
        now += 3.0
        self.tracker.evaluate(None, None, port_open=False, now=now)
        self.assertEqual(self.tracker.state, CameraHealthState.OFFLINE)
        self.assertIn("offline or not running", self.tracker.reason)

    def test_recovery_lifecycle_and_stabilization(self):
        now = 1000.0
        # Put camera in OFFLINE state
        self.tracker.evaluate(None, None, port_open=False, now=now)
        self.tracker.evaluate(None, None, port_open=False, now=now + 1)
        self.assertEqual(self.tracker.state, CameraHealthState.OFFLINE)

        # Stream comes back online with good metrics -> Enters RECOVERING
        now += 5.0
        self.tracker.evaluate({
            "sourceFps": 12.0,
            "totalSourceFrames": 10,
            "stages": {"sourceFps": 12.0}
        }, b"frame-1", port_open=True, now=now)

        self.assertEqual(self.tracker.state, CameraHealthState.RECOVERING)
        self.assertIn("Verifying stability", self.tracker.reason)

        # 2 seconds later (within 4s stability window): still RECOVERING
        now += 2.0
        self.tracker.evaluate({
            "sourceFps": 12.0,
            "totalSourceFrames": 34,
            "stages": {"sourceFps": 12.0}
        }, b"frame-2", port_open=True, now=now)
        self.assertEqual(self.tracker.state, CameraHealthState.RECOVERING)

        # 5 seconds later (> 4.0s stability window): transitions to HEALTHY!
        now += 3.0
        self.tracker.evaluate({
            "sourceFps": 12.0,
            "totalSourceFrames": 70,
            "stages": {"sourceFps": 12.0}
        }, b"frame-3", port_open=True, now=now)
        self.assertEqual(self.tracker.state, CameraHealthState.HEALTHY)
        self.assertIn("Stream healthy and stable", self.tracker.reason)
        self.assertIsNone(self.tracker.incident_started_at)

    def test_zombie_server_detection(self):
        """Port is open, but frame counter stalled for longer than 3x freshness timeout."""
        now = 1000.0
        # Initialize
        self.tracker.evaluate({"sourceFps": 12.0, "totalSourceFrames": 100}, b"f", port_open=True, now=now)

        # Frame counter completely stopped for 15s (freshness timeout is 4.0s)
        now += 15.0
        self.tracker.evaluate({"sourceFps": 0.0, "totalSourceFrames": 100}, b"f", port_open=True, now=now)

        self.assertEqual(self.tracker.state, CameraHealthState.OFFLINE)
        self.assertIn("Stream stalled", self.tracker.reason)

    def test_sanitize_sensitive_data(self):
        url = "rtsp://admin:SecretPass123@192.168.100.6:10554/tcp/av0_0"
        sanitized = sanitize_sensitive_data(url)
        self.assertNotIn("SecretPass123", sanitized)
        self.assertIn("rtsp://admin:***@192.168.100.6:10554/tcp/av0_0", sanitized)

        cmd = "dotnet run -- --username hendra --password MySecretPassword --ip 192.168.100.24"
        sanitized_cmd = sanitize_sensitive_data(cmd)
        self.assertNotIn("MySecretPassword", sanitized_cmd)
        self.assertIn("--password ***", sanitized_cmd)

    def test_fleet_health_summary_aggregation(self):
        def dummy_cfg():
            return {
                "cameras": [
                    {"id": "cam-1", "name": "Cam 1", "port": 8080},
                    {"id": "cam-2", "name": "Cam 2", "port": 8081}
                ]
            }

        monitor = CameraHealthMonitor(dummy_cfg)
        monitor._sync_cameras()
        summary = monitor.get_all_health()

        self.assertEqual(summary["summary"]["total"], 2)
        self.assertEqual(summary["summary"]["unknown"], 2)
        self.assertIn("cam-1", summary["cameras"])
        self.assertIn("cam-2", summary["cameras"])


if __name__ == "__main__":
    unittest.main()

