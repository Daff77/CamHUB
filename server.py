"""
CamHub Host Server & Camera Process Manager
Serves the CamHub web dashboard and provides REST APIs to control camera processes.
"""

import os
import sys
import json
import time
import socket
import argparse
import subprocess
from urllib.parse import urlparse, parse_qs
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

from health_monitor import CameraHealthMonitor, sanitize_sensitive_data

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
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

MANAGER = ProcessManager()
HEALTH_MONITOR = CameraHealthMonitor(load_config)

class CamHubHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def log_message(self, format, *args):
        # Silence routine static asset logs
        if "/api/services" in (args[0] if args else ""):
            print(f"[API] {self.command} {args[0]}", flush=True)

    def send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")

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

    def do_GET(self):
        url = urlparse(self.path)
        qs = parse_qs(url.query)

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

        super().do_GET()

    def do_POST(self):
        url = urlparse(self.path)
        qs = parse_qs(url.query)
        cid = qs.get("id", [None])[0]

        if url.path == "/api/services/start-all":
            results = MANAGER.start_all()
            time.sleep(0.5)
            status = MANAGER.get_status()
            self.send_json(200, {"success": True, "results": results, "status": status})
            return

        if url.path == "/api/services/stop-all":
            results = MANAGER.stop_all()
            time.sleep(0.5)
            status = MANAGER.get_status()
            self.send_json(200, {"success": True, "results": results, "status": status})
            return

        if url.path == "/api/services/restart-all":
            results = MANAGER.restart_all()
            time.sleep(0.5)
            status = MANAGER.get_status()
            self.send_json(200, {"success": True, "results": results, "status": status})
            return

        if url.path == "/api/services/start" and cid:
            ok, msg = MANAGER.start_camera(cid)
            time.sleep(0.5)
            status = MANAGER.get_status()
            self.send_json(200, {"success": ok, "message": msg, "status": status})
            return

        if url.path == "/api/services/stop" and cid:
            ok, msg = MANAGER.stop_camera(cid)
            time.sleep(0.5)
            status = MANAGER.get_status()
            self.send_json(200, {"success": ok, "message": msg, "status": status})
            return

        if url.path == "/api/services/restart" and cid:
            MANAGER.stop_camera(cid)
            time.sleep(0.8)
            ok, msg = MANAGER.start_camera(cid)
            time.sleep(0.5)
            status = MANAGER.get_status()
            self.send_json(200, {"success": ok, "message": msg, "status": status})
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

    HEALTH_MONITOR.start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[CAMHUB] Shutting down...", flush=True)
    finally:
        HEALTH_MONITOR.stop()
        server.server_close()

if __name__ == "__main__":
    main()

