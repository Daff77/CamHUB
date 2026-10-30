"""
CamHUB Diagnostics & Export Report Service
Provides one-click system troubleshooting bundles, sanitized configurations,
health telemetry, port connectivity verification, error aggregation, and ZIP exports.
"""

import os
import sys
import json
import time
import socket
import platform
import subprocess
import zipfile
import hashlib
import re
import shutil
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger("CamHub.Diagnostics")

# Whitelist of safe commands to check tool versions
WHITELISTED_COMMANDS = {
    "ffmpeg": ["ffmpeg", "-version"],
    "dotnet": ["dotnet", "--version"]
}

# Whitelist of safe environment variables (avoid leaking tokens/secrets)
SAFE_ENV_VARS = [
    "OS", "PROCESSOR_ARCHITECTURE", "PROCESSOR_IDENTIFIER",
    "NUMBER_OF_PROCESSORS", "PYTHONPATH", "TEMP", "TMP", "LANG"
]

# Sensitive keys to redact from configuration dictionaries
SENSITIVE_KEY_PATTERNS = [
    r"pass", r"pwd", r"secret", r"token", r"cred", r"auth", r"key"
]

def sanitize_value(val: Any) -> Any:
    """Recursively sanitize sensitive credentials from any data structure."""
    if isinstance(val, dict):
        sanitized = {}
        for k, v in val.items():
            k_lower = str(k).lower()
            if any(re.search(pat, k_lower) for pat in SENSITIVE_KEY_PATTERNS):
                if isinstance(v, (dict, list)):
                    sanitized[k] = sanitize_value(v)
                else:
                    sanitized[k] = "[REDACTED]"
            else:
                sanitized[k] = sanitize_value(v)
        return sanitized
    elif isinstance(val, list):
        return [sanitize_value(item) for item in val]
    elif isinstance(val, str):
        return sanitize_string(val)
    return val

def sanitize_string(text: str) -> str:
    """Mask URLs with credentials, CLI password flags, and bot tokens."""
    if not text:
        return ""
    # Mask URL credentials: http://user:pass@host -> http://user:***@host
    text = re.sub(r'://([^:]+):([^@]+)@', r'://\1:***@', text)
    # Mask CLI arguments: --password Secret123 -> --password [REDACTED]
    text = re.sub(r'(--password\s+)[^\s]+', r'\1[REDACTED]', text, flags=re.IGNORECASE)
    # Mask username parameters if desired or keep username, but always mask password
    text = re.sub(r'(-p\s+)[^\s]+', r'\1[REDACTED]', text)
    # Mask Telegram bot tokens: 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11 -> [BOT_TOKEN_REDACTED]
    text = re.sub(r'\b\d{8,11}:[A-Za-z0-9_-]{20,50}\b', '[BOT_TOKEN_REDACTED]', text)
    # Mask potential Bearer tokens
    text = re.sub(r'(Bearer\s+)[A-Za-z0-9_\-\.]{20,}', r'\1[REDACTED]', text, flags=re.IGNORECASE)
    return text

def test_tcp_port(host: str, port: int, timeout: float = 0.5) -> Tuple[bool, float, Optional[str]]:
    """Test TCP port availability with latency measurement."""
    start = time.perf_counter()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        sock.close()
        if result == 0:
            return True, elapsed_ms, None
        else:
            return False, elapsed_ms, f"Port closed (errno: {result})"
    except Exception as e:
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        return False, elapsed_ms, str(e)


