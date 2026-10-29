"""
CamHUB Test Suite Package Initialization
Ensures core and root directories are present in sys.path during test discovery.
"""

import os
import sys

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.abspath(os.path.join(TESTS_DIR, ".."))
CORE_DIR = os.path.join(ROOT_DIR, "core")

if CORE_DIR not in sys.path:
    sys.path.insert(0, CORE_DIR)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
