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

from .ai_detector import (
    LocalObjectDetector,
    AIObjectDetectorWorker,
    COCO_CLASSES,
    CATEGORY_MAP,
    DEFAULT_MODEL_PATH
)

from .storage_manager import (
    CamHubStorageManager,
    PlaybackLockManager,
    get_disk_usage_stats,
    DEFAULT_STORAGE_CONFIG
)

from .notification_center import (
    NotificationCenter,
    DEFAULT_NOTIF_CONFIG,
    sanitize_text,
    mask_token
)

from .diagnostics_service import (
    CamHubDiagnosticsService,
    sanitize_value,
    sanitize_string,
    test_tcp_port
)

__all__ = [
    "CamHubDiagnosticsService",
    "sanitize_value",
    "sanitize_string",
    "test_tcp_port",
    "NotificationCenter",
    "DEFAULT_NOTIF_CONFIG",
    "sanitize_text",
    "mask_token",
    "CamHubStorageManager",
    "PlaybackLockManager",
    "get_disk_usage_stats",
    "DEFAULT_STORAGE_CONFIG",
    "LocalObjectDetector",
    "AIObjectDetectorWorker",
    "COCO_CLASSES",
    "CATEGORY_MAP",
    "DEFAULT_MODEL_PATH",
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
