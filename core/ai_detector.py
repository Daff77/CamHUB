"""
CamHub Local AI Object Detection Engine
Hardware-accelerated edge inference using ONNX Runtime with DirectML (GPU) and CPU fallback.
Provides decoupled, non-blocking frame analysis, latest-frame queuing, ROI filtering,
and COCO class taxonomy mapping (person, car, motorcycle, animal).
"""

import os
import io
import sys
import time
import queue
import logging
import threading
from typing import List, Dict, Any, Tuple, Optional
import numpy as np
from PIL import Image

logger = logging.getLogger("CamHub.AI")

# Default paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_DIR = os.path.join(BASE_DIR, "models")
DEFAULT_MODEL_PATH = os.path.join(MODELS_DIR, "yolov5n.onnx")

# COCO 80 Class Names
COCO_CLASSES = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat", "traffic light",
    "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep", "cow",
    "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
    "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove", "skateboard", "surfboard",
    "tennis racket", "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple",
    "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
    "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote", "keyboard", "cell phone",
    "microwave", "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase", "scissors", "teddy bear",
    "hair drier", "toothbrush"
]

# CamHub Category Grouping
CATEGORY_MAP = {
    "person": "person",
    "car": "car",
    "truck": "car",
    "bus": "car",
    "motorcycle": "motorcycle",
    "bicycle": "motorcycle",
    "cat": "animal",
    "dog": "animal",
    "bird": "animal",
    "horse": "animal",
    "sheep": "animal",
    "cow": "animal",
    "bear": "animal",
    "elephant": "animal",
    "zebra": "animal",
    "giraffe": "animal"
}

def map_coco_category(class_name: str) -> str:
    """Map raw COCO class name to standardized CamHUB category."""
    return CATEGORY_MAP.get(class_name.lower(), "other")


def compute_iou(box1: np.ndarray, boxes: np.ndarray) -> np.ndarray:
    """
    Compute Intersection over Union (IoU) of one box against an array of boxes.
    Boxes format: [x1, y1, x2, y2]
    """
    x1 = np.maximum(box1[0], boxes[:, 0])
    y1 = np.maximum(box1[1], boxes[:, 1])
    x2 = np.minimum(box1[2], boxes[:, 2])
    y2 = np.minimum(box1[3], boxes[:, 3])

    intersection = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
    area1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
    area2 = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    union = area1 + area2 - intersection

    return np.where(union > 0, intersection / union, 0.0)


def non_max_suppression(
    boxes: np.ndarray,
    scores: np.ndarray,
    class_ids: np.ndarray,
    iou_threshold: float = 0.45
) -> List[int]:
    """
    Vectorized class-aware Non-Maximum Suppression (NMS).
    boxes: Nx4 [x1, y1, x2, y2]
    """
    if len(boxes) == 0:
        return []

    keep = []
    # Process per unique class to avoid cross-class suppression
    for cid in np.unique(class_ids):
        indices = np.where(class_ids == cid)[0]
        cls_boxes = boxes[indices]
        cls_scores = scores[indices]

        order = cls_scores.argsort()[::-1]
        while order.size > 0:
            i = order[0]
            keep.append(indices[i])
            if order.size == 1:
                break
            ious = compute_iou(cls_boxes[i], cls_boxes[order[1:]])
            order = order[np.where(ious <= iou_threshold)[0] + 1]

    return sorted(keep)


