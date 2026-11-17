"""
CamHub Host Server & Camera Process Manager
Serves the CamHub web dashboard strictly from web/ and provides authenticated,
role-authorized REST APIs to control and monitor camera processes, recordings, and storage.
"""

import os
import sys
import json
import time
import shutil
import socket
import argparse
import subprocess
import threading
import re
from datetime import datetime
from urllib.parse import urlparse, parse_qs
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from typing import Optional, Tuple, Type

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
from core.recording_manager import RecordingManager
from core.media_index import sanitize_path
from core.motion_detector import MotionDetectorService
from core.storage_manager import CamHubStorageManager
from core.notification_center import NotificationCenter
from core.diagnostics_service import CamHubDiagnosticsService
from core.ptz_service import CamHubPTZService
from core.auth_manager import AuthManager, get_required_permission

# Config file discovery: config/services_config.json first, fallback to root
CONFIG_FILE = os.path.join(CONFIG_DIR, "services_config.json")
if not os.path.exists(CONFIG_FILE):
    CONFIG_FILE = os.path.join(BASE_DIR, "services_config.json")

# Static serving is strictly confined to web/ — never fall back to BASE_DIR!
STATIC_DIR = WEB_DIR

ALLOWED_SNAPSHOT_EXTENSIONS = {".jpg", ".jpeg", ".png"}


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
            return s.connect_ex(("127.0.0.1", int(port))) == 0
    except Exception:
        return False


def kill_port_process(port):
    """Forcefully terminate any process holding a specific port on Windows."""
    try:
        port_int = int(port)
        out = subprocess.check_output(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"(Get-NetTCPConnection -LocalPort {port_int} -ErrorAction SilentlyContinue).OwningProcess",
            ],
            text=True,
        ).strip()
        pids = set(out.split())
        for pid_str in pids:
            if pid_str.isdigit():
                pid = int(pid_str)
                if pid > 0:
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
                    print(f"[SERVER] Killed PID {pid} on port {port_int}", flush=True)
    except Exception as e:
        print(f"[SERVER] kill_port_process error: {e}", file=sys.stderr)


def parse_http_byte_range(range_header: str, file_size: int) -> Tuple[int, int]:
    """
    Parse an RFC 9110 single HTTP Range header ('bytes=start-end', 'bytes=start-', 'bytes=-suffix').
    Returns (start_inclusive, end_inclusive).
    Raises ValueError if the range syntax is invalid, multi-part, negative, or past EOF (HTTP 416).
    """
    if file_size <= 0:
        raise ValueError("Empty file cannot satisfy byte range")
    if not range_header or not isinstance(range_header, str):
        raise ValueError("Missing Range header")

    raw = range_header.strip()
    if not raw.startswith("bytes="):
        raise ValueError("Unsupported range unit")

    spec = raw[len("bytes="):].strip()
    if not spec or "," in spec or "-" not in spec:
        raise ValueError("Invalid or unsupported multi-range specification")

    start_str, sep, end_str = spec.partition("-")
    if sep != "-":
        raise ValueError("Malformed byte range")

    start_str = start_str.strip()
    end_str = end_str.strip()

    if not start_str and not end_str:
        raise ValueError("Empty byte range bounds")

    if start_str and not start_str.isdigit():
        raise ValueError("Invalid range start")
    if end_str and not end_str.isdigit():
        raise ValueError("Invalid range end")

    # 1. Suffix byte-range-spec: bytes=-N (last N bytes)
    if not start_str:
        suffix_len = int(end_str)
        if suffix_len <= 0:
            raise ValueError("Suffix length must be positive")
        if suffix_len >= file_size:
            return 0, file_size - 1
        return file_size - suffix_len, file_size - 1

    # 2. Open-ended byte-range-spec: bytes=S-
    start = int(start_str)
    if start < 0 or start >= file_size:
        raise ValueError("Range start is at or past EOF")

    if not end_str:
        return start, file_size - 1

    # 3. Explicit byte-range-spec: bytes=S-E
    end = int(end_str)
    if start > end:
        raise ValueError("Range start exceeds range end")
    if end >= file_size:
        end = file_size - 1

    return start, end


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
                "running": running,
            }
            if running:
                any_running = True
            else:
                all_running = False

        return {
            "services": status,
            "allRunning": all_running and len(status) > 0,
            "anyRunning": any_running,
        }

    def start_camera(self, cid):
        cfg = load_config()
        cam = next((c for c in cfg.get("cameras", []) if c.get("id") == cid or cid in c.get("aliases", [])), None)
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
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
            )
            self.processes[cid] = proc
            return True, f"Started camera '{cid}'"
        except Exception as e:
            return False, str(e)

    def stop_camera(self, cid):
        cfg = load_config()
        cam = next((c for c in cfg.get("cameras", []) if c.get("id") == cid or cid in c.get("aliases", [])), None)
        if not cam:
            return False, f"Camera '{cid}' not found in configuration"

        port = cam.get("port")
        kill_port_process(port)
        if cid in self.processes:
            try:
                self.processes[cid].terminate()
            except Exception:
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


class CamHubRuntime:
    """
    Holds all service instances for a CamHUB server instance.
    Allows isolated temporary directories and mocked services during tests without side effects.
    """

    def __init__(
        self,
        base_dir: str = BASE_DIR,
        static_dir: Optional[str] = None,
        config_provider=None,
        auth_manager: Optional[AuthManager] = None,
        enable_ai_on_init: bool = True,
    ):
        self.base_dir = os.path.abspath(base_dir)
        self.static_dir = os.path.abspath(static_dir or os.path.join(self.base_dir, "web"))
        self.config_provider = config_provider or load_config
        self.server_start_time = time.time()

        def _motion_cfg_provider():
            cfg = dict(self.config_provider() or {})
            if not enable_ai_on_init:
                ai_cfg = dict(cfg.get("aiDetection", {}))
                ai_cfg["enabled"] = False
                cfg["aiDetection"] = ai_cfg
            return cfg

        self.auth_manager = auth_manager or AuthManager(
            base_dir=self.base_dir,
            config_provider=self.config_provider,
        )
        self.health_monitor = CameraHealthMonitor(self.config_provider)
        self.manager = AutoRecoveryManager(self.config_provider, health_monitor=self.health_monitor)
        self.storage_manager = CamHubStorageManager(self.config_provider, base_dir=self.base_dir)
        self.recording_manager = RecordingManager(
            self.config_provider,
            base_dir=self.base_dir,
            storage_manager=self.storage_manager,
        )
        self.motion_service = MotionDetectorService(_motion_cfg_provider, base_dir=self.base_dir)
        self.storage_manager.attach_managers(
            recording_manager=self.recording_manager,
            motion_service=self.motion_service,
        )
        self.notification_center = NotificationCenter(self.config_provider, base_dir=self.base_dir)
        self.diagnostics_service = CamHubDiagnosticsService(
            self.config_provider,
            base_dir=self.base_dir,
            health_monitor=self.health_monitor,
            supervisor_manager=self.manager,
            recording_manager=self.recording_manager,
            motion_service=self.motion_service,
            storage_manager=self.storage_manager,
            notification_center=self.notification_center,
        )
        self.ptz_service = CamHubPTZService(self.config_provider)

    def start_background_services(self) -> None:
        self.health_monitor.start()
        self.manager.start()
        self.recording_manager.start()
        self.motion_service.start()
        self.storage_manager.start()

    def stop_background_services(self, shutdown_children: bool = True) -> None:
        self.notification_center.stop()
        self.storage_manager.stop()
        self.motion_service.stop()
        self.recording_manager.stop()
        if shutdown_children:
            self.manager.shutdown_all()
        self.manager.stop()
        self.health_monitor.stop()


