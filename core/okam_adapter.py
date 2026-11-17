"""
CamHUB O-Kam Pro / VStarcam Multi-Camera Stream Adapter
Bridges RTSP streams to HTTP MJPEG, Snapshots, and Telemetry for multiple cameras concurrently.
Supports independent workers per camera, dedicated frame buffers, robust auto-recovery,
and full backward compatibility with legacy single-camera endpoints.
"""

import sys
import time
import subprocess
import threading
import argparse
import json
import os
import re
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from collections import deque
from urllib.parse import parse_qs, urlparse


def sanitize_rtsp_url(url: str) -> str:
    """Masks credentials in RTSP URL for secure logging and telemetry exposure."""
    if not url:
        return ""
    return re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", url)


def extract_jpeg_dimensions(jpeg_bytes: bytes):
    """Extracts (width, height) from JPEG SOF0/SOF1/SOF2 markers without external dependencies."""
    if not jpeg_bytes or len(jpeg_bytes) < 24 or jpeg_bytes[0:2] != b"\xff\xd8":
        return None
    idx = 2
    length = len(jpeg_bytes)
    while idx < length - 8:
        if jpeg_bytes[idx] != 0xFF:
            idx += 1
            continue
        marker = jpeg_bytes[idx + 1]
        if marker == 0xFF:
            idx += 1
            continue
        if marker in (0xD8, 0xD9) or (0xD0 <= marker <= 0xD7):
            idx += 2
            continue
        seg_len = (jpeg_bytes[idx + 2] << 8) | jpeg_bytes[idx + 3]
        if seg_len < 2:
            break
        if marker in (0xC0, 0xC1, 0xC2):
            if idx + 8 < length:
                h = (jpeg_bytes[idx + 5] << 8) | jpeg_bytes[idx + 6]
                w = (jpeg_bytes[idx + 7] << 8) | jpeg_bytes[idx + 8]
                if w > 0 and h > 0:
                    return w, h
            break
        idx += 2 + seg_len
    return None


