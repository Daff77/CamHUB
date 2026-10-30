"""
CamHub Host Server & Camera Process Manager
Serves the CamHub web dashboard and provides REST APIs to control camera processes.
"""

import os
import sys
import json
import time
import shutil
import socket
import argparse
import subprocess
from urllib.parse import urlparse, parse_qs
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CORE_DIR = os.path.join(BASE_DIR, "core")
WEB_DIR = os.path.join(BASE_DIR, "web")
CONFIG_DIR = os.path.join(BASE_DIR, "config")

# Ensure core package and root directory are in sys.path
if CORE_DIR not in sys.path:
    sys.path.insert(0, CORE_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.health_monitor import CameraHealthMonitor, sanitize_sensitive_data
from core.auto_recovery import AutoRecoveryManager, kill_process_tree, kill_port_owner
from core.recording_manager import RecordingManager, sanitize_path
from core.motion_detector import MotionDetectorService

# Config file discovery: config/services_config.json first, fallback to root
CONFIG_FILE = os.path.join(CONFIG_DIR, "services_config.json")
if not os.path.exists(CONFIG_FILE):
    CONFIG_FILE = os.path.join(BASE_DIR, "services_config.json")

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[SERVER] Error loading config: {e}", file=sys.stderr)
    return {"cameras": []}

def is_port_open(port):
    """Check if a TCP port is currently open and listening on localhost."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.4)
            return s.connect_ex(("127.0.0.1", port)) == 0
    except:
        return False

def kill_port_process(port):
    """Forcefully terminate any process holding a specific port on Windows."""
    try:
        cmd = f'powershell -NoProfile -Command "(Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue).OwningProcess"'
        out = subprocess.check_output(cmd, shell=True, text=True).strip()
        pids = set(out.split())
        for pid_str in pids:
            if pid_str.isdigit():
                pid = int(pid_str)
                if pid > 0:
                    subprocess.run(f"taskkill /F /T /PID {pid}", shell=True, capture_output=True)
                    print(f"[SERVER] Killed PID {pid} on port {port}", flush=True)
    except Exception as e:
        print(f"[SERVER] kill_port_process error: {e}", file=sys.stderr)

class ProcessManager:
    def __init__(self):
        self.processes = {}

    def get_status(self):
        cfg = load_config()
        status = {}
        all_running = True
        any_running = False

        for cam in cfg.get("cameras", []):
            cid = cam.get("id")
            port = cam.get("port")
            running = is_port_open(port)

            status[cid] = {
                "id": cid,
                "name": cam.get("name"),
                "port": port,
                "running": running
            }
            if running:
                any_running = True
            else:
                all_running = False

        return {
            "services": status,
            "allRunning": all_running and len(status) > 0,
            "anyRunning": any_running
        }

    def start_camera(self, cid):
        cfg = load_config()
        cam = next((c for c in cfg.get("cameras", []) if c.get("id") == cid), None)
        if not cam:
            return False, f"Camera '{cid}' not found in configuration"

        port = cam.get("port")
        if is_port_open(port):
            return True, f"Camera '{cid}' is already running on port {port}"

        cmd = cam.get("cmd")
        if not cmd:
            return False, f"No command defined for camera '{cid}'"

        try:
            print(f"[SERVER] Spawning camera '{cid}' on port {port}...", flush=True)
            proc = subprocess.Popen(
                cmd,
                shell=True,
                cwd=BASE_DIR,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
            )
            self.processes[cid] = proc
            return True, f"Started camera '{cid}'"
        except Exception as e:
            return False, str(e)

    def stop_camera(self, cid):
        cfg = load_config()
        cam = next((c for c in cfg.get("cameras", []) if c.get("id") == cid), None)
        if not cam:
            return False, f"Camera '{cid}' not found in configuration"

        port = cam.get("port")
        kill_port_process(port)
        if cid in self.processes:
            try:
                self.processes[cid].terminate()
            except:
                pass
            del self.processes[cid]

        return True, f"Stopped camera '{cid}'"

    def start_all(self):
        cfg = load_config()
        results = {}
        for cam in cfg.get("cameras", []):
            cid = cam.get("id")
            ok, msg = self.start_camera(cid)
            results[cid] = {"success": ok, "message": msg}
            time.sleep(0.3)
        return results

    def stop_all(self):
        cfg = load_config()
        results = {}
        for cam in cfg.get("cameras", []):
            cid = cam.get("id")
            ok, msg = self.stop_camera(cid)
            results[cid] = {"success": ok, "message": msg}
        return results

    def restart_all(self):
        self.stop_all()
        time.sleep(1.0)
        return self.start_all()

HEALTH_MONITOR = CameraHealthMonitor(load_config)
MANAGER = AutoRecoveryManager(load_config, health_monitor=HEALTH_MONITOR)
RECORDING_MANAGER = RecordingManager(load_config, base_dir=BASE_DIR)
MOTION_SERVICE = MotionDetectorService(load_config, base_dir=BASE_DIR)

STATIC_DIR = WEB_DIR if os.path.isdir(WEB_DIR) else BASE_DIR

class CamHubHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=STATIC_DIR, **kwargs)

    def translate_path(self, path):
        # Look in web/ directory first, fall back to BASE_DIR
        res = super().translate_path(path)
        if os.path.exists(res):
            return res
        rel = path.lstrip("/")
        fallback = os.path.join(BASE_DIR, rel)
        if os.path.exists(fallback):
            return fallback
        return res

    def log_message(self, format, *args):
        # Silence routine static asset logs
        if "/api/services" in (args[0] if args else ""):
            print(f"[API] {args[0]}", flush=True)

    def send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("ngrok-skip-browser-warning", "1")

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("ngrok-skip-browser-warning", "1")
        super().end_headers()

    def send_file_with_range(self, file_path, content_type="video/mp4", as_download=False):
        """Supports HTTP 206 Partial Content for video seeking/scrubbing and downloads."""
        if not os.path.exists(file_path):
            self.send_json(404, {"error": "Recording file not found on disk"})
            return

        file_size = os.path.getsize(file_path)
        range_header = self.headers.get("Range")
        filename = os.path.basename(file_path)
        disposition = f'attachment; filename="{filename}"' if as_download else "inline"

        if not range_header or as_download:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(file_size))
            self.send_header("Content-Disposition", disposition)
            self.send_header("Accept-Ranges", "bytes")
            self.send_cors_headers()
            self.end_headers()
            with open(file_path, "rb") as f:
                shutil.copyfileobj(f, self.wfile, length=65536)
            return

        try:
            bytes_range = range_header.strip().split("=")[1]
            start_str, end_str = bytes_range.split("-")
            start = int(start_str) if start_str else 0
            end = int(end_str) if end_str else file_size - 1
            if end >= file_size:
                end = file_size - 1
            length = end - start + 1
        except Exception:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{file_size}")
            self.end_headers()
            return

        self.send_response(206)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
        self.send_header("Content-Length", str(length))
        self.send_header("Content-Disposition", disposition)
        self.send_header("Accept-Ranges", "bytes")
        self.send_cors_headers()
        self.end_headers()

        with open(file_path, "rb") as f:
            f.seek(start)
            remaining = length
            chunk_size = 65536
            while remaining > 0:
                read_size = min(chunk_size, remaining)
                chunk = f.read(read_size)
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def send_json(self, status_code, data):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_cors_headers()
        self.end_headers()
        try:
            self.wfile.write(body)
        except:
            pass

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_cors_headers()
        self.end_headers()

    def proxy_mjpeg_stream(self, camera_id):
        cfg = load_config()
        cam = next((c for c in cfg.get("cameras", []) if c.get("id") == camera_id), None)
        if not cam:
            self.send_json(404, {"error": f"Camera '{camera_id}' not found in configuration"})
            return

        port = cam.get("port")
        if not port or not is_port_open(port):
            self.send_json(503, {"error": f"Camera '{camera_id}' decoder service is offline on port {port}"})
            return

        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            sock.connect(("127.0.0.1", port))
            req = f"GET /stream.mjpg HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n".encode("utf-8")
            sock.sendall(req)

            header_data = b""
            while b"\r\n\r\n" not in header_data:
                chunk = sock.recv(2048)
                if not chunk:
                    break
                header_data += chunk

            header_part, _, body_init = header_data.partition(b"\r\n\r\n")
            header_lines = header_part.decode("utf-8", errors="replace").split("\r\n")

            content_type = "multipart/x-mixed-replace; boundary=--boundary"
            for h in header_lines[1:]:
                if ":" in h:
                    k, v = h.split(":", 1)
                    if k.strip().lower() == "content-type":
                        content_type = v.strip()

            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.send_header("Connection", "close")
            self.send_header("ngrok-skip-browser-warning", "1")
            self.send_cors_headers()
            self.end_headers()

            if body_init:
                self.wfile.write(body_init)
                self.wfile.flush()

            sock.settimeout(None)
            while True:
                data = sock.recv(32768)
                if not data:
                    break
                self.wfile.write(data)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            pass
        finally:
            if sock:
                try:
                    sock.close()
                except:
                    pass

    def proxy_snapshot(self, camera_id):
        cfg = load_config()
        cam = next((c for c in cfg.get("cameras", []) if c.get("id") == camera_id), None)
        if not cam:
            self.send_json(404, {"error": f"Camera '{camera_id}' not found"})
            return

        port = cam.get("port")
        if not port or not is_port_open(port):
            self.send_json(503, {"error": f"Camera '{camera_id}' decoder service is offline on port {port}"})
            return

        try:
            req = Request(f"http://127.0.0.1:{port}/snapshot")
            req.add_header("User-Agent", "CamHub-Proxy/1.0")
            req.add_header("ngrok-skip-browser-warning", "1")
            with urlopen(req, timeout=2.5) as resp:
                data = resp.read()

            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("ngrok-skip-browser-warning", "1")
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self.send_json(502, {"error": f"Failed to retrieve snapshot from port {port}: {e}"})

    def proxy_metrics(self, camera_id, qs):
        cfg = load_config()
        cam = next((c for c in cfg.get("cameras", []) if c.get("id") == camera_id), None)
        if not cam:
            self.send_json(404, {"error": f"Camera '{camera_id}' not found"})
            return

        port = cam.get("port")
        if not port or not is_port_open(port):
            self.send_json(503, {"error": f"Camera '{camera_id}' decoder service is offline on port {port}"})
            return

        client_fps = qs.get("clientFps", [None])[0]
        query = f"?clientFps={client_fps}" if client_fps else ""

        try:
            req = Request(f"http://127.0.0.1:{port}/api/metrics{query}")
            req.add_header("User-Agent", "CamHub-Proxy/1.0")
            req.add_header("ngrok-skip-browser-warning", "1")
            with urlopen(req, timeout=2.0) as resp:
                data = resp.read()

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("ngrok-skip-browser-warning", "1")
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self.send_json(502, {"error": f"Failed to retrieve metrics from port {port}: {e}"})

    def do_GET(self):
        url = urlparse(self.path)
        qs = parse_qs(url.query)

        # Reverse Proxy endpoints for Ngrok & remote HTTPS access (avoids Mixed Content & extra port forwards)
        if url.path.startswith("/proxy/stream/"):
            cid = url.path[len("/proxy/stream/"):].strip("/")
            self.proxy_mjpeg_stream(cid)
            return

        if url.path == "/proxy/stream":
            cid = qs.get("id", [None])[0]
            if cid:
                self.proxy_mjpeg_stream(cid)
            else:
                self.send_json(400, {"error": "Missing 'id' parameter"})
            return

        if url.path.startswith("/proxy/snapshot/"):
            cid = url.path[len("/proxy/snapshot/"):].strip("/")
            self.proxy_snapshot(cid)
            return

        if url.path == "/proxy/snapshot":
            cid = qs.get("id", [None])[0]
            if cid:
                self.proxy_snapshot(cid)
            else:
                self.send_json(400, {"error": "Missing 'id' parameter"})
            return

        if url.path.startswith("/proxy/metrics/"):
            cid = url.path[len("/proxy/metrics/"):].strip("/")
            self.proxy_metrics(cid, qs)
            return

        if url.path == "/proxy/metrics":
            cid = qs.get("id", [None])[0]
            if cid:
                self.proxy_metrics(cid, qs)
            else:
                self.send_json(400, {"error": "Missing 'id' parameter"})
            return

        # Health monitor endpoints
        if url.path == "/api/health":
            cid = qs.get("id", [None])[0]
            if cid:
                data = HEALTH_MONITOR.get_camera_health(cid)
                if data:
                    self.send_json(200, data)
                else:
                    self.send_json(404, {"error": f"Camera '{cid}' not found in health monitor"})
            else:
                data = HEALTH_MONITOR.get_all_health()
                self.send_json(200, data)
            return

        if url.path.startswith("/api/health/"):
            cid = url.path[len("/api/health/"):].strip("/")
            data = HEALTH_MONITOR.get_camera_health(cid)
            if data:
                self.send_json(200, data)
            else:
                self.send_json(404, {"error": f"Camera '{cid}' not found in health monitor"})
            return

        if url.path == "/api/recovery/status":
            data = MANAGER.get_status()
            self.send_json(200, data)
            return

        if url.path == "/api/services/status":
            data = MANAGER.get_status()
            # Enrich service status with smart health monitor data
            for cid, s_info in data.get("services", {}).items():
                h = HEALTH_MONITOR.get_camera_health(cid)
                if h:
                    s_info["health"] = h
                    s_info["healthStatus"] = h.get("status")
                    s_info["healthReason"] = h.get("reason")
            self.send_json(200, data)
            return

        # Recordings list & metadata
        if url.path == "/api/recordings":
            cam_id = qs.get("cameraId", [None])[0]
            date_str = qs.get("date", [None])[0]
            limit_str = qs.get("limit", ["100"])[0]
            limit = int(limit_str) if limit_str.isdigit() else 100
            items = RECORDING_MANAGER.list_recordings(camera_id=cam_id, date_str=date_str, limit=limit)
            self.send_json(200, {"recordings": items, "count": len(items)})
            return

        if url.path == "/api/recordings/storage":
            stats = RECORDING_MANAGER.get_storage_status()
            self.send_json(200, stats)
            return

        # Stream recording with HTTP 206 Partial Content
        if url.path == "/api/recordings/stream":
            seg_id = qs.get("id", [None])[0]
            if not seg_id:
                self.send_json(400, {"error": "Missing 'id' query parameter"})
                return
            item = RECORDING_MANAGER.get_recording_item(seg_id)
            if not item:
                self.send_json(404, {"error": "Recording not found"})
                return
            try:
                full_path = sanitize_path(BASE_DIR, os.path.join(BASE_DIR, item["filePath"]))
                self.send_file_with_range(full_path, content_type="video/mp4", as_download=False)
            except Exception as e:
                self.send_json(403, {"error": str(e)})
            return

        # Download recording attachment
        if url.path == "/api/recordings/download":
            seg_id = qs.get("id", [None])[0]
            if not seg_id:
                self.send_json(400, {"error": "Missing 'id' query parameter"})
                return
            item = RECORDING_MANAGER.get_recording_item(seg_id)
            if not item:
                self.send_json(404, {"error": "Recording not found"})
                return
            try:
                full_path = sanitize_path(BASE_DIR, os.path.join(BASE_DIR, item["filePath"]))
                self.send_file_with_range(full_path, content_type="video/mp4", as_download=True)
            except Exception as e:
                self.send_json(403, {"error": str(e)})
            return

        # AI Status & Telemetry
        if url.path == "/api/ai/status":
            stats = MOTION_SERVICE.get_stats()
            cfg = load_config()
            ai_cfg = cfg.get("aiDetection", {})
            detector_info = {
                "enabled": ai_cfg.get("enabled", True),
                "configuredProvider": ai_cfg.get("provider", "auto"),
                "modelPath": ai_cfg.get("modelPath", "models/yolov5n.onnx"),
                "confidenceThreshold": ai_cfg.get("confidenceThreshold", 0.40),
                "targetClasses": ai_cfg.get("targetClasses", ["person", "car", "motorcycle", "animal"]),
                "worker": stats.get("ai", {}),
                "cameras": ai_cfg.get("cameras", {})
            }
            self.send_json(200, detector_info)
            return

        # Motion Detection & Events
        if url.path == "/api/events":
            cam_id = qs.get("cameraId", [None])[0] or qs.get("id", [None])[0]
            date_str = qs.get("date", [None])[0]
            score_str = qs.get("minScore", [None])[0]
            limit_str = qs.get("limit", ["100"])[0]
            obj_class = qs.get("objectClass", [None])[0] or qs.get("class", [None])[0]
            category = qs.get("category", [None])[0]
            min_score = float(score_str) if score_str else None
            limit = int(limit_str) if limit_str.isdigit() else 100

            events = MOTION_SERVICE.list_events(
                camera_id=cam_id,
                date_str=date_str,
                min_score=min_score,
                limit=limit,
                object_class=obj_class,
                category=category
            )
            self.send_json(200, {"events": events, "count": len(events)})
            return

        if url.path == "/api/events/detail":
            evt_id = qs.get("id", [None])[0]
            if not evt_id:
                self.send_json(400, {"error": "Missing 'id' parameter"})
                return
            evt = MOTION_SERVICE.get_event(evt_id)
            if evt:
                self.send_json(200, evt)
            else:
                self.send_json(404, {"error": "Event not found"})
            return

        if url.path == "/api/events/stats":
            stats = MOTION_SERVICE.get_stats()
            self.send_json(200, stats)
            return

        if url.path == "/api/events/snapshot":
            evt_id = qs.get("id", [None])[0]
            raw_path = qs.get("path", [None])[0]
            full_path = None
            if evt_id:
                evt = MOTION_SERVICE.get_event(evt_id)
                if evt and "snapshotPath" in evt:
                    full_path = sanitize_path(BASE_DIR, os.path.join(BASE_DIR, evt["snapshotPath"]))
            elif raw_path:
                full_path = sanitize_path(BASE_DIR, os.path.join(BASE_DIR, raw_path))

            if not full_path or not os.path.exists(full_path):
                self.send_json(404, {"error": "Snapshot image file not found on disk"})
                return

            try:
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(os.path.getsize(full_path)))
                self.send_header("Cache-Control", "public, max-age=86400")
                self.send_header("ngrok-skip-browser-warning", "1")
                self.send_cors_headers()
                self.end_headers()
                with open(full_path, "rb") as f:
                    shutil.copyfileobj(f, self.wfile, length=65536)
                return
            except Exception as e:
                self.send_json(403, {"error": str(e)})
                return

        super().do_GET()

    def do_POST(self):
        url = urlparse(self.path)
        qs = parse_qs(url.query)
        cid = qs.get("id", [None])[0] or qs.get("cameraId", [None])[0]

        # Recording controls
        if url.path == "/api/recordings/start":
            if not cid:
                self.send_json(400, {"error": "Missing 'cameraId' or 'id' parameter"})
                return
            ok, msg = RECORDING_MANAGER.start_recording(cid, mode="manual")
            self.send_json(200 if ok else 400, {"success": ok, "message": msg, "storage": RECORDING_MANAGER.get_storage_status()})
            return

        if url.path == "/api/recordings/stop":
            if not cid:
                self.send_json(400, {"error": "Missing 'cameraId' or 'id' parameter"})
                return
            ok, msg = RECORDING_MANAGER.stop_recording(cid)
            self.send_json(200 if ok else 400, {"success": ok, "message": msg, "storage": RECORDING_MANAGER.get_storage_status()})
            return

        if url.path == "/api/recordings/trigger-motion":
            if not cid:
                self.send_json(400, {"error": "Missing 'cameraId' or 'id' parameter"})
                return
            dur_str = qs.get("duration", ["30"])[0]
            dur = int(dur_str) if dur_str.isdigit() else 30
            ok, msg = RECORDING_MANAGER.trigger_motion_recording(cid, duration=dur)
            self.send_json(200 if ok else 400, {"success": ok, "message": msg, "storage": RECORDING_MANAGER.get_storage_status()})
            return

        if url.path == "/api/services/start-all":
            results = MANAGER.start_all()
            time.sleep(0.4)
            status = MANAGER.get_status()
            self.send_json(200, {"success": True, "results": results, "status": status})
            return

        if url.path == "/api/services/stop-all":
            results = MANAGER.stop_all()
            time.sleep(0.4)
            status = MANAGER.get_status()
            self.send_json(200, {"success": True, "results": results, "status": status})
            return

        if url.path == "/api/services/restart-all":
            results = MANAGER.restart_all()
            time.sleep(0.5)
            status = MANAGER.get_status()
            self.send_json(200, {"success": True, "results": results, "status": status})
            return

        if url.path == "/api/services/start":
            if not cid:
                self.send_json(400, {"error": "Missing 'id' query parameter"})
                return
            ok, msg = MANAGER.start_camera(cid)
            time.sleep(0.4)
            status = MANAGER.get_status()
            self.send_json(200 if ok else 400, {"success": ok, "message": msg, "status": status})
            return

        if url.path == "/api/services/stop":
            if not cid:
                self.send_json(400, {"error": "Missing 'id' query parameter"})
                return
            ok, msg = MANAGER.stop_camera(cid)
            time.sleep(0.4)
            status = MANAGER.get_status()
            self.send_json(200 if ok else 400, {"success": ok, "message": msg, "status": status})
            return

        if url.path == "/api/services/restart":
            if not cid:
                self.send_json(400, {"error": "Missing 'id' query parameter"})
                return
            ok, msg = MANAGER.restart_camera(cid)
            time.sleep(0.5)
            status = MANAGER.get_status()
            self.send_json(200 if ok else 400, {"success": ok, "message": msg, "status": status})
            return

        if url.path == "/api/recovery/reset":
            if not cid:
                self.send_json(400, {"error": "Missing 'id' query parameter"})
                return
            ok, msg = MANAGER.reset_camera(cid)
            status = MANAGER.get_status()
            self.send_json(200 if ok else 404, {"success": ok, "message": msg, "status": status})
            return

        # AI Detection & Benchmark endpoints
        if url.path == "/api/ai/benchmark":
            if not MOTION_SERVICE.ai_detector:
                self.send_json(503, {"error": "AI Object Detector is not initialized"})
                return
            runs_str = qs.get("runs", ["3"])[0]
            runs = int(runs_str) if runs_str.isdigit() else 3
            result = MOTION_SERVICE.ai_detector.benchmark(runs=runs)
            self.send_json(200, result)
            return

        if url.path == "/api/ai/enrich":
            evt_id = qs.get("id", [None])[0]
            if not evt_id:
                self.send_json(400, {"error": "Missing 'id' parameter"})
                return
            enriched = MOTION_SERVICE.enrich_event_with_ai(evt_id)
            if enriched:
                self.send_json(200, enriched)
            else:
                self.send_json(404, {"error": f"Failed to enrich event '{evt_id}'"})
            return

        if url.path == "/api/ai/detect":
            if not cid:
                self.send_json(400, {"error": "Missing 'id' or 'cameraId' parameter"})
                return
            cfg = load_config()
            cam = next((c for c in cfg.get("cameras", []) if c.get("id") == cid), None)
            if not cam:
                self.send_json(404, {"error": f"Camera '{cid}' not found"})
                return
            port = cam.get("port")
            if not port or not is_port_open(port):
                self.send_json(503, {"error": f"Camera decoder on port {port} is offline"})
                return

            try:
                req = Request(f"http://127.0.0.1:{port}/snapshot")
                with urlopen(req, timeout=2.0) as resp:
                    snap_data = resp.read()

                t0 = time.perf_counter()
                cam_ai = MOTION_SERVICE._get_camera_ai_config(cid)
                detections = MOTION_SERVICE.ai_detector.detect(
                    snap_data,
                    conf_threshold=cam_ai.get("confidenceThreshold"),
                    target_classes=cam_ai.get("targetClasses"),
                    roi=cam_ai.get("roi")
                )
                latency = round((time.perf_counter() - t0) * 1000.0, 2)
                self.send_json(200, {
                    "cameraId": cid,
                    "detections": detections,
                    "count": len(detections),
                    "latencyMs": latency,
                    "provider": MOTION_SERVICE.ai_detector.active_provider
                })
            except Exception as e:
                self.send_json(500, {"error": f"Detection failed: {e}"})
            return

        self.send_json(404, {"error": "Endpoint not found"})

    def do_DELETE(self):
        url = urlparse(self.path)
        qs = parse_qs(url.query)
        item_id = qs.get("id", [None])[0]

        if url.path == "/api/recordings":
            if not item_id:
                self.send_json(400, {"error": "Missing 'id' query parameter"})
                return
            ok, msg = RECORDING_MANAGER.delete_recording(item_id)
            self.send_json(200 if ok else 404, {"success": ok, "message": msg})
            return

        if url.path == "/api/events":
            if not item_id:
                self.send_json(400, {"error": "Missing 'id' query parameter"})
                return
            ok, msg = MOTION_SERVICE.delete_event(item_id)
            self.send_json(200 if ok else 404, {"success": ok, "message": msg})
            return

        self.send_json(404, {"error": "Endpoint not found"})


def main():
    parser = argparse.ArgumentParser(description="CamHub Host Server & Camera Manager")
    parser.add_argument("--port", type=int, default=3000, help="Web server port (default: 3000)")
    args = parser.parse_args()

    server = ThreadingHTTPServer(("0.0.0.0", args.port), CamHubHandler)
    server.daemon_threads = True
    print(f"[CAMHUB] Dashboard web server running on http://127.0.0.1:{args.port}", flush=True)
    print(f"[CAMHUB] Service Manager API ready at http://127.0.0.1:{args.port}/api/services/status", flush=True)
    print(f"[CAMHUB] Health Monitor API ready at http://127.0.0.1:{args.port}/api/health", flush=True)
    print(f"[CAMHUB] Auto-Recovery API ready at http://127.0.0.1:{args.port}/api/recovery/status", flush=True)
    print(f"[CAMHUB] Recording & Playback API ready at http://127.0.0.1:{args.port}/api/recordings", flush=True)
    print(f"[CAMHUB] Motion Detection API ready at http://127.0.0.1:{args.port}/api/events", flush=True)

    HEALTH_MONITOR.start()
    MANAGER.start()
    RECORDING_MANAGER.start()
    MOTION_SERVICE.start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[CAMHUB] Shutting down...", flush=True)
    finally:
        MOTION_SERVICE.stop()
        RECORDING_MANAGER.stop()
        MANAGER.shutdown_all()
        MANAGER.stop()
        HEALTH_MONITOR.stop()
        server.server_close()

if __name__ == "__main__":
    main()

