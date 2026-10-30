"""
Unit tests for CamHUB Notification Center.
Tests deduplication, cooldown grouping, acknowledgment, filtering, and credential sanitization.
"""

import os
import shutil
import tempfile
import unittest
import json

from core.notification_center import (
    NotificationCenter,
    DEFAULT_NOTIF_CONFIG,
    sanitize_text,
    mask_token
)


class TestNotificationCenter(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.config = {
            "notifications": {
                "enabled": True,
                "cooldowns": {
                    "camera_offline": 10,
                    "low_fps": 5,
                    "stream_frozen": 5,
                    "decoder_restart": 5,
                    "motion_detected": 5,
                    "storage_warning": 10
                },
                "categories": {
                    "camera_offline": {"enabled": True, "severity": "critical"},
                    "low_fps": {"enabled": True, "severity": "warning"},
                    "stream_frozen": {"enabled": True, "severity": "critical"},
                    "decoder_restart": {"enabled": True, "severity": "warning"},
                    "motion_detected": {"enabled": True, "severity": "info"},
                    "storage_warning": {"enabled": True, "severity": "warning"}
                },
                "telegram": {
                    "enabled": False,
                    "botToken": "",
                    "chatId": ""
                }
            }
        }
        self.nc = NotificationCenter(lambda: self.config, base_dir=self.test_dir)

    def tearDown(self):
        self.nc.stop()
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_notify_creation_and_stats(self):
        notif = self.nc.notify(
            category="camera_offline",
            camera_id="v380-1",
            camera_name="Indoor Camera",
            severity="critical",
            title="Camera Offline",
            message="Connection refused to RTSP port",
            action_url="#camera-v380-1"
        )
        self.assertIsNotNone(notif)
        self.assertEqual(notif["category"], "camera_offline")
        self.assertEqual(notif["cameraId"], "v380-1")
        self.assertEqual(notif["severity"], "critical")
        self.assertFalse(notif["acknowledged"])
        self.assertEqual(notif["count"], 1)

        stats = self.nc.get_stats()
        self.assertEqual(stats["totalCount"], 1)
        self.assertEqual(stats["unreadCount"], 1)
        self.assertEqual(stats["bySeverity"]["critical"], 1)

    def test_deduplication_and_cooldown(self):
        # First notification
        n1 = self.nc.notify(
            category="camera_offline",
            camera_id="cam-1",
            camera_name="Cam 1",
            severity="critical",
            title="Offline",
            message="First drop"
        )
        self.assertEqual(n1["count"], 1)

        # Immediate second notification (within cooldown)
        n2 = self.nc.notify(
            category="camera_offline",
            camera_id="cam-1",
            camera_name="Cam 1",
            severity="critical",
            title="Offline again",
            message="Second drop"
        )
        # Should return same grouped notification with count = 2
        self.assertEqual(n2["id"], n1["id"])
        self.assertEqual(n2["count"], 2)

        # Notification list should only contain 1 grouped item
        items = self.nc.list_notifications()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["count"], 2)

    def test_acknowledgment(self):
        n = self.nc.notify(
            category="low_fps",
            camera_id="cam-2",
            camera_name="Cam 2",
            severity="warning",
            title="Low FPS",
            message="FPS dropped to 4.2"
        )
        self.assertFalse(n["acknowledged"])

        # Ack single
        ack_count = self.nc.acknowledge(notification_id=n["id"])
        self.assertEqual(ack_count, 1)

        items = self.nc.list_notifications()
        self.assertTrue(items[0]["acknowledged"])

        # Stats should show 0 unread
        stats = self.nc.get_stats()
        self.assertEqual(stats["unreadCount"], 0)

    def test_filtering(self):
        self.nc.notify("camera_offline", "cam-1", "Cam 1", "critical", "Offline", "msg")
        self.nc.notify("low_fps", "cam-2", "Cam 2", "warning", "Low FPS", "msg")
        self.nc.notify("motion_detected", "cam-3", "Cam 3", "info", "Motion", "msg")

        # Filter by severity
        crit = self.nc.list_notifications(severity="critical")
        self.assertEqual(len(crit), 1)
        self.assertEqual(crit[0]["cameraId"], "cam-1")

        # Filter by camera
        cam2 = self.nc.list_notifications(camera_id="cam-2")
        self.assertEqual(len(cam2), 1)

        # Filter by category
        motion = self.nc.list_notifications(category="motion_detected")
        self.assertEqual(len(motion), 1)

    def test_clear_notifications(self):
        n1 = self.nc.notify("camera_offline", "cam-1", "Cam 1", "critical", "Offline", "msg")
        n2 = self.nc.notify("low_fps", "cam-2", "Cam 2", "warning", "Low FPS", "msg")

        # Delete single
        deleted = self.nc.clear(notification_id=n1["id"])
        self.assertEqual(deleted, 1)
        self.assertEqual(len(self.nc.list_notifications()), 1)

        # Clear all
        cleared = self.nc.clear(all_notifications=True)
        self.assertEqual(cleared, 1)
        self.assertEqual(len(self.nc.list_notifications()), 0)

    def test_credential_sanitization(self):
        raw_text = "Failed to connect to rtsp://admin:SecretPass123@192.168.1.100:554/live and token 123456789:ABCdefGHIjklMNOpqrSTUvwxYZ"
        sanitized = sanitize_text(raw_text)
        self.assertNotIn("SecretPass123", sanitized)
        self.assertIn("rtsp://admin:***@192.168.1.100:554/live", sanitized)
        self.assertNotIn("123456789:ABCdefGHIjklMNOpqrSTUvwxYZ", sanitized)
        self.assertIn("[BOT_TOKEN_REDACTED]", sanitized)

        # Token masking
        token = "123456789:ABCdefGHIjklMNOpqrSTUvwxYZ"
        masked = mask_token(token)
        self.assertTrue(masked.startswith("1234"))
        self.assertTrue(masked.endswith("xYZ"))
        self.assertIn("...", masked)

    def test_simulation(self):
        sim = self.nc.simulate_event(
            category="storage_warning",
            camera_id="disk",
            camera_name="Local Disk",
            severity="warning"
        )
        self.assertIsNotNone(sim)
        self.assertEqual(sim["category"], "storage_warning")
        self.assertEqual(sim["severity"], "warning")
        self.assertTrue(len(sim["title"]) > 0)


if __name__ == "__main__":
    unittest.main()