class CameraStreamWorker:
    """Independent RTSP-to-MJPEG stream worker and frame buffer for a single camera."""

    def __init__(self, camera_id: str, name: str, rtsp_url: str,
                 resolution: str = "1920x1080", rtsp_transport: str = "tcp",
                 target_fps: float = 15.0):
        self.camera_id = camera_id
        self.name = name
        self.rtsp_url = rtsp_url
        self.resolution = resolution
        self.rtsp_transport = rtsp_transport
        self.target_fps = target_fps

        self.running = False
        self.subscribers = set()
        self.lock = threading.Lock()
        self.latest_frame = None
        self.latest_frame_time = 0.0
        self.total_frames = 0
        self.frame_times = deque(maxlen=30)
        self.process = None
        self.reconnect_count = 0
        self.decode_errors = 0
        self.last_error = ""
        self.browser_render_fps = 0.0
        self.worker_thread = None
        self.status = "stopped"  # "connected" | "reconnecting" | "stopped"

    def add_subscriber(self, callback):
        with self.lock:
            self.subscribers.add(callback)

    def remove_subscriber(self, callback):
        with self.lock:
            self.subscribers.discard(callback)

    def start(self):
        with self.lock:
            if self.running:
                return
            self.running = True
            self.status = "reconnecting"
            self.worker_thread = threading.Thread(
                target=self._run_ffmpeg,
                daemon=True,
                name=f"okam-worker-{self.camera_id}"
            )
            self.worker_thread.start()

    def _terminate_process(self):
        proc = self.process
        self.process = None
        if proc:
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    try:
                        proc.wait(timeout=1.0)
                    except Exception:
                        pass
                if proc.stdout:
                    try:
                        proc.stdout.close()
                    except Exception:
                        pass
                if proc.stderr:
                    try:
                        proc.stderr.close()
                    except Exception:
                        pass
            except Exception:
                pass

    def stop(self):
        with self.lock:
            self.running = False
            self.status = "stopped"
            self.frame_times.clear()
        self._terminate_process()
        with self.lock:
            self.status = "stopped"
            self.frame_times.clear()

    def restart(self):
        self.stop()
        time.sleep(0.2)
        self.start()

    def get_metrics(self):
        now = time.time()
        with self.lock:
            fps = 0.0
            if len(self.frame_times) >= 2:
                duration = self.frame_times[-1] - self.frame_times[0]
                if duration > 0:
                    fps = round((len(self.frame_times) - 1) / duration, 1)

            # If no frame arrived within the last 2.5s, report 0 fps
            if self.latest_frame_time == 0 or (now - self.latest_frame_time) > 2.5:
                fps = 0.0

            latency_ms = 0.0
            if self.latest_frame_time > 0:
                latency_ms = round(max(0, (now - self.latest_frame_time) * 1000), 1)

            active_clients = len(self.subscribers)
            status = self.status

            if status == "connected" and fps >= 10.0:
                dominant = "Nominal"
                severity = "nominal"
                desc = f"RTSP-to-MJPEG pipeline beroperasi normal pada {fps} fps ({self.resolution}) dengan latensi {latency_ms}ms."
            elif status == "connected" and fps > 0.0:
                dominant = "CameraSource"
                severity = "warning"
                desc = f"RTSP stream beroperasi dengan framerate tereduksi ({fps} fps)."
            elif self.reconnect_count > 0:
                dominant = "CameraSource"
                severity = "warning"
                desc = f"RTSP stream mengalami interupsi LAN ({self.reconnect_count} kali reconnect). FPS saat ini {fps} fps."
            else:
                dominant = "CameraSource"
                severity = "nominal"
                desc = f"Menunggu koneksi stream untuk {self.name}."

            stages = {
                "cameraDeclaredFps": self.target_fps,
                "sourceFps": fps,
                "decoderInFps": fps,
                "decoderOutFps": fps,
                "mjpegOutFps": fps if active_clients > 0 else 0.0,
                "rtspOutFps": fps,
                "browserRenderFps": self.browser_render_fps
            }

            latency = {
                "decodeLatencyMs": latency_ms,
                "queueLatencyMs": 0.0,
                "mjpegLatencyMs": 0.0
            }

            health = {
                "droppedDecoderIn": 0,
                "droppedMjpegIn": 0,
                "droppedWaitingForKeyframe": 0,
                "queueDepth": 0,
                "reconnectCount": self.reconnect_count,
                "decodingErrors": self.decode_errors,
                "lastError": self.last_error,
                "cpuUsagePercent": 0.0,
                "memoryUsageMb": 0.0,
                "activeFfmpegCount": 1 if self.process and self.process.poll() is None else 0
            }

            bottleneck = {
                "dominantStage": dominant,
                "severity": severity,
                "description": desc
            }

            return {
                "cameraId": self.camera_id,
                "name": self.name,
                "status": status,
                "sourceFps": fps,
                "targetFps": self.target_fps,
                "resolution": self.resolution,
                "xcodeInFps": fps,
                "xcodeOutFps": fps,
                "xcodeLatencyMs": latency_ms,
                "rtspFps": fps,
                "mjpegFps": fps if active_clients > 0 else 0.0,
                "totalSourceFrames": self.total_frames,
                "totalRtspFrames": self.total_frames,
                "totalMjpegFrames": self.total_frames,
                "activeRtspSessions": 0,
                "activeMjpegClients": active_clients,
                "stages": stages,
                "latency": latency,
                "health": health,
                "bottleneck": bottleneck
            }

    def _run_ffmpeg(self):
        transport = (self.rtsp_transport or "tcp").lower()
        if transport not in ("tcp", "udp"):
            transport = "tcp"

        cmd = [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel", "error",
            "-rtsp_transport", transport,
            "-timeout", "5000000",
            "-fflags", "nobuffer+discardcorrupt",
            "-flags", "low_delay",
            "-probesize", "1000000",
            "-analyzeduration", "1000000",
            "-i", self.rtsp_url,
            "-an",
            "-fps_mode", "passthrough",
            "-c:v", "mjpeg",
            "-pix_fmt", "yuvj420p",
            "-q:v", "5",
            "-f", "mpjpeg",
            "-boundary_tag", "frame",
            "pipe:1"
        ]

        clean_url = sanitize_rtsp_url(self.rtsp_url)
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0

        while self.running:
            print(f"[OKAM-{self.camera_id}] Connecting to RTSP ({transport.upper()}): {clean_url}", flush=True)
            self.status = "reconnecting"

            try:
                self.process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=0,
                    creationflags=creation_flags
                )

                proc_ref = self.process
                last_io = [time.time()]

                def stall_watchdog(p=proc_ref, io_ref=last_io):
                    while self.running and p.poll() is None:
                        if (time.time() - io_ref[0]) > 12.0:
                            print(f"[OKAM-{self.camera_id}] RTSP stream stalled >12s, restarting FFmpeg...", flush=True)
                            try:
                                p.kill()
                            except Exception:
                                pass
                            break
                        time.sleep(1.0)

                threading.Thread(target=stall_watchdog, daemon=True, name=f"okam-wd-{self.camera_id}").start()

                def read_stderr(p=proc_ref):
                    try:
                        for line in p.stderr:
                            if not self.running:
                                break
                            text = line.decode("utf-8", errors="ignore").strip()
                            if text:
                                with self.lock:
                                    self.decode_errors += 1
                                    self.last_error = sanitize_rtsp_url(text)
                                print(f"[OKAM-FFMPEG-{self.camera_id}] {sanitize_rtsp_url(text)}", file=sys.stderr, flush=True)
                    except Exception:
                        pass

                t_err = threading.Thread(target=read_stderr, daemon=True, name=f"okam-err-{self.camera_id}")
                t_err.start()

                stdout = proc_ref.stdout
                buffer = bytearray()
                delimiter = b"--frame\r\n"

                while self.running and proc_ref.poll() is None:
                    chunk = stdout.read(32768)
                    if not chunk:
                        break
                    last_io[0] = time.time()
                    buffer.extend(chunk)

                    while True:
                        idx = buffer.find(delimiter)
                        if idx == -1:
                            break

                        next_idx = buffer.find(delimiter, idx + len(delimiter))
                        if next_idx == -1:
                            break

                        frame_data = bytes(buffer[idx:next_idx])
                        del buffer[:next_idx]

                        # Extract raw JPEG payload
                        header_end = frame_data.find(b"\r\n\r\n")
                        if header_end != -1:
                            jpeg_bytes = frame_data[header_end + 4:].rstrip(b"\r\n")
                        else:
                            jpeg_bytes = None

                        dims = extract_jpeg_dimensions(jpeg_bytes) if jpeg_bytes else None

                        now = time.time()
                        with self.lock:
                            self.total_frames += 1
                            self.frame_times.append(now)
                            if dims:
                                self.resolution = f"{dims[0]}x{dims[1]}"
                            if jpeg_bytes:
                                self.latest_frame = jpeg_bytes
                                self.latest_frame_time = now
                                self.status = "connected"

                            subs = list(self.subscribers)

                        for sub in subs:
                            try:
                                sub(frame_data)
                            except Exception:
                                pass

            except Exception as e:
                print(f"[OKAM-{self.camera_id}] Worker error: {e}", file=sys.stderr, flush=True)

            # Cleanup process to prevent zombies
            self._terminate_process()

            if self.running:
                with self.lock:
                    self.reconnect_count += 1
                    self.status = "reconnecting"
                print(f"[OKAM-{self.camera_id}] Stream disconnected, retrying in 3 seconds...", flush=True)
                for _ in range(15):
                    if not self.running:
                        break
                    time.sleep(0.2)


