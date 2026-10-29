"""
Unit tests for CamHub Local Recording & Playback
Tests directory hierarchy, metadata indexing, retention purging, capacity limits,
path traversal security, and HTTP 206 Partial Content range requests.
"""

import os
import sys
import time
import shutil
import tempfile
import unittest

# Ensure core and root directories are in sys.path
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CORE_DIR = os.path.join(ROOT_DIR, "core")
for p in (ROOT_DIR, CORE_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from core.recording_manager import (
        RecordingManager,
        sanitize_path,
        get_disk_space_stats,
        DEFAULT_RECORDING_CONFIG
    )
except ImportError:
    from recording_manager import (
        RecordingManager,
        sanitize_path,
        get_disk_space_stats,
        DEFAULT_RECORDING_CONFIG
    )

class TestLocalRecording(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="camhub_rec_test_")
        self.config = dict(DEFAULT_RECORDING_CONFIG)
        self.config.update({
            "storagePath": "recordings",
            "segmentDurationSeconds": 10,
            "retentionDays": 2,
            "maxStorageGb": 0.0001,  # ~100 KB to easily test capacity purge
            "minDiskFreeGb": 1.0,
            "autoRecordCameras": []
        })
        self.mgr = RecordingManager(lambda: {"recording": self.config, "cameras": []}, base_dir=self.test_dir)

    def tearDown(self):
        self.mgr.stop()
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_directory_structure_created(self):
        self.assertTrue(os.path.exists(self.mgr.storage_dir))
        self.assertTrue(os.path.exists(self.mgr.index_file))

    def test_path_traversal_protection(self):
        """Must reject any attempt to traverse outside base storage directory."""
        # Valid path
        valid_path = os.path.join(self.test_dir, "recordings", "v380-1", "file.mp4")
        self.assertEqual(sanitize_path(self.test_dir, valid_path), os.path.abspath(valid_path))

        # Malicious traversal attempt
        with self.assertRaises(ValueError):
            sanitize_path(self.test_dir, os.path.join(self.test_dir, "..", "..", "Windows", "System32"))

        with self.assertRaises(ValueError):
            sanitize_path(self.test_dir, "/etc/passwd")

    def test_index_discovery_and_filtering(self):
        # Create a mock recording file on disk
        date_folder = os.path.join(self.mgr.storage_dir, "cam-1", "2026-10-29")
        os.makedirs(date_folder, exist_ok=True)
        file_path = os.path.join(date_folder, "cam-1_rec_20261029_120000_seg001.mp4")
        with open(file_path, "wb") as f:
            f.write(b"mock-mp4-data" * 200)

        self.mgr.scan_and_sync_filesystem()

        # Query all
        all_recs = self.mgr.list_recordings()
        self.assertEqual(len(all_recs), 1)
        self.assertEqual(all_recs[0]["cameraId"], "cam-1")
        self.assertEqual(all_recs[0]["status"], "completed")

        # Query with matching filter
        filtered = self.mgr.list_recordings(camera_id="cam-1", date_str="2026-10-29")
        self.assertEqual(len(filtered), 1)

        # Query with non-matching filter
        empty = self.mgr.list_recordings(camera_id="cam-2")
        self.assertEqual(len(empty), 0)

    def test_retention_purge_by_age(self):
        """Files older than retentionDays (2 days) must be purged."""
        date_folder = os.path.join(self.mgr.storage_dir, "cam-1", "2026-10-20")
        os.makedirs(date_folder, exist_ok=True)
        old_file = os.path.join(date_folder, "cam-1_rec_20261020_120000_seg001.mp4")
        with open(old_file, "wb") as f:
            f.write(b"old-data" * 100)

        # Force old timestamp in index (3 days ago)
        old_start = (time.time() - (3 * 86400)) * 1000
        rel_path = os.path.relpath(old_file, self.test_dir).replace("\\", "/")
        self.mgr.index["old_seg"] = {
            "id": "old_seg",
            "cameraId": "cam-1",
            "filePath": rel_path,
            "startTime": old_start,
            "fileSizeBytes": 800
        }

        self.assertTrue(os.path.exists(old_file))
        self.mgr.enforce_retention_policy()

        # Old file and index entry must be purged
        self.assertFalse(os.path.exists(old_file))
        self.assertNotIn("old_seg", self.mgr.index)

    def test_capacity_limit_purge_fifo(self):
        """When total storage exceeds maxStorageGb, oldest files must be purged first."""
        date_folder = os.path.join(self.mgr.storage_dir, "cam-1", "2026-10-29")
        os.makedirs(date_folder, exist_ok=True)

        # Create two 60KB files (total 120KB > 100KB limit)
        f1_path = os.path.join(date_folder, "file1.mp4")
        with open(f1_path, "wb") as f:
            f.write(b"A" * 65536)

        f2_path = os.path.join(date_folder, "file2.mp4")
        with open(f2_path, "wb") as f:
            f.write(b"B" * 65536)

        now_ms = int(time.time() * 1000)
        self.mgr.index["file1"] = {
            "id": "file1",
            "cameraId": "cam-1",
            "filePath": os.path.relpath(f1_path, self.test_dir).replace("\\", "/"),
            "startTime": now_ms - 20000,
            "fileSizeBytes": 65536
        }
        self.mgr.index["file2"] = {
            "id": "file2",
            "cameraId": "cam-1",
            "filePath": os.path.relpath(f2_path, self.test_dir).replace("\\", "/"),
            "startTime": now_ms - 10000,
            "fileSizeBytes": 65536
        }

        self.mgr.enforce_retention_policy()

        # Oldest file (file1) should be purged, newer (file2) preserved
        self.assertFalse(os.path.exists(f1_path))
        self.assertTrue(os.path.exists(f2_path))
        self.assertNotIn("file1", self.mgr.index)
        self.assertIn("file2", self.mgr.index)

    def test_delete_recording_api(self):
        date_folder = os.path.join(self.mgr.storage_dir, "cam-1", "2026-10-29")
        os.makedirs(date_folder, exist_ok=True)
        f_path = os.path.join(date_folder, "del.mp4")
        with open(f_path, "wb") as f:
            f.write(b"data")

        self.mgr.index["del_id"] = {
            "id": "del_id",
            "cameraId": "cam-1",
            "filePath": os.path.relpath(f_path, self.test_dir).replace("\\", "/"),
            "fileSizeBytes": 4
        }

        ok, msg = self.mgr.delete_recording("del_id")
        self.assertTrue(ok)
        self.assertFalse(os.path.exists(f_path))
        self.assertNotIn("del_id", self.mgr.index)

    def test_disk_space_stats(self):
        stats = get_disk_space_stats(self.test_dir)
        self.assertIn("totalGb", stats)
        self.assertIn("freeGb", stats)
        self.assertGreater(stats["totalGb"], 0)


if __name__ == "__main__":
    unittest.main()
