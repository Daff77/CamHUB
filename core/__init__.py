"""
CamHUB Core Package
Unified engine services for camera process supervision, health telemetry,
motion detection analytics, local segmented recording, and hardware adapters.
"""

from .health_monitor import (
    CameraHealthMonitor,
    CameraHealthTracker,
    CameraHealthState,
    sanitize_sensitive_data,
    DEFAULT_THRESHOLDS
)

from .auto_recovery import (
    AutoRecoveryManager,
    CameraSupervisor,
    SupervisorState,
    kill_process_tree,
    kill_port_owner,
    DEFAULT_SUPERVISOR_CONFIG
)

from .recording_manager import (
    RecordingManager,
    RecordingSession,
    sanitize_path,
    get_disk_space_stats,
    DEFAULT_RECORDING_CONFIG
)

from .motion_detector import (
    MotionDetectorService,
    CameraMotionTracker,
    DEFAULT_EVENTS_DIR,
    DEFAULT_MOTION_CONFIG
)

from .okam_adapter import (
    StreamBroker,
    run_server as run_okam_adapter
)

__all__ = [
    "CameraHealthMonitor",
    "CameraHealthTracker",
    "CameraHealthState",
    "sanitize_sensitive_data",
    "DEFAULT_THRESHOLDS",
    "AutoRecoveryManager",
    "CameraSupervisor",
    "SupervisorState",
    "kill_process_tree",
    "kill_port_owner",
    "DEFAULT_SUPERVISOR_CONFIG",
    "RecordingManager",
    "RecordingSession",
    "sanitize_path",
    "get_disk_space_stats",
    "DEFAULT_RECORDING_CONFIG",
    "MotionDetectorService",
    "CameraMotionTracker",
    "DEFAULT_EVENTS_DIR",
    "DEFAULT_MOTION_CONFIG",
    "StreamBroker",
    "run_okam_adapter"
]