# Backward compatibility alias for legacy tests / single-camera scripts
StreamBroker = CameraStreamWorker


class MultiCameraManager:
    """Coordinates multiple independent CameraStreamWorker instances."""

    def __init__(self):
        self.workers = {}
        self.aliases = {}
        self.default_id = None
        self.lock = threading.Lock()

    def register_camera(self, camera_id: str, name: str, rtsp_url: str,
                        resolution: str = "1920x1080", rtsp_transport: str = "tcp",
                        target_fps: float = 15.0, aliases: list = None):
        with self.lock:
            # Prevent spawning duplicate decoder processes for the exact same RTSP URL
            if rtsp_url:
                for existing_cid, existing_w in self.workers.items():
                    if existing_cid != camera_id and existing_w.rtsp_url == rtsp_url:
                        self.aliases[camera_id] = existing_cid
                        if aliases:
                            for alias in aliases:
                                self.aliases[alias] = existing_cid
                        return existing_w

            # Stop existing worker if re-registering same camera_id to prevent duplicate decoder processes
            if camera_id in self.workers:
                try:
                    self.workers[camera_id].stop()
                except Exception:
                    pass

            worker = CameraStreamWorker(
                camera_id=camera_id,
                name=name,
                rtsp_url=rtsp_url,
                resolution=resolution,
                rtsp_transport=rtsp_transport,
                target_fps=target_fps
            )
            self.workers[camera_id] = worker
            if self.default_id is None:
                self.default_id = camera_id

            if aliases:
                for alias in aliases:
                    self.aliases[alias] = camera_id
            return worker

    def add_alias(self, alias: str, target_id: str):
        with self.lock:
            self.aliases[alias] = target_id

    def get_worker(self, camera_id: str):
        with self.lock:
            if not camera_id:
                camera_id = self.default_id
            resolved_id = self.aliases.get(camera_id, camera_id)
            return self.workers.get(resolved_id)

    def get_all_cameras_info(self):
        info_list = []
        with self.lock:
            for cid, w in self.workers.items():
                m = w.get_metrics()
                info_list.append({
                    "id": cid,
                    "name": w.name,
                    "rtspUrl": sanitize_rtsp_url(w.rtsp_url),
                    "streamPath": f"/api/cameras/{cid}/stream.mjpg",
                    "snapshotPath": f"/api/cameras/{cid}/snapshot",
                    "metricsPath": f"/api/cameras/{cid}/metrics",
                    "status": w.status,
                    "fps": m.get("sourceFps", 0.0),
                    "resolution": w.resolution,
                    "latency": m.get("xcodeLatencyMs", 0.0)
                })
        return info_list

    def start_all(self):
        with self.lock:
            for w in self.workers.values():
                w.start()

    def stop_all(self):
        with self.lock:
            for w in self.workers.values():
                w.stop()


class ThreadedServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address, RequestHandlerClass, manager=None):
        super().__init__(server_address, RequestHandlerClass)
        self.manager = manager


class HttpHandler(BaseHTTPRequestHandler):
    """HTTP request handler supporting both multi-camera /api/cameras/... and legacy endpoints."""
    manager = None
    broker = None  # Backward compatibility class attribute

    def log_message(self, format, *args):
        pass

    def send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("ngrok-skip-browser-warning", "1")

    def do_OPTIONS(self):
        try:
            self.send_response(204)
            self.send_cors_headers()
            self.end_headers()
        except Exception:
            pass

    def _resolve_worker(self, camera_id=None):
        # Prefer server instance manager
        mgr = getattr(self.server, "manager", None) or self.manager
        if mgr:
            return mgr.get_worker(camera_id)
        # Fallback to class broker attribute
        return self.broker

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parsed.query
        qs = parse_qs(query)

        mgr = getattr(self.server, "manager", None) or self.manager

        # --- 1. GET /api/cameras ---
        if path == "/api/cameras" or path == "/api/cameras/":
            try:
                cams = mgr.get_all_cameras_info() if mgr else []
                body = json.dumps({"cameras": cams}, indent=2).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(body)
            except Exception:
                pass
            return

        # --- 2. Multi-camera routes: /api/cameras/{camera_id}/(metrics|snapshot|stream.mjpg) ---
        match = re.match(r"^/api/cameras/([^/]+)/(metrics|snapshot|stream\.mjpg)$", path)
        if match:
            target_cid, endpoint = match.group(1), match.group(2)
            worker = self._resolve_worker(target_cid)
            if not worker:
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"error": f"Camera '{target_cid}' not found in adapter registry"}).encode("utf-8"))
                return

            if endpoint == "metrics":
                self._handle_metrics(worker, qs)
                return
            elif endpoint == "snapshot":
                self._handle_snapshot(worker)
                return
            elif endpoint == "stream.mjpg":
                self._handle_stream(worker)
                return

        # --- 3. Legacy single-camera endpoints ---
        if path == "/api/metrics":
            worker = self._resolve_worker()
            if worker:
                self._handle_metrics(worker, qs)
            else:
                self._send_404_or_503("No camera worker available")
            return

        if path == "/snapshot":
            worker = self._resolve_worker()
            if worker:
                self._handle_snapshot(worker)
            else:
                self._send_404_or_503("No camera worker available")
            return

        if path == "/stream.mjpg":
            worker = self._resolve_worker()
            if worker:
                self._handle_stream(worker)
            else:
                self._send_404_or_503("No camera worker available")
            return

        # --- 4. Default / Info ---
        try:
            cams = mgr.get_all_cameras_info() if mgr else []
            body = (
                f"CamHUB O-Kam Multi-Camera Adapter running.\n"
                f"Registered cameras: {len(cams)}\n"
                f"Endpoints:\n"
                f"  GET /api/cameras\n"
                f"  GET /api/cameras/<id>/metrics\n"
                f"  GET /api/cameras/<id>/snapshot\n"
                f"  GET /api/cameras/<id>/stream.mjpg\n"
                f"Legacy Endpoints: /stream.mjpg, /snapshot, /api/metrics\n"
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(body)
        except Exception:
            pass

    def _handle_metrics(self, worker: CameraStreamWorker, qs: dict):
        try:
            if "clientFps" in qs:
                try:
                    worker.browser_render_fps = float(qs["clientFps"][0])
                except Exception:
                    pass

            metrics = worker.get_metrics()
            body = json.dumps(metrics).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(body)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
            pass

    def _handle_snapshot(self, worker: CameraStreamWorker):
        try:
            frame = worker.latest_frame
            if not frame:
                self.send_response(503)
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(b"No snapshot available yet")
                return

            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(frame)))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(frame)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
            pass

    def _handle_stream(self, worker: CameraStreamWorker):
        try:
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Connection", "close")
            self.send_cors_headers()
            self.end_headers()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
            return

        # Deliver latest frame immediately if available so browser renders without delay
        init_frame = worker.latest_frame
        if init_frame:
            try:
                part = (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(init_frame)).encode("ascii") + b"\r\n\r\n"
                    + init_frame + b"\r\n"
                )
                self.wfile.write(part)
                self.wfile.flush()
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
                return

        client_alive = [True]

        def on_frame(data):
            if not client_alive[0]:
                return
            try:
                self.wfile.write(data)
                self.wfile.flush()
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
                client_alive[0] = False

        worker.add_subscriber(on_frame)
        try:
            while client_alive[0] and worker.running:
                time.sleep(0.2)
        except Exception:
            pass
        finally:
            client_alive[0] = False
            worker.remove_subscriber(on_frame)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        match = re.match(r"^/api/cameras/([^/]+)/(start|stop|restart)$", path)
        if match:
            target_cid, action = match.group(1), match.group(2)
            worker = self._resolve_worker(target_cid)
            if not worker:
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"error": f"Camera '{target_cid}' not found"}).encode("utf-8"))
                return

            if action == "start":
                worker.start()
            elif action == "stop":
                worker.stop()
            elif action == "restart":
                worker.restart()

            body = json.dumps({
                "success": True,
                "cameraId": worker.camera_id,
                "action": action,
                "status": worker.status
            }).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.send_cors_headers()
        self.end_headers()
        self.wfile.write(json.dumps({"error": "Endpoint not found"}).encode("utf-8"))

    def _send_404_or_503(self, message: str):
        try:
            self.send_response(503)
            self.send_header("Content-Type", "text/plain")
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(message.encode("utf-8"))
        except Exception:
            pass


