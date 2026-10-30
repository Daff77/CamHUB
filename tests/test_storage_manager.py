"""
Unit Tests for CamHUB Storage Manager (AGENT 8).
Tests disk space monitoring, threshold alerts (80%, 90%, 95%), retention evaluation,
dry-run enforcement, active file protection, playback locks, and self-healing index reconciliation.
"""

import os
import time
import json
import shutil
import tempfile
import unittest

from core.storage_manager import (
    CamHubStorageManager,
    PlaybackLockManager,
    get_disk_usage_stats,
    sanitize_path,
    DEFAULT_STORAGE_CONFIG
)


class TestStorageManager(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="camhub_storage_test_")
        self.recordings_dir = os.path.join(self.temp_dir, "recordings")
        self.events_dir = os.path.join(self.temp_dir, "events")
        os.makedirs(self.recordings_dir, exist_ok=True)
        os.makedirs(self.events_dir, exist_ok=True)

        self.config = {
            "storageManagement": {
                "enabled": True,
                "checkIntervalSeconds": 10.0,
                "warningThresholdPercent": 80.0,
                "criticalThresholdPercent": 90.0,
                "emergencyThresholdPercent": 95.0,
                "minDiskFreeGb": 5.0,
                "retention": {
                    "recordings": {
                        "maxAgeDays": 7,
                        "maxStorageGb": 1.0,
                        "protectActiveRecordings": True,
                        "protectActivePlayback": True
                    },
                    "events": {
                        "maxAgeDays": 7,
                        "maxStorageMb": 50.0
                    },
                    "tempFiles": {
                        "maxAgeHours": 1.0
                    }
                }
            }
        }
        self.manager = CamHubStorageManager(lambda: self.config, base_dir=self.temp_dir)

    def tearDown(self):
        if self.manager:
            self.manager.stop()
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_sanitize_path_safety(self):
        """Verify path traversal outside base directory is blocked."""
        safe_path = os.path.join(self.temp_dir, "recordings", "test.mp4")
        self.assertEqual(sanitize_path(self.temp_dir, safe_path), os.path.abspath(safe_path))

        with self.assertRaises(ValueError):
            sanitize_path(self.temp_dir, os.path.join(self.temp_dir, "..", "secret.txt"))

        with self.assertRaises(ValueError):
            sanitize_path(self.temp_dir, "C:\\Windows\\System32\\calc.exe")

    def test_disk_usage_stats(self):
        """Verify disk usage stats returns valid structure and percentages."""
        stats = get_disk_usage_stats(self.temp_dir)
        self.assertIn("totalBytes", stats)
        self.assertIn("usedPercent", stats)
        self.assertIn("freeGb", stats)
        self.assertTrue(stats["totalBytes"] > 0)
        self.assertTrue(0.0 <= stats["usedPercent"] <= 100.0)

    def test_playback_lock_manager(self):
        """Verify playback lock acquisition, expiration, and release."""
        locks = PlaybackLockManager()
        file_a = "recordings/cam1/2026-10-30/seg001.mp4"

        # Initially unlocked
        self.assertFalse(locks.is_locked(file_a))

        # Acquire lock for 0.2s
        locks.acquire(file_a, lease_seconds=0.2)
        self.assertTrue(locks.is_locked(file_a))
        self.assertIn(file_a, locks.get_active_locks())

        # Wait for expiration
        time.sleep(0.25)
        self.assertFalse(locks.is_locked(file_a))

        # Manual release
        locks.acquire(file_a, lease_seconds=60.0)
        self.assertTrue(locks.is_locked(file_a))
        locks.release(file_a)
        self.assertFalse(locks.is_locked(file_a))

    def test_scan_locations_and_camera_breakdown(self):
        """Verify scan_location groups file count and bytes by camera."""
        # Create dummy event jpgs for 2 cameras
        cam1_dir = os.path.join(self.events_dir, "cam-1", "2026-10-30")
        cam2_dir = os.path.join(self.events_dir, "cam-2", "2026-10-30")
        os.makedirs(cam1_dir, exist_ok=True)
        os.makedirs(cam2_dir, exist_ok=True)

        with open(os.path.join(cam1_dir, "evt1.jpg"), "wb") as f:
            f.write(b"x" * 2048)
        with open(os.path.join(cam1_dir, "evt2.jpg"), "wb") as f:
            f.write(b"x" * 1024)
        with open(os.path.join(cam2_dir, "evt3.jpg"), "wb") as f:
            f.write(b"x" * 4096)

        evt_scan = self.manager.scan_location(self.events_dir, ".jpg")
        self.assertEqual(evt_scan["fileCount"], 3)
        self.assertEqual(evt_scan["totalBytes"], 7168)
        self.assertIn("cam-1", evt_scan["cameras"])
        self.assertIn("cam-2", evt_scan["cameras"])
        self.assertEqual(evt_scan["cameras"]["cam-1"]["count"], 2)
        self.assertEqual(evt_scan["cameras"]["cam-1"]["bytes"], 3072)
        self.assertEqual(evt_scan["cameras"]["cam-2"]["count"], 1)
        self.assertEqual(evt_scan["cameras"]["cam-2"]["bytes"], 4096)

    def test_scan_temp_and_corrupt_files(self):
        """Verify temporary files (.tmp, .part) and 0-byte corrupt files are detected."""
        temp_file = os.path.join(self.recordings_dir, "download.tmp.123")
        part_file = os.path.join(self.recordings_dir, "seg002.mp4.part")
        with open(temp_file, "wb") as f:
            f.write(b"temp" * 100)
        with open(part_file, "wb") as f:
            f.write(b"part" * 100)

        # 0-byte file older than 10 mins
        corrupt_file = os.path.join(self.events_dir, "empty_corrupt.jpg")
        with open(corrupt_file, "wb") as f:
            pass
        old_time = time.time() - 900
        os.utime(corrupt_file, (old_time, old_time))

        scan = self.manager.scan_temp_and_corrupt()
        self.assertEqual(scan["tempFilesCount"], 2)
        self.assertEqual(scan["corruptedFilesCount"], 1)

    def test_retention_dry_run_vs_execution(self):
        """Verify dry-run evaluates files without deleting, and real run safely removes them."""
        # Create an event older than 7 days
        old_date_dir = os.path.join(self.events_dir, "cam-1", "2026-10-01")
        os.makedirs(old_date_dir, exist_ok=True)
        old_jpg = os.path.join(old_date_dir, "evt_old.jpg")
        with open(old_jpg, "wb") as f:
            f.write(b"snapshot" * 100)

        old_timestamp = int((time.time() - (10 * 86400)) * 1000)
        index_file = os.path.join(self.events_dir, "events_index.json")
        with open(index_file, "w", encoding="utf-8") as f:
            json.dump({
                "evt_old": {
                    "id": "evt_old",
                    "cameraId": "cam-1",
                    "timestamp": old_timestamp,
                    "snapshotPath": "events/cam-1/2026-10-01/evt_old.jpg",
                    "fileSizeBytes": 800
                }
            }, f)

        # 1. DRY RUN
        dry = self.manager.evaluate_retention(dry_run=True)
        self.assertTrue(dry["dryRun"])
        self.assertEqual(dry["filesToDeleteCount"], 1)
        self.assertEqual(dry["filesDeletedCount"], 0)
        self.assertTrue(os.path.exists(old_jpg))  # File MUST still exist!

        # 2. REAL EXECUTION
        real = self.manager.evaluate_retention(dry_run=False)
        self.assertFalse(real["dryRun"])
        self.assertEqual(real["filesDeletedCount"], 1)
        self.assertFalse(os.path.exists(old_jpg))  # File now deleted!

        # Check index was updated
        with open(index_file, "r", encoding="utf-8") as f:
            updated_idx = json.load(f)
            self.assertNotIn("evt_old", updated_idx)

    def test_active_file_protection(self):
        """Verify files protected by active recording or active playback are NOT deleted."""
        # Create an old recording that would normally be deleted
        old_dir = os.path.join(self.recordings_dir, "cam-1", "2026-10-01")
        os.makedirs(old_dir, exist_ok=True)
        old_rec = os.path.join(old_dir, "seg_active.mp4")
        with open(old_rec, "wb") as f:
            f.write(b"video" * 1000)

        old_timestamp = int((time.time() - (15 * 86400)) * 1000)
        index_file = os.path.join(self.recordings_dir, "recordings_index.json")
        with open(index_file, "w", encoding="utf-8") as f:
            json.dump({
                "seg_active": {
                    "id": "seg_active",
                    "cameraId": "cam-1",
                    "startTime": old_timestamp,
                    "path": "recordings/cam-1/2026-10-01/seg_active.mp4",
                    "fileSizeBytes": 5000
                }
            }, f)

        # Acquire active playback lock
        self.manager.playback_locks.acquire("recordings/cam-1/2026-10-01/seg_active.mp4", lease_seconds=60.0)

        # Run retention
        res = self.manager.evaluate_retention(dry_run=False)
        # Should be protected by playback lock!
        self.assertEqual(res["filesDeletedCount"], 0)
        self.assertTrue(os.path.exists(old_rec))

        # Release lock and run again
        self.manager.playback_locks.release("recordings/cam-1/2026-10-01/seg_active.mp4")
        res2 = self.manager.evaluate_retention(dry_run=False)
        self.assertEqual(res2["filesDeletedCount"], 1)
        self.assertFalse(os.path.exists(old_rec))

    def test_reconcile_and_repair_index(self):
        """Verify self-healing index recovery: adds missing files and purges ghost records."""
        # 1. Create a physical MP4 on disk without an index entry
        cam_dir = os.path.join(self.recordings_dir, "cam-1", "2026-10-30")
        os.makedirs(cam_dir, exist_ok=True)
        phys_mp4 = os.path.join(cam_dir, "cam1_unindexed.mp4")
        with open(phys_mp4, "wb") as f:
            f.write(b"mp4data" * 100)

        # 2. Create index with a ghost entry whose file doesn't exist on disk
        rec_index_file = os.path.join(self.recordings_dir, "recordings_index.json")
        with open(rec_index_file, "w", encoding="utf-8") as f:
            json.dump({
                "ghost_segment": {
                    "id": "ghost_segment",
                    "cameraId": "cam-1",
                    "path": "recordings/cam-1/2026-10-30/non_existent.mp4"
                }
            }, f)

        reconcile_res = self.manager.reconcile_and_repair_index()
        self.assertEqual(reconcile_res["recordingsGhostPurged"], 1)
        self.assertEqual(reconcile_res["recordingsReconciled"], 1)

        # Verify index now contains the physical file and removed ghost
        with open(rec_index_file, "r", encoding="utf-8") as f:
            idx = json.load(f)
            self.assertNotIn("ghost_segment", idx)
            self.assertIn("cam1_unindexed", idx)

    def test_growth_rate_and_forecasting(self):
        """Verify growth rate calculation and time remaining forecasting."""
        overview = self.manager.get_storage_overview()
        forecasting = overview["forecasting"]
        self.assertIn("growthRateMbPerHour", forecasting)
        self.assertIn("estimatedHoursRemaining", forecasting)
        self.assertIn("status", forecasting)
        self.assertTrue(forecasting["growthRateMbPerHour"] > 0)


if __name__ == "__main__":
    unittest.main()
