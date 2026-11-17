"""
CamHub Auto-Recovery & Process Supervisor
Provides safe, controlled process supervision on Windows for camera decoders and adapters.
Prevents orphan FFmpeg/.NET processes, implements exponential backoff, circuit breaking,
and state machine (STARTING, RUNNING, STOPPING, RESTARTING, FAILED).
"""

import os
import sys
import time
import json
import socket
import threading
import subprocess
from enum import Enum
from urllib.request import Request, urlopen
try:
    from core.health_monitor import sanitize_sensitive_data, is_port_listening
except ImportError:
    from .health_monitor import sanitize_sensitive_data, is_port_listening

# CamHUB project root directory (parent of core/)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

class SupervisorState(str, Enum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    RESTARTING = "RESTARTING"
    FAILED = "FAILED"

DEFAULT_SUPERVISOR_CONFIG = {
    "enabled": True,
    "maxRestartAttempts": 5,
    "windowSeconds": 300,
    "initialBackoffSeconds": 2.0,
    "maxBackoffSeconds": 30.0,
    "backoffMultiplier": 2.0,
    "unhealthyThresholdSeconds": 25.0,
    "stableDurationToResetAttempts": 30.0
}

def kill_process_tree(pid: int, timeout: float = 4.0):
    """Forcefully and cleanly terminate a Windows process tree (parent and all children like ffmpeg)."""
    if not pid or pid <= 0:
        return
    try:
        # /F = forcefully, /T = tree kill
        subprocess.run(
            f"taskkill /F /T /PID {pid}",
            shell=True,
            capture_output=True,
            timeout=timeout
        )
    except:
        pass

def kill_port_owner(port: int, timeout: float = 4.0):
    """Terminate any process holding a specific TCP port on Windows."""
    try:
        cmd = f'powershell -NoProfile -Command "(Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue).OwningProcess"'
        out = subprocess.check_output(cmd, shell=True, text=True, timeout=timeout).strip()
        pids = set(out.split())
        for pid_str in pids:
            if pid_str.isdigit():
                pid = int(pid_str)
                if pid > 0:
                    kill_process_tree(pid, timeout=timeout)
    except:
        pass

class CameraSupervisor:
    """Manages the process lifecycle, restarts, and backoff for a single camera."""

    def __init__(self, camera_id: str, name: str, port: int, cmd: str, config: dict = None, cam_type: str = "v380", shared_port: bool = False):
        self.camera_id = camera_id
        self.name = name
        self.port = port
        self.cmd = cmd
        self.cam_type = cam_type
        self.shared_port = shared_port
        self.config = dict(DEFAULT_SUPERVISOR_CONFIG)
        if config:
            self.config.update(config)

        self.state = SupervisorState.STOPPED
        self.process = None
        self.pid = None
        self.lock = threading.Lock()

        # Supervision metrics
        self.restart_history = []  # list of float timestamps
        self.last_restart_time = 0.0
        self.last_exit_code = None
        self.last_failure_reason = ""
        self.state_entered_at = time.time()
        self.healthy_since = None
        self.unhealthy_since = None
        self.recovery_attempts = 0
        self.current_backoff = self.config.get("initialBackoffSeconds", 2.0)
        self.next_restart_allowed_at = 0.0

    def _set_state(self, new_state: SupervisorState, reason: str = ""):
        if self.state != new_state:
            self.state = new_state
            self.state_entered_at = time.time()
            if reason:
                self.last_failure_reason = reason

    def _adapter_worker_action(self, action: str) -> bool:
        """Send start/stop/restart action to a specific worker inside the multi-camera adapter."""
        try:
            url = f"http://127.0.0.1:{self.port}/api/cameras/{self.camera_id}/{action}"
            req = Request(url, method="POST", headers={"User-Agent": "CamHub-Supervisor/1.0"})
            with urlopen(req, timeout=1.5) as resp:
                return resp.status == 200
        except Exception:
            return False

    def start(self, reason: str = "manual_start") -> tuple[bool, str]:
        with self.lock:
            if self.state in (SupervisorState.RUNNING, SupervisorState.STARTING):
                if self.process and self.process.poll() is None:
                    return True, f"Camera '{self.camera_id}' is already running (PID {self.pid})"
                if self.shared_port and is_port_listening(self.port, timeout=0.3):
                    self._adapter_worker_action("start")
                    self._set_state(SupervisorState.RUNNING, "Adapter worker active")
                    return True, f"Camera '{self.camera_id}' worker is active on port {self.port}"

            # If failed, require explicit reset or manual restart
            if self.state == SupervisorState.FAILED and reason != "manual_start" and reason != "user_reset":
                return False, f"Camera '{self.camera_id}' in FAILED state. Reset circuit breaker before restarting."

            self._set_state(SupervisorState.STARTING, reason)

            # For shared-port multi-camera adapter (O-Kam), if the adapter server is already listening,
            # do NOT kill the port; just ensure this camera's stream worker is started!
            if self.shared_port and is_port_listening(self.port, timeout=0.3):
                self._adapter_worker_action("start")
                self._set_state(SupervisorState.RUNNING, "Attached to running multi-camera adapter")
                return True, f"Started camera '{self.camera_id}' worker on running adapter (port {self.port})"

            # Ensure port is clean before launching
            if is_port_listening(self.port, timeout=0.3):
                kill_port_owner(self.port)
                time.sleep(0.4)

            try:
                clean_cmd = sanitize_sensitive_data(self.cmd)
                print(f"[SUPERVISOR] Starting '{self.camera_id}' on port {self.port} ({clean_cmd[:70]}...)", flush=True)

                self.process = subprocess.Popen(
                    self.cmd,
                    shell=True,
                    cwd=BASE_DIR,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                )
                self.pid = self.process.pid
                if self.shared_port:
                    # Wait briefly for the multi-camera adapter HTTP server to bind the shared port
                    # so subsequent sibling camera starts attach to it instead of respawning it
                    for _ in range(15):
                        if is_port_listening(self.port, timeout=0.2):
                            break
                        time.sleep(0.15)
                self._set_state(SupervisorState.RUNNING, "Started successfully")
                return True, f"Started camera '{self.camera_id}' (PID {self.pid})"
            except Exception as e:
                self._set_state(SupervisorState.FAILED, str(e))
                return False, f"Failed to start camera '{self.camera_id}': {e}"

    def stop(self, reason: str = "manual_stop", force_kill_port: bool = False) -> tuple[bool, str]:
        with self.lock:
            self._set_state(SupervisorState.STOPPING, reason)

            # If stopping a single worker on a shared multi-camera adapter (and not shutting down all),
            # stop only this camera's worker via HTTP so sibling cameras continue streaming!
            if self.shared_port and not force_kill_port and reason not in ("manual_stop_all", "server_shutdown"):
                if is_port_listening(self.port, timeout=0.3):
                    self._adapter_worker_action("stop")
                    self._set_state(SupervisorState.STOPPED, reason)
                    return True, f"Stopped camera '{self.camera_id}' worker on port {self.port}"

            if self.process:
                pid = self.process.pid
                kill_process_tree(pid)
                try:
                    self.process.terminate()
                except:
                    pass
                self.process = None
                self.pid = None

            # Always ensure port is freed when stopping non-shared or force_kill_port
            if not self.shared_port or force_kill_port or reason in ("manual_stop_all", "server_shutdown"):
                kill_port_owner(self.port)

            self._set_state(SupervisorState.STOPPED, reason)
            return True, f"Stopped camera '{self.camera_id}'"

    def restart(self, reason: str = "manual_restart") -> tuple[bool, str]:
        now = time.time()
        with self.lock:
            self._set_state(SupervisorState.RESTARTING, reason)
            self.restart_history.append(now)
            self.last_restart_time = now

            if self.shared_port and is_port_listening(self.port, timeout=0.3):
                if self._adapter_worker_action("restart"):
                    self._set_state(SupervisorState.RUNNING, "Restarted camera worker")
                    return True, f"Restarted camera '{self.camera_id}' worker on port {self.port}"

        self.stop(reason=reason)
        time.sleep(0.8)
        return self.start(reason=reason)

    def reset_circuit_breaker(self) -> tuple[bool, str]:
        with self.lock:
            self.recovery_attempts = 0
            self.restart_history.clear()
            self.current_backoff = self.config.get("initialBackoffSeconds", 2.0)
            self.next_restart_allowed_at = 0.0
            self._set_state(SupervisorState.STOPPED, "Circuit breaker reset by user")
            return True, f"Reset circuit breaker for camera '{self.camera_id}'"

    def check_health_and_supervise(self, health_data: dict, now: float = None):
        """Called by background supervision loop to detect crashes, zombie streams, and manage auto-recovery."""
        if now is None:
            now = time.time()

        if not self.config.get("enabled", True):
            return

        with self.lock:
            # Only supervise RUNNING or STARTING processes
            if self.state not in (SupervisorState.RUNNING, SupervisorState.STARTING):
                return

            # 1. Process Exit Detection
            if self.process is not None:
                ret = self.process.poll()
                if ret is not None:
                    # Process died!
                    self.last_exit_code = ret
                    self.process = None
                    self.pid = None
                    self._trigger_auto_recovery(f"Process crashed with exit code {ret}", now)
                    return

            # 2. Stream Health Inspection (Integration with Smart Health Monitor)
            if health_data:
                h_status = health_data.get("status")
                h_reason = health_data.get("reason", "")
                checks = health_data.get("checks", {})

                if h_status == "HEALTHY":
                    if self.healthy_since is None:
                        self.healthy_since = now
                    self.unhealthy_since = None

                    # If camera has sustained healthy state, reset backoff and attempt counters
                    stable_window = self.config.get("stableDurationToResetAttempts", 30.0)
                    if (now - self.healthy_since) >= stable_window:
                        self.recovery_attempts = 0
                        self.current_backoff = self.config.get("initialBackoffSeconds", 2.0)
                        # Clean old restart history outside window
                        win = self.config.get("windowSeconds", 300)
                        self.restart_history = [t for t in self.restart_history if now - t < win]
                elif h_status in ("OFFLINE", "DEGRADED"):
                    self.healthy_since = None
                    if self.unhealthy_since is None:
                        self.unhealthy_since = now

                    unhealthy_dur = now - self.unhealthy_since
                    thresh = self.config.get("unhealthyThresholdSeconds", 25.0)

                    # Trigger recovery if stream is stalled/frozen or port closed for longer than threshold
                    is_critical = (h_status == "OFFLINE") or checks.get("streamFrozen") or not checks.get("portListening")
                    if is_critical and unhealthy_dur >= thresh:
                        self._trigger_auto_recovery(f"Stream unhealthy for {round(unhealthy_dur, 1)}s: {h_reason}", now)
                        return

    def _trigger_auto_recovery(self, reason: str, now: float):
        """Evaluate circuit breaker, backoff, and perform auto-restart if safe."""
        win = self.config.get("windowSeconds", 300)
        max_attempts = self.config.get("maxRestartAttempts", 5)

        # Filter recent restarts in the rolling window
        self.restart_history = [t for t in self.restart_history if now - t < win]

        if len(self.restart_history) >= max_attempts:
            # Trip the circuit breaker!
            msg = f"Circuit breaker tripped: {len(self.restart_history)} restarts in {win}s. Waiting for manual intervention."
            print(f"[SUPERVISOR] Camera '{self.camera_id}' -> FAILED: {msg}", flush=True)
            self._set_state(SupervisorState.FAILED, msg)
            if self.process:
                kill_process_tree(self.process.pid)
                self.process = None
            kill_port_owner(self.port)
            return

        # Check backoff cooldown
        if now < self.next_restart_allowed_at:
            # Still in backoff waiting period
            return

        self.recovery_attempts += 1
        backoff = min(
            self.config.get("maxBackoffSeconds", 30.0),
            self.config.get("initialBackoffSeconds", 2.0) * (self.config.get("backoffMultiplier", 2.0) ** (self.recovery_attempts - 1))
        )
        self.current_backoff = backoff
        self.next_restart_allowed_at = now + backoff

        print(f"[SUPERVISOR] Auto-recovering '{self.camera_id}' (attempt {self.recovery_attempts}/{max_attempts}, backoff {backoff}s). Reason: {reason}", flush=True)

        # Execute safe restart in separate worker thread to prevent blocking supervision loop
        threading.Thread(target=self._execute_auto_restart, args=(reason,), daemon=True).start()

    def _execute_auto_restart(self, reason: str):
        if self.shared_port and is_port_listening(self.port, timeout=0.3):
            if self._adapter_worker_action("restart"):
                with self.lock:
                    self._set_state(SupervisorState.RUNNING, f"auto_recovery_worker: {reason}")
                return
        self.stop(reason=f"auto_restart_stop: {reason}")
        time.sleep(1.0)
        self.start(reason=f"auto_recovery: {reason}")

    def to_dict(self) -> dict:
        now = time.time()
        win = self.config.get("windowSeconds", 300)
        recent_count = sum(1 for t in self.restart_history if now - t < win)
        state_dur = round(now - self.state_entered_at, 1)

        is_running = False
        if self.process is not None:
            is_running = self.process.poll() is None
        elif self.state == SupervisorState.RUNNING or self.shared_port:
            is_running = is_port_listening(self.port, timeout=0.2) and self.state != SupervisorState.STOPPED

        return {
            "id": self.camera_id,
            "name": self.name,
            "port": self.port,
            "state": self.state.value,
            "running": is_running,
            "pid": self.pid,
            "lastExitCode": self.last_exit_code,
            "lastRestartTime": int(self.last_restart_time * 1000) if self.last_restart_time > 0 else None,
            "stateDurationSeconds": state_dur,
            "recentRestartCount": recent_count,
            "maxRestartAttempts": self.config.get("maxRestartAttempts", 5),
            "circuitBreakerTripped": self.state == SupervisorState.FAILED,
            "currentBackoffSeconds": round(self.current_backoff, 1),
            "nextAllowedRestartIn": max(0.0, round(self.next_restart_allowed_at - now, 1)),
            "reason": self.last_failure_reason
        }


class AutoRecoveryManager:
    """Fleet-wide process supervisor & auto-recovery manager."""

    def __init__(self, config_provider, health_monitor=None):
        self.config_provider = config_provider
        self.health_monitor = health_monitor
        self.supervisors = {}
        self.aliases = {}
        self.lock = threading.RLock()
        self.running = False
        self.worker_thread = None

    def _resolve_sup(self, cid: str):
        with self.lock:
            resolved = self.aliases.get(cid, cid)
            return self.supervisors.get(resolved)

    def start(self):
        with self.lock:
            if self.running:
                return
            self.running = True
            self._sync_supervisors()
            self.worker_thread = threading.Thread(target=self._run_loop, daemon=True, name="AutoRecoveryLoop")
            self.worker_thread.start()
            print("[SUPERVISOR] Auto-Recovery Manager started.", flush=True)

    def stop(self):
        with self.lock:
            self.running = False

    def shutdown_all(self):
        """Cleanly terminate all managed child processes when CamHUB server shuts down."""
        print("[SUPERVISOR] Cleaning up all managed camera process trees...", flush=True)
        with self.lock:
            sups = list(self.supervisors.values())
        for s in sups:
            try:
                s.stop(reason="server_shutdown", force_kill_port=True)
            except:
                pass
        print("[SUPERVISOR] All child processes cleanly terminated.", flush=True)

    def _sync_supervisors(self):
        cfg = self.config_provider()
        global_rec_cfg = cfg.get("autoRecovery", {})
        cameras = cfg.get("cameras", [])

        # Count how many cameras share each port
        port_counts = {}
        for cam in cameras:
            p = cam.get("port")
            if p:
                port_counts[p] = port_counts.get(p, 0) + 1

        with self.lock:
            active_ids = set()
            self.aliases.clear()
            for cam in cameras:
                cid = cam.get("id")
                port = cam.get("port")
                name = cam.get("name", cid)
                cmd = cam.get("cmd", "")
                cam_type = cam.get("type", "v380")
                shared_port = (port_counts.get(port, 0) > 1) or (cam_type == "okam")
                active_ids.add(cid)

                for al in cam.get("aliases", []):
                    self.aliases[al] = cid

                merged_cfg = dict(DEFAULT_SUPERVISOR_CONFIG)
                merged_cfg.update(global_rec_cfg)
                if "autoRecovery" in cam:
                    merged_cfg.update(cam["autoRecovery"])

                if cid not in self.supervisors:
                    self.supervisors[cid] = CameraSupervisor(cid, name, port, cmd, merged_cfg, cam_type=cam_type, shared_port=shared_port)
                else:
                    self.supervisors[cid].port = port
                    self.supervisors[cid].cmd = cmd
                    self.supervisors[cid].config = merged_cfg
                    self.supervisors[cid].cam_type = cam_type
                    self.supervisors[cid].shared_port = shared_port

            to_remove = [cid for cid in self.supervisors if cid not in active_ids]
            for cid in to_remove:
                self.supervisors[cid].stop("camera_removed")
                del self.supervisors[cid]

    def _run_loop(self):
        while self.running:
            try:
                self._sync_supervisors()
                with self.lock:
                    sups = list(self.supervisors.values())

                now = time.time()
                for sup in sups:
                    h_info = None
                    if self.health_monitor:
                        h_info = self.health_monitor.get_camera_health(sup.camera_id)
                    sup.check_health_and_supervise(h_info, now=now)

                time.sleep(1.5)
            except Exception as e:
                time.sleep(2.0)

    def get_status(self) -> dict:
        with self.lock:
            sups = [s.to_dict() for s in self.supervisors.values()]
            aliases_copy = dict(self.aliases)

        services_map = {s["id"]: s for s in sups}
        for al, target_id in aliases_copy.items():
            if target_id in services_map and al not in services_map:
                services_map[al] = services_map[target_id]

        all_running = all(s["running"] for s in sups) and len(sups) > 0
        any_running = any(s["running"] for s in sups)
        any_failed = any(s["circuitBreakerTripped"] for s in sups)

        return {
            "services": services_map,
            "allRunning": all_running,
            "anyRunning": any_running,
            "anyFailed": any_failed,
            "totalCameras": len(sups)
        }

    def start_camera(self, cid: str) -> tuple[bool, str]:
        sup = self._resolve_sup(cid)
        if not sup:
            return False, f"Camera '{cid}' not found"
        return sup.start("manual_start")

    def stop_camera(self, cid: str) -> tuple[bool, str]:
        sup = self._resolve_sup(cid)
        if not sup:
            return False, f"Camera '{cid}' not found"
        return sup.stop("manual_stop")

    def restart_camera(self, cid: str) -> tuple[bool, str]:
        sup = self._resolve_sup(cid)
        if not sup:
            return False, f"Camera '{cid}' not found"
        return sup.restart("manual_restart")

    def reset_camera(self, cid: str) -> tuple[bool, str]:
        sup = self._resolve_sup(cid)
        if not sup:
            return False, f"Camera '{cid}' not found"
        return sup.reset_circuit_breaker()

    def start_all(self) -> dict:
        with self.lock:
            sups = list(self.supervisors.values())
        results = {}
        for s in sups:
            ok, msg = s.start("manual_start_all")
            results[s.camera_id] = {"success": ok, "message": msg}
            time.sleep(0.35)
        return results

    def stop_all(self) -> dict:
        with self.lock:
            sups = list(self.supervisors.values())
        results = {}
        for s in sups:
            ok, msg = s.stop("manual_stop_all", force_kill_port=True)
            results[s.camera_id] = {"success": ok, "message": msg}
        return results

    def restart_all(self) -> dict:
        self.stop_all()
        time.sleep(1.0)
        return self.start_all()

