"""
Unit tests for CamHub PTZ Service & Controller
Tests multi-direction pan/tilt/zoom, step pulses, preset management, and auxiliary controls.
"""

import os
import json
import time
import shutil
import unittest
import tempfile
from unittest.mock import patch, MagicMock

from core.ptz_service import (
    CamHubPTZService,
    VALID_DIRECTIONS,
    VALID_AUX_COMMANDS,
    DEFAULT_PRESETS
)


class TestCamHubPTZService(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.presets_file = os.path.join(self.test_dir, "ptz_presets.json")
        
        self.mock_config = {
            "cameras": [
                {
                    "id": "v380-1",
                    "name": "Camera 1 · Indoor",
                    "port": 8080,
                    "type": "v380"
                },
                {
                    "id": "v380-2",
                    "name": "Camera 2 · Garage",
                    "port": 8081,
                    "type": "v380"
                },
                {
                    "id": "okam-3",
                    "name": "Camera 3 · O-Kam Pro",
                    "port": 8082,
                    "type": "okam"
                }
            ]
        }
        
        self.service = CamHubPTZService(
            config_loader=lambda: self.mock_config,
            presets_file=self.presets_file
        )

    def tearDown(self):
        # Stop any active timers
        with self.service.lock:
            for t in self.service.stop_timers.values():
                t.cancel()
            self.service.stop_timers.clear()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_initial_presets_loaded(self):
        """Verify default presets are loaded when no presets file exists."""
        presets = self.service.get_presets("v380-1")
        self.assertIsInstance(presets, list)
        self.assertEqual(len(presets), 5)
        self.assertEqual(presets[0]["name"], "Preset 1 · Center / Home")
        self.assertTrue(presets[0]["configured"])

    def test_preset_set_and_persistence(self):
        """Verify setting a preset updates memory and saves to file atomically."""
        ok, msg = self.service.preset_set("v380-1", 4, name="Area Khusus")
        self.assertTrue(ok)
        self.assertIn("Saved preset 4", msg)
        
        # Check in-memory
        presets = self.service.get_presets("v380-1")
        p4 = next(p for p in presets if p["id"] == 4)
        self.assertTrue(p4["configured"])
        self.assertEqual(p4["name"], "Area Khusus")
        
        # Check on-disk persistence
        self.assertTrue(os.path.exists(self.presets_file))
        with open(self.presets_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("v380-1", data)
        p4_disk = next(p for p in data["v380-1"] if p["id"] == 4)
        self.assertEqual(p4_disk["name"], "Area Khusus")

    def test_preset_clear(self):
        """Verify clearing a preset resets configured flag."""
        # Set first
        self.service.preset_set("v380-1", 2, name="Pintu Samping")
        # Now clear
        ok, msg = self.service.preset_clear("v380-1", 2)
        self.assertTrue(ok)
        
        presets = self.service.get_presets("v380-1")
        p2 = next(p for p in presets if p["id"] == 2)
        self.assertFalse(p2["configured"])

    def test_direction_validation(self):
        """Verify valid directions pass and invalid directions fail cleanly."""
        for d in VALID_DIRECTIONS:
            # We mock _is_port_listening to return True and mock http call
            with patch.object(self.service, "_is_port_listening", return_value=True), \
                 patch.object(self.service, "_send_http_command", return_value=(True, "OK")), \
                 patch.object(self.service, "_send_onvif_soap", return_value=(True, "OK")):
                ok, msg = self.service.move("v380-1", d)
                self.assertTrue(ok, f"Direction {d} failed: {msg}")

        # Invalid direction
        ok, msg = self.service.move("v380-1", "backflip")
        self.assertFalse(ok)
        self.assertIn("Invalid direction", msg)

    def test_speed_clamping(self):
        """Verify speed is clamped within [0.1, 1.0]."""
        with patch.object(self.service, "_is_port_listening", return_value=True), \
             patch.object(self.service, "_send_http_command", return_value=(True, "OK")):
            self.service.move("v380-1", "up", speed=2.5)
            self.assertEqual(self.service.motion_state["v380-1"]["speed"], 1.0)
            
            self.service.move("v380-1", "up", speed=-0.8)
            self.assertEqual(self.service.motion_state["v380-1"]["speed"], 0.1)

    def test_step_mode_auto_stop(self):
        """Verify step mode schedules an auto-stop timer."""
        with patch.object(self.service, "_is_port_listening", return_value=True), \
             patch.object(self.service, "_send_http_command", return_value=(True, "OK")):
            ok, msg = self.service.move("v380-1", "left", mode="step", duration_ms=100)
            self.assertTrue(ok)
            self.assertIn("v380-1", self.service.stop_timers)
            
            # Wait for auto-stop to trigger (100ms)
            time.sleep(0.2)
            self.assertFalse(self.service.motion_state.get("v380-1", {}).get("is_moving", False))

    def test_auxiliary_commands(self):
        """Verify auxiliary commands dispatch correctly and invalid commands reject."""
        for aux in VALID_AUX_COMMANDS:
            with patch.object(self.service, "_is_port_listening", return_value=True), \
                 patch.object(self.service, "_send_http_command", return_value=(True, "OK")) as mock_http:
                ok, msg = self.service.auxiliary("v380-1", aux)
                self.assertTrue(ok)
                mock_http.assert_called_once()

        # Invalid command
        ok, msg = self.service.auxiliary("v380-1", "disco_mode")
        self.assertFalse(ok)
        self.assertIn("Invalid auxiliary command", msg)

    def test_offline_camera_handling(self):
        """Verify operations on an offline camera fail gracefully with descriptive error."""
        with patch.object(self.service, "_is_port_listening", return_value=False):
            ok, msg = self.service.move("v380-2", "up")
            self.assertFalse(ok)
            self.assertIn("offline", msg.lower())

    def test_get_status_structure(self):
        """Verify get_status returns complete telemetry and capabilities payload."""
        with patch.object(self.service, "_is_port_listening", return_value=True):
            status = self.service.get_status("v380-1")
            self.assertEqual(status["cameraId"], "v380-1")
            self.assertTrue(status["supported"])
            self.assertTrue(status["online"])
            self.assertIn("capabilities", status)
            self.assertTrue(status["capabilities"]["panTilt"])
            self.assertTrue(status["capabilities"]["presets"])
            self.assertIn("presets", status)
            self.assertEqual(len(status["presets"]), 5)


if __name__ == "__main__":
    unittest.main()

