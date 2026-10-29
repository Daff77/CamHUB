"""
CamHUB O-Kam Adapter Root Wrapper
Backward compatibility shim forwarding to core.okam_adapter
"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CORE_DIR = os.path.join(BASE_DIR, "core")

if CORE_DIR not in sys.path:
    sys.path.insert(0, CORE_DIR)

from okam_adapter import run_server

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="O-Kam Pro / VStarcam Stream Adapter")
    parser.add_argument("--rtsp", default="rtsp://admin:Danendra07.@192.168.100.6:10554/tcp/av0_0", help="RTSP URL")
    parser.add_argument("--port", type=int, default=8082, help="HTTP Port")
    args = parser.parse_args()

    run_server(args.rtsp, args.port)
