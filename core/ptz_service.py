"""
CamHub PTZ (Pan-Tilt-Zoom) Service & Controller
Provides multi-protocol PTZ management conforming to ONVIF Profile S/T PTZ specifications
and native V380 binary/REST protocols.
"""

import os
import sys
import json
import time
import socket
import logging
import threading
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

logger = logging.getLogger("camhub.ptz")

# Default presets structure
DEFAULT_PRESETS = {
    "v380-1": [
        {"id": 1, "name": "Preset 1 · Center / Home", "configured": True, "token": "Preset_1", "pan": 0.0, "tilt": 0.0, "zoom": 1.0},
        {"id": 2, "name": "Preset 2 · Pintu Masuk", "configured": True, "token": "Preset_2", "pan": -0.6, "tilt": 0.1, "zoom": 1.0},
        {"id": 3, "name": "Preset 3 · Lorong Utama", "configured": True, "token": "Preset_3", "pan": 0.5, "tilt": -0.2, "zoom": 1.2},
        {"id": 4, "name": "Preset 4 · Meja Kerja", "configured": False, "token": "Preset_4", "pan": 0.0, "tilt": -0.5, "zoom": 1.0},
        {"id": 5, "name": "Preset 5 · Area Parkir", "configured": False, "token": "Preset_5", "pan": 0.8, "tilt": 0.3, "zoom": 1.5}
    ],
    "okam-3": [
        {"id": 1, "name": "Preset 1 · Area Depan", "configured": True, "token": "Preset_1", "pan": 0.0, "tilt": 0.0, "zoom": 1.0},
        {"id": 2, "name": "Preset 2 · Pagar Luar", "configured": True, "token": "Preset_2", "pan": -0.5, "tilt": 0.0, "zoom": 1.2},
        {"id": 3, "name": "Preset 3 · Halaman", "configured": False, "token": "Preset_3", "pan": 0.5, "tilt": -0.1, "zoom": 1.0},
        {"id": 4, "name": "Preset 4 · Gerbang", "configured": False, "token": "Preset_4", "pan": -0.8, "tilt": 0.2, "zoom": 1.4},
        {"id": 5, "name": "Preset 5 · Sudut Jalan", "configured": False, "token": "Preset_5", "pan": 0.9, "tilt": 0.1, "zoom": 1.6}
    ]
}

VALID_DIRECTIONS = {
    "up", "down", "left", "right",
    "upleft", "upright", "downleft", "downright",
    "stop"
}

VALID_AUX_COMMANDS = {
    "light_on", "light_off", "light_auto",
    "image_color", "image_bw", "image_auto", "image_flip"
}


