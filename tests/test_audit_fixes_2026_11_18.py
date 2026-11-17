"""
Regression & End-to-End Integration Tests for Audit 2026-11-18 Fixes.
Covers:
  1. Static file confinement to web/ & media endpoint path validation (Finding #1)
  2. Server-verified authentication, centralized RBAC (unauth/viewer/admin), & CORS policy (Finding #2)
  3. Unified canonical recording metadata schema, legacy migration, & idempotent atomic reindex (Finding #3)
  4. Camera identity preservation for underscore IDs (okam_1, okam_2, okam_3) & legacy repair (Finding #4)
  5. Single retention policy path, active recording & playback lock protection, verified deletion, & partial failure reporting (Findings #5 & #6)
  6. RFC 9110 HTTP Range (standard, open-ended, suffix, 416 invalid/past-EOF) (Finding #7)
  7. Full integration pipeline: record -> scan -> reindex -> reload -> filter kamera -> playback -> retention

All tests run strictly in temporary directories using mock cameras and synthetic fixtures without touching active cameras or user files.
"""

import os
import io
import sys
import json
import time
import shutil
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.request import Request, urlopen, HTTPErrorProcessor, build_opener
from unittest.mock import patch
from PIL import Image

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from server import CamHubRuntime, create_camhub_handler, parse_http_byte_range
from core.auth_manager import AuthManager
from core.recording_manager import RecordingManager, RecordingSession
from core.storage_manager import CamHubStorageManager


class _NoErrorOpener(HTTPErrorProcessor):
    """Allow inspecting 4xx/5xx status codes, headers, and JSON payloads directly without raising."""

    def http_response(self, request, response):
        return response

    https_response = http_response


def http_call(url: str, method: str = "GET", headers: dict = None, json_body: dict = None):
    hdrs = dict(headers or {})
    data = None
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    req = Request(url, data=data, headers=hdrs, method=method)
    opener = build_opener(_NoErrorOpener)
    with opener.open(req, timeout=5.0) as resp:
        raw = resp.read()
        resp_headers = {k.lower(): v for k, v in resp.info().items()}
        return resp.status, resp_headers, raw


