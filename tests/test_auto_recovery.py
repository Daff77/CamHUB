"""
Unit tests for CamHub Auto-Recovery & Process Supervisor
Tests state machine transitions: STOPPED, STARTING, RUNNING, STOPPING, RESTARTING, FAILED
Tests crash detection, exponential backoff, circuit breaking, stable reset, and camera isolation.
"""

import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

# Ensure root directory is in sys.path
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from core.auto_recovery import (
    SupervisorState,
    CameraSupervisor,
    AutoRecoveryManager,
    DEFAULT_SUPERVISOR_CONFIG
)

class TestAutoRecovery(unittest.TestCase):

    def setUp(self):
        self.config = dict(DEFAULT_SUPERVISOR_CONFIG)
        self.config.update({
            "maxRestartAttempts": 3,
            "windowSeconds": 60,
            "initialBackoffSeconds": 1.0,
            "maxBackoffSeconds": 8.0,
            "backoffMultiplier": 2.0,
            "unhealthyThresholdSeconds": 5.0,
            "stableDurationToResetAttempts": 10.0
        })
        self.sup = CameraSupervisor("cam-test-1", "Test Indoor", 8080, "dummy-cmd", self.config)

    def test_initial_state_is_stopped(self):
        self.assertEqual(self.sup.state, SupervisorState.STOPPED)
        d = self.sup.to_dict()
        self.assertEqual(d["state"], "STOPPED")
        self.assertFalse(d["circuitBreakerTripped"])

    def test_crash_detection_triggers_recovery(self):
        now = 1000.0
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1  # Process crashed with exit code 1
        mock_proc.pid = 9999

        self.sup.process = mock_proc
        self.sup.pid = 9999
        self.sup.state = SupervisorState.RUNNING

        with patch.object(self.sup, "_trigger_auto_recovery") as mock_rec:
            self.sup.check_health_and_supervise(None, now=now)
            mock_rec.assert_called_once()
            self.assertEqual(self.sup.last_exit_code, 1)

    def test_exponential_backoff_calculation(self):
        now = 1000.0
        # Trigger 1
        self.sup._trigger_auto_recovery("Test failure 1", now)
        self.assertEqual(self.sup.recovery_attempts, 1)
        self.assertEqual(self.sup.current_backoff, 1.0)
        self.assertEqual(self.sup.next_restart_allowed_at, now + 1.0)

        # Trigger 2 (after backoff elapsed)
        now += 2.0
        self.sup._trigger_auto_recovery("Test failure 2", now)
        self.assertEqual(self.sup.recovery_attempts, 2)
        self.assertEqual(self.sup.current_backoff, 2.0)
        self.assertEqual(self.sup.next_restart_allowed_at, now + 2.0)

        # Trigger 3 (after backoff elapsed)
        now += 3.0
        self.sup._trigger_auto_recovery("Test failure 3", now)
        self.assertEqual(self.sup.recovery_attempts, 3)
        self.assertEqual(self.sup.current_backoff, 4.0)

    def test_circuit_breaker_trips_to_failed(self):
        """After maxRestartAttempts (3) within window, state must transition to FAILED and stop restarts."""
        now = 1000.0
        # Attempt 1
        self.sup.restart_history.append(now)
        # Attempt 2
        self.sup.restart_history.append(now + 2)
        # Attempt 3
        self.sup.restart_history.append(now + 5)

        # 4th failure occurs within 60s window
        now += 8.0
        self.sup._trigger_auto_recovery("Repeated failure", now)

        self.assertEqual(self.sup.state, SupervisorState.FAILED)
        self.assertTrue(self.sup.to_dict()["circuitBreakerTripped"])
        self.assertIn("Circuit breaker tripped", self.sup.last_failure_reason)

    def test_manual_reset_circuit_breaker(self):
        self.sup.state = SupervisorState.FAILED
        self.sup.recovery_attempts = 3
        self.sup.restart_history = [100.0, 102.0, 104.0]

        ok, msg = self.sup.reset_circuit_breaker()
        self.assertTrue(ok)
        self.assertEqual(self.sup.state, SupervisorState.STOPPED)
        self.assertEqual(self.sup.recovery_attempts, 0)
        self.assertEqual(len(self.sup.restart_history), 0)

    def test_stable_healthy_resets_backoff_and_attempts(self):
        now = 1000.0
        self.sup.state = SupervisorState.RUNNING
        self.sup.recovery_attempts = 2
        self.sup.current_backoff = 4.0

        # Health report HEALTHY
        h_info = {"status": "HEALTHY", "reason": "OK"}
        self.sup.check_health_and_supervise(h_info, now=now)
        self.assertEqual(self.sup.healthy_since, now)

        # After stableDurationToResetAttempts (10.0s):
        now += 11.0
        self.sup.check_health_and_supervise(h_info, now=now)
        self.assertEqual(self.sup.recovery_attempts, 0)
        self.assertEqual(self.sup.current_backoff, 1.0)

    def test_camera_isolation(self):
        """Camera A crashing does not trigger or affect Camera B."""
        def dummy_cfg():
            return {
                "cameras": [
                    {"id": "cam-a", "name": "Cam A", "port": 8080, "cmd": "cmd-a"},
                    {"id": "cam-b", "name": "Cam B", "port": 8081, "cmd": "cmd-b"}
                ]
            }

        mgr = AutoRecoveryManager(dummy_cfg)
        mgr._sync_supervisors()

        sup_a = mgr.supervisors["cam-a"]
        sup_b = mgr.supervisors["cam-b"]

        sup_a.state = SupervisorState.RUNNING
        sup_b.state = SupervisorState.RUNNING

        # Simulate crash on Cam A only
        mock_a = MagicMock()
        mock_a.poll.return_value = 137
        sup_a.process = mock_a

        mock_b = MagicMock()
        mock_b.poll.return_value = None  # Cam B still healthy
        sup_b.process = mock_b

        with patch.object(sup_a, "_trigger_auto_recovery") as mock_rec_a, \
             patch.object(sup_b, "_trigger_auto_recovery") as mock_rec_b:
            sup_a.check_health_and_supervise(None, now=1000.0)
            sup_b.check_health_and_supervise(None, now=1000.0)

            mock_rec_a.assert_called_once()
            mock_rec_b.assert_not_called()
            self.assertEqual(sup_b.state, SupervisorState.RUNNING)


if __name__ == "__main__":
    unittest.main()