class LocalObjectDetector:
    """
    High-performance, local ONNX Runtime object detector.
    Supports DirectML (NVIDIA/AMD/Intel GPU) and CPU fallback.
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        provider: str = "auto",
        confidence_threshold: float = 0.40,
        nms_threshold: float = 0.45,
        target_classes: Optional[List[str]] = None
    ):
        self.model_path = model_path or DEFAULT_MODEL_PATH
        self.preferred_provider = provider.lower()
        self.confidence_threshold = confidence_threshold
        self.nms_threshold = nms_threshold
        self.target_classes = [c.lower() for c in target_classes] if target_classes else None

        self.session = None
        self.input_name = "images"
        self.input_shape = (1, 3, 640, 640)
        self.input_dtype = np.float16
        self.active_provider = "none"
        self.is_mock = False

        self._init_session()

    def _init_session(self):
        """Initialize ONNX Runtime inference session with requested or auto provider."""
        if self.preferred_provider == "mock" or not os.path.exists(self.model_path):
            self.is_mock = True
            self.active_provider = "mock"
            return

        try:
            import onnxruntime as ort
        except ImportError:
            logger.warning("[AI] onnxruntime not installed. Falling back to mock detector.")
            self.is_mock = True
            self.active_provider = "mock"
            return

        # Determine execution providers based on preference
        if self.preferred_provider == "directml":
            providers = ["DmlExecutionProvider", "CPUExecutionProvider"]
        elif self.preferred_provider == "cpu":
            providers = ["CPUExecutionProvider"]
        else: # "auto"
            providers = ["DmlExecutionProvider", "CPUExecutionProvider"]

        # Filter against available providers on this system
        avail = ort.get_available_providers()
        valid_providers = [p for p in providers if p in avail]
        if not valid_providers:
            valid_providers = ["CPUExecutionProvider"]

        session_options = ort.SessionOptions()
        session_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        try:
            self.session = ort.InferenceSession(
                self.model_path,
                sess_options=session_options,
                providers=valid_providers
            )
            active = self.session.get_providers()
            self.active_provider = "DirectML" if "DmlExecutionProvider" in active else "CPU"
            
            # Inspect model input
            inp = self.session.get_inputs()[0]
            self.input_name = inp.name
            if inp.type == "tensor(float16)":
                self.input_dtype = np.float16
            else:
                self.input_dtype = np.float32

            # Input shape: usually [1, 3, 640, 640]
            h = inp.shape[2] if isinstance(inp.shape[2], int) else 640
            w = inp.shape[3] if isinstance(inp.shape[3], int) else 640
            self.input_shape = (1, 3, h, w)
            self.is_mock = False
        except Exception as e:
            logger.error(f"[AI] Failed to load ONNX model ({e}). Falling back to CPUExecutionProvider.")
            try:
                self.session = ort.InferenceSession(
                    self.model_path,
                    sess_options=session_options,
                    providers=["CPUExecutionProvider"]
                )
                self.active_provider = "CPU"
                self.is_mock = False
            except Exception as e_cpu:
                logger.error(f"[AI] CPU initialization also failed ({e_cpu}). Enabling mock mode.")
                self.is_mock = True
                self.active_provider = "mock"

    def preprocess(self, img: Image.Image) -> Tuple[np.ndarray, Tuple[int, int], Tuple[int, int], float]:
        """
        Letterbox image resize preserving aspect ratio, with padding to model dimensions.
        Returns: (input_tensor, (orig_w, orig_h), (pad_x, pad_y), scale)
        """
        orig_w, orig_h = img.size
        target_w = self.input_shape[3]
        target_h = self.input_shape[2]

        scale = min(target_w / orig_w, target_h / orig_h)
        new_w, new_h = int(orig_w * scale), int(orig_h * scale)
        resized = img.resize((new_w, new_h), Image.Resampling.BILINEAR)

        canvas = Image.new("RGB", (target_w, target_h), (114, 114, 114))
        pad_x = (target_w - new_w) // 2
        pad_y = (target_h - new_h) // 2
        canvas.paste(resized, (pad_x, pad_y))

        arr = np.array(canvas, dtype=np.float32) / 255.0
        arr = np.transpose(arr, (2, 0, 1)) # HWC to CHW
        arr = np.expand_dims(arr, axis=0)  # 1CHW
        tensor = arr.astype(self.input_dtype)

        return tensor, (orig_w, orig_h), (pad_x, pad_y), scale

    def detect(
        self,
        image_or_bytes: Any,
        conf_threshold: Optional[float] = None,
        target_classes: Optional[List[str]] = None,
        roi: Optional[Dict[str, float]] = None
    ) -> List[Dict[str, Any]]:
        """
        Run object detection on an image.
        Returns list of detected objects with normalized bounding boxes and confidence.
        """
        t0 = time.perf_counter()
        if conf_threshold is None:
            conf_threshold = self.confidence_threshold
        targets = [c.lower() for c in target_classes] if target_classes is not None else self.target_classes

        # Load PIL image
        if isinstance(image_or_bytes, (str, os.PathLike)):
            img = Image.open(str(image_or_bytes)).convert("RGB")
        elif isinstance(image_or_bytes, bytes):
            img = Image.open(io.BytesIO(image_or_bytes)).convert("RGB")
        elif isinstance(image_or_bytes, Image.Image):
            img = image_or_bytes.convert("RGB")
        else:
            raise ValueError(f"Unsupported image type: {type(image_or_bytes)}")

        orig_w, orig_h = img.size

        # If in mock mode, return synthetic detections
        if self.is_mock or self.session is None:
            return self._mock_detect(orig_w, orig_h, conf_threshold, targets, roi)

        tensor, (w, h), (pad_x, pad_y), scale = self.preprocess(img)

        # Execute ONNX model
        preds = self.session.run(None, {self.input_name: tensor})[0][0]
        preds = preds.astype(np.float32) # ensure float32 for post-processing

        # YOLO output format: [cx, cy, w, h, obj_conf, class_scores...]
        boxes_cxcywh = preds[:, :4]
        obj_conf = preds[:, 4]
        class_scores = preds[:, 5:]

        class_ids = np.argmax(class_scores, axis=1)
        max_class_scores = np.max(class_scores, axis=1)
        scores = obj_conf * max_class_scores

        # Filter by confidence threshold
        mask = scores >= conf_threshold
        if not np.any(mask):
            return []

        cand_boxes = boxes_cxcywh[mask]
        cand_scores = scores[mask]
        cand_classes = class_ids[mask]

        # Convert [cx, cy, w, h] to [x1, y1, x2, y2] on letterbox canvas
        x1 = cand_boxes[:, 0] - cand_boxes[:, 2] / 2.0
        y1 = cand_boxes[:, 1] - cand_boxes[:, 3] / 2.0
        x2 = cand_boxes[:, 0] + cand_boxes[:, 2] / 2.0
        y2 = cand_boxes[:, 1] + cand_boxes[:, 3] / 2.0
        box_coords = np.column_stack([x1, y1, x2, y2])

        # Run Non-Maximum Suppression (NMS)
        keep_indices = non_max_suppression(
            box_coords,
            cand_scores,
            cand_classes,
            iou_threshold=self.nms_threshold
        )

        detections = []
        for idx in keep_indices:
            cid = int(cand_classes[idx])
            raw_class_name = COCO_CLASSES[cid] if cid < len(COCO_CLASSES) else f"class_{cid}"
            category = map_coco_category(raw_class_name)
            score = float(cand_scores[idx])

            # Class filtering (check either raw class or category)
            if targets:
                if raw_class_name.lower() not in targets and category.lower() not in targets:
                    continue

            # Unpad and scale back to original image dimensions
            b_x1 = (box_coords[idx, 0] - pad_x) / scale
            b_y1 = (box_coords[idx, 1] - pad_y) / scale
            b_x2 = (box_coords[idx, 2] - pad_x) / scale
            b_y2 = (box_coords[idx, 3] - pad_y) / scale

            # Clamp to [0, orig_w / orig_h]
            b_x1 = max(0.0, min(float(b_x1), float(orig_w)))
            b_y1 = max(0.0, min(float(b_y1), float(orig_h)))
            b_x2 = max(0.0, min(float(b_x2), float(orig_w)))
            b_y2 = max(0.0, min(float(b_y2), float(orig_h)))

            # Normalized 0.0 - 1.0 bounding box
            norm_box = {
                "x": round(b_x1 / orig_w, 4),
                "y": round(b_y1 / orig_h, 4),
                "width": round(max(0.01, (b_x2 - b_x1) / orig_w), 4),
                "height": round(max(0.01, (b_y2 - b_y1) / orig_h), 4)
            }

            # ROI filter check if specified
            if roi:
                center_x = norm_box["x"] + norm_box["width"] / 2.0
                center_y = norm_box["y"] + norm_box["height"] / 2.0
                roi_x1 = roi.get("x", 0.0)
                roi_y1 = roi.get("y", 0.0)
                roi_x2 = roi_x1 + roi.get("width", 1.0)
                roi_y2 = roi_y1 + roi.get("height", 1.0)
                if not (roi_x1 <= center_x <= roi_x2 and roi_y1 <= center_y <= roi_y2):
                    continue

            detections.append({
                "class": raw_class_name,
                "category": category,
                "confidence": round(score, 3),
                "box": norm_box
            })

        return detections

    def _mock_detect(
        self,
        orig_w: int,
        orig_h: int,
        conf_threshold: float,
        targets: Optional[List[str]],
        roi: Optional[Dict[str, float]]
    ) -> List[Dict[str, Any]]:
        """Deterministic mock detector for unit tests and fallback environments."""
        detections = [
            {
                "class": "person",
                "category": "person",
                "confidence": 0.88,
                "box": {"x": 0.25, "y": 0.30, "width": 0.20, "height": 0.45}
            },
            {
                "class": "car",
                "category": "car",
                "confidence": 0.76,
                "box": {"x": 0.60, "y": 0.55, "width": 0.30, "height": 0.25}
            }
        ]
        results = []
        for d in detections:
            if d["confidence"] < conf_threshold:
                continue
            if targets and (d["class"] not in targets and d["category"] not in targets):
                continue
            if roi:
                cx = d["box"]["x"] + d["box"]["width"] / 2.0
                cy = d["box"]["y"] + d["box"]["height"] / 2.0
                rx1, ry1 = roi.get("x", 0.0), roi.get("y", 0.0)
                rx2, ry2 = rx1 + roi.get("width", 1.0), ry1 + roi.get("height", 1.0)
                if not (rx1 <= cx <= rx2 and ry1 <= cy <= ry2):
                    continue
            results.append(d)
        return results

    def benchmark(self, sample_image: Optional[Image.Image] = None, runs: int = 5) -> Dict[str, Any]:
        """
        Evaluate and compare DirectML GPU vs CPU execution latency and memory.
        """
        if self.is_mock or not os.path.exists(self.model_path):
            return {
                "status": "mock",
                "message": "Model not found on disk or mock mode active",
                "model": os.path.basename(self.model_path),
                "results": {"mock": {"latencyMs": 1.5, "fpsCapacity": 666.0}}
            }

        import onnxruntime as ort

        if sample_image is None:
            sample_image = Image.new("RGB", (640, 640), (128, 128, 128))

        tensor, _, _, _ = self.preprocess(sample_image)

        results = {}
        for prov_name, prov_keys in [("DirectML (GPU)", ["DmlExecutionProvider"]), ("CPU", ["CPUExecutionProvider"])]:
            avail = ort.get_available_providers()
            if not any(k in avail for k in prov_keys):
                results[prov_name] = {"available": False, "reason": "Provider not available on this platform"}
                continue

            try:
                sess = ort.InferenceSession(self.model_path, providers=prov_keys)
                # Warmup
                sess.run(None, {self.input_name: tensor})

                durations = []
                for _ in range(runs):
                    t_start = time.perf_counter()
                    sess.run(None, {self.input_name: tensor})
                    durations.append((time.perf_counter() - t_start) * 1000.0)

                avg_ms = float(np.mean(durations))
                min_ms = float(np.min(durations))
                max_ms = float(np.max(durations))
                fps_cap = round(1000.0 / avg_ms, 1) if avg_ms > 0 else 0.0

                results[prov_name] = {
                    "available": True,
                    "avgLatencyMs": round(avg_ms, 2),
                    "minLatencyMs": round(min_ms, 2),
                    "maxLatencyMs": round(max_ms, 2),
                    "fpsCapacity": fps_cap
                }
            except Exception as e:
                results[prov_name] = {"available": False, "error": str(e)}

        return {
            "status": "success",
            "model": os.path.basename(self.model_path),
            "modelSizeBytes": os.path.getsize(self.model_path),
            "runs": runs,
            "results": results
        }


class AIObjectDetectorWorker:
    """
    Decoupled background worker for AI inference with latest-frame queue.
    Ensures zero blocking on live video streaming and web server.
    """

    def __init__(self, detector: LocalObjectDetector, max_fps: float = 2.0):
        self.detector = detector
        self.min_interval = 1.0 / max(0.1, max_fps)
        self.frame_queue = queue.Queue(maxsize=1)
        self.running = False
        self.worker_thread = None

        # Telemetry metrics
        self.total_processed = 0
        self.total_dropped = 0
        self.last_latency_ms = 0.0
        self.last_inference_time = 0.0
        self.measured_fps = 0.0
        self._fps_window = []
        self._lock = threading.Lock()

    def start(self):
        """Start the background worker thread."""
        if self.running:
            return
        self.running = True
        self.worker_thread = threading.Thread(
            target=self._worker_loop,
            name="CamHub-AIWorker",
            daemon=True
        )
        self.worker_thread.start()
        logger.info(f"[AI] Worker thread started with provider: {self.detector.active_provider}")

    def stop(self):
        """Stop worker cleanly."""
        self.running = False
        if self.worker_thread and self.worker_thread.is_alive():
            try:
                self.frame_queue.put_nowait(None) # wakeup sentinel
            except queue.Full:
                pass
            self.worker_thread.join(timeout=1.0)

    def submit_frame(self, frame_bytes: bytes, metadata: Dict[str, Any]) -> bool:
        """
        Submit a new frame for analysis.
        Uses latest-frame dropping: if queue is occupied, replace the older frame.
        Returns True if accepted, False if dropped.
        """
        if not self.running:
            return False

        item = (frame_bytes, metadata)
        try:
            self.frame_queue.put_nowait(item)
            return True
        except queue.Full:
            # Drop older frame and push newest
            try:
                self.frame_queue.get_nowait()
                with self._lock:
                    self.total_dropped += 1
            except queue.Empty:
                pass
            try:
                self.frame_queue.put_nowait(item)
                return True
            except queue.Full:
                with self._lock:
                    self.total_dropped += 1
                return False

    def _worker_loop(self):
        """Continuous worker thread loop."""
        while self.running:
            try:
                task = self.frame_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if task is None or not self.running:
                break

            frame_bytes, metadata = task
            callback = metadata.get("callback")

            try:
                t0 = time.perf_counter()
                roi = metadata.get("roi")
                conf = metadata.get("confidenceThreshold")
                targets = metadata.get("targetClasses")

                detections = self.detector.detect(
                    frame_bytes,
                    conf_threshold=conf,
                    target_classes=targets,
                    roi=roi
                )
                latency_ms = (time.perf_counter() - t0) * 1000.0

                now = time.time()
                with self._lock:
                    self.total_processed += 1
                    self.last_latency_ms = round(latency_ms, 2)
                    self.last_inference_time = now
                    self._fps_window.append(now)
                    # Keep rolling 5-second window for FPS
                    cutoff = now - 5.0
                    self._fps_window = [t for t in self._fps_window if t >= cutoff]
                    if len(self._fps_window) > 1:
                        span = self._fps_window[-1] - self._fps_window[0]
                        self.measured_fps = round((len(self._fps_window) - 1) / max(0.1, span), 2)
                    else:
                        self.measured_fps = 0.0

                if callback and callable(callback):
                    try:
                        callback(detections, metadata)
                    except Exception as cb_err:
                        logger.error(f"[AI] Error in detection callback: {cb_err}")

            except Exception as e:
                logger.error(f"[AI] Inference error in worker loop: {e}")

            # Throttle to prevent saturating the system
            elapsed = (time.perf_counter() - t0)
            sleep_time = self.min_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    def get_metrics(self) -> Dict[str, Any]:
        """Return real-time AI worker performance metrics."""
        with self._lock:
            return {
                "activeProvider": self.detector.active_provider,
                "isMock": self.detector.is_mock,
                "model": os.path.basename(self.detector.model_path),
                "totalInferences": self.total_processed,
                "droppedFrames": self.total_dropped,
                "lastLatencyMs": self.last_latency_ms,
                "inferenceFps": self.measured_fps,
                "queueDepth": self.frame_queue.qsize()
            }
