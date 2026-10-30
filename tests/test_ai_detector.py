"""
Unit and Integration Tests for CamHUB Local AI Object Detection Engine.
Tests ONNX Runtime inference, DirectML / CPU provider resolution, letterbox preprocessing,
Non-Maximum Suppression (NMS), category mapping, ROI filtering, latest-frame queuing,
and fallback behaviors using local synthetic samples without requiring active cameras.
"""

import os
import io
import time
import shutil
import tempfile
import unittest
import numpy as np
from PIL import Image

from core.ai_detector import (
    LocalObjectDetector,
    AIObjectDetectorWorker,
    COCO_CLASSES,
    CATEGORY_MAP,
    map_coco_category,
    compute_iou,
    non_max_suppression,
    DEFAULT_MODEL_PATH
)
from core.motion_detector import MotionDetectorService


class TestLocalAIObjectDetection(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="camhub_ai_test_")

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _generate_synthetic_image(self, width=640, height=480, color=(100, 150, 200)) -> bytes:
        img = Image.new("RGB", (width, height), color)
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        return buf.getvalue()

    def test_coco_taxonomy_and_mapping(self):
        """Verify COCO class taxonomy and CamHUB category mappings."""
        self.assertIn("person", COCO_CLASSES)
        self.assertIn("car", COCO_CLASSES)
        self.assertIn("motorcycle", COCO_CLASSES)
        self.assertIn("dog", COCO_CLASSES)
        self.assertIn("cat", COCO_CLASSES)

        self.assertEqual(map_coco_category("person"), "person")
        self.assertEqual(map_coco_category("car"), "car")
        self.assertEqual(map_coco_category("truck"), "car")
        self.assertEqual(map_coco_category("bus"), "car")
        self.assertEqual(map_coco_category("motorcycle"), "motorcycle")
        self.assertEqual(map_coco_category("bicycle"), "motorcycle")
        self.assertEqual(map_coco_category("dog"), "animal")
        self.assertEqual(map_coco_category("cat"), "animal")
        self.assertEqual(map_coco_category("bird"), "animal")
        self.assertEqual(map_coco_category("toaster"), "other")

    def test_compute_iou_and_nms(self):
        """Verify Intersection over Union (IoU) calculation and Non-Maximum Suppression."""
        box1 = np.array([10.0, 10.0, 50.0, 50.0]) # 40x40 = 1600
        boxes = np.array([
            [10.0, 10.0, 50.0, 50.0],  # Exact same: IoU 1.0
            [100.0, 100.0, 140.0, 140.0], # Non-overlapping: IoU 0.0
            [30.0, 10.0, 70.0, 50.0]   # 50% overlap: intersection 20x40=800, union 2400 => 0.333
        ])
        ious = compute_iou(box1, boxes)
        self.assertAlmostEqual(ious[0], 1.0, places=3)
        self.assertAlmostEqual(ious[1], 0.0, places=3)
        self.assertAlmostEqual(ious[2], 0.3333, places=2)

        # Test NMS on overlapping candidates
        cand_boxes = np.array([
            [10.0, 10.0, 50.0, 50.0],
            [12.0, 11.0, 51.0, 50.0], # high overlap with #0
            [100.0, 100.0, 150.0, 150.0]
        ])
        scores = np.array([0.90, 0.85, 0.95])
        class_ids = np.array([0, 0, 0])
        keep = non_max_suppression(cand_boxes, scores, class_ids, iou_threshold=0.45)
        # Should keep highest score overlapping (#0) and disjoint (#2)
        self.assertIn(0, keep)
        self.assertIn(2, keep)
        self.assertNotIn(1, keep)

    def test_mock_detector_mode(self):
        """Verify mock detector operates deterministically when requested."""
        detector = LocalObjectDetector(provider="mock")
        self.assertTrue(detector.is_mock)
        self.assertEqual(detector.active_provider, "mock")

        raw_bytes = self._generate_synthetic_image()
        dets = detector.detect(raw_bytes, conf_threshold=0.5)
        self.assertTrue(len(dets) > 0)
        first = dets[0]
        self.assertIn("class", first)
        self.assertIn("category", first)
        self.assertIn("confidence", first)
        self.assertIn("box", first)
        self.assertTrue(0.0 <= first["box"]["x"] <= 1.0)
        self.assertTrue(0.0 <= first["box"]["width"] <= 1.0)

    def test_target_class_and_category_filtering(self):
        """Verify targetClasses filter restricts detected objects."""
        detector = LocalObjectDetector(provider="mock")
        raw_bytes = self._generate_synthetic_image()

        # Only person
        dets_person = detector.detect(raw_bytes, target_classes=["person"])
        for d in dets_person:
            self.assertEqual(d["category"], "person")

        # Only car
        dets_car = detector.detect(raw_bytes, target_classes=["car"])
        for d in dets_car:
            self.assertEqual(d["category"], "car")

        # Disjoint filter
        dets_none = detector.detect(raw_bytes, target_classes=["airplane"])
        self.assertEqual(len(dets_none), 0)

    def test_roi_zone_filtering(self):
        """Verify Region of Interest (ROI) filter rejects bounding boxes outside zone."""
        detector = LocalObjectDetector(provider="mock")
        raw_bytes = self._generate_synthetic_image()

        # ROI covering only the right half [x: 0.5 to 1.0] -> should keep car (x:0.60), exclude person (x:0.25)
        roi_right = {"x": 0.5, "y": 0.0, "width": 0.5, "height": 1.0}
        dets = detector.detect(raw_bytes, roi=roi_right)
        classes = [d["class"] for d in dets]
        self.assertIn("car", classes)
        self.assertNotIn("person", classes)

        # ROI covering top-left -> should keep person, exclude car
        roi_left = {"x": 0.0, "y": 0.0, "width": 0.5, "height": 1.0}
        dets_l = detector.detect(raw_bytes, roi=roi_left)
        classes_l = [d["class"] for d in dets_l]
        self.assertIn("person", classes_l)
        self.assertNotIn("car", classes_l)

    def test_letterbox_preprocessing(self):
        """Verify image letterbox resizing preserves aspect ratio and outputs normalized tensor."""
        detector = LocalObjectDetector(provider="mock")
        img = Image.new("RGB", (1280, 720), (128, 64, 32))
        tensor, orig_size, pad, scale = detector.preprocess(img)

        self.assertEqual(orig_size, (1280, 720))
        self.assertEqual(tensor.shape, (1, 3, 640, 640))
        # Tensor values must be normalized [0.0, 1.0]
        self.assertTrue(0.0 <= np.min(tensor) <= np.max(tensor) <= 1.0)

    def test_onnx_model_execution_and_fallback(self):
        """Verify real ONNX model loading and CPU fallback execution."""
        if not os.path.exists(DEFAULT_MODEL_PATH):
            self.skipTest("yolov5n.onnx not present on disk")

        # Auto or DirectML
        det = LocalObjectDetector(DEFAULT_MODEL_PATH, provider="auto")
        self.assertIn(det.active_provider, ["DirectML", "CPU"])
        raw_bytes = self._generate_synthetic_image(640, 480)
        dets = det.detect(raw_bytes, conf_threshold=0.2)
        self.assertIsInstance(dets, list)

        # Explicit CPU
        det_cpu = LocalObjectDetector(DEFAULT_MODEL_PATH, provider="cpu")
        self.assertEqual(det_cpu.active_provider, "CPU")
        dets_cpu = det_cpu.detect(raw_bytes, conf_threshold=0.2)
        self.assertIsInstance(dets_cpu, list)

    def test_directml_vs_cpu_benchmark(self):
        """Verify benchmark reports latency and fpsCapacity for available execution providers."""
        if not os.path.exists(DEFAULT_MODEL_PATH):
            self.skipTest("yolov5n.onnx not present on disk")

        det = LocalObjectDetector(DEFAULT_MODEL_PATH)
        bench = det.benchmark(runs=2)
        self.assertEqual(bench["status"], "success")
        self.assertIn("DirectML (GPU)", bench["results"])
        self.assertIn("CPU", bench["results"])

        cpu_res = bench["results"]["CPU"]
        self.assertTrue(cpu_res["available"])
        self.assertTrue(cpu_res["avgLatencyMs"] > 0)
        self.assertTrue(cpu_res["fpsCapacity"] > 0)

    def test_worker_queue_and_frame_dropping(self):
        """Verify AIObjectDetectorWorker drops older frames when queue is occupied."""
        det = LocalObjectDetector(provider="mock")
        worker = AIObjectDetectorWorker(det, max_fps=5.0)
        worker.start()

        results = []
        def on_detect(detections, meta):
            results.append(meta["frame_id"])

        raw_bytes = self._generate_synthetic_image()

        # Submit 10 frames in immediate succession
        for i in range(10):
            worker.submit_frame(raw_bytes, {"frame_id": f"f_{i}", "callback": on_detect})

        time.sleep(0.4)
        worker.stop()

        metrics = worker.get_metrics()
        # Must have processed at least 1 and dropped remaining
        self.assertTrue(metrics["totalInferences"] >= 1)
        self.assertTrue(metrics["droppedFrames"] > 0)
        self.assertEqual(metrics["queueDepth"], 0)

    def test_motion_detector_service_enrichment(self):
        """Verify MotionDetectorService enriches captured events with AI classifications."""
        config_data = {
            "motionDetection": {
                "enabled": True,
                "samplingIntervalSeconds": 0.2
            },
            "aiDetection": {
                "enabled": True,
                "provider": "mock",
                "confidenceThreshold": 0.3
            },
            "cameras": [
                {"id": "cam-mock-1", "name": "Mock Camera", "port": 9999}
            ]
        }

        svc = MotionDetectorService(lambda: config_data, base_dir=self.temp_dir)
        try:
            # Create a synthetic event
            raw_bytes = self._generate_synthetic_image()
            event_data = {
                "cameraId": "cam-mock-1",
                "cameraName": "Mock Camera",
                "score": 42.0,
                "timestamp": int(time.time() * 1000),
                "isoTime": "2026-10-30 20:00:00",
                "durationSeconds": 1.2,
                "boundingBox": {"x": 0.1, "y": 0.1, "width": 0.4, "height": 0.4}
            }
            svc._record_event(event_data, raw_bytes)

            events = svc.list_events(camera_id="cam-mock-1")
            self.assertEqual(len(events), 1)
            evt = events[0]

            # Run on-demand enrichment
            enriched = svc.enrich_event_with_ai(evt["id"])
            self.assertIsNotNone(enriched)
            self.assertTrue(len(enriched.get("detectedObjects", [])) > 0)
            self.assertIsNotNone(enriched.get("primaryClass"))

            # Test event filtering by objectClass
            filtered = svc.list_events(object_class=enriched["primaryClass"])
            self.assertEqual(len(filtered), 1)
            self.assertEqual(filtered[0]["id"], evt["id"])

            # Test stats contains AI section
            stats = svc.get_stats()
            self.assertIn("ai", stats)
            self.assertEqual(stats["ai"]["activeProvider"], "mock")
        finally:
            svc.stop()


if __name__ == "__main__":
    unittest.main()