_RUNTIME_LOCK = threading.Lock()
_DEFAULT_RUNTIME: Optional[CamHubRuntime] = None


def get_default_runtime() -> CamHubRuntime:
    global _DEFAULT_RUNTIME
    with _RUNTIME_LOCK:
        if _DEFAULT_RUNTIME is None:
            _DEFAULT_RUNTIME = CamHubRuntime(base_dir=BASE_DIR, static_dir=WEB_DIR, config_provider=load_config)
        return _DEFAULT_RUNTIME


class CamHubHandler(SimpleHTTPRequestHandler):
    runtime: Optional[CamHubRuntime] = None
    static_root: str = STATIC_DIR

    def __init__(self, *args, **kwargs):
        rt = self.runtime
        target_static = os.path.abspath(rt.static_dir if rt else self.static_root)
        self._effective_static_dir = target_static
        self.current_principal = None
        super().__init__(*args, directory=target_static, **kwargs)

    @property
    def rt(self) -> CamHubRuntime:
        if self.runtime is not None:
            return self.runtime
        return get_default_runtime()

    def list_directory(self, path):
        """Disable raw directory listings completely."""
        self.send_json(404, {"error": "Not found"})
        return None

    def translate_path(self, path):
        """
        Strictly confine static file resolution to web/ (self._effective_static_dir).
        Never fall back to BASE_DIR, and block dotfiles / hidden directories / path traversal.
        """
        static_base = os.path.abspath(getattr(self, "_effective_static_dir", getattr(self, "directory", STATIC_DIR)))
        sentinel_missing = os.path.join(static_base, "__nonexistent_camhub_asset__")

        parsed_path = urlparse(path or "/").path
        # Reject explicit hidden files or dot-directories (e.g. /.git, /.env)
        segments = [seg for seg in parsed_path.replace("\\", "/").split("/") if seg]
        if any(seg.startswith(".") for seg in segments):
            return sentinel_missing

        res = super().translate_path(parsed_path)
        try:
            checked = sanitize_path(static_base, res)
        except ValueError:
            return sentinel_missing

        return checked

    def _is_https_request(self) -> bool:
        if not hasattr(self, "headers") or self.headers is None:
            return False
        xf_proto = (self.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip().lower()
        return xf_proto == "https"

    def _client_key(self) -> str:
        cfg = self.rt.config_provider() or {}
        trust_proxy = cfg.get("security", {}).get("trustProxyHeaders", True)
        if trust_proxy and hasattr(self, "headers") and self.headers:
            xff = (self.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
            if xff:
                return xff
        return self.client_address[0] if getattr(self, "client_address", None) else "unknown"

    def is_admin_authorized(self) -> bool:
        """
        Verify Admin role strictly from a server-verified session or API token.
        Explicitly ignores X-CamHub-Role, unverified Bearer strings, and loopback client IP.
        """
        principal = self.rt.auth_manager.extract_request_principal(getattr(self, "headers", None))
        return bool(principal and principal.get("role") == "admin")

    def _authorize_request(self, method: str) -> bool:
        """
        Centralized origin & RBAC permission gate executed at the top of every HTTP verb handler.
        """
        url = urlparse(self.path)
        auth_mgr = self.rt.auth_manager

        # 1. Cross-Origin mutation guard (CSRF / disallowed Origin defense)
        origin = self.headers.get("Origin") if self.headers else None
        if origin and method.upper() in ("POST", "PUT", "PATCH", "DELETE"):
            if not auth_mgr.is_origin_allowed(origin, self.headers):
                self.send_json(403, {"error": "Origin not allowed"})
                return False

        # 2. Route permission check
        required = get_required_permission(method, url.path)
        if required == "public":
            self.current_principal = auth_mgr.extract_request_principal(self.headers)
            return True

        principal = auth_mgr.extract_request_principal(self.headers)
        if principal is None:
            self.send_json(
                401,
                {
                    "error": "Authentication required",
                    "setupRequired": auth_mgr.is_setup_required(),
                },
                extra_headers={"WWW-Authenticate": 'Bearer realm="CamHUB"'},
            )
            return False

        if required == "admin" and principal.get("role") != "admin":
            self.send_json(403, {"error": "Admin privileges required"})
            return False

        self.current_principal = principal
        return True

    def log_message(self, format, *args):
        msg = str(args[0]) if args else ""
        if any(api in msg for api in ("/api/", "/proxy/")):
            clean_msg = sanitize_sensitive_data(msg)
            print(f"[API] {clean_msg}", flush=True)
            try:
                self.rt.diagnostics_service.log_event(clean_msg, level="API")
            except Exception:
                pass

    def send_cors_headers(self):
        headers = getattr(self, "headers", None)
        origin = headers.get("Origin") if headers else None
        if origin and self.rt.auth_manager.is_origin_allowed(origin, headers):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Credentials", "true")
            self.send_header("Access-Control-Allow-Methods", "GET, HEAD, POST, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.send_header("Vary", "Origin")
        self.send_header("ngrok-skip-browser-warning", "1")

    def end_headers(self):
        super().end_headers()

    def send_file_with_range(self, file_path, content_type="video/mp4", as_download=False):
        """
        Supports RFC 9110 HTTP 206 Partial Content (standard, open-ended, and suffix ranges),
        returns HTTP 416 for invalid or past-EOF ranges, and maintains active playback/download locks.
        """
        if not os.path.isfile(file_path):
            self.send_json(404, {"error": "Recording file not found on disk"})
            return

        file_size = os.path.getsize(file_path)
        range_header = self.headers.get("Range") if self.headers else None
        filename = os.path.basename(file_path)
        disposition = f'attachment; filename="{filename}"' if as_download else "inline"
        is_head = getattr(self, "command", "GET").upper() == "HEAD"

        locks = self.rt.storage_manager.playback_locks
        locks.begin_transfer(file_path, lease_seconds=180.0)
        try:
            if not range_header:
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(file_size))
                self.send_header("Content-Disposition", disposition)
                self.send_header("Accept-Ranges", "bytes")
                self.send_cors_headers()
                self.end_headers()
                if is_head:
                    return
                last_renew = time.time()
                with open(file_path, "rb") as f:
                    while True:
                        chunk = f.read(65536)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        now = time.time()
                        if (now - last_renew) >= 30.0:
                            locks.renew(file_path, lease_seconds=180.0)
                            last_renew = now
                return

            try:
                start, end = parse_http_byte_range(range_header, file_size)
            except ValueError:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{file_size}")
                self.send_header("Content-Length", "0")
                self.send_header("Accept-Ranges", "bytes")
                self.send_cors_headers()
                self.end_headers()
                return

            length = end - start + 1
            self.send_response(206)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
            self.send_header("Content-Length", str(length))
            self.send_header("Content-Disposition", disposition)
            self.send_header("Accept-Ranges", "bytes")
            self.send_cors_headers()
            self.end_headers()

            if is_head:
                return

            last_renew = time.time()
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
                    now = time.time()
                    if (now - last_renew) >= 30.0:
                        locks.renew(file_path, lease_seconds=180.0)
                        last_renew = now
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            locks.end_transfer(file_path, grace_lease_seconds=60.0)

    def send_json(self, status_code, data, extra_headers: Optional[dict] = None):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        if extra_headers:
            for hk, hv in extra_headers.items():
                self.send_header(hk, hv)
        self.send_cors_headers()
        self.end_headers()
        if getattr(self, "command", "GET").upper() == "HEAD":
            return
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def do_OPTIONS(self):
        origin = self.headers.get("Origin") if self.headers else None
        if origin and not self.rt.auth_manager.is_origin_allowed(origin, self.headers):
            self.send_response(403)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(204)
        self.send_cors_headers()
        self.end_headers()

    def do_HEAD(self):
        if not self._authorize_request("HEAD"):
            return
        url = urlparse(self.path)
        if url.path.startswith("/api/") or url.path.startswith("/proxy/"):
            self.do_GET()
            return
        super().do_HEAD()

    def proxy_mjpeg_stream(self, camera_id):
        cfg = self.rt.config_provider()
        cam = next((c for c in cfg.get("cameras", []) if c.get("id") == camera_id or camera_id in c.get("aliases", [])), None)
        if not cam:
            self.send_json(404, {"error": f"Camera '{camera_id}' not found in configuration"})
            return

        port = cam.get("port")
        if not port or not is_port_open(port):
            self.send_json(503, {"error": f"Camera '{camera_id}' decoder service is offline on port {port}"})
            return

        if camera_id in ("okam_1", "okam_2", "okam_3") or camera_id.startswith("okam_"):
            stream_path = f"/api/cameras/{camera_id}/stream.mjpg"
        else:
            stream_path = cam.get("streamPath") or (
                f"/api/cameras/{camera_id}/stream.mjpg" if cam.get("type") == "okam" else "/stream.mjpg"
            )

        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            sock.connect(("127.0.0.1", port))
            req = f"GET {stream_path} HTTP/1.0\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n".encode("utf-8")
            sock.sendall(req)

            header_data = b""
            while b"\r\n\r\n" not in header_data:
                chunk = sock.recv(2048)
                if not chunk:
                    break
                header_data += chunk

            header_part, _, body_init = header_data.partition(b"\r\n\r\n")
            header_lines = header_part.decode("utf-8", errors="replace").split("\r\n")

            content_type = "multipart/x-mixed-replace; boundary=frame"
            is_chunked = False
            for h in header_lines[1:]:
                if ":" in h:
                    k, v = h.split(":", 1)
                    kl = k.strip().lower()
                    if kl == "content-type":
                        content_type = v.strip()
                    elif kl == "transfer-encoding" and "chunked" in v.lower():
                        is_chunked = True

            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.send_header("Connection", "close")
            self.send_cors_headers()
            self.end_headers()

            if is_chunked:
                stream_buf = body_init
                sock.settimeout(8.0)
                while True:
                    while b"\r\n" not in stream_buf:
                        more = sock.recv(16384)
                        if not more:
                            break
                        stream_buf += more
                    if b"\r\n" not in stream_buf:
                        break
                    line, _, rest = stream_buf.partition(b"\r\n")
                    chunk_hex = line.split(b";")[0].strip()
                    if not chunk_hex:
                        stream_buf = rest
                        continue
                    try:
                        chunk_size = int(chunk_hex, 16)
                    except ValueError:
                        break
                    if chunk_size == 0:
                        break
                    stream_buf = rest
                    while len(stream_buf) < chunk_size + 2:
                        more = sock.recv(max(16384, chunk_size + 2 - len(stream_buf)))
                        if not more:
                            break
                        stream_buf += more
                    payload = stream_buf[:chunk_size]
                    stream_buf = stream_buf[chunk_size + 2:]
                    self.wfile.write(payload)
                    self.wfile.flush()
            else:
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
                except Exception:
                    pass

    def proxy_snapshot(self, camera_id):
        cfg = self.rt.config_provider()
        cam = next((c for c in cfg.get("cameras", []) if c.get("id") == camera_id or camera_id in c.get("aliases", [])), None)
        if not cam:
            self.send_json(404, {"error": f"Camera '{camera_id}' not found"})
            return

        port = cam.get("port")
        if not port or not is_port_open(port):
            self.send_json(503, {"error": f"Camera '{camera_id}' decoder service is offline on port {port}"})
            return

        if camera_id in ("okam_1", "okam_2", "okam_3") or camera_id.startswith("okam_"):
            snap_path = f"/api/cameras/{camera_id}/snapshot"
        else:
            snap_path = cam.get("snapshotPath") or (
                f"/api/cameras/{camera_id}/snapshot" if cam.get("type") == "okam" else "/snapshot"
            )

        try:
            req = Request(f"http://127.0.0.1:{port}{snap_path}")
            req.add_header("User-Agent", "CamHub-Proxy/1.0")
            req.add_header("ngrok-skip-browser-warning", "1")
            with urlopen(req, timeout=2.5) as resp:
                data = resp.read()

            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self.send_json(502, {"error": f"Failed to retrieve snapshot from port {port}: {e}"})

    def proxy_metrics(self, camera_id, qs):
        cfg = self.rt.config_provider()
        cam = next((c for c in cfg.get("cameras", []) if c.get("id") == camera_id or camera_id in c.get("aliases", [])), None)
        if not cam:
            self.send_json(404, {"error": f"Camera '{camera_id}' not found"})
            return

        port = cam.get("port")
        if not port or not is_port_open(port):
            self.send_json(503, {"error": f"Camera '{camera_id}' decoder service is offline on port {port}"})
            return

        if camera_id in ("okam_1", "okam_2", "okam_3") or camera_id.startswith("okam_"):
            metrics_path = f"/api/cameras/{camera_id}/metrics"
        else:
            metrics_path = cam.get("metricsPath") or (
                f"/api/cameras/{camera_id}/metrics" if cam.get("type") == "okam" else "/api/metrics"
            )

        client_fps = qs.get("clientFps", [None])[0]
        query = f"?clientFps={client_fps}" if client_fps else ""

        try:
            req = Request(f"http://127.0.0.1:{port}{metrics_path}{query}")
            req.add_header("User-Agent", "CamHub-Proxy/1.0")
            req.add_header("ngrok-skip-browser-warning", "1")
            with urlopen(req, timeout=2.0) as resp:
                data = resp.read()

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self.send_json(502, {"error": f"Failed to retrieve metrics from port {port}: {e}"})

    def do_GET(self):
        if not self._authorize_request("GET"):
            return

        url = urlparse(self.path)
        qs = parse_qs(url.query)
        rt = self.rt

        # Auth session status endpoint (public)
        if url.path in ("/api/auth/session", "/api/auth/session/"):
            principal = rt.auth_manager.extract_request_principal(self.headers)
            if principal:
                self.send_json(
                    200,
                    {
                        "authenticated": True,
                        "username": principal["username"],
                        "role": principal["role"],
                        "setupRequired": rt.auth_manager.is_setup_required(),
                    },
                )
            else:
                self.send_json(
                    200,
                    {
                        "authenticated": False,
                        "username": None,
                        "role": None,
                        "setupRequired": rt.auth_manager.is_setup_required(),
                    },
                )
            return

        # Multi-camera REST API endpoints
        if url.path == "/api/cameras" or url.path == "/api/cameras/":
            cfg = rt.config_provider()
            cam_list = []
            health_all = rt.health_monitor.get_all_health().get("cameras", {})
            for cam in cfg.get("cameras", []):
                cid = cam.get("id")
                port = cam.get("port")
                h = health_all.get(cid, {})
                m = h.get("metrics", {})
                status_str = (h.get("status") or h.get("state") or cam.get("status") or "UNKNOWN").lower()
                raw_rtsp = cam.get("rtspUrl", "")
                if not raw_rtsp and cam.get("rtspPort"):
                    raw_rtsp = f"rtsp://{cam.get('ip', '127.0.0.1')}:{cam.get('rtspPort')}/live"
                cam_list.append({
                    "id": cid,
                    "name": cam.get("name", cid),
                    "type": cam.get("type", "unknown"),
                    "port": port,
                    "rtspUrl": sanitize_sensitive_data(raw_rtsp),
                    "status": status_str,
                    "fps": m.get("fps", cam.get("fps", 0.0)),
                    "resolution": m.get("resolution") or cam.get("resolution", "1920x1080"),
                    "latency": m.get("latencyMs", cam.get("latency", 0.0)),
                    "streamPath": cam.get("streamPath") or f"/api/cameras/{cid}/stream.mjpg",
                    "snapshotPath": cam.get("snapshotPath") or f"/api/cameras/{cid}/snapshot",
                    "metricsPath": cam.get("metricsPath") or f"/api/cameras/{cid}/metrics",
                    "proxyStreamUrl": f"/proxy/stream/{cid}",
                    "proxySnapshotUrl": f"/proxy/snapshot/{cid}",
                    "proxyMetricsUrl": f"/proxy/metrics/{cid}",
                    "aliases": cam.get("aliases", []),
                })
            self.send_json(200, {"cameras": cam_list})
            return

        match_cam_api = re.match(r"^/api/cameras/([^/]+)/(metrics|snapshot|stream\.mjpg)$", url.path)
        if match_cam_api:
            target_cid, endpoint = match_cam_api.group(1), match_cam_api.group(2)
            if endpoint == "metrics":
                self.proxy_metrics(target_cid, qs)
                return
            elif endpoint == "snapshot":
                self.proxy_snapshot(target_cid)
                return
            elif endpoint == "stream.mjpg":
                self.proxy_mjpeg_stream(target_cid)
                return

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

        if url.path == "/api/health":
            cid = qs.get("id", [None])[0]
            if cid:
                data = rt.health_monitor.get_camera_health(cid)
                if data:
                    self.send_json(200, data)
                else:
                    self.send_json(404, {"error": f"Camera '{cid}' not found in health monitor"})
            else:
                self.send_json(200, rt.health_monitor.get_all_health())
            return

        if url.path.startswith("/api/health/"):
            cid = url.path[len("/api/health/"):].strip("/")
            data = rt.health_monitor.get_camera_health(cid)
            if data:
                self.send_json(200, data)
            else:
                self.send_json(404, {"error": f"Camera '{cid}' not found in health monitor"})
            return

        if url.path == "/api/recovery/status":
            self.send_json(200, rt.manager.get_status())
            return

        if url.path == "/api/services/status":
            data = rt.manager.get_status()
            for cid, s_info in data.get("services", {}).items():
                h = rt.health_monitor.get_camera_health(cid)
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
            items = rt.recording_manager.list_recordings(camera_id=cam_id, date_str=date_str, limit=limit)
            self.send_json(200, {"recordings": items, "count": len(items)})
            return

        if url.path == "/api/recordings/storage":
            self.send_json(200, rt.recording_manager.get_storage_status())
            return

        # Central Storage Management Endpoints
        if url.path == "/api/storage/status":
            self.send_json(200, rt.storage_manager.get_storage_overview())
            return

        if url.path == "/api/storage/report":
            overview = rt.storage_manager.get_storage_overview()
            gen_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            report_text = (
                f"=== CamHUB Unified Storage Report ===\n"
                f"Generated: {gen_time}\n"
                f"Host Disk: {overview['disk']['totalGb']} GB total | {overview['disk']['usedGb']} GB used ({overview['disk']['usedPercent']}%) | {overview['disk']['freeGb']} GB free\n"
                f"Alert Status: [{overview['alerts']['level']}] {overview['alerts']['message']}\n"
                f"CamHUB Total: {overview['camhub']['totalMb']} MB ({overview['camhub']['totalGb']} GB)\n"
                f" - Recordings: {overview['recordings']['fileCount']} MP4 files ({overview['recordings']['totalMb']} MB)\n"
                f" - Events: {overview['events']['fileCount']} JPEG snapshots ({overview['events']['totalMb']} MB)\n"
                f" - Temp/Corrupt: {overview['tempAndCorrupt']['tempFilesCount']} temp files, {overview['tempAndCorrupt']['corruptedFilesCount']} corrupted files\n"
                f"Forecasting: {overview['forecasting']['estimatedDaysRemaining']} days remaining ({overview['forecasting']['growthRateMbPerHour']} MB/hr burn rate)\n"
            )
            self.send_json(200, {"report": report_text, "overview": overview})
            return

        # Stream recording with HTTP 206 Partial Content (strictly validated within recordings_dir)
        if url.path in ("/api/recordings/stream", "/api/recordings/download"):
            seg_id = qs.get("id", [None])[0]
            if not seg_id:
                self.send_json(400, {"error": "Missing 'id' query parameter"})
                return
            item = rt.recording_manager.get_recording_item(seg_id)
            if not item:
                self.send_json(404, {"error": "Recording not found"})
                return
            rel_path = item.get("filePath") or item.get("path") or ""
            if not rel_path:
                self.send_json(404, {"error": "Recording path missing"})
                return
            try:
                full_path = sanitize_path(
                    rt.recording_manager.storage_dir,
                    os.path.join(rt.base_dir, rel_path),
                )
                if os.path.splitext(full_path)[1].lower() != ".mp4":
                    self.send_json(403, {"error": "Invalid recording media format"})
                    return
                self.send_file_with_range(
                    full_path,
                    content_type="video/mp4",
                    as_download=(url.path == "/api/recordings/download"),
                )
            except ValueError as e:
                self.send_json(403, {"error": str(e)})
            return

        # AI Status & Telemetry
        if url.path == "/api/ai/status":
            stats = rt.motion_service.get_stats()
            cfg = rt.config_provider()
            ai_cfg = cfg.get("aiDetection", {})
            detector_info = {
                "enabled": ai_cfg.get("enabled", True),
                "configuredProvider": ai_cfg.get("provider", "auto"),
                "modelPath": ai_cfg.get("modelPath", "models/yolov5n.onnx"),
                "confidenceThreshold": ai_cfg.get("confidenceThreshold", 0.40),
                "targetClasses": ai_cfg.get("targetClasses", ["person", "car", "motorcycle", "animal"]),
                "worker": stats.get("ai", {}),
                "cameras": ai_cfg.get("cameras", {}),
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

            events = rt.motion_service.list_events(
                camera_id=cam_id,
                date_str=date_str,
                min_score=min_score,
                limit=limit,
                object_class=obj_class,
                category=category,
            )
            self.send_json(200, {"events": events, "count": len(events)})
            return

        if url.path == "/api/events/detail":
            evt_id = qs.get("id", [None])[0]
            if not evt_id:
                self.send_json(400, {"error": "Missing 'id' parameter"})
                return
            evt = rt.motion_service.get_event(evt_id)
            if evt:
                self.send_json(200, evt)
            else:
                self.send_json(404, {"error": "Event not found"})
            return

        if url.path == "/api/events/stats":
            self.send_json(200, rt.motion_service.get_stats())
            return

        if url.path == "/api/events/snapshot":
            evt_id = qs.get("id", [None])[0]
            raw_path = qs.get("path", [None])[0]
            full_path = None
            try:
                if evt_id:
                    evt = rt.motion_service.get_event(evt_id)
                    if evt and evt.get("snapshotPath"):
                        full_path = sanitize_path(
                            rt.motion_service.storage_dir,
                            os.path.join(rt.base_dir, evt["snapshotPath"]),
                        )
                elif raw_path:
                    # Strictly confine raw path queries to events storage directory and image extensions!
                    candidate = (
                        os.path.join(rt.base_dir, raw_path)
                        if raw_path.replace("\\", "/").lstrip("/").startswith("events/")
                        else os.path.join(rt.motion_service.storage_dir, raw_path.lstrip("/\\"))
                    )
                    full_path = sanitize_path(rt.motion_service.storage_dir, candidate)
            except ValueError as ve:
                self.send_json(403, {"error": str(ve)})
                return

            if full_path and os.path.splitext(full_path)[1].lower() not in ALLOWED_SNAPSHOT_EXTENSIONS:
                self.send_json(403, {"error": "Invalid snapshot image format"})
                return

            if not full_path or not os.path.isfile(full_path):
                self.send_json(404, {"error": "Snapshot image file not found on disk"})
                return

            try:
                ext = os.path.splitext(full_path)[1].lower()
                mime = "image/png" if ext == ".png" else "image/jpeg"
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(os.path.getsize(full_path)))
                self.send_header("Cache-Control", "private, max-age=86400")
                self.send_cors_headers()
                self.end_headers()
                with open(full_path, "rb") as f:
                    shutil.copyfileobj(f, self.wfile, length=65536)
                return
            except Exception as e:
                self.send_json(403, {"error": str(e)})
                return

        # Diagnostics Endpoints (Admin-only enforced centrally)
        if url.path == "/api/diagnostics/summary":
            try:
                software = rt.diagnostics_service.get_software_versions()
                resources = rt.diagnostics_service.get_system_resources()
                ports = rt.diagnostics_service.check_ports()
                telemetry = rt.diagnostics_service.get_services_telemetry()
                errors = rt.diagnostics_service.get_recent_errors()
                bundles = rt.diagnostics_service.list_bundles()
                overall = (
                    "HEALTHY"
                    if errors["totalErrorCount"] == 0
                    else ("DEGRADED" if len(errors["offlineCameras"]) < 2 else "CRITICAL")
                )
                self.send_json(
                    200,
                    {
                        "overallStatus": overall,
                        "issueCount": errors["totalErrorCount"],
                        "uptimeSeconds": round(time.time() - rt.server_start_time, 1),
                        "software": software,
                        "resources": resources,
                        "ports": ports,
                        "telemetry": telemetry,
                        "errors": errors,
                        "bundles": bundles,
                    },
                )
            except Exception as e:
                self.send_json(500, {"error": f"Diagnostics error: {e}"})
            return

        if url.path == "/api/diagnostics/list":
            self.send_json(200, {"bundles": rt.diagnostics_service.list_bundles()})
            return

        if url.path == "/api/diagnostics/download":
            fname = qs.get("file", [None])[0] or qs.get("filename", [None])[0]
            if not fname:
                self.send_json(400, {"error": "Missing 'file' query parameter"})
                return
            clean_name = os.path.basename(fname)
            if not clean_name.startswith("camhub_diagnostics_") or not clean_name.endswith(".zip"):
                self.send_json(400, {"error": "Invalid diagnostic file name"})
                return
            diag_dir = os.path.join(rt.base_dir, "diagnostics")
            try:
                full_path = sanitize_path(diag_dir, os.path.join(diag_dir, clean_name))
            except ValueError as ve:
                self.send_json(403, {"error": str(ve)})
                return
            if not os.path.isfile(full_path):
                self.send_json(404, {"error": "Diagnostic bundle not found on disk"})
                return
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Disposition", f'attachment; filename="{clean_name}"')
                self.send_header("Content-Length", str(os.path.getsize(full_path)))
                self.send_cors_headers()
                self.end_headers()
                with open(full_path, "rb") as f:
                    shutil.copyfileobj(f, self.wfile, length=65536)
                return
            except Exception as e:
                self.send_json(403, {"error": str(e)})
                return

        # Notification Center Endpoints
        if url.path == "/api/notifications":
            severity = qs.get("severity", [None])[0]
            camera_id = qs.get("camera", [None])[0] or qs.get("cameraId", [None])[0]
            category = qs.get("category", [None])[0]
            unack_only = qs.get("unacknowledgedOnly", ["false"])[0].lower() == "true"
            limit_str = qs.get("limit", ["100"])[0]
            limit = int(limit_str) if limit_str.isdigit() else 100
            items = rt.notification_center.list_notifications(
                severity=severity,
                camera_id=camera_id,
                category=category,
                unacknowledged_only=unack_only,
                limit=limit,
            )
            self.send_json(200, {"notifications": items, "stats": rt.notification_center.get_stats()})
            return

        if url.path == "/api/notifications/stats":
            self.send_json(200, rt.notification_center.get_stats())
            return

        # PTZ Status & Presets Endpoints
        if url.path == "/api/ptz/status":
            cid = qs.get("id", [None])[0] or qs.get("cameraId", ["v380-1"])[0]
            self.send_json(200, rt.ptz_service.get_status(cid))
            return

        if url.path == "/api/ptz/presets":
            cid = qs.get("id", [None])[0] or qs.get("cameraId", ["v380-1"])[0]
            self.send_json(200, {"cameraId": cid, "presets": rt.ptz_service.get_presets(cid)})
            return

        if url.path.startswith("/api/") or url.path.startswith("/proxy/"):
            self.send_json(404, {"error": "Endpoint not found"})
            return

        super().do_GET()

    def do_POST(self):
        if not self._authorize_request("POST"):
            return

        url = urlparse(self.path)
        qs = parse_qs(url.query)
        rt = self.rt
        cid = qs.get("id", [None])[0] or qs.get("cameraId", [None])[0]

        # Read JSON body payload (bounded to 2 MB to prevent memory abuse)
        body_json = {}
        try:
            content_len = int(self.headers.get("Content-Length", 0) or 0)
        except ValueError:
            content_len = 0
        if content_len > 2 * 1024 * 1024:
            self.send_json(413, {"error": "Payload too large"})
            return
        if content_len > 0 and "application/json" in (self.headers.get("Content-Type") or ""):
            try:
                body_bytes = self.rfile.read(content_len)
                parsed = json.loads(body_bytes.decode("utf-8"))
                if isinstance(parsed, dict):
                    body_json = parsed
                    if not cid:
                        cid = body_json.get("cameraId") or body_json.get("camera_id") or body_json.get("id")
            except Exception:
                pass

        # --- Authentication & Session Endpoints ---
        if url.path == "/api/auth/login":
            username = body_json.get("username") or qs.get("username", [""])[0]
            password = body_json.get("password") or ""
            ok, status_code, payload = rt.auth_manager.authenticate_credentials(
                username=username,
                password=password,
                client_key=self._client_key(),
            )
            if ok:
                cookie_val = rt.auth_manager.build_session_cookie(
                    payload["token"],
                    payload["maxAgeSeconds"],
                    is_secure=self._is_https_request(),
                )
                self.send_json(status_code, {"success": True, **payload}, extra_headers={"Set-Cookie": cookie_val})
            else:
                self.send_json(status_code, {"success": False, **payload})
            return

        if url.path == "/api/auth/logout":
            rt.auth_manager.revoke_request_session(self.headers)
            clear_cookie = rt.auth_manager.build_clear_cookie(is_secure=self._is_https_request())
            self.send_json(200, {"success": True, "authenticated": False}, extra_headers={"Set-Cookie": clear_cookie})
            return

        if url.path == "/api/auth/setup":
            ok, status_code, payload = rt.auth_manager.complete_initial_setup(
                bootstrap_token=body_json.get("bootstrapToken", ""),
                admin_password=body_json.get("adminPassword", ""),
                admin_username=body_json.get("adminUsername", "admin"),
                viewer_password=body_json.get("viewerPassword") or None,
                client_key=self._client_key(),
            )
            if ok:
                cookie_val = rt.auth_manager.build_session_cookie(
                    payload["token"],
                    payload["maxAgeSeconds"],
                    is_secure=self._is_https_request(),
                )
                self.send_json(status_code, {"success": True, **payload}, extra_headers={"Set-Cookie": cookie_val})
            else:
                self.send_json(status_code, {"success": False, **payload})
            return

        if url.path == "/api/auth/users":
            # Protected by centralized Admin gate
            uname = body_json.get("username", "")
            pw = body_json.get("password", "")
            role = body_json.get("role", "viewer")
            try:
                rt.auth_manager.set_user(uname, pw, role=role)
                self.send_json(200, {"success": True, "username": uname, "role": role})
            except ValueError as ve:
                self.send_json(400, {"success": False, "error": str(ve)})
            return

        if url.path == "/api/cameras/config":
            # Protected by centralized Admin gate
            if not cid:
                self.send_json(400, {"error": "Missing 'cameraId' or 'id' parameter"})
                return
            cfg = rt.config_provider()
            cam = next((c for c in cfg.get("cameras", []) if c.get("id") == cid or cid in c.get("aliases", [])), None)
            if not cam:
                self.send_json(404, {"error": f"Camera '{cid}' not found"})
                return
            new_name = (body_json.get("name") or "").strip()
            if new_name:
                cam["name"] = new_name
            self.send_json(
                200,
                {
                    "success": True,
                    "cameraId": cam.get("id"),
                    "name": cam.get("name"),
                },
            )
            return

        # --- PTZ Camera Controls (Admin-only enforced centrally) ---
        if url.path == "/api/ptz/move":
            direction = (
                body_json.get("direction")
                or body_json.get("dir")
                or qs.get("dir", [None])[0]
                or qs.get("direction", [None])[0]
            )
            speed = body_json.get("speed") or qs.get("speed", ["0.5"])[0]
            duration = body_json.get("duration") or qs.get("duration", [None])[0]
            mode = body_json.get("mode") or qs.get("mode", ["continuous"])[0]
            if not cid:
                self.send_json(400, {"error": "Missing 'id' or 'cameraId' parameter"})
                return
            if not direction:
                self.send_json(400, {"error": "Missing 'dir' or 'direction' parameter"})
                return
            ok, msg = rt.ptz_service.move(cid, direction, speed=speed, duration_ms=duration, mode=mode)
            self.send_json(
                200 if ok else 400,
                {"success": ok, "message": msg, "status": rt.ptz_service.get_status(cid)},
            )
            return

        if url.path == "/api/ptz/stop":
            if not cid:
                self.send_json(400, {"error": "Missing 'id' or 'cameraId' parameter"})
                return
            ok, msg = rt.ptz_service.stop(cid)
            self.send_json(
                200 if ok else 400,
                {"success": ok, "message": msg, "status": rt.ptz_service.get_status(cid)},
            )
            return

        if url.path == "/api/ptz/zoom":
            action = body_json.get("action") or qs.get("action", [None])[0] or qs.get("dir", [None])[0]
            speed = body_json.get("speed") or qs.get("speed", ["0.5"])[0]
            if not cid:
                self.send_json(400, {"error": "Missing 'id' or 'cameraId' parameter"})
                return
            if not action:
                self.send_json(400, {"error": "Missing 'action' parameter ('in', 'out', or 'reset')"})
                return
            ok, msg = rt.ptz_service.zoom(cid, action, speed=speed)
            self.send_json(
                200 if ok else 400,
                {"success": ok, "message": msg, "status": rt.ptz_service.get_status(cid)},
            )
            return

        if url.path == "/api/ptz/preset":
            action = body_json.get("action") or qs.get("action", ["goto"])[0]
            preset_id = body_json.get("preset") or body_json.get("presetId") or qs.get("preset", [None])[0]
            preset_name = body_json.get("name") or qs.get("name", [None])[0]
            if not cid:
                self.send_json(400, {"error": "Missing 'id' or 'cameraId' parameter"})
                return
            if not preset_id:
                self.send_json(400, {"error": "Missing 'preset' ID parameter (1-5)"})
                return
            if action == "goto":
                ok, msg = rt.ptz_service.preset_goto(cid, preset_id)
            elif action in ("set", "save"):
                ok, msg = rt.ptz_service.preset_set(cid, preset_id, name=preset_name)
            elif action in ("clear", "remove"):
                ok, msg = rt.ptz_service.preset_clear(cid, preset_id)
            else:
                self.send_json(400, {"error": f"Invalid preset action '{action}'. Use 'goto', 'set', or 'clear'."})
                return
            self.send_json(
                200 if ok else 400,
                {
                    "success": ok,
                    "message": msg,
                    "presets": rt.ptz_service.get_presets(cid),
                    "status": rt.ptz_service.get_status(cid),
                },
            )
            return

        if url.path == "/api/ptz/aux":
            cmd = body_json.get("command") or body_json.get("cmd") or qs.get("cmd", [None])[0]
            if not cid:
                self.send_json(400, {"error": "Missing 'id' or 'cameraId' parameter"})
                return
            if not cmd:
                self.send_json(400, {"error": "Missing 'command' or 'cmd' parameter"})
                return
            ok, msg = rt.ptz_service.auxiliary(cid, cmd)
            self.send_json(
                200 if ok else 400,
                {"success": ok, "message": msg, "status": rt.ptz_service.get_status(cid)},
            )
            return

        # --- Recording controls (Admin-only enforced centrally) ---
        if url.path == "/api/recordings/start":
            if not cid:
                self.send_json(400, {"error": "Missing 'cameraId' or 'id' parameter"})
                return

            cfg = rt.config_provider()
            cam = next((c for c in cfg.get("cameras", []) if c.get("id") == cid or cid in c.get("aliases", [])), None)
            if cam:
                cid = cam.get("id")
                port = cam.get("port")
                if port and not is_port_open(port):
                    self.send_json(
                        400,
                        {
                            "success": False,
                            "status": "error",
                            "error": f"Camera '{cid}' decoder on port {port} is offline. Start the camera first.",
                            "message": f"Camera '{cid}' decoder on port {port} is offline. Please start camera first via 'Run All'.",
                        },
                    )
                    return

            mode = body_json.get("mode") or "manual"
            dur_val = body_json.get("duration") or 0
            dur = int(dur_val) if str(dur_val).isdigit() else 0
            ok, msg = rt.recording_manager.start_recording(cid, mode=mode, duration=dur)
            self.send_json(
                200 if ok else 400,
                {
                    "success": ok,
                    "status": "ok" if ok else "error",
                    "message": msg,
                    "storage": rt.recording_manager.get_storage_status(),
                },
            )
            return

        if url.path == "/api/recordings/stop":
            if not cid:
                self.send_json(400, {"error": "Missing 'cameraId' or 'id' parameter"})
                return
            ok, msg = rt.recording_manager.stop_recording(cid)
            self.send_json(
                200 if ok else 400,
                {
                    "success": ok,
                    "status": "ok" if ok else "error",
                    "message": msg,
                    "storage": rt.recording_manager.get_storage_status(),
                },
            )
            return

        if url.path == "/api/recordings/trigger-motion":
            if not cid:
                self.send_json(400, {"error": "Missing 'cameraId' or 'id' parameter"})
                return
            dur_val = body_json.get("duration") or qs.get("duration", ["30"])[0]
            dur = int(dur_val) if str(dur_val).isdigit() else 30
            ok, msg = rt.recording_manager.trigger_motion_recording(cid, duration=dur)
            self.send_json(
                200 if ok else 400,
                {
                    "success": ok,
                    "status": "ok" if ok else "error",
                    "message": msg,
                    "storage": rt.recording_manager.get_storage_status(),
                },
            )
            return

        # --- Service & Recovery controls (Admin-only enforced centrally) ---
        if url.path == "/api/services/start-all":
            results = rt.manager.start_all()
            time.sleep(0.4)
            self.send_json(200, {"success": True, "results": results, "status": rt.manager.get_status()})
            return

        if url.path == "/api/services/stop-all":
            results = rt.manager.stop_all()
            time.sleep(0.4)
            self.send_json(200, {"success": True, "results": results, "status": rt.manager.get_status()})
            return

        if url.path == "/api/services/restart-all":
            results = rt.manager.restart_all()
            time.sleep(0.5)
            self.send_json(200, {"success": True, "results": results, "status": rt.manager.get_status()})
            return

        if url.path == "/api/services/start":
            if not cid:
                self.send_json(400, {"error": "Missing 'id' query parameter"})
                return
            ok, msg = rt.manager.start_camera(cid)
            time.sleep(0.4)
            self.send_json(200 if ok else 400, {"success": ok, "message": msg, "status": rt.manager.get_status()})
            return

        if url.path == "/api/services/stop":
            if not cid:
                self.send_json(400, {"error": "Missing 'id' query parameter"})
                return
            ok, msg = rt.manager.stop_camera(cid)
            time.sleep(0.4)
            self.send_json(200 if ok else 400, {"success": ok, "message": msg, "status": rt.manager.get_status()})
            return

        if url.path == "/api/services/restart":
            if not cid:
                self.send_json(400, {"error": "Missing 'id' query parameter"})
                return
            ok, msg = rt.manager.restart_camera(cid)
            time.sleep(0.5)
            self.send_json(200 if ok else 400, {"success": ok, "message": msg, "status": rt.manager.get_status()})
            return

        if url.path == "/api/recovery/reset":
            if not cid:
                self.send_json(400, {"error": "Missing 'id' query parameter"})
                return
            ok, msg = rt.manager.reset_camera(cid)
            self.send_json(200 if ok else 404, {"success": ok, "message": msg, "status": rt.manager.get_status()})
            return

        # --- AI Detection & Benchmark endpoints (Admin-only enforced centrally) ---
        if url.path == "/api/ai/benchmark":
            if not rt.motion_service.ai_detector:
                self.send_json(503, {"error": "AI Object Detector is not initialized"})
                return
            runs_str = qs.get("runs", ["3"])[0]
            runs = int(runs_str) if runs_str.isdigit() else 3
            self.send_json(200, rt.motion_service.ai_detector.benchmark(runs=runs))
            return

        if url.path == "/api/ai/enrich":
            evt_id = qs.get("id", [None])[0]
            if not evt_id:
                self.send_json(400, {"error": "Missing 'id' parameter"})
                return
            enriched = rt.motion_service.enrich_event_with_ai(evt_id)
            if enriched:
                self.send_json(200, enriched)
            else:
                self.send_json(404, {"error": f"Failed to enrich event '{evt_id}'"})
            return

        if url.path == "/api/ai/detect":
            if not cid:
                self.send_json(400, {"error": "Missing 'id' or 'cameraId' parameter"})
                return
            cfg = rt.config_provider()
            cam = next((c for c in cfg.get("cameras", []) if c.get("id") == cid or cid in c.get("aliases", [])), None)
            if not cam:
                self.send_json(404, {"error": f"Camera '{cid}' not found"})
                return
            cid = cam.get("id")
            port = cam.get("port")
            if not port or not is_port_open(port):
                self.send_json(503, {"error": f"Camera decoder on port {port} is offline"})
                return

            snap_path = cam.get("snapshotPath") or (
                f"/api/cameras/{cid}/snapshot" if cam.get("type") == "okam" else "/snapshot"
            )
            try:
                req = Request(f"http://127.0.0.1:{port}{snap_path}")
                with urlopen(req, timeout=2.0) as resp:
                    snap_data = resp.read()

                t0 = time.perf_counter()
                cam_ai = rt.motion_service._get_camera_ai_config(cid)
                detections = rt.motion_service.ai_detector.detect(
                    snap_data,
                    conf_threshold=cam_ai.get("confidenceThreshold"),
                    target_classes=cam_ai.get("targetClasses"),
                    roi=cam_ai.get("roi"),
                )
                latency = round((time.perf_counter() - t0) * 1000.0, 2)
                self.send_json(
                    200,
                    {
                        "cameraId": cid,
                        "detections": detections,
                        "count": len(detections),
                        "latencyMs": latency,
                        "provider": rt.motion_service.ai_detector.active_provider,
                    },
                )
            except Exception as e:
                self.send_json(500, {"error": f"Detection failed: {e}"})
            return

        # --- Central Storage Management Clean & Reindex (Admin-only enforced centrally) ---
        if url.path == "/api/storage/cleanup":
            dry_run_str = str(body_json.get("dryRun", qs.get("dryRun", ["true"])[0])).lower()
            dry_run = dry_run_str in ("true", "1", "yes")
            # Active recording segments and playback locks are collected automatically inside evaluate_retention
            result = rt.storage_manager.evaluate_retention(dry_run=dry_run)
            status_http = 200 if result.get("success", True) or result.get("partialFailure") else 500
            self.send_json(status_http, result)
            return

        if url.path == "/api/storage/reindex":
            result = rt.storage_manager.reconcile_and_repair_index()
            self.send_json(200, {"success": True, "reconciled": result})
            return

        # --- Diagnostics Generation (Admin-only enforced centrally) ---
        if url.path == "/api/diagnostics/generate":
            try:
                bundle = rt.diagnostics_service.create_diagnostic_bundle()
                bundle.setdefault("status", "ok" if bundle.get("success") else "error")
                self.send_json(200, bundle)
            except Exception as e:
                self.send_json(500, {"error": f"Failed to generate diagnostic bundle: {e}"})
            return

        # --- Notification Center Actions (Admin-only enforced centrally) ---
        if url.path == "/api/notifications/ack":
            notif_id = body_json.get("id") or qs.get("id", [None])[0]
            all_unread = bool(body_json.get("all")) or qs.get("all", ["false"])[0].lower() == "true"
            count = rt.notification_center.acknowledge(notification_id=notif_id, all_unread=all_unread)
            self.send_json(200, {"success": True, "acknowledgedCount": count, "stats": rt.notification_center.get_stats()})
            return

        if url.path == "/api/notifications/simulate":
            cat = body_json.get("category") or qs.get("category", ["camera_offline"])[0]
            sim_cid = body_json.get("cameraId") or qs.get("cameraId", ["sim-1"])[0]
            cname = body_json.get("camera") or body_json.get("cameraName") or qs.get("cameraName", ["Simulated Camera"])[0]
            sev = body_json.get("severity") or qs.get("severity", ["warning"])[0]
            item = rt.notification_center.simulate_event(category=cat, camera_id=sim_cid, camera_name=cname, severity=sev)
            self.send_json(200, {"success": True, "notification": item, "stats": rt.notification_center.get_stats()})
            return

        if url.path == "/api/notifications/test-telegram":
            bot_token = body_json.get("botToken") or qs.get("botToken", [""])[0]
            chat_id = body_json.get("chatId") or qs.get("chatId", [""])[0]
            ok, msg = rt.notification_center.test_telegram_connection(bot_token, chat_id)
            self.send_json(200 if ok else 400, {"success": ok, "message": msg})
            return

        self.send_json(404, {"error": "Endpoint not found"})

    def do_DELETE(self):
        if not self._authorize_request("DELETE"):
            return

        url = urlparse(self.path)
        qs = parse_qs(url.query)
        rt = self.rt
        item_id = qs.get("id", [None])[0]

        if url.path == "/api/diagnostics":
            fname = qs.get("file", [None])[0] or qs.get("filename", [None])[0]
            if not fname:
                self.send_json(400, {"error": "Missing 'file' query parameter"})
                return
            ok, msg = rt.diagnostics_service.delete_bundle(fname)
            self.send_json(200 if ok else 404, {"success": ok, "message": msg})
            return

        if url.path == "/api/notifications":
            notif_id = qs.get("id", [None])[0]
            all_notifs = qs.get("all", ["false"])[0].lower() == "true" or notif_id is None
            count = rt.notification_center.clear(notification_id=notif_id, all_notifications=all_notifs)
            self.send_json(200, {"success": True, "clearedCount": count, "stats": rt.notification_center.get_stats()})
            return

        if url.path == "/api/recordings":
            if not item_id:
                self.send_json(400, {"error": "Missing 'id' query parameter"})
                return
            ok, msg = rt.recording_manager.delete_recording(item_id)
            if ok:
                self.send_json(200, {"success": True, "message": msg})
            elif "not found" in msg.lower():
                self.send_json(404, {"success": False, "error": msg, "message": msg})
            elif "protected" in msg.lower() or "lock" in msg.lower():
                self.send_json(409, {"success": False, "error": msg, "message": msg})
            else:
                self.send_json(500, {"success": False, "error": msg, "message": msg})
            return

        if url.path == "/api/events":
            if not item_id:
                self.send_json(400, {"error": "Missing 'id' query parameter"})
                return
            ok, msg = rt.motion_service.delete_event(item_id)
            if ok:
                self.send_json(200, {"success": True, "message": msg})
            elif "not found" in msg.lower():
                self.send_json(404, {"success": False, "error": msg, "message": msg})
            else:
                self.send_json(500, {"success": False, "error": msg, "message": msg})
            return

        self.send_json(404, {"error": "Endpoint not found"})


def create_camhub_handler(runtime: CamHubRuntime) -> Type[CamHubHandler]:
    """Create a bound CamHubHandler subclass for an isolated CamHubRuntime (ideal for testing)."""
    class BoundCamHubHandler(CamHubHandler):
        pass

    BoundCamHubHandler.runtime = runtime
    BoundCamHubHandler.static_root = runtime.static_dir
    return BoundCamHubHandler


def main():
    parser = argparse.ArgumentParser(description="CamHub Host Server & Camera Manager")
    parser.add_argument("--port", type=int, default=3000, help="Web server port (default: 3000)")
    args = parser.parse_args()

    rt = get_default_runtime()
    handler_cls = create_camhub_handler(rt)
    server = ThreadingHTTPServer(("0.0.0.0", args.port), handler_cls)
    server.daemon_threads = True

    print(f"[CAMHUB] Dashboard web server running on http://127.0.0.1:{args.port}", flush=True)
    if rt.auth_manager.is_setup_required():
        print(
            "[AUTH] Initial admin setup required. Use token in config/auth_bootstrap.token or 'python -m core.auth_manager set-user'.",
            flush=True,
        )
    print(f"[CAMHUB] Service Manager API ready at http://127.0.0.1:{args.port}/api/services/status", flush=True)
    print(f"[CAMHUB] Health Monitor API ready at http://127.0.0.1:{args.port}/api/health", flush=True)
    print(f"[CAMHUB] Auto-Recovery API ready at http://127.0.0.1:{args.port}/api/recovery/status", flush=True)
    print(f"[CAMHUB] Recording & Playback API ready at http://127.0.0.1:{args.port}/api/recordings", flush=True)
    print(f"[CAMHUB] Motion Detection API ready at http://127.0.0.1:{args.port}/api/events", flush=True)
    print(f"[CAMHUB] Storage Manager API ready at http://127.0.0.1:{args.port}/api/storage/status", flush=True)
    print(f"[CAMHUB] Diagnostics API ready at http://127.0.0.1:{args.port}/api/diagnostics/summary", flush=True)
    print(f"[CAMHUB] Notifications API ready at http://127.0.0.1:{args.port}/api/notifications", flush=True)
    print(f"[CAMHUB] PTZ Controller API ready at http://127.0.0.1:{args.port}/api/ptz/status", flush=True)

    rt.start_background_services()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[CAMHUB] Shutting down...", flush=True)
    finally:
        rt.stop_background_services(shutdown_children=True)
        server.server_close()


if __name__ == "__main__":
    main()