DEFAULT_OKAM_CAMERAS = [
    {
        "id": "okam_1",
        "name": "O-Kam 1 · Panoramic Main (Sensor Tetap)",
        "rtspUrl": "rtsp://admin:Danendra07.@192.168.100.6:10554/tcp/av0_0",
        "rtspTransport": "tcp",
        "resolution": "1920x1080",
        "targetFps": 15.0,
        "aliases": ["okam-3", "okam-1"]
    },
    {
        "id": "okam_2",
        "name": "O-Kam 2 · PTZ Motorik (Area Teras & Pintu)",
        "rtspUrl": "rtsp://admin:Danendra07.@192.168.100.6:10555/tcp/av0_0",
        "rtspTransport": "tcp",
        "resolution": "1920x1080",
        "targetFps": 15.0,
        "aliases": ["okam-2"]
    },
    {
        "id": "okam_3",
        "name": "O-Kam 3 · Sub-Stream Sensor (Wide Aux)",
        "rtspUrl": "rtsp://admin:Danendra07.@192.168.100.6:10554/tcp/av0_1",
        "rtspTransport": "tcp",
        "resolution": "448x256",
        "targetFps": 15.0,
        "aliases": ["okam-sub"]
    }
]


def create_manager_from_config(config_path: str = None) -> MultiCameraManager:
    """Builds a MultiCameraManager from services_config.json or default cameras."""
    manager = MultiCameraManager()

    cameras_to_load = []
    seen_rtsp = set()

    if config_path and os.path.isfile(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                for cam in cfg.get("cameras", []):
                    if cam.get("type") == "okam" or str(cam.get("id", "")).startswith("okam"):
                        if "lenses" in cam and isinstance(cam["lenses"], list):
                            for idx, lens in enumerate(cam["lenses"]):
                                lid = f"okam_{lens.get('id', idx + 1)}"
                                rtsp_url = lens.get("rtspUrl", "")
                                if not rtsp_url or rtsp_url in seen_rtsp:
                                    continue
                                seen_rtsp.add(rtsp_url)
                                aliases = [f"okam-lens-{lens.get('id', idx + 1)}"]
                                if idx == 0:
                                    aliases.extend(["okam-3", "okam-1"])
                                cameras_to_load.append({
                                    "id": lid,
                                    "name": f"{cam.get('name', 'O-Kam')} · {lens.get('name', f'Lens {idx+1}')}",
                                    "rtspUrl": rtsp_url,
                                    "rtspTransport": lens.get("rtspTransport", cam.get("rtspTransport", "tcp")),
                                    "resolution": lens.get("resolution", "1920x1080"),
                                    "targetFps": lens.get("targetFps", cam.get("targetFps", 15.0)),
                                    "aliases": aliases
                                })
                        else:
                            rtsp_url = cam.get("rtspUrl") or cam.get("rtsp")
                            if not rtsp_url and "--rtsp" in cam.get("cmd", ""):
                                cmd_str = cam.get("cmd", "")
                                match = re.search(r'--rtsp\s+["\']?([^"\']+)["\']?', cmd_str)
                                if match:
                                    rtsp_url = match.group(1)

                            if rtsp_url and rtsp_url not in seen_rtsp:
                                seen_rtsp.add(rtsp_url)
                                cameras_to_load.append({
                                    "id": cam.get("id"),
                                    "name": cam.get("name", cam.get("id")),
                                    "rtspUrl": rtsp_url,
                                    "rtspTransport": cam.get("rtspTransport", "tcp"),
                                    "resolution": cam.get("resolution", "1920x1080"),
                                    "targetFps": cam.get("targetFps", 15.0),
                                    "aliases": cam.get("aliases", [])
                                })
        except Exception as e:
            print(f"[OKAM-ADAPTER] Warning reading config {config_path}: {e}", file=sys.stderr)

    if not cameras_to_load:
        cameras_to_load = DEFAULT_OKAM_CAMERAS

    for c in cameras_to_load:
        manager.register_camera(
            camera_id=c["id"],
            name=c["name"],
            rtsp_url=c["rtspUrl"],
            resolution=c.get("resolution", "1920x1080"),
            rtsp_transport=c.get("rtspTransport", "tcp"),
            target_fps=c.get("targetFps", 15.0),
            aliases=c.get("aliases", [])
        )

    # Ensure backward compatibility alias okam-3 exists
    if "okam-3" not in manager.workers and "okam_1" in manager.workers:
        manager.add_alias("okam-3", "okam_1")

    return manager


def run_server(rtsp_url: str = None, port: int = 8082, config_path: str = None, camera_id: str = "okam_1"):
    """Starts the multi-camera HTTP adapter service."""
    if rtsp_url and not config_path:
        # Legacy single-camera invocation mode
        manager = MultiCameraManager()
        manager.register_camera(
            camera_id=camera_id,
            name="O-Kam Pro / VStarcam",
            rtsp_url=rtsp_url,
            resolution="1920x1080",
            aliases=["okam-3"] if camera_id != "okam-3" else []
        )
    else:
        # Multi-camera mode
        manager = create_manager_from_config(config_path)

    manager.start_all()

    # Set backward-compat class attributes
    first_worker = manager.get_worker(manager.default_id)
    HttpHandler.broker = first_worker
    HttpHandler.manager = manager

    server = ThreadedServer(("0.0.0.0", port), HttpHandler, manager=manager)
    print(f"[OKAM-ADAPTER] HTTP Server running on http://0.0.0.0:{port}", flush=True)
    print(f"[OKAM-ADAPTER] Registered Cameras: {[w.camera_id for w in manager.workers.values()]}", flush=True)
    print(f"[OKAM-ADAPTER] Fleet API: http://127.0.0.1:{port}/api/cameras", flush=True)
    for cid in manager.workers.keys():
        print(f"  • {cid} -> Stream: http://127.0.0.1:{port}/api/cameras/{cid}/stream.mjpg | Snapshot: http://127.0.0.1:{port}/api/cameras/{cid}/snapshot", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        print("[OKAM-ADAPTER] Shutting down all camera workers...", flush=True)
        manager.stop_all()
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CamHUB O-Kam Pro Multi-Camera Stream Adapter")
    parser.add_argument("--config", default="config/services_config.json", help="Path to services_config.json")
    parser.add_argument("--rtsp", default="", help="Single camera RTSP URL override")
    parser.add_argument("--id", default="okam_1", help="Camera ID when using single-camera override")
    parser.add_argument("--port", type=int, default=8082, help="HTTP Port")
    args = parser.parse_args()

    rtsp_override = args.rtsp if args.rtsp else None
    cfg_file = args.config if (not args.rtsp and os.path.isfile(args.config)) else None

    run_server(rtsp_url=rtsp_override, port=args.port, config_path=cfg_file, camera_id=args.id)
