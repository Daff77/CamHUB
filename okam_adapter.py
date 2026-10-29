"""
O-Kam Pro / VStarcam Stream Adapter for CamHub
Bridges RTSP stream to HTTP MJPEG (/stream.mjpg), Snapshot (/snapshot), and Telemetry (/api/metrics).
Uses multi-threaded HTTP server so /api/metrics and /snapshot are never blocked by live streams.
"""

import sys
import time
import subprocess
import threading
import argparse
import json
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from collections import deque

class StreamBroker:
    def __init__(self, rtsp_url):
        self.rtsp_url = rtsp_url
        self.running = True
        self.subscribers = set()
        self.lock = threading.Lock()
        self.latest_frame = None
        self.latest_frame_time = 0
        self.total_frames = 0
        self.frame_times = deque(maxlen=30)
        self.process = None

    def add_subscriber(self, callback):
        with self.lock:
            self.subscribers.add(callback)

    def remove_subscriber(self, callback):
        with self.lock:
            self.subscribers.discard(callback)

    def get_metrics(self):
        now = time.time()
        with self.lock:
            fps = 0.0
            if len(self.frame_times) >= 2:
                duration = self.frame_times[-1] - self.frame_times[0]
                if duration > 0:
                    fps = round((len(self.frame_times) - 1) / duration, 1)

            # If no frame arrived within the last 2.5s, report 0 fps
            if self.latest_frame_time == 0 or (now - self.latest_frame_time) > 2.5:
                fps = 0.0

            latency_ms = 0.0
            if self.latest_frame_time > 0:
                latency_ms = round(max(0, (now - self.latest_frame_time) * 1000), 1)

            active_clients = len(self.subscribers)

            return {
                "sourceFps": fps,
                "xcodeInFps": fps,
                "xcodeOutFps": fps,
                "xcodeLatencyMs": latency_ms,
                "rtspFps": fps,
                "mjpegFps": fps if active_clients > 0 else 0.0,
                "totalSourceFrames": self.total_frames,
                "totalRtspFrames": self.total_frames,
                "totalMjpegFrames": self.total_frames,
                "activeRtspSessions": 0,
                "activeMjpegClients": active_clients
            }

    def start(self):
        t = threading.Thread(target=self._run_ffmpeg, daemon=True, name="ffmpeg-worker")
        t.start()

    def _run_ffmpeg(self):
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "error",
            "-fflags", "nobuffer",
            "-flags", "low_delay",
            "-rtsp_transport", "tcp",
            "-i", self.rtsp_url,
            "-an",
            "-c:v", "mjpeg",
            "-q:v", "5",
            "-f", "mpjpeg",
            "-boundary_tag", "frame",
            "pipe:1"
        ]

        while self.running:
            clean_url = self.rtsp_url.split('@')[-1] if '@' in self.rtsp_url else self.rtsp_url
            print(f"[OKAM-ADAPTER] Connecting to RTSP: {clean_url}", flush=True)
            try:
                self.process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=1048576
                )

                def read_stderr():
                    try:
                        for line in self.process.stderr:
                            if not self.running:
                                break
                            text = line.decode('utf-8', errors='ignore').strip()
                            if text:
                                print(f"[OKAM-FFMPEG] {text}", file=sys.stderr, flush=True)
                    except:
                        pass

                t_err = threading.Thread(target=read_stderr, daemon=True)
                t_err.start()

                stdout = self.process.stdout
                buffer = bytearray()
                delimiter = b"--frame\r\n"

                while self.running and self.process.poll() is None:
                    chunk = stdout.read(16384)
                    if not chunk:
                        break
                    buffer.extend(chunk)

                    while True:
                        idx = buffer.find(delimiter)
                        if idx == -1:
                            break

                        next_idx = buffer.find(delimiter, idx + len(delimiter))
                        if next_idx == -1:
                            break

                        frame_data = bytes(buffer[idx:next_idx])
                        del buffer[:next_idx]

                        # Extract JPEG bytes from multipart part
                        header_end = frame_data.find(b"\r\n\r\n")
                        if header_end != -1:
                            jpeg_bytes = frame_data[header_end + 4:].rstrip(b"\r\n")
                        else:
                            jpeg_bytes = None

                        now = time.time()
                        with self.lock:
                            self.total_frames += 1
                            self.frame_times.append(now)
                            if jpeg_bytes:
                                self.latest_frame = jpeg_bytes
                                self.latest_frame_time = now

                            subs = list(self.subscribers)

                        for sub in subs:
                            try:
                                sub(frame_data)
                            except:
                                pass

            except Exception as e:
                print(f"[OKAM-ADAPTER] Error: {e}", file=sys.stderr, flush=True)

            if self.running:
                print("[OKAM-ADAPTER] Stream lost, retrying in 3 seconds...", flush=True)
                time.sleep(3)


class ThreadedServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class HttpHandler(BaseHTTPRequestHandler):
    broker = None

    def log_message(self, format, *args):
        pass

    def send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")

    def do_OPTIONS(self):
        try:
            self.send_response(204)
            self.send_cors_headers()
            self.end_headers()
        except:
            pass

    def do_GET(self):
        path = self.path.split("?")[0]

        if path == "/api/metrics":
            try:
                metrics = self.broker.get_metrics()
                body = json.dumps(metrics).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(body)
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
                pass
            return

        if path == "/snapshot":
            try:
                frame = self.broker.latest_frame
                if not frame:
                    self.send_response(503)
                    self.send_cors_headers()
                    self.end_headers()
                    self.wfile.write(b"No snapshot available yet")
                    return

                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(frame)))
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(frame)
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
                pass
            return

        if path == "/stream.mjpg":
            try:
                self.send_response(200)
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.send_header("Pragma", "no-cache")
                self.send_header("Connection", "close")
                self.send_cors_headers()
                self.end_headers()
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
                return

            client_alive = [True]

            def on_frame(data):
                if not client_alive[0]:
                    return
                try:
                    self.wfile.write(data)
                    self.wfile.flush()
                except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
                    client_alive[0] = False

            self.broker.add_subscriber(on_frame)
            try:
                while client_alive[0] and self.broker.running:
                    time.sleep(0.2)
            except:
                pass
            finally:
                client_alive[0] = False
                self.broker.remove_subscriber(on_frame)
            return

        # Default info
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(b"O-Kam Pro Adapter running. Endpoints: /stream.mjpg, /snapshot, /api/metrics\n")
        except:
            pass


def run_server(rtsp_url, port):
    broker = StreamBroker(rtsp_url)
    broker.start()

    HttpHandler.broker = broker
    server = ThreadedServer(("0.0.0.0", port), HttpHandler)
    print(f"[OKAM-ADAPTER] HTTP Server running on http://0.0.0.0:{port}", flush=True)
    print(f"[OKAM-ADAPTER] Stream:   http://127.0.0.1:{port}/stream.mjpg", flush=True)
    print(f"[OKAM-ADAPTER] Snapshot: http://127.0.0.1:{port}/snapshot", flush=True)
    print(f"[OKAM-ADAPTER] Metrics:  http://127.0.0.1:{port}/api/metrics", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        broker.running = False
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="O-Kam Pro / VStarcam Stream Adapter")
    parser.add_argument("--rtsp", default="rtsp://admin:Danendra07.@192.168.100.6:10554/tcp/av0_0", help="RTSP URL")
    parser.add_argument("--port", type=int, default=8082, help="HTTP Port")
    args = parser.parse_args()

    run_server(args.rtsp, args.port)
