"""
Unit tests for CamHUB Diagnostics & Export Report Service.
Tests software version detection, system telemetry, port checks,
strict credential sanitization, ZIP bundle generation, and offline camera resilience.
"""

import os
import sys
import shutil
import tempfile
import unittest
import zipfile
import json
from unittest.mock import MagicMock, patch

from core.diagnostics_service import (
    CamHubDiagnosticsService,
    sanitize_value,
    sanitize_string,
    test_tcp_port
)


class TestDiagnosticsService(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.config = {
            "cameras": [
                {
                    "id": "v380-1",
                    "name": "Camera 1 · Indoor",
                    "port": 8080,
                    "rtspPort": 8554,
                    "type": "v380",
                    "cmd": "dotnet run --username admin --password SecretPass123. --ip 192.168.1.100"
                },
                {
                    "id": "okam-3",
                    "name": "Camera 3 · O-Kam Pro",
                    "port": 8082,
                    "type": "okam",
                    "cmd": "python adapter.py --rtsp rtsp://admin:Danendra07.@192.168.100.6:10554/live"
                }
            ],
            "notifications": {
                "telegram": {
                    "enabled": True,
                    "botToken": "123456789:ABCdefGHIjklMNOpqrSTUvwxYZ_extraSecretToken1234",
                    "chatId": "987654321"
                }
            }
        }
        self.service = CamHubDiagnosticsService(
            lambda: self.config,
            base_dir=self.test_dir
        )

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_sanitize_string(self):
        # 1. RTSP credentials
        raw_url = "rtsp://admin:Danendra07.@192.168.100.6:10554/live"
        s_url = sanitize_string(raw_url)
        self.assertNotIn("Danendra07.", s_url)
        self.assertEqual(s_url, "rtsp://admin:***@192.168.100.6:10554/live")

        # 2. CLI password flag
        raw_cli = "dotnet run --password SecretPass123. --ip 192.168.1.100"
        s_cli = sanitize_string(raw_cli)
        self.assertNotIn("SecretPass123.", s_cli)
        self.assertIn("--password [REDACTED]", s_cli)

        # 3. Telegram bot token
        raw_tg = "token 123456789:ABCdefGHIjklMNOpqrSTUvwxYZ_extraSecretToken1234 in message"
        s_tg = sanitize_string(raw_tg)
        self.assertNotIn("ABCdefGHIjklMNOpqrSTUvwxYZ_extraSecretToken1234", s_tg)
        self.assertIn("[BOT_TOKEN_REDACTED]", s_tg)

    def test_sanitize_value_dict_recursive(self):
        data = {
            "credentials": {
                "password": "MySuperSecretPassword",
                "api_token": "token_abc_123",
                "normal_field": "hello world"
            },
            "commands": [
                "dotnet run --password SecretPass123.",
                "rtsp://admin:PassWord999@10.0.0.1/stream"
            ]
        }
        sanitized = sanitize_value(data)

        # Ensure all passwords and tokens are redacted
        self.assertNotIn("MySuperSecretPassword", json.dumps(sanitized))
        self.assertNotIn("token_abc_123", json.dumps(sanitized))
        self.assertNotIn("SecretPass123.", json.dumps(sanitized))
        self.assertNotIn("PassWord999", json.dumps(sanitized))

        self.assertEqual(sanitized["credentials"]["password"], "[REDACTED]")
        self.assertEqual(sanitized["credentials"]["api_token"], "[REDACTED]")
        self.assertEqual(sanitized["credentials"]["normal_field"], "hello world")

    def test_software_versions(self):
        versions = self.service.get_software_versions()
        self.assertIn("app", versions)
        self.assertIn("python", versions)
        self.assertIn("ffmpeg", versions)
        self.assertIn("dotnet", versions)
        self.assertTrue(len(versions["python"]["version"]) > 0)

    def test_system_resources(self):
        res = self.service.get_system_resources()
        self.assertIn("os", res)
        self.assertIn("process", res)
        self.assertIn("disk", res)
        self.assertIn("safeEnvironment", res)
        self.assertGreater(res["os"]["cpuCount"], 0)
        self.assertEqual(res["process"]["pid"], os.getpid())

    def test_check_ports(self):
        ports = self.service.check_ports()
        self.assertIn("dashboard", ports)
        self.assertIn("cameras", ports)
        self.assertIn("v380-1", ports["cameras"])
        self.assertIn("okam-3", ports["cameras"])

    def test_bundle_creation_and_zero_credential_leak(self):
        bundle = self.service.create_diagnostic_bundle()
        self.assertTrue(bundle["success"])
        self.assertTrue(os.path.exists(bundle["filePath"]))
        self.assertGreater(bundle["sizeBytes"], 0)
        self.assertTrue(bundle["filename"].endswith(".zip"))

        # Inspect all contents in zip
        with zipfile.ZipFile(bundle["filePath"], "r") as zf:
            names = zf.namelist()
            self.assertIn("manifest.json", names)
            self.assertIn("diagnostics_summary.md", names)
            self.assertIn("system_info.json", names)
            self.assertIn("services_status.json", names)
            self.assertIn("ports_status.json", names)
            self.assertIn("sanitized_config.json", names)
            self.assertIn("recent_errors.json", names)

            # Check zero credentials in every single file
            for fname in names:
                content = zf.read(fname).decode("utf-8")
                self.assertNotIn("SecretPass123.", content, f"Leaked SecretPass123 in {fname}")
                self.assertNotIn("Danendra07.", content, f"Leaked Danendra07. in {fname}")
                self.assertNotIn("ABCdefGHIjklMNOpqrSTUvwxYZ_extraSecretToken1234", content, f"Leaked bot token in {fname}")

    def test_bundle_creation_resilience_when_camera_offline(self):
        # Mock health monitor and supervisor where cameras are offline/failed
        mock_health = MagicMock()
        mock_health.get_all_health.return_value = {
            "v380-1": {
                "status": "OFFLINE",
                "fps": 0.0,
                "failureReason": "TCP Connection refused on port 8080",
                "reconnectCount": 5
            }
        }
        mock_supervisor = MagicMock()
        mock_supervisor.get_status.return_value = {
            "services": {
                "v380-1": {
                    "state": "FAILED",
                    "stateMessage": "Circuit breaker tripped: 5 restarts in 300s",
                    "circuitBreakerTripped": True,
                    "restartCount": 5
                }
            }
        }

        service = CamHubDiagnosticsService(
            lambda: self.config,
            base_dir=self.test_dir,
            health_monitor=mock_health,
            supervisor_manager=mock_supervisor
        )

        # Must succeed without throwing any exceptions
        bundle = service.create_diagnostic_bundle()
        self.assertTrue(bundle["success"])
        self.assertEqual(bundle["manifest"]["overallStatus"], "DEGRADED")
        self.assertGreater(bundle["manifest"]["issueCount"], 0)

    def test_list_and_delete_bundles(self):
        # Create a bundle
        bundle = self.service.create_diagnostic_bundle()
        fname = bundle["filename"]

        bundles = self.service.list_bundles()
        self.assertGreaterEqual(len(bundles), 1)
        self.assertEqual(bundles[0]["filename"], fname)

        # Delete bundle
        ok, msg = self.service.delete_bundle(fname)
        self.assertTrue(ok)
        self.assertFalse(os.path.exists(bundle["filePath"]))

        # Delete invalid filename should fail safely
        bad_ok, _ = self.service.delete_bundle("../evil.zip")
        self.assertFalse(bad_ok)


if __name__ == "__main__":
    unittest.main()