def make_jpeg_bytes(color=(40, 120, 200)) -> bytes:
    img = Image.new("RGB", (64, 36), color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


class _MockCameraHandler(BaseHTTPRequestHandler):
    jpeg_payload = b""

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if "snapshot" in self.path:
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(self.jpeg_payload)))
            self.end_headers()
            self.wfile.write(self.jpeg_payload)
            return
        if "metrics" in self.path:
            body = json.dumps({"cameraId": "okam_1", "status": "connected", "sourceFps": 12.5}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()


class TestAuditFixesServerAndSecurity(unittest.TestCase):
    """End-to-end HTTP server regression tests for Findings #1, #2, #6, #7, and full integration."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="camhub_audit_test_")
        self.web_dir = os.path.join(self.temp_dir, "web")
        self.cfg_dir = os.path.join(self.temp_dir, "config")
        os.makedirs(self.web_dir, exist_ok=True)
        os.makedirs(self.cfg_dir, exist_ok=True)

        # Create public web assets inside web/
        with open(os.path.join(self.web_dir, "index.html"), "w", encoding="utf-8") as f:
            f.write("<!doctype html><title>CamHub Test UI</title>")
        with open(os.path.join(self.web_dir, "app.js"), "w", encoding="utf-8") as f:
            f.write("console.log('ui-ok');")
        with open(os.path.join(self.web_dir, ".hidden_secret"), "w", encoding="utf-8") as f:
            f.write("DO_NOT_SERVE_DOTFILE")

        # Create sensitive files OUTSIDE web/ in temp base_dir to verify zero static fallback leakage
        with open(os.path.join(self.cfg_dir, "services_config.json"), "w", encoding="utf-8") as f:
            json.dump({"sensitive": "DO_NOT_LEAK_CONFIG"}, f)
        with open(os.path.join(self.temp_dir, "README.md"), "w", encoding="utf-8") as f:
            f.write("SENSITIVE_README_CONTENT")
        with open(os.path.join(self.temp_dir, "server.py"), "w", encoding="utf-8") as f:
            f.write("# SENSITIVE_SOURCE_CODE")

        # Start ephemeral mock camera HTTP server on dynamic port
        _MockCameraHandler.jpeg_payload = make_jpeg_bytes()
        self.mock_cam_server = ThreadingHTTPServer(("127.0.0.1", 0), _MockCameraHandler)
        self.mock_cam_port = self.mock_cam_server.server_address[1]
        self.mock_cam_thread = threading.Thread(target=self.mock_cam_server.serve_forever, daemon=True)
        self.mock_cam_thread.start()

        self.test_config = {
            "security": {
                "allowedOrigins": ["https://trusted-camhub.example.com"],
                "trustProxyHeaders": True,
            },
            "recording": {
                "storagePath": "recordings",
                "retentionDays": 7,
                "maxStorageGb": 1.0,
                "minDiskFreeGb": 0.01,
            },
            "cameras": [
                {
                    "id": "v380-1",
                    "name": "Camera 1 Indoor",
                    "type": "v380",
                    "port": self.mock_cam_port,
                    "cmd": "echo mock",
                },
                {
                    "id": "okam_1",
                    "name": "O-Kam 1 Main",
                    "type": "okam",
                    "port": self.mock_cam_port,
                    "cmd": "echo mock",
                    "snapshotPath": "/api/cameras/okam_1/snapshot",
                    "metricsPath": "/api/cameras/okam_1/metrics",
                },
                {
                    "id": "okam_2",
                    "name": "O-Kam 2 PTZ",
                    "type": "okam",
                    "port": self.mock_cam_port,
                    "cmd": "echo mock",
                    "snapshotPath": "/api/cameras/okam_2/snapshot",
                    "metricsPath": "/api/cameras/okam_2/metrics",
                },
                {
                    "id": "okam_3",
                    "name": "O-Kam 3 Sub",
                    "type": "okam",
                    "port": self.mock_cam_port,
                    "cmd": "echo mock",
                    "snapshotPath": "/api/cameras/okam_3/snapshot",
                    "metricsPath": "/api/cameras/okam_3/metrics",
                },
            ],
        }

        self.runtime = CamHubRuntime(
            base_dir=self.temp_dir,
            static_dir=self.web_dir,
            config_provider=lambda: self.test_config,
            enable_ai_on_init=False,
        )
        handler_cls = create_camhub_handler(self.runtime)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.server_thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.server_thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.runtime.stop_background_services(shutdown_children=False)
        self.mock_cam_server.shutdown()
        self.mock_cam_server.server_close()
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _provision_accounts_and_tokens(self):
        """Bootstrap admin and viewer users via server-verified setup + login."""
        boot_path = self.runtime.auth_manager.bootstrap_token_file
        with open(boot_path, "r", encoding="utf-8") as f:
            bootstrap_tok = f.read().strip()

        st, hdrs, raw = http_call(
            f"{self.base_url}/api/auth/setup",
            method="POST",
            json_body={
                "bootstrapToken": bootstrap_tok,
                "adminUsername": "admin",
                "adminPassword": "TestAdminPassword!234",
                "viewerPassword": "TestViewerPassword!234",
            },
        )
        self.assertEqual(st, 200)
        admin_data = json.loads(raw.decode("utf-8"))
        admin_token = admin_data["token"]
        self.assertIn("httponly", hdrs.get("set-cookie", "").lower())
        self.assertFalse(os.path.exists(boot_path), "Bootstrap token file must be deleted after initial setup")

        st_v, _, raw_v = http_call(
            f"{self.base_url}/api/auth/login",
            method="POST",
            json_body={"username": "viewer", "password": "TestViewerPassword!234"},
        )
        self.assertEqual(st_v, 200)
        viewer_token = json.loads(raw_v.decode("utf-8"))["token"]
        return admin_token, viewer_token

    def test_1_static_file_leakage_closed_and_media_paths_validated(self):
        """Finding #1: Only web/ is served statically; config, source, README, and dotfiles are unreachable."""
        # Valid web/ assets succeed without auth
        st_idx, _, body_idx = http_call(f"{self.base_url}/index.html")
        self.assertEqual(st_idx, 200)
        self.assertIn(b"CamHub Test UI", body_idx)

        st_js, _, body_js = http_call(f"{self.base_url}/app.js")
        self.assertEqual(st_js, 200)
        self.assertIn(b"ui-ok", body_js)

        # Sensitive files outside web/ and dotfiles MUST return 404 (never fall back to project root)
        forbidden_paths = [
            "/config/services_config.json",
            "/config/auth_config.json",
            "/config/auth_bootstrap.token",
            "/README.md",
            "/server.py",
            "/recordings/recordings_index.json",
            "/.hidden_secret",
            "/.env",
            "/../config/services_config.json",
            "/%2e%2e/config/services_config.json",
        ]
        for p in forbidden_paths:
            st, _, raw = http_call(f"{self.base_url}{p}")
            self.assertEqual(st, 404, f"Path {p} must return 404, got {st}")
            self.assertNotIn(b"DO_NOT_LEAK_CONFIG", raw)
            self.assertNotIn(b"SENSITIVE_README_CONTENT", raw)
            self.assertNotIn(b"SENSITIVE_SOURCE_CODE", raw)
            self.assertNotIn(b"DO_NOT_SERVE_DOTFILE", raw)

        # Media snapshot endpoint must ALSO reject attempts to read outside events/
        admin_tok, viewer_tok = self._provision_accounts_and_tokens()
        v_hdr = {"Authorization": f"Bearer {viewer_tok}"}

        for bad_snap_query in [
            "/api/events/snapshot?path=../config/services_config.json",
            "/api/events/snapshot?path=config/services_config.json",
            "/api/events/snapshot?path=../../README.md",
        ]:
            st_s, _, raw_s = http_call(f"{self.base_url}{bad_snap_query}", headers=v_hdr)
            self.assertIn(st_s, (403, 404))
            self.assertNotIn(b"DO_NOT_LEAK_CONFIG", raw_s)

        # Valid event snapshot inside events/ succeeds for Viewer
        evt_dir = os.path.join(self.temp_dir, "events", "okam_1", "2026-11-18")
        os.makedirs(evt_dir, exist_ok=True)
        jpg_bytes = make_jpeg_bytes()
        snap_file = os.path.join(evt_dir, "evt_test_1.jpg")
        with open(snap_file, "wb") as f:
            f.write(jpg_bytes)
        self.runtime.motion_service.index["evt_test_1"] = {
            "id": "evt_test_1",
            "cameraId": "okam_1",
            "timestamp": int(time.time() * 1000),
            "snapshotPath": "events/okam_1/2026-11-18/evt_test_1.jpg",
            "fileSizeBytes": len(jpg_bytes),
        }
        self.runtime.motion_service.save_index()

        st_ok, hdr_ok, raw_ok = http_call(f"{self.base_url}/api/events/snapshot?id=evt_test_1", headers=v_hdr)
        self.assertEqual(st_ok, 200)
        self.assertEqual(hdr_ok.get("content-type"), "image/jpeg")
        self.assertEqual(raw_ok, jpg_bytes)
        _ = admin_tok

    def test_2_authentication_rbac_spoofing_resistance_and_cors(self):
        """Finding #2: Unauthenticated, spoofed X-CamHub-Role, fake Bearer, and loopback bypass all fail; RBAC & CORS enforced."""
        admin_tok, viewer_tok = self._provision_accounts_and_tokens()

        # Re-running /api/auth/setup after setup is completed must fail with 409
        st_re, _, _ = http_call(
            f"{self.base_url}/api/auth/setup",
            method="POST",
            json_body={"bootstrapToken": "anything", "adminPassword": "AnotherPassword!234"},
        )
        self.assertEqual(st_re, 409)

        # 1. Unauthenticated & spoofed headers from loopback 127.0.0.1 MUST be 401
        spoof_headers_list = [
            {},  # bare loopback without auth
            {"X-CamHub-Role": "admin"},  # spoofed role header
            {"Authorization": "Bearer invalid_arbitrary_token"},  # arbitrary Bearer string
            {"Authorization": f"Bearer {viewer_tok}tampered"},  # tampered HMAC signature
            {"Cookie": "camhub_session=forged.000000"},  # forged cookie
        ]
        for hdrs in spoof_headers_list:
            for method, path in [
                ("GET", "/api/cameras"),
                ("GET", "/api/recordings"),
                ("GET", "/api/diagnostics/summary"),
                ("POST", "/api/services/stop-all"),
                ("POST", "/api/ptz/stop?id=okam_2"),
                ("POST", "/api/storage/cleanup?dryRun=true"),
                ("DELETE", "/api/recordings?id=any"),
            ]:
                st, _, _ = http_call(f"{self.base_url}{path}", method=method, headers=hdrs)
                self.assertEqual(st, 401, f"Expected 401 for {method} {path} with {hdrs}, got {st}")

        # 2. Viewer role: allowed feed/status/playback, forbidden on ALL admin endpoints (even with X-CamHub-Role: admin)
        v_hdrs = {"Authorization": f"Bearer {viewer_tok}", "X-CamHub-Role": "admin"}

        for allowed_get in [
            "/api/cameras",
            "/api/cameras/okam_1/snapshot",
            "/proxy/snapshot/okam_1",
            "/api/health",
            "/api/services/status",
            "/api/recordings",
            "/api/storage/status",
            "/api/events",
            "/api/notifications",
            "/api/ptz/status?id=okam_2",
        ]:
            st, _, _ = http_call(f"{self.base_url}{allowed_get}", method="GET", headers=v_hdrs)
            self.assertEqual(st, 200, f"Viewer should access {allowed_get}, got {st}")

        for admin_only_method, admin_only_path in [
            ("POST", "/api/ptz/move?id=okam_2&dir=left"),
            ("POST", "/api/ptz/stop?id=okam_2"),
            ("POST", "/api/ptz/zoom?id=okam_2&action=in"),
            ("POST", "/api/ptz/preset?id=okam_2&preset=1&action=set"),
            ("POST", "/api/services/start?id=okam_1"),
            ("POST", "/api/services/stop?id=okam_1"),
            ("POST", "/api/services/stop-all"),
            ("POST", "/api/services/restart-all"),
            ("POST", "/api/recovery/reset?id=okam_1"),
            ("POST", "/api/recordings/start?id=okam_1"),
            ("POST", "/api/recordings/stop?id=okam_1"),
            ("DELETE", "/api/recordings?id=seg1"),
            ("POST", "/api/storage/cleanup?dryRun=true"),
            ("POST", "/api/storage/reindex"),
            ("DELETE", "/api/events?id=evt1"),
            ("GET", "/api/diagnostics/summary"),
            ("POST", "/api/diagnostics/generate"),
            ("DELETE", "/api/diagnostics?file=camhub_diagnostics_test.zip"),
            ("DELETE", "/api/notifications"),
            ("POST", "/api/auth/users"),
            ("POST", "/api/cameras/config?id=okam_1"),
        ]:
            st, _, _ = http_call(f"{self.base_url}{admin_only_path}", method=admin_only_method, headers=v_hdrs)
            self.assertEqual(
                st,
                403,
                f"Viewer must receive 403 on {admin_only_method} {admin_only_path}, got {st}",
            )

        # 3. Admin role succeeds on protected operations
        a_hdrs = {"Authorization": f"Bearer {admin_tok}"}
        st_clean, _, _ = http_call(f"{self.base_url}/api/storage/cleanup?dryRun=true", method="POST", headers=a_hdrs)
        self.assertEqual(st_clean, 200)
        st_reidx, _, _ = http_call(f"{self.base_url}/api/storage/reindex", method="POST", headers=a_hdrs)
        self.assertEqual(st_reidx, 200)
        st_cfg_upd, _, raw_cfg_upd = http_call(
            f"{self.base_url}/api/cameras/config",
            method="POST",
            headers=a_hdrs,
            json_body={"cameraId": "okam_1", "name": "O-Kam 1 Updated"},
        )
        self.assertEqual(st_cfg_upd, 200)
        self.assertEqual(json.loads(raw_cfg_upd.decode("utf-8"))["name"], "O-Kam 1 Updated")

        # 4. CORS & Origin validation (local, reverse proxy X-Forwarded-Host, configured domain, vs untrusted origin)
        st_evil_get, hdr_evil_get, _ = http_call(
            f"{self.base_url}/api/cameras",
            headers={**v_hdrs, "Origin": "https://malicious.attacker.invalid"},
        )
        self.assertEqual(st_evil_get, 200)
        self.assertNotIn("access-control-allow-origin", hdr_evil_get)

        # Cross-origin POST from untrusted Origin is blocked with 403 even with valid admin token
        st_evil_post, _, _ = http_call(
            f"{self.base_url}/api/storage/reindex",
            method="POST",
            headers={**a_hdrs, "Origin": "https://malicious.attacker.invalid"},
        )
        self.assertEqual(st_evil_post, 403)

        # Configured trusted origin & reverse-proxy X-Forwarded-Host origin are allowed
        st_trust, hdr_trust, _ = http_call(
            f"{self.base_url}/api/cameras",
            headers={**v_hdrs, "Origin": "https://trusted-camhub.example.com"},
        )
        self.assertEqual(st_trust, 200)
        self.assertEqual(hdr_trust.get("access-control-allow-origin"), "https://trusted-camhub.example.com")

        st_proxy, hdr_proxy, _ = http_call(
            f"{self.base_url}/api/storage/reindex",
            method="POST",
            headers={
                **a_hdrs,
                "Origin": "https://my-tunnel.ngrok-free.app",
                "X-Forwarded-Host": "my-tunnel.ngrok-free.app",
                "X-Forwarded-Proto": "https",
            },
        )
        self.assertEqual(st_proxy, 200)
        self.assertEqual(hdr_proxy.get("access-control-allow-origin"), "https://my-tunnel.ngrok-free.app")

        # 5. Logout revokes session server-side immediately
        st_out, _, _ = http_call(f"{self.base_url}/api/auth/logout", method="POST", headers=v_hdrs)
        self.assertEqual(st_out, 200)
        st_after, _, _ = http_call(f"{self.base_url}/api/cameras", headers={"Authorization": f"Bearer {viewer_tok}"})
        self.assertEqual(st_after, 401)

    def test_6_http_range_standard_open_suffix_and_416(self):
        """Finding #7: Standard, open-ended, suffix ranges, and HTTP 416 on invalid/past-EOF ranges."""
        _, viewer_tok = self._provision_accounts_and_tokens()
        v_hdrs = {"Authorization": f"Bearer {viewer_tok}"}

        # Create deterministic 1000-byte MP4 fixture
        rec_dir = os.path.join(self.temp_dir, "recordings", "okam_1", "2026-11-18")
        os.makedirs(rec_dir, exist_ok=True)
        payload = bytes((i % 251) for i in range(1000))
        mp4_path = os.path.join(rec_dir, "okam_1_rec_20261118_010000_seg000.mp4")
        with open(mp4_path, "wb") as f:
            f.write(payload)

        self.runtime.recording_manager.scan_and_sync_filesystem()
        seg_id = "okam_1_rec_20261118_010000_seg000"
        stream_url = f"{self.base_url}/api/recordings/stream?id={seg_id}"

        # 1. Full 200 response without Range
        st_200, h_200, b_200 = http_call(stream_url, headers=v_hdrs)
        self.assertEqual(st_200, 200)
        self.assertEqual(int(h_200["content-length"]), 1000)
        self.assertEqual(b_200, payload)

        # 2. Standard explicit range: bytes=100-349
        st_std, h_std, b_std = http_call(stream_url, headers={**v_hdrs, "Range": "bytes=100-349"})
        self.assertEqual(st_std, 206)
        self.assertEqual(h_std["content-range"], "bytes 100-349/1000")
        self.assertEqual(int(h_std["content-length"]), 250)
        self.assertEqual(b_std, payload[100:350])

        # 3. Open-ended range: bytes=750-
        st_open, h_open, b_open = http_call(stream_url, headers={**v_hdrs, "Range": "bytes=750-"})
        self.assertEqual(st_open, 206)
        self.assertEqual(h_open["content-range"], "bytes 750-999/1000")
        self.assertEqual(int(h_open["content-length"]), 250)
        self.assertEqual(b_open, payload[750:])

        # 4. Suffix range: bytes=-180 (must return LAST 180 bytes, NOT 0..180!)
        st_suf, h_suf, b_suf = http_call(stream_url, headers={**v_hdrs, "Range": "bytes=-180"})
        self.assertEqual(st_suf, 206)
        self.assertEqual(h_suf["content-range"], "bytes 820-999/1000")
        self.assertEqual(int(h_suf["content-length"]), 180)
        self.assertEqual(b_suf, payload[-180:])

        # 5. Suffix larger than file size: bytes=-5000 -> entire 1000 bytes
        st_suf_all, h_suf_all, b_suf_all = http_call(stream_url, headers={**v_hdrs, "Range": "bytes=-5000"})
        self.assertEqual(st_suf_all, 206)
        self.assertEqual(h_suf_all["content-range"], "bytes 0-999/1000")
        self.assertEqual(int(h_suf_all["content-length"]), 1000)
        self.assertEqual(b_suf_all, payload)

        # 6. Clamped end when start < EOF < end: bytes=900-5000 -> 900-999
        st_clamp, h_clamp, b_clamp = http_call(stream_url, headers={**v_hdrs, "Range": "bytes=900-5000"})
        self.assertEqual(st_clamp, 206)
        self.assertEqual(h_clamp["content-range"], "bytes 900-999/1000")
        self.assertEqual(int(h_clamp["content-length"]), 100)
        self.assertEqual(b_clamp, payload[900:])

        # 7. Invalid or past-EOF ranges MUST return HTTP 416 with Content-Range: bytes */1000
        invalid_ranges = [
            "bytes=1000-",        # exact EOF (valid offsets are 0..999)
            "bytes=1500-2000",    # past EOF
            "bytes=500-200",      # start > end
            "bytes=-0",           # zero-length suffix
            "bytes=-",            # empty bounds
            "bytes=0-10,20-30",   # unsupported multi-part
            "items=0-50",         # wrong unit
            "bytes=abc-def",      # non-numeric
            "bytes=-10-20",       # negative start
        ]
        for bad_rng in invalid_ranges:
            st_bad, h_bad, b_bad = http_call(stream_url, headers={**v_hdrs, "Range": bad_rng})
            self.assertEqual(st_bad, 416, f"Range '{bad_rng}' must return 416, got {st_bad}")
            self.assertEqual(h_bad.get("content-range"), "bytes */1000")
            self.assertEqual(int(h_bad.get("content-length", "0")), 0)
            self.assertEqual(len(b_bad), 0)

        # 8. HEAD request with Range returns 206 headers with accurate Content-Length and empty body
        st_head, h_head, b_head = http_call(
            stream_url, method="HEAD", headers={**v_hdrs, "Range": "bytes=-120"}
        )
        self.assertEqual(st_head, 206)
        self.assertEqual(h_head.get("content-range"), "bytes 880-999/1000")
        self.assertEqual(int(h_head.get("content-length", "0")), 120)
        self.assertEqual(len(b_head), 0)

        # 9. Direct unit check for 0-byte file Range -> ValueError (416)
        with self.assertRaises(ValueError):
            parse_http_byte_range("bytes=0-0", 0)

    def test_7_full_pipeline_integration_record_scan_reindex_reload_filter_playback_retention(self):
        """
        Full integration workflow:
        record -> scan -> reindex -> reload -> filter kamera -> playback -> retention
        """
        admin_tok, viewer_tok = self._provision_accounts_and_tokens()
        a_hdrs = {"Authorization": f"Bearer {admin_tok}"}
        v_hdrs = {"Authorization": f"Bearer {viewer_tok}"}

        now = time.time()
        old_ts = now - (10 * 86400)  # 10 days old (> 7 day retention)

        def write_segment(cid: str, day: str, name: str, content: bytes, mtime_sec: float) -> str:
            folder = os.path.join(self.temp_dir, "recordings", cid, day)
            os.makedirs(folder, exist_ok=True)
            fpath = os.path.join(folder, name)
            with open(fpath, "wb") as f:
                f.write(content)
            os.utime(fpath, (mtime_sec, mtime_sec))
            return fpath

        # --- STEP 1: RECORD (simulated segments for okam_1, okam_2, okam_3 + active live session on okam_1) ---
        # okam_1: 1 expired unlocked segment, 1 recent segment, 1 active segment (even with old mtime to prove lock works!)
        p_okam1_old = write_segment(
            "okam_1", "2026-11-01", "okam_1_rec_20261101_080000_seg000.mp4", b"OLD_OKAM1_" * 300, old_ts
        )
        p_okam1_recent = write_segment(
            "okam_1", "2026-11-18", "okam_1_rec_20261118_090000_seg000.mp4", b"NEW_OKAM1_" * 300, now - 120
        )
        p_okam1_active = write_segment(
            "okam_1", "2026-11-18", "okam_1_rec_20261118_100000_seg000.mp4", b"LIVE_ACTIVE_" * 300, old_ts
        )

        # Register mock active recording session for okam_1 pointing to p_okam1_active
        active_sess = RecordingSession("okam_1", "rtsp://127.0.0.1:8554/live", self.runtime.recording_manager.storage_dir)
        active_sess.running = True
        active_sess.session_dir = os.path.dirname(p_okam1_active)
        active_sess.session_prefix = "okam_1_rec_20261118_100000_seg"
        active_sess.active_file_path = p_okam1_active
        self.runtime.recording_manager.active_sessions["okam_1"] = active_sess

        # okam_2: 1 recent segment
        p_okam2_recent = write_segment(
            "okam_2", "2026-11-18", "okam_2_rec_20261118_091500_seg000.mp4", b"NEW_OKAM2_" * 300, now - 90
        )

        # okam_3: 1 expired segment that will be played back right before retention runs!
        okam3_payload = b"PLAYBACK_PROTECTED_OKAM3_" * 200
        p_okam3_old_played = write_segment(
            "okam_3", "2026-11-01", "okam_3_rec_20261101_083000_seg000.mp4", okam3_payload, old_ts
        )

        # --- STEP 2: SCAN ---
        self.runtime.recording_manager.scan_and_sync_filesystem()
        # Force startTime of the two 2026-11-01 segments + active segment to old_ts*1000 (on Windows st_ctime is creation time)
        with self.runtime.recording_manager.lock:
            for sid in (
                "okam_1_rec_20261101_080000_seg000",
                "okam_1_rec_20261118_100000_seg000",
                "okam_3_rec_20261101_083000_seg000",
            ):
                self.runtime.recording_manager.index[sid]["startTime"] = int(old_ts * 1000)
            self.runtime.recording_manager.save_index()

        # --- STEP 3: REINDEX (must be idempotent and preserve canonical filePath/fileName) ---
        st_re1, _, raw_re1 = http_call(f"{self.base_url}/api/storage/reindex", method="POST", headers=a_hdrs)
        self.assertEqual(st_re1, 200)
        re1 = json.loads(raw_re1.decode("utf-8"))["reconciled"]
        self.assertEqual(re1["recordingsReconciled"], 0, "Already scanned segments must not be duplicated on reindex")
        self.assertEqual(re1["recordingsGhostPurged"], 0)

        st_re2, _, raw_re2 = http_call(f"{self.base_url}/api/storage/reindex", method="POST", headers=a_hdrs)
        self.assertEqual(st_re2, 200)
        re2 = json.loads(raw_re2.decode("utf-8"))["reconciled"]
        self.assertEqual(re2["recordingsReconciled"], 0)
        self.assertEqual(re2["recordingsMigrated"], 0)

        # --- STEP 4: RELOAD ---
        self.runtime.recording_manager.load_index()
        reloaded_mgr = RecordingManager(lambda: self.test_config, base_dir=self.temp_dir)
        self.addCleanup(reloaded_mgr.stop)
        self.assertEqual(len(reloaded_mgr.index), 5)
        for item in reloaded_mgr.index.values():
            self.assertIn("filePath", item)
            self.assertIn("fileName", item)
            self.assertNotIn("path", item)
            self.assertNotIn("filename", item)

        # --- STEP 5: FILTER KAMERA (okam_1, okam_2, okam_3 must stay strictly separate) ---
        for expected_cid, expected_count in [("okam_1", 3), ("okam_2", 1), ("okam_3", 1), ("okam", 0)]:
            st_f, _, raw_f = http_call(
                f"{self.base_url}/api/recordings?cameraId={expected_cid}", headers=v_hdrs
            )
            self.assertEqual(st_f, 200)
            recs_f = json.loads(raw_f.decode("utf-8"))["recordings"]
            self.assertEqual(
                len(recs_f),
                expected_count,
                f"Expected {expected_count} recordings for cameraId={expected_cid}, got {len(recs_f)}",
            )

        # --- STEP 6: PLAYBACK (acquires playback lock & streams partial content accurately) ---
        okam3_id = "okam_3_rec_20261101_083000_seg000"
        st_play, h_play, b_play = http_call(
            f"{self.base_url}/api/recordings/stream?id={okam3_id}",
            headers={**v_hdrs, "Range": "bytes=-100"},
        )
        self.assertEqual(st_play, 206)
        self.assertEqual(b_play, okam3_payload[-100:])
        self.assertIn("bytes ", h_play.get("content-range", ""))

        # Deleting a playback-locked recording via API must return 409 Conflict!
        st_del_locked, _, _ = http_call(
            f"{self.base_url}/api/recordings?id={okam3_id}", method="DELETE", headers=a_hdrs
        )
        self.assertEqual(st_del_locked, 409)
        self.assertTrue(os.path.exists(p_okam3_old_played))

        # --- STEP 7: RETENTION (dry-run then real cleanup across both API and RecordingManager) ---
        st_dry, _, raw_dry = http_call(
            f"{self.base_url}/api/storage/cleanup?dryRun=true", method="POST", headers=a_hdrs
        )
        self.assertEqual(st_dry, 200)
        dry_res = json.loads(raw_dry.decode("utf-8"))
        self.assertTrue(dry_res["dryRun"])
        self.assertEqual(dry_res["filesToDeleteCount"], 1)  # Only p_okam1_old! Active & playback-locked are skipped!
        self.assertGreaterEqual(dry_res["protectedSkippedCount"], 2)
        self.assertTrue(os.path.exists(p_okam1_old), "Dry-run must never delete files")

        st_exec, _, raw_exec = http_call(
            f"{self.base_url}/api/storage/cleanup?dryRun=false", method="POST", headers=a_hdrs
        )
        self.assertEqual(st_exec, 200)
        exec_res = json.loads(raw_exec.decode("utf-8"))
        self.assertTrue(exec_res["success"])
        self.assertEqual(exec_res["filesDeletedCount"], 1)

        # Verify RecordingManager's background retention path ALSO respects the exact same locks!
        self.runtime.recording_manager.enforce_retention_policy()

        self.assertFalse(os.path.exists(p_okam1_old), "Unlocked expired segment must be purged")
        self.assertTrue(os.path.exists(p_okam1_active), "Active recording segment must be protected")
        self.assertTrue(os.path.exists(p_okam3_old_played), "Playback-locked segment must be protected")
        self.assertTrue(os.path.exists(p_okam1_recent), "Recent okam_1 segment must be preserved")
        self.assertTrue(os.path.exists(p_okam2_recent), "Recent okam_2 segment must be preserved")


class TestMetadataMigrationIdentityAndPartialFailures(unittest.TestCase):
    """Focused unit regression tests for Findings #3, #4, #5, and #6."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="camhub_meta_test_")
        self.rec_dir = os.path.join(self.temp_dir, "recordings")
        self.evt_dir = os.path.join(self.temp_dir, "events")
        os.makedirs(self.rec_dir, exist_ok=True)
        os.makedirs(self.evt_dir, exist_ok=True)
        self.cfg = {
            "recording": {"retentionDays": 3, "maxStorageGb": 5.0},
            "cameras": [{"id": "okam_1"}, {"id": "okam_2"}, {"id": "okam_3"}],
        }

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_legacy_index_migration_and_truncated_camera_id_repair(self):
        """Findings #3 & #4: Migrate legacy path/filename keys and repair truncated cameraId='okam' -> 'okam_2'."""
        seg_dir = os.path.join(self.rec_dir, "okam_2", "2026-11-15")
        os.makedirs(seg_dir, exist_ok=True)
        seg_file = os.path.join(seg_dir, "okam_2_rec_20261115_120000_seg001.mp4")
        with open(seg_file, "wb") as f:
            f.write(b"LEGACY_MP4_DATA" * 200)

        index_file = os.path.join(self.rec_dir, "recordings_index.json")
        # Write old broken StorageManager/truncated entry on disk
        with open(index_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "okam_2_rec_20261115_120000_seg001": {
                        "id": "okam_2_rec_20261115_120000_seg001",
                        "cameraId": "okam",  # Old truncated bug!
                        "filename": "okam_2_rec_20261115_120000_seg001.mp4",  # Legacy key!
                        "path": "recordings/okam_2/2026-11-15/okam_2_rec_20261115_120000_seg001.mp4",  # Legacy key!
                        "fileSizeBytes": 3000,
                        "startTime": int(time.time() * 1000) - 60000,
                        "durationSeconds": 60.0,
                        "customNote": "preserved_metadata",
                    }
                },
                f,
            )

        storage = CamHubStorageManager(lambda: self.cfg, base_dir=self.temp_dir)
        rec_mgr = RecordingManager(lambda: self.cfg, base_dir=self.temp_dir, storage_manager=storage)
        self.addCleanup(rec_mgr.stop)

        item = rec_mgr.get_recording_item("okam_2_rec_20261115_120000_seg001")
        self.assertIsNotNone(item)
        self.assertEqual(item["cameraId"], "okam_2")
        self.assertEqual(
            item["filePath"], "recordings/okam_2/2026-11-15/okam_2_rec_20261115_120000_seg001.mp4"
        )
        self.assertEqual(item["fileName"], "okam_2_rec_20261115_120000_seg001.mp4")
        self.assertEqual(item["customNote"], "preserved_metadata")
        self.assertNotIn("path", item)
        self.assertNotIn("filename", item)
        self.assertTrue(os.path.exists(seg_file))

    def test_metadata_retained_when_file_deletion_fails_and_partial_failure_reported(self):
        """Finding #6: Metadata must NOT be removed if os.remove fails, and partial failures are reported."""
        storage = CamHubStorageManager(lambda: self.cfg, base_dir=self.temp_dir)
        rec_mgr = RecordingManager(lambda: self.cfg, base_dir=self.temp_dir, storage_manager=storage)
        self.addCleanup(rec_mgr.stop)

        old_ms = int((time.time() - (10 * 86400)) * 1000)
        folder = os.path.join(self.rec_dir, "okam_1", "2026-11-01")
        os.makedirs(folder, exist_ok=True)
        f_ok = os.path.join(folder, "okam_1_rec_20261101_010000_seg000.mp4")
        f_locked_os = os.path.join(folder, "okam_1_rec_20261101_010100_seg001.mp4")
        for fp in (f_ok, f_locked_os):
            with open(fp, "wb") as f:
                f.write(b"VIDEO_BYTES" * 200)

        rec_mgr.scan_and_sync_filesystem()
        with rec_mgr.lock:
            rec_mgr.index["okam_1_rec_20261101_010000_seg000"]["startTime"] = old_ms
            rec_mgr.index["okam_1_rec_20261101_010100_seg001"]["startTime"] = old_ms + 1000
            rec_mgr.save_index()

        real_remove = os.remove

        def flaky_remove(target_path):
            if os.path.basename(target_path) == "okam_1_rec_20261101_010100_seg001.mp4":
                raise PermissionError("Simulated Windows file-in-use lock")
            return real_remove(target_path)

        # 1. Explicit single-item delete_recording when OS blocks os.remove must fail & preserve index
        with patch("core.media_index.os.remove", side_effect=flaky_remove):
            ok_del, msg_del = rec_mgr.delete_recording("okam_1_rec_20261101_010100_seg001")
            self.assertFalse(ok_del)
            self.assertIn("Failed to delete", msg_del)
            self.assertIsNotNone(rec_mgr.get_recording_item("okam_1_rec_20261101_010100_seg001"))

            # 2. Retention cleanup with 1 deletable + 1 OS-locked file reports partial failure accurately
            ret_res = storage.evaluate_retention(dry_run=False)
            self.assertFalse(ret_res["success"])
            self.assertTrue(ret_res["partialFailure"])
            self.assertEqual(ret_res["status"], "partial")
            self.assertEqual(ret_res["filesDeletedCount"], 1)
            self.assertEqual(ret_res["failedCount"], 1)

        # f_ok was deleted and removed from index; f_locked_os failed deletion and MUST remain in index!
        self.assertFalse(os.path.exists(f_ok))
        self.assertIsNone(rec_mgr.get_recording_item("okam_1_rec_20261101_010000_seg000"))
        self.assertTrue(os.path.exists(f_locked_os))
        self.assertIsNotNone(rec_mgr.get_recording_item("okam_1_rec_20261101_010100_seg001"))

    def test_empty_path_entry_never_targets_root_directory(self):
        """Finding #3/#6 safety: Malformed empty path in index must never resolve to or delete base_dir."""
        from core.media_index import safe_remove_media_file

        can_unindex, deleted, err = safe_remove_media_file(self.temp_dir, self.rec_dir, "")
        self.assertFalse(can_unindex)
        self.assertFalse(deleted)
        self.assertIsNotNone(err)
        self.assertTrue(os.path.isdir(self.temp_dir))
        self.assertTrue(os.path.isdir(self.rec_dir))

    def test_concurrent_atomic_index_sync_between_managers(self):
        """Finding #3: Concurrent scans and reindex calls must remain valid JSON without lost entries."""
        storage = CamHubStorageManager(lambda: self.cfg, base_dir=self.temp_dir)
        rec_mgr = RecordingManager(lambda: self.cfg, base_dir=self.temp_dir, storage_manager=storage)
        self.addCleanup(rec_mgr.stop)

        for idx, cid in enumerate(["okam_1", "okam_2", "okam_3"]):
            folder = os.path.join(self.rec_dir, cid, "2026-11-18")
            os.makedirs(folder, exist_ok=True)
            for seg_num in range(4):
                fp = os.path.join(folder, f"{cid}_rec_20261118_12000{idx}_seg00{seg_num}.mp4")
                with open(fp, "wb") as f:
                    f.write(b"MP4_SEGMENT_PAYLOAD" * 100)

        errors = []

        def worker_scan():
            for _ in range(8):
                try:
                    rec_mgr.scan_and_sync_filesystem()
                except Exception as exc:
                    errors.append(exc)

        def worker_reindex():
            for _ in range(8):
                try:
                    storage.reconcile_and_repair_index()
                except Exception as exc:
                    errors.append(exc)

        t1 = threading.Thread(target=worker_scan)
        t2 = threading.Thread(target=worker_reindex)
        t1.start()
        t2.start()
        t1.join(timeout=10.0)
        t2.join(timeout=10.0)

        self.assertEqual(errors, [])
        with open(rec_mgr.index_file, "r", encoding="utf-8") as f:
            disk_idx = json.load(f)
        self.assertEqual(len(disk_idx), 12)
        for item in disk_idx.values():
            self.assertIn(item["cameraId"], {"okam_1", "okam_2", "okam_3"})
            self.assertIn("filePath", item)
            self.assertIn("fileName", item)


if __name__ == "__main__":
    unittest.main()