class CamHubDiagnosticsService:
    """
    Central service for gathering diagnostic data, executing port health checks,
    aggregating error logs, and creating secure exportable diagnostic bundles.
    """

    def __init__(self, config_provider, base_dir: str = None,
                 health_monitor=None, supervisor_manager=None,
                 recording_manager=None, motion_service=None,
                 storage_manager=None, notification_center=None):
        self.config_provider = config_provider
        self.base_dir = base_dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.diagnostics_dir = os.path.join(self.base_dir, "diagnostics")
        os.makedirs(self.diagnostics_dir, exist_ok=True)

        self.health_monitor = health_monitor
        self.supervisor_manager = supervisor_manager
        self.recording_manager = recording_manager
        self.motion_service = motion_service
        self.storage_manager = storage_manager
        self.notification_center = notification_center

        self.recent_logs: List[str] = []
        self._max_recent_logs = 500
        self._lock = None

    def log_event(self, message: str, level: str = "INFO"):
        """Record a timestamped log event in the in-memory ring buffer."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = f"[{timestamp}] [{level.upper()}] {sanitize_string(message)}"
        self.recent_logs.append(entry)
        if len(self.recent_logs) > self._max_recent_logs:
            self.recent_logs.pop(0)

    def get_software_versions(self) -> Dict[str, Any]:
        """Query and return software environment versions."""
        versions = {
            "app": "CamHUB 1.0.0",
            "python": {
                "version": sys.version.split()[0],
                "full": sys.version,
                "implementation": platform.python_implementation(),
                "compiler": platform.python_compiler()
            },
            "ffmpeg": {"installed": False, "version": "Not found", "error": None},
            "dotnet": {"installed": False, "version": "Not found", "error": None}
        }

        # Check FFmpeg safely
        try:
            res = subprocess.run(
                WHITELISTED_COMMANDS["ffmpeg"],
                capture_output=True, text=True, timeout=3.0
            )
            if res.returncode == 0 and res.stdout:
                first_line = res.stdout.splitlines()[0].strip()
                versions["ffmpeg"] = {
                    "installed": True,
                    "version": first_line,
                    "error": None
                }
            else:
                versions["ffmpeg"]["error"] = f"Exit code {res.returncode}"
        except Exception as e:
            versions["ffmpeg"]["error"] = str(e)

        # Check .NET safely
        try:
            res = subprocess.run(
                WHITELISTED_COMMANDS["dotnet"],
                capture_output=True, text=True, timeout=3.0
            )
            if res.returncode == 0 and res.stdout:
                versions["dotnet"] = {
                    "installed": True,
                    "version": res.stdout.strip(),
                    "error": None
                }
            else:
                versions["dotnet"]["error"] = f"Exit code {res.returncode}"
        except Exception as e:
            versions["dotnet"]["error"] = str(e)

        return versions

    def get_system_resources(self) -> Dict[str, Any]:
        """Collect host system architecture, platform, and disk storage info."""
        res = {
            "os": {
                "system": platform.system(),
                "release": platform.release(),
                "version": platform.version(),
                "platform": platform.platform(),
                "machine": platform.machine(),
                "processor": platform.processor(),
                "cpuCount": os.cpu_count() or 1
            },
            "process": {
                "pid": os.getpid(),
                "cwd": self.base_dir,
                "pythonExecutable": sys.executable
            },
            "disk": {},
            "safeEnvironment": {}
        }

        # Disk space of base directory
        try:
            du = shutil.disk_usage(self.base_dir)
            res["disk"] = {
                "totalBytes": du.total,
                "usedBytes": du.used,
                "freeBytes": du.free,
                "totalGb": round(du.total / (1024**3), 2),
                "freeGb": round(du.free / (1024**3), 2),
                "usedPercent": round((du.used / du.total) * 100, 1)
            }
        except Exception as e:
            res["disk"] = {"error": str(e)}

        # Safe environment variables
        for var in SAFE_ENV_VARS:
            val = os.environ.get(var)
            if val is not None:
                res["safeEnvironment"][var] = sanitize_string(val)

        return res

    def check_ports(self) -> Dict[str, Any]:
        """Perform TCP connection verification across dashboard, HTTP ports, and RTSP ports."""
        config = self.config_provider() or {}
        cameras = config.get("cameras", [])
        ports_report = {
            "timestamp": datetime.now().isoformat(),
            "dashboard": {},
            "cameras": {}
        }

        # Test Dashboard Port (typically 3000)
        open_3000, rtt_3000, err_3000 = test_tcp_port("127.0.0.1", 3000, timeout=0.3)
        ports_report["dashboard"] = {
            "port": 3000,
            "status": "OPEN" if open_3000 else "CLOSED",
            "latencyMs": rtt_3000,
            "error": err_3000
        }

        # Test each camera ports concurrently or with 0.3s timeout
        for cam in cameras:
            cid = cam.get("id")
            cname = cam.get("name", cid)
            http_port = cam.get("port")
            rtsp_port = cam.get("rtspPort")

            cam_entry = {
                "id": cid,
                "name": cname,
                "http": None,
                "rtsp": None
            }

            if http_port:
                h_open, h_rtt, h_err = test_tcp_port("127.0.0.1", int(http_port), timeout=0.3)
                cam_entry["http"] = {
                    "port": http_port,
                    "status": "OPEN" if h_open else "CLOSED",
                    "latencyMs": h_rtt,
                    "error": h_err
                }

            if rtsp_port:
                r_open, r_rtt, r_err = test_tcp_port("127.0.0.1", int(rtsp_port), timeout=0.3)
                cam_entry["rtsp"] = {
                    "port": rtsp_port,
                    "status": "OPEN" if r_open else "CLOSED",
                    "latencyMs": r_rtt,
                    "error": r_err
                }

            ports_report["cameras"][cid] = cam_entry

        return ports_report

    def get_services_telemetry(self) -> Dict[str, Any]:
        """Aggregate health, supervisor, recording, motion, AI, and storage states."""
        telemetry = {
            "timestamp": datetime.now().isoformat(),
            "supervisors": {},
            "health": {},
            "recording": {},
            "motionAndAI": {},
            "storage": {},
            "notifications": {}
        }

        if self.supervisor_manager:
            try:
                telemetry["supervisors"] = self.supervisor_manager.get_status()
            except Exception as e:
                telemetry["supervisors"] = {"error": str(e)}

        if self.health_monitor:
            try:
                telemetry["health"] = self.health_monitor.get_all_health()
            except Exception as e:
                telemetry["health"] = {"error": str(e)}

        if self.recording_manager:
            try:
                telemetry["recording"] = self.recording_manager.get_storage_status()
            except Exception as e:
                telemetry["recording"] = {"error": str(e)}

        if self.motion_service:
            try:
                telemetry["motionAndAI"] = self.motion_service.get_stats()
            except Exception as e:
                telemetry["motionAndAI"] = {"error": str(e)}

        if self.storage_manager:
            try:
                telemetry["storage"] = self.storage_manager.get_storage_overview()
            except Exception as e:
                telemetry["storage"] = {"error": str(e)}

        if self.notification_center:
            try:
                telemetry["notifications"] = self.notification_center.get_stats()
            except Exception as e:
                telemetry["notifications"] = {"error": str(e)}

        return telemetry

    def get_recent_errors(self) -> Dict[str, Any]:
        """Compile and summarize recent errors across all CamHUB subsystems."""
        errors_summary = {
            "timestamp": datetime.now().isoformat(),
            "totalErrorCount": 0,
            "offlineCameras": [],
            "circuitBreakers": [],
            "storageWarnings": [],
            "healthFailures": [],
            "recentAlerts": []
        }

        # Check offline cameras and circuit breakers from supervisors
        if self.supervisor_manager:
            try:
                status = self.supervisor_manager.get_status()
                for cid, s_info in status.get("services", {}).items():
                    if s_info.get("state") in ("FAILED", "STOPPED"):
                        errors_summary["offlineCameras"].append({
                            "cameraId": cid,
                            "state": s_info.get("state"),
                            "message": s_info.get("stateMessage"),
                            "restartCount": s_info.get("restartCount")
                        })
                    if s_info.get("circuitBreakerTripped"):
                        errors_summary["circuitBreakers"].append({
                            "cameraId": cid,
                            "restarts": s_info.get("restartCount"),
                            "reason": s_info.get("stateMessage")
                        })
            except Exception as e:
                logger.error("Error inspecting supervisor status: %s", e)

        # Check health failures
        if self.health_monitor:
            try:
                health = self.health_monitor.get_all_health()
                for cid, h in health.items():
                    if h.get("status") in ("OFFLINE", "DEGRADED"):
                        errors_summary["healthFailures"].append({
                            "cameraId": cid,
                            "status": h.get("status"),
                            "fps": h.get("fps"),
                            "reason": h.get("failureReason"),
                            "reconnectCount": h.get("reconnectCount"),
                            "isFrozen": h.get("isFrozen")
                        })
            except Exception as e:
                logger.error("Error inspecting health status: %s", e)

        # Check storage warnings
        if self.storage_manager:
            try:
                st = self.storage_manager.get_storage_overview()
                if st.get("health", {}).get("alertLevel") in ("WARNING", "CRITICAL", "EMERGENCY"):
                    errors_summary["storageWarnings"].append(st["health"])
            except Exception as e:
                logger.error("Error inspecting storage status: %s", e)

        # Check notifications
        if self.notification_center:
            try:
                notifs = self.notification_center.list_notifications(limit=50)
                for n in notifs:
                    if n.get("severity") in ("critical", "warning"):
                        errors_summary["recentAlerts"].append({
                            "id": n.get("id"),
                            "category": n.get("category"),
                            "severity": n.get("severity"),
                            "cameraId": n.get("cameraId"),
                            "title": n.get("title"),
                            "message": n.get("message"),
                            "count": n.get("count", 1),
                            "timestamp": n.get("isoTime")
                        })
            except Exception as e:
                logger.error("Error inspecting notifications: %s", e)

        errors_summary["totalErrorCount"] = (
            len(errors_summary["offlineCameras"]) +
            len(errors_summary["circuitBreakers"]) +
            len(errors_summary["storageWarnings"]) +
            len(errors_summary["healthFailures"]) +
            len(errors_summary["recentAlerts"])
        )

        return errors_summary

    def generate_markdown_summary(self, software: dict, resources: dict,
                                  ports: dict, telemetry: dict,
                                  errors: dict) -> str:
        """Create a human-readable Markdown summary report for troubleshooting."""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        overall_health = "HEALTHY"
        if errors["totalErrorCount"] > 0:
            overall_health = "DEGRADED" if len(errors["offlineCameras"]) < 2 else "CRITICAL"

        lines = [
            f"# CamHUB Diagnostics & Troubleshooting Report",
            f"**Generated:** {now_str}  ",
            f"**Overall System Status:** `{overall_health}`  ",
            f"**Total Issues Detected:** `{errors['totalErrorCount']}`  ",
            "",
            "---",
            "",
            "## 1. ⚙️ Environment & Software Versions",
            f"- **CamHUB Engine:** {software.get('app', '1.0.0')}",
            f"- **Python:** {software.get('python', {}).get('version')} ({software.get('python', {}).get('implementation')})",
            f"- **FFmpeg:** {software.get('ffmpeg', {}).get('version', 'Not installed')}",
            f"- **.NET Runtime:** {software.get('dotnet', {}).get('version', 'Not installed')}",
            f"- **Host OS:** {resources.get('os', {}).get('platform')} ({resources.get('os', {}).get('cpuCount')} CPU cores)",
            f"- **PID:** {resources.get('process', {}).get('pid')}  |  **Executable:** `{resources.get('process', {}).get('pythonExecutable')}`",
            "",
            "---",
            "",
            "## 2. 📹 Camera & Telemetry Matrix",
            "| Camera ID | Name | Supervisor State | Health | FPS | Latency | Reconnects | HTTP Port | RTSP Port |",
            "| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |"
        ]

        supervisors = telemetry.get("supervisors", {}).get("services", {})
        health_data = telemetry.get("health", {})
        cam_ports = ports.get("cameras", {})

        for cid, p_info in cam_ports.items():
            cname = p_info.get("name", cid)
            s_state = supervisors.get(cid, {}).get("state", "UNKNOWN")
            h = health_data.get(cid, {})
            h_state = h.get("status", "UNKNOWN")
            fps = h.get("fps", 0.0)
            latency = f"{h.get('latencyMs', 0)}ms" if h.get("latencyMs") else "N/A"
            reconnects = h.get("reconnectCount", 0)

            http_data = p_info.get('http') or {}
            rtsp_data = p_info.get('rtsp') or {}
            http_str = f"{http_data.get('port', '-')} ({http_data.get('status', '-')})" if http_data else "N/A"
            rtsp_str = f"{rtsp_data.get('port', '-')} ({rtsp_data.get('status', '-')})" if rtsp_data else "N/A"

            lines.append(
                f"| `{cid}` | {cname} | `{s_state}` | `{h_state}` | {fps} | {latency} | {reconnects} | {http_str} | {rtsp_str} |"
            )

        lines.extend([
            "",
            "---",
            "",
            "## 3. 💾 Storage Status",
        ])

        disk = resources.get("disk", {})
        if disk and "totalGb" in disk:
            lines.extend([
                f"- **Disk Capacity:** {disk.get('freeGb')} GB free of {disk.get('totalGb')} GB ({disk.get('usedPercent')}% used)",
            ])
        st_overview = telemetry.get("storage", {})
        if st_overview and "recordings" in st_overview:
            lines.extend([
                f"- **Recordings Storage:** {st_overview['recordings'].get('totalMb', 0)} MB ({st_overview['recordings'].get('fileCount', 0)} files)",
                f"- **Event Snapshots:** {st_overview['events'].get('totalMb', 0)} MB ({st_overview['events'].get('fileCount', 0)} snapshots)",
                f"- **Storage Alert Level:** `{st_overview.get('health', {}).get('alertLevel', 'NORMAL')}`",
            ])

        lines.extend([
            "",
            "---",
            "",
            "## 4. ⚠️ Issue Summary & Actionable Recommendations",
        ])

        if errors["totalErrorCount"] == 0:
            lines.append("✅ **No critical issues or degraded states detected.** All cameras and services are operating normally.")
        else:
            if errors["offlineCameras"]:
                lines.append("### Offline Cameras")
                for off in errors["offlineCameras"]:
                    lines.append(f"- **Camera `{off['cameraId']}`** is in `{off['state']}` state. Message: {off['message']}")

            if errors["circuitBreakers"]:
                lines.append("### Circuit Breakers Tripped")
                for cb in errors["circuitBreakers"]:
                    lines.append(f"- **Camera `{cb['cameraId']}`** triggered circuit breaker after {cb['restarts']} restarts. Reason: {cb['reason']}")

            if errors["healthFailures"]:
                lines.append("### Telemetry Degraded / Frozen Feeds")
                for hf in errors["healthFailures"]:
                    lines.append(f"- **Camera `{hf['cameraId']}`** is `{hf['status']}`: {hf['reason']} (FPS: {hf['fps']})")

            if errors["storageWarnings"]:
                lines.append("### Storage Capacity Warnings")
                for sw in errors["storageWarnings"]:
                    lines.append(f"- **Disk Alert:** {sw.get('message', 'Storage capacity threshold exceeded')}")

        lines.append("")
        return "\n".join(lines)

    def create_diagnostic_bundle(self, max_size_bytes: int = 10 * 1024 * 1024) -> Dict[str, Any]:
        """
        Assemble all telemetry, software versions, sanitized config, and errors into
        a timestamped ZIP archive with manifest.json.
        """
        start_time = time.perf_counter()
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        bundle_filename = f"camhub_diagnostics_{timestamp_str}.zip"
        bundle_path = os.path.join(self.diagnostics_dir, bundle_filename)

        # 1. Gather all diagnostic facets safely
        software = self.get_software_versions()
        resources = self.get_system_resources()
        ports = self.check_ports()
        telemetry = self.get_services_telemetry()
        errors = self.get_recent_errors()

        raw_config = self.config_provider() or {}
        sanitized_config = sanitize_value(raw_config)

        markdown_report = self.generate_markdown_summary(
            software, resources, ports, telemetry, errors
        )

        recent_logs_text = "\n".join(self.recent_logs[-self._max_recent_logs:])

        # 2. Prepare file dictionary to package
        files_to_pack = {
            "diagnostics_summary.md": markdown_report.encode("utf-8"),
            "system_info.json": json.dumps({"software": software, "resources": resources}, indent=2).encode("utf-8"),
            "services_status.json": json.dumps(telemetry, indent=2).encode("utf-8"),
            "ports_status.json": json.dumps(ports, indent=2).encode("utf-8"),
            "sanitized_config.json": json.dumps(sanitized_config, indent=2).encode("utf-8"),
            "recent_errors.json": json.dumps(errors, indent=2).encode("utf-8"),
            "recent_logs.txt": recent_logs_text.encode("utf-8")
        }

        # 3. Create manifest
        total_uncompressed_bytes = sum(len(content) for content in files_to_pack.values())
        file_hashes = {}
        for fname, content in files_to_pack.items():
            file_hashes[fname] = {
                "sizeBytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest()
            }

        manifest = {
            "bundleVersion": "1.0.0",
            "generator": "CamHUB Diagnostics Engine",
            "timestamp": datetime.now().isoformat(),
            "hostname": platform.node(),
            "os": platform.platform(),
            "totalFiles": len(files_to_pack) + 1,  # + manifest.json
            "totalUncompressedBytes": total_uncompressed_bytes,
            "overallStatus": "DEGRADED" if errors["totalErrorCount"] > 0 else "HEALTHY",
            "issueCount": errors["totalErrorCount"],
            "files": file_hashes
        }
        manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")
        files_to_pack["manifest.json"] = manifest_bytes

        # 4. Write to ZIP file atomically
        temp_zip_path = bundle_path + ".tmp"
        try:
            with zipfile.ZipFile(temp_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for fname, content in files_to_pack.items():
                    zf.writestr(fname, content)

            # Move temp to final
            if os.path.exists(bundle_path):
                os.remove(bundle_path)
            os.replace(temp_zip_path, bundle_path)

            bundle_size = os.path.getsize(bundle_path)
            if bundle_size > max_size_bytes:
                os.remove(bundle_path)
                raise ValueError(f"Diagnostic bundle exceeded maximum size: {bundle_size} > {max_size_bytes}")

            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            sha256_bundle = hashlib.sha256()
            with open(bundle_path, "rb") as f:
                while chunk := f.read(65536):
                    sha256_bundle.update(chunk)

            logger.info("Diagnostic bundle created: %s (%d bytes in %sms)", bundle_filename, bundle_size, duration_ms)
            self.log_event(f"Diagnostic bundle generated: {bundle_filename} ({bundle_size} bytes)")

            return {
                "success": True,
                "filename": bundle_filename,
                "filePath": bundle_path,
                "sizeBytes": bundle_size,
                "sha256": sha256_bundle.hexdigest(),
                "durationMs": duration_ms,
                "downloadUrl": f"/api/diagnostics/download?file={bundle_filename}",
                "manifest": manifest
            }
        except Exception as e:
            if os.path.exists(temp_zip_path):
                os.remove(temp_zip_path)
            logger.error("Failed to generate diagnostic bundle: %s", e)
            raise

    def list_bundles(self) -> List[Dict[str, Any]]:
        """List previously generated diagnostic bundles."""
        bundles = []
        if not os.path.exists(self.diagnostics_dir):
            return bundles

        for fname in sorted(os.listdir(self.diagnostics_dir), reverse=True):
            if fname.endswith(".zip") and fname.startswith("camhub_diagnostics_"):
                fpath = os.path.join(self.diagnostics_dir, fname)
                try:
                    stat = os.stat(fpath)
                    bundles.append({
                        "filename": fname,
                        "sizeBytes": stat.st_size,
                        "sizeFormatted": f"{round(stat.st_size / 1024, 1)} KB",
                        "createdAt": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                        "downloadUrl": f"/api/diagnostics/download?file={fname}"
                    })
                except Exception:
                    pass
        return bundles

    def delete_bundle(self, filename: str) -> Tuple[bool, str]:
        """Delete an old diagnostic bundle."""
        clean_name = os.path.basename(filename)
        if not clean_name.endswith(".zip") or not clean_name.startswith("camhub_diagnostics_"):
            return False, "Invalid diagnostic bundle filename"
        target_path = os.path.join(self.diagnostics_dir, clean_name)
        if not os.path.exists(target_path):
            return False, "Diagnostic bundle not found"
        try:
            os.remove(target_path)
            return True, f"Deleted {clean_name}"
        except Exception as e:
            return False, str(e)