class CamHubPTZService:
    def __init__(self, config_loader=None, presets_file=None):
        self.config_loader = config_loader
        self.lock = threading.Lock()
        self.stop_timers = {}  # {camera_id: threading.Timer}
        
        # Determine presets storage path
        if presets_file:
            self.presets_file = presets_file
        else:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.presets_file = os.path.join(base_dir, "config", "ptz_presets.json")
            
        self.presets = self._load_presets()
        
        # Real-time PTZ runtime state
        self.motion_state = {}  # {camera_id: {"is_moving": bool, "direction": str, "start_time": float, "speed": float}}
        self.stats = {
            "total_commands": 0,
            "last_command_time": 0,
            "last_error": None
        }

    def _load_presets(self):
        """Loads PTZ presets from disk or returns default configuration."""
        if os.path.exists(self.presets_file):
            try:
                with open(self.presets_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return data
            except Exception as e:
                logger.warning(f"Failed to load presets file: {e}")
        return json.loads(json.dumps(DEFAULT_PRESETS))

    def _save_presets(self):
        """Saves current PTZ presets to disk atomically."""
        try:
            os.makedirs(os.path.dirname(self.presets_file), exist_ok=True)
            tmp_path = self.presets_file + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self.presets, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, self.presets_file)
            return True
        except Exception as e:
            logger.error(f"Failed to save presets: {e}")
            return False

    def _get_camera_config(self, camera_id):
        """Finds camera entry from server config."""
        if not self.config_loader:
            return None
        cfg = self.config_loader()
        for cam in cfg.get("cameras", []):
            if cam.get("id") == camera_id:
                return cam
        return None

    def _is_port_listening(self, port):
        """Quick check if a TCP port is open locally."""
        if not port:
            return False
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.3)
                return s.connect_ex(("127.0.0.1", port)) == 0
        except Exception:
            return False

    def _send_http_command(self, port, path, timeout=1.5):
        """Dispatches an HTTP POST command to the local camera decoder service."""
        url = f"http://127.0.0.1:{port}{path}"
        try:
            req = Request(url, data=b"", method="POST")
            req.add_header("User-Agent", "CamHub-PTZ/2.0")
            req.add_header("Content-Length", "0")
            with urlopen(req, timeout=timeout) as resp:
                return resp.status in (200, 204), f"HTTP {resp.status}"
        except HTTPError as e:
            return False, f"HTTP Error {e.code}: {e.reason}"
        except URLError as e:
            return False, f"Connection Error: {e.reason}"
        except Exception as e:
            return False, str(e)

    def _send_onvif_soap(self, port, action, body_xml, timeout=2.0):
        """Dispatches an ONVIF SOAP 1.2 command to the ONVIF PTZ service."""
        url = f"http://127.0.0.1:{port}/onvif/ptz_service"
        envelope = f"""<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:tt="http://www.onvif.org/ver10/schema"
            xmlns:tptz="http://www.onvif.org/ver10/ptz/wsdl">
  <s:Body>
    {body_xml}
  </s:Body>
</s:Envelope>""".encode("utf-8")

        headers = {
            "Content-Type": f'application/soap+xml; charset=utf-8; action="{action}"',
            "User-Agent": "CamHub-ONVIF-PTZ/2.0",
            "Content-Length": str(len(envelope))
        }

        try:
            req = Request(url, data=envelope, headers=headers, method="POST")
            with urlopen(req, timeout=timeout) as resp:
                resp_bytes = resp.read()
                return resp.status in (200, 204), resp_bytes.decode("utf-8", errors="ignore")
        except Exception as e:
            return False, str(e)

    def move(self, camera_id, direction, speed=0.5, duration_ms=None, mode="continuous"):
        """
        Executes a directional PTZ movement command.
        Supports 8 directions: up, down, left, right, upleft, upright, downleft, downright, and stop.
        """
        direction = (direction or "").strip().lower()
        if direction not in VALID_DIRECTIONS:
            return False, f"Invalid direction '{direction}'. Must be one of: {sorted(list(VALID_DIRECTIONS))}"

        if direction == "stop":
            return self.stop(camera_id)

        cam = self._get_camera_config(camera_id)
        if not cam:
            return False, f"Camera '{camera_id}' not found in configuration"

        port = cam.get("port")
        if not port or not self._is_port_listening(port):
            return False, f"Camera '{camera_id}' decoder is offline (port {port} not listening)"

        # Normalize speed in [0.1, 1.0]
        try:
            spd = float(speed)
            spd = max(0.1, min(1.0, spd))
        except (ValueError, TypeError):
            spd = 0.5

        with self.lock:
            # Cancel any existing auto-stop timer for this camera
            if camera_id in self.stop_timers:
                try:
                    self.stop_timers[camera_id].cancel()
                except Exception:
                    pass
                del self.stop_timers[camera_id]

            self.stats["total_commands"] += 1
            self.stats["last_command_time"] = time.time()

            # Map direction to vector coordinates
            dx, dy = 0.0, 0.0
            if "left" in direction:
                dx -= spd
            if "right" in direction:
                dx += spd
            if "up" in direction:
                dy += spd
            if "down" in direction:
                dy -= spd

            success = False
            msg = ""

            # Check if camera decoder natively supports REST PTZ endpoints
            # For diagonal commands or single axis:
            if direction in ("up", "down", "left", "right"):
                # Single axis: native REST endpoint
                ok, msg = self._send_http_command(port, f"/api/ptz/{direction}")
                success = ok
            else:
                # Diagonal move: send ONVIF ContinuousMove with both X and Y
                onvif_body = f"""<tptz:ContinuousMove>
      <tptz:ProfileToken>Profile_1</tptz:ProfileToken>
      <tptz:Velocity>
        <tt:PanTilt x="{dx:.2f}" y="{dy:.2f}" space="http://www.onvif.org/ver10/tptz/PanTiltSpaces/VelocityGenericSpace"/>
      </tptz:Velocity>
      <tptz:Timeout>PT10S</tptz:Timeout>
    </tptz:ContinuousMove>"""
                ok, resp = self._send_onvif_soap(port, "ContinuousMove", onvif_body)
                if ok:
                    success = True
                    msg = "ONVIF ContinuousMove executed"
                else:
                    # Fallback: execute primary axis REST
                    primary_dir = "up" if "up" in direction else ("down" if "down" in direction else ("left" if "left" in direction else "right"))
                    ok, msg = self._send_http_command(port, f"/api/ptz/{primary_dir}")
                    success = ok

            if success:
                self.motion_state[camera_id] = {
                    "is_moving": True,
                    "direction": direction,
                    "speed": spd,
                    "start_time": time.time()
                }

                # If duration or step mode is requested, schedule auto-stop
                timeout_sec = None
                if duration_ms is not None:
                    try:
                        ms = int(duration_ms)
                        timeout_sec = max(0.1, min(5.0, ms / 1000.0))
                    except (ValueError, TypeError):
                        pass
                elif mode == "step":
                    timeout_sec = 0.4  # Default 400ms step pulse

                if timeout_sec:
                    timer = threading.Timer(timeout_sec, self._auto_stop_callback, args=[camera_id])
                    timer.daemon = True
                    self.stop_timers[camera_id] = timer
                    timer.start()

            return success, msg

    def _auto_stop_callback(self, camera_id):
        """Callback invoked by threading.Timer to halt motion in step mode."""
        try:
            self.stop(camera_id)
        except Exception as e:
            logger.error(f"Error in auto-stop for {camera_id}: {e}")

    def stop(self, camera_id):
        """Halts all active PTZ pan, tilt, and zoom motors."""
        cam = self._get_camera_config(camera_id)
        if not cam:
            return False, f"Camera '{camera_id}' not found"

        port = cam.get("port")
        with self.lock:
            if camera_id in self.stop_timers:
                try:
                    self.stop_timers[camera_id].cancel()
                except Exception:
                    pass
                del self.stop_timers[camera_id]

            self.motion_state[camera_id] = {
                "is_moving": False,
                "direction": None,
                "speed": 0.0,
                "stop_time": time.time()
            }

            self.stats["total_commands"] += 1
            self.stats["last_command_time"] = time.time()

        if port and self._is_port_listening(port):
            ok, msg = self._send_http_command(port, "/api/ptz/stop")
            if not ok:
                # Try ONVIF Stop SOAP
                onvif_stop = """<tptz:Stop>
      <tptz:ProfileToken>Profile_1</tptz:ProfileToken>
      <tptz:PanTilt>true</tptz:PanTilt>
      <tptz:Zoom>true</tptz:Zoom>
    </tptz:Stop>"""
                ok, msg = self._send_onvif_soap(port, "Stop", onvif_stop)
            return ok, msg

        return True, "PTZ motion state cleared"

    def zoom(self, camera_id, action, speed=0.5):
        """Controls optical or digital zoom in/out."""
        action = (action or "").strip().lower()
        if action not in ("in", "out", "reset"):
            return False, f"Invalid zoom action '{action}'. Must be 'in', 'out', or 'reset'."

        cam = self._get_camera_config(camera_id)
        if not cam:
            return False, f"Camera '{camera_id}' not found"

        port = cam.get("port")
        if not port or not self._is_port_listening(port):
            return False, f"Camera '{camera_id}' decoder is offline"

        spd = max(0.1, min(1.0, float(speed)))
        z_val = spd if action == "in" else (-spd if action == "out" else 0.0)

        # Dispatch ONVIF Zoom SOAP command
        zoom_soap = f"""<tptz:ContinuousMove>
      <tptz:ProfileToken>Profile_1</tptz:ProfileToken>
      <tptz:Velocity>
        <tt:Zoom x="{z_val:.2f}" space="http://www.onvif.org/ver10/tptz/ZoomSpaces/VelocityGenericSpace"/>
      </tptz:Velocity>
      <tptz:Timeout>PT1S</tptz:Timeout>
    </tptz:ContinuousMove>"""
        ok, msg = self._send_onvif_soap(port, "ContinuousMove", zoom_soap)
        return ok, msg or f"Zoom {action} initiated"

    def auxiliary(self, camera_id, command):
        """Dispatches auxiliary commands (infrared lights, color mode, image flip)."""
        cmd = (command or "").strip().lower()
        if cmd not in VALID_AUX_COMMANDS:
            return False, f"Invalid auxiliary command '{cmd}'. Must be one of: {sorted(list(VALID_AUX_COMMANDS))}"

        cam = self._get_camera_config(camera_id)
        if not cam:
            return False, f"Camera '{camera_id}' not found"

        port = cam.get("port")
        if not port or not self._is_port_listening(port):
            return False, f"Camera '{camera_id}' decoder is offline"

        # Map aux commands to decoder REST endpoints
        mapping = {
            "light_on": "/api/light/on",
            "light_off": "/api/light/off",
            "light_auto": "/api/light/auto",
            "image_color": "/api/image/color",
            "image_bw": "/api/image/bw",
            "image_auto": "/api/image/auto",
            "image_flip": "/api/image/flip"
        }

        endpoint = mapping.get(cmd)
        if endpoint:
            ok, msg = self._send_http_command(port, endpoint)
            return ok, msg

        return False, "Unsupported command"

    def get_presets(self, camera_id):
        """Returns the list of presets for a given camera."""
        with self.lock:
            cam_presets = self.presets.get(camera_id)
            if not cam_presets:
                # Return template
                cam_presets = [
                    {"id": i, "name": f"Preset {i}", "configured": False, "token": f"Preset_{i}"}
                    for i in range(1, 6)
                ]
            return cam_presets

    def preset_goto(self, camera_id, preset_id):
        """Directs the camera to a configured preset position."""
        try:
            pid = int(preset_id)
        except (ValueError, TypeError):
            return False, f"Invalid preset ID '{preset_id}'"

        cam = self._get_camera_config(camera_id)
        if not cam:
            return False, f"Camera '{camera_id}' not found"

        port = cam.get("port")
        if not port or not self._is_port_listening(port):
            return False, f"Camera '{camera_id}' decoder is offline"

        presets = self.get_presets(camera_id)
        target = next((p for p in presets if p.get("id") == pid), None)
        if not target or not target.get("configured"):
            return False, f"Preset {pid} is not configured yet"

        token = target.get("token") or f"Preset_{pid}"

        # Dispatch ONVIF GotoPreset SOAP
        goto_soap = f"""<tptz:GotoPreset>
      <tptz:ProfileToken>Profile_1</tptz:ProfileToken>
      <tptz:PresetToken>{token}</tptz:PresetToken>
    </tptz:GotoPreset>"""

        ok, msg = self._send_onvif_soap(port, "GotoPreset", goto_soap)
        return True, f"Navigating to {target.get('name', f'Preset {pid}')}"

    def preset_set(self, camera_id, preset_id, name=None):
        """Saves current position into a preset slot."""
        try:
            pid = int(preset_id)
        except (ValueError, TypeError):
            return False, f"Invalid preset ID '{preset_id}'"

        with self.lock:
            if camera_id not in self.presets:
                self.presets[camera_id] = [
                    {"id": i, "name": f"Preset {i}", "configured": False, "token": f"Preset_{i}"}
                    for i in range(1, 6)
                ]

            target = next((p for p in self.presets[camera_id] if p.get("id") == pid), None)
            if not target:
                target = {"id": pid, "token": f"Preset_{pid}"}
                self.presets[camera_id].append(target)

            target["configured"] = True
            target["name"] = name.strip() if name and name.strip() else f"Preset {pid}"
            target["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")

            self._save_presets()

        # Send ONVIF SetPreset if camera online
        cam = self._get_camera_config(camera_id)
        if cam:
            port = cam.get("port")
            if port and self._is_port_listening(port):
                set_soap = f"""<tptz:SetPreset>
      <tptz:ProfileToken>Profile_1</tptz:ProfileToken>
      <tptz:PresetName>{target['name']}</tptz:PresetName>
      <tptz:PresetToken>Preset_{pid}</tptz:PresetToken>
    </tptz:SetPreset>"""
                self._send_onvif_soap(port, "SetPreset", set_soap)

        return True, f"Saved preset {pid} ({target['name']})"

    def preset_clear(self, camera_id, preset_id):
        """Clears a configured preset slot."""
        try:
            pid = int(preset_id)
        except (ValueError, TypeError):
            return False, f"Invalid preset ID '{preset_id}'"

        with self.lock:
            if camera_id in self.presets:
                target = next((p for p in self.presets[camera_id] if p.get("id") == pid), None)
                if target:
                    target["configured"] = False
                    target["name"] = f"Preset {pid}"
                    target.pop("timestamp", None)
                    self._save_presets()
                    return True, f"Cleared preset {pid}"
        return False, f"Preset {pid} not found"

    def get_status(self, camera_id):
        """Returns comprehensive PTZ status, capabilities, and presets for the given camera."""
        cam = self._get_camera_config(camera_id)
        port = cam.get("port") if cam else None
        port_open = self._is_port_listening(port) if port else False
        cam_type = cam.get("type", "unknown") if cam else "unknown"

        # Determine capabilities based on camera model and configuration
        is_v380 = cam_type == "v380" or "v380" in camera_id
        is_ptz_capable = is_v380 or camera_id == "v380-1" or camera_id == "okam-3"

        motion = self.motion_state.get(camera_id, {
            "is_moving": False,
            "direction": None,
            "speed": 0.0
        })

        presets = self.get_presets(camera_id)

        return {
            "cameraId": camera_id,
            "supported": is_ptz_capable,
            "online": port_open,
            "port": port,
            "ptzType": "motorized_onvif" if is_v380 else "hybrid_digital",
            "isMoving": motion.get("is_moving", False),
            "currentDirection": motion.get("direction"),
            "speed": motion.get("speed", 0.5),
            "capabilities": {
                "panTilt": is_ptz_capable,
                "continuousMove": port_open,
                "relativeStepMove": port_open,
                "presets": True,
                "maxPresets": 5,
                "zoom": is_ptz_capable,
                "auxiliaryLights": is_v380,
                "auxiliaryImageFlip": is_v380
            },
            "presets": presets,
            "auxiliary": {
                "lightModes": ["auto", "on", "off"] if is_v380 else [],
                "imageModes": ["auto", "color", "bw", "flip"] if is_v380 else []
            },
            "stats": self.stats
        }
