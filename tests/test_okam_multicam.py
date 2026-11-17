"""
Unit Tests for CamHUB O-Kam Multi-Camera Support
Tests multi-camera configuration, independent workers, separate buffers,
API endpoints (/api/cameras, /api/cameras/{id}/...), and backward compatibility.
"""

import unittest
import time
import json
import threading
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from core.okam_adapter import (
    CameraStreamWorker,
    MultiCameraManager,
    ThreadedServer,
    HttpHandler,
    sanitize_rtsp_url,
    extract_jpeg_dimensions,
    create_manager_from_config
)


class TestOkamMultiCamera(unittest.TestCase):

    def setUp(self):
        self.manager = MultiCameraManager()
        self.manager.register_camera(
            camera_id="okam_1",
            name="Camera 3 · O-Kam Lens 1 (Main)",
            rtsp_url="rtsp://admin:SecretPass1@192.168.100.6:10554/tcp/av0_0",
            resolution="1920x1080",
            aliases=["okam-3", "okam-1"]
        )
        self.manager.register_camera(
            camera_id="okam_2",
            name="Camera 4 · O-Kam Lens 2 (Wide)",
            rtsp_url="rtsp://admin:SecretPass2@192.168.100.6:10555/tcp/av0_0",
            resolution="1920x1080",
            aliases=["okam-2"]
        )
        self.manager.register_camera(
            camera_id="okam_3",
            name="Camera 5 · O-Kam Lens 3 (Sub)",
            rtsp_url="rtsp://admin:SecretPass3@192.168.100.6:10554/tcp/av0_1",
            resolution="448x256",
            aliases=["okam-sub"]
        )

    def test_sanitize_rtsp_url(self):
        raw = "rtsp://admin:Danendra07.@192.168.100.6:10554/tcp/av0_0"
        clean = sanitize_rtsp_url(raw)
        self.assertNotIn("Danendra07.", clean)
        self.assertIn("rtsp://admin:***@192.168.100.6:10554/tcp/av0_0", clean)

    def test_manager_registration_and_aliases(self):
        w1 = self.manager.get_worker("okam_1")
        self.assertIsNotNone(w1)
        self.assertEqual(w1.camera_id, "okam_1")

        # Alias lookup
        w_alias = self.manager.get_worker("okam-3")
        self.assertEqual(w1, w_alias)

        w2 = self.manager.get_worker("okam_2")
        self.assertIsNotNone(w2)
        self.assertEqual(w2.camera_id, "okam_2")

        w3 = self.manager.get_worker("okam_3")
        self.assertIsNotNone(w3)
        self.assertEqual(w3.camera_id, "okam_3")

        # Non-existent
        self.assertIsNone(self.manager.get_worker("nonexistent_cam"))

    def test_independent_frame_buffers(self):
        w1 = self.manager.get_worker("okam_1")
        w2 = self.manager.get_worker("okam_2")
        w3 = self.manager.get_worker("okam_3")

        frame1 = b"\xff\xd8\xff\xe0...jpeg_frame_1...\xff\xd9"
        frame2 = b"\xff\xd8\xff\xe0...jpeg_frame_2...\xff\xd9"
        frame3 = b"\xff\xd8\xff\xe0...jpeg_frame_3...\xff\xd9"

        with w1.lock:
            w1.latest_frame = frame1
            w1.latest_frame_time = time.time()
            w1.total_frames = 10
            w1.status = "connected"

        with w2.lock:
            w2.latest_frame = frame2
            w2.latest_frame_time = time.time()
            w2.total_frames = 20
            w2.status = "connected"

        with w3.lock:
            w3.latest_frame = frame3
            w3.latest_frame_time = time.time()
            w3.total_frames = 30
            w3.status = "reconnecting"

        # Verify completely independent memory buffers
        self.assertEqual(w1.latest_frame, frame1)
        self.assertEqual(w2.latest_frame, frame2)
        self.assertEqual(w3.latest_frame, frame3)
        self.assertNotEqual(w1.latest_frame, w2.latest_frame)

        # Verify independent telemetry
        m1 = w1.get_metrics()
        m2 = w2.get_metrics()
        m3 = w3.get_metrics()

        self.assertEqual(m1["status"], "connected")
        self.assertEqual(m1["totalSourceFrames"], 10)
        self.assertEqual(m2["status"], "connected")
        self.assertEqual(m2["totalSourceFrames"], 20)
        self.assertEqual(m3["status"], "reconnecting")
        self.assertEqual(m3["totalSourceFrames"], 30)

    def test_independent_subscribers(self):
        w1 = self.manager.get_worker("okam_1")
        w2 = self.manager.get_worker("okam_2")

        rec_w1 = []
        rec_w2 = []

        def cb1(data): rec_w1.append(data)
        def cb2(data): rec_w2.append(data)

        w1.add_subscriber(cb1)
        w2.add_subscriber(cb2)

        # Dispatch simulated frame on w1 only
        with w1.lock:
            subs = list(w1.subscribers)
        for sub in subs:
            sub(b"frame_for_w1")

        self.assertEqual(len(rec_w1), 1)
        self.assertEqual(rec_w1[0], b"frame_for_w1")
        self.assertEqual(len(rec_w2), 0, "Worker 2 must not receive worker 1 frames")

        w1.remove_subscriber(cb1)
        w2.remove_subscriber(cb2)

    def test_duplicate_rtsp_url_prevention(self):
        # Attempting to register a 4th camera with an identical RTSP URL to okam_1
        # must reuse the existing worker rather than spawning a duplicate decoder process
        w_dup = self.manager.register_camera(
            camera_id="okam_dup",
            name="Duplicate Camera",
            rtsp_url="rtsp://admin:SecretPass1@192.168.100.6:10554/tcp/av0_0",
            resolution="1920x1080"
        )
        w1 = self.manager.get_worker("okam_1")
        self.assertIs(w_dup, w1)
        self.assertEqual(len(self.manager.workers), 3)
        self.assertIs(self.manager.get_worker("okam_dup"), w1)

    def test_create_manager_from_services_config(self):
        mgr = create_manager_from_config()
        self.assertEqual(len(mgr.workers), 3)
        self.assertIn("okam_1", mgr.workers)
        self.assertIn("okam_2", mgr.workers)
        self.assertIn("okam_3", mgr.workers)
        urls = {w.rtsp_url for w in mgr.workers.values()}
        self.assertEqual(len(urls), 3, "All 3 O-Kam cameras must have distinct RTSP URLs")

    def test_one_offline_two_active_isolation(self):
        w1 = self.manager.get_worker("okam_1")
        w2 = self.manager.get_worker("okam_2")
        w3 = self.manager.get_worker("okam_3")

        now = time.time()
        with w1.lock:
            w1.status = "connected"
            w1.latest_frame_time = now
            w1.frame_times.extend([now - 0.2, now - 0.1, now])
        with w2.lock:
            w2.status = "connected"
            w2.latest_frame_time = now
            w2.frame_times.extend([now - 0.2, now - 0.1, now])
        with w3.lock:
            w3.status = "offline"
            w3.frame_times.clear()

        summary = {c["id"]: c for c in self.manager.get_all_cameras_info()}
        self.assertEqual(summary["okam_1"]["status"], "connected")
        self.assertEqual(summary["okam_2"]["status"], "connected")
        self.assertEqual(summary["okam_3"]["status"], "offline")
        self.assertGreater(summary["okam_1"]["fps"], 0.0)
        self.assertGreater(summary["okam_2"]["fps"], 0.0)
        self.assertEqual(summary["okam_3"]["fps"], 0.0)


