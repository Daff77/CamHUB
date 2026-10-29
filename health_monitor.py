"""
CamHUB Health Monitor Root Compatibility Shim
Forwards all attributes and execution to core.health_monitor
"""
import sys
import os

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_CORE_DIR = os.path.join(_BASE_DIR, "core")
if _CORE_DIR not in sys.path:
    sys.path.insert(0, _CORE_DIR)

from core.health_monitor import *
