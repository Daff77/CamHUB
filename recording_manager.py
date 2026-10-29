"""
CamHUB Recording Manager Root Compatibility Shim
Forwards all attributes and execution to core.recording_manager
"""
import sys
import os

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_CORE_DIR = os.path.join(_BASE_DIR, "core")
if _CORE_DIR not in sys.path:
    sys.path.insert(0, _CORE_DIR)

from core.recording_manager import *