class TestOkamHttpApi(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.manager = MultiCameraManager()
        cls.manager.register_camera(
            camera_id="okam_1",
            name="Camera 3 · O-Kam Lens 1 (Main)",
            rtsp_url="rtsp://admin:SecretPass1@192.168.100.6:10554/tcp/av0_0",
            resolution="1920x1080",
            aliases=["okam-3", "okam-1"]
        )
        cls.manager.register_camera(
            camera_id="okam_2",
            name="Camera 4 · O-Kam Lens 2 (Wide)",
            rtsp_url="rtsp://admin:SecretPass2@192.168.100.6:10555/tcp/av0_0",
            resolution="1920x1080",
            aliases=["okam-2"]
        )
        cls.manager.register_camera(
            camera_id="okam_3",
            name="Camera 5 · O-Kam Lens 3 (Sub)",
            rtsp_url="rtsp://admin:SecretPass3@192.168.100.6:10554/tcp/av0_1",
            resolution="448x256",
            aliases=["okam-sub"]
        )

        # Populate test frames
        w1 = cls.manager.get_worker("okam_1")
        w1.latest_frame = b"\xff\xd8\xff\xe0_FAKE_CAM1_JPEG_\xff\xd9"
        w1.latest_frame_time = time.time()
        w1.status = "connected"

        w2 = cls.manager.get_worker("okam_2")
        w2.latest_frame = b"\xff\xd8\xff\xe0_FAKE_CAM2_JPEG_\xff\xd9"
        w2.latest_frame_time = time.time()
        w2.status = "connected"

        w3 = cls.manager.get_worker("okam_3")
        w3.latest_frame = b"\xff\xd8\xff\xe0_FAKE_CAM3_JPEG_\xff\xd9"
        w3.latest_frame_time = time.time()
        w3.status = "reconnecting"

        # Start HTTP server on ephemeral test port
        cls.port = 18082
        HttpHandler.manager = cls.manager
        HttpHandler.broker = w1
        cls.server = ThreadedServer(("127.0.0.1", cls.port), HttpHandler, manager=cls.manager)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        time.sleep(0.3)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_get_api_cameras(self):
        url = f"http://127.0.0.1:{self.port}/api/cameras"
        req = Request(url)
        with urlopen(req, timeout=2.0) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))

        self.assertIn("cameras", data)
        cams = data["cameras"]
        self.assertEqual(len(cams), 3)

        ids = [c["id"] for c in cams]
        self.assertIn("okam_1", ids)
        self.assertIn("okam_2", ids)
        self.assertIn("okam_3", ids)

        # Zero password leaks check
        for c in cams:
            self.assertNotIn("SecretPass", c["rtspUrl"])
            self.assertIn("***", c["rtspUrl"])
            self.assertIn("streamPath", c)
            self.assertIn("snapshotPath", c)
            self.assertIn("metricsPath", c)

    def test_get_camera_metrics_independent(self):
        # Camera 1 metrics
        url1 = f"http://127.0.0.1:{self.port}/api/cameras/okam_1/metrics"
        with urlopen(Request(url1), timeout=2.0) as resp:
            data1 = json.loads(resp.read().decode("utf-8"))
        self.assertEqual(data1["cameraId"], "okam_1")
        self.assertEqual(data1["status"], "connected")

        # Camera 3 (alias okam-3) metrics
        url_alias = f"http://127.0.0.1:{self.port}/api/cameras/okam-3/metrics"
        with urlopen(Request(url_alias), timeout=2.0) as resp:
            data_alias = json.loads(resp.read().decode("utf-8"))
        self.assertEqual(data_alias["cameraId"], "okam_1")

        # Camera 2 metrics
        url2 = f"http://127.0.0.1:{self.port}/api/cameras/okam_2/metrics"
        with urlopen(Request(url2), timeout=2.0) as resp:
            data2 = json.loads(resp.read().decode("utf-8"))
        self.assertEqual(data2["cameraId"], "okam_2")

        # Camera 3 (Sub) metrics
        url3 = f"http://127.0.0.1:{self.port}/api/cameras/okam_3/metrics"
        with urlopen(Request(url3), timeout=2.0) as resp:
            data3 = json.loads(resp.read().decode("utf-8"))
        self.assertEqual(data3["cameraId"], "okam_3")
        self.assertEqual(data3["status"], "reconnecting")

    def test_get_camera_snapshots_distinct(self):
        url1 = f"http://127.0.0.1:{self.port}/api/cameras/okam_1/snapshot"
        with urlopen(Request(url1), timeout=2.0) as resp:
            snap1 = resp.read()

        url2 = f"http://127.0.0.1:{self.port}/api/cameras/okam_2/snapshot"
        with urlopen(Request(url2), timeout=2.0) as resp:
            snap2 = resp.read()

        self.assertIn(b"_FAKE_CAM1_JPEG_", snap1)
        self.assertIn(b"_FAKE_CAM2_JPEG_", snap2)
        self.assertNotEqual(snap1, snap2, "Each camera must serve its own unique frame buffer")

    def test_legacy_backward_compatibility(self):
        # /api/metrics
        url_m = f"http://127.0.0.1:{self.port}/api/metrics"
        with urlopen(Request(url_m), timeout=2.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        self.assertEqual(data["cameraId"], "okam_1")

        # /snapshot
        url_s = f"http://127.0.0.1:{self.port}/snapshot"
        with urlopen(Request(url_s), timeout=2.0) as resp:
            snap = resp.read()
        self.assertIn(b"_FAKE_CAM1_JPEG_", snap)

    def test_mjpeg_stream_endpoint_per_camera(self):
        for cid, marker in [
            ("okam_1", b"_FAKE_CAM1_JPEG_"),
            ("okam_2", b"_FAKE_CAM2_JPEG_"),
            ("okam_3", b"_FAKE_CAM3_JPEG_"),
        ]:
            url = f"http://127.0.0.1:{self.port}/api/cameras/{cid}/stream.mjpg"
            with urlopen(Request(url), timeout=2.0) as resp:
                self.assertEqual(resp.status, 200)
                chunk = resp.read(128)
                self.assertIn(b"--frame", chunk)
                self.assertIn(marker, chunk)


if __name__ == "__main__":
    unittest.main()

