"""
CamHub Notification Center
Centralized alert consolidation, deduplication, cooldown throttling, and incident acknowledgment.
Monitors camera offline transitions, degraded FPS, frozen streams, supervisor restarts,
motion detections, and disk storage warnings.
Supports optional, non-blocking, credential-redacted Telegram bot notifications.
"""

import os
import sys
import time
import json
import uuid
import queue
import logging
import threading
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

logger = logging.getLogger("CamHub.Notifications")

# Base project directory
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOTIFICATIONS_DIR = os.path.join(BASE_DIR, "notifications")

DEFAULT_COOLDOWNS = {
    "camera_offline": 300.0,    # 5 minutes
    "low_fps": 180.0,           # 3 minutes
    "stream_frozen": 180.0,     # 3 minutes
    "decoder_restart": 60.0,    # 1 minute
    "motion_detected": 120.0,   # 2 minutes
    "storage_warning": 1800.0   # 30 minutes
}

DEFAULT_CATEGORIES_CONFIG = {
    "camera_offline": {"enabled": True, "telegram": True, "minSeverity": "critical"},
    "stream_frozen": {"enabled": True, "telegram": True, "minSeverity": "critical"},
    "decoder_restart": {"enabled": True, "telegram": True, "minSeverity": "warning"},
    "low_fps": {"enabled": True, "telegram": False, "minSeverity": "warning"},
    "storage_warning": {"enabled": True, "telegram": True, "minSeverity": "warning"},
    "motion_detected": {"enabled": True, "telegram": False, "minSeverity": "info"}
}

DEFAULT_NOTIF_CONFIG = {
    "enabled": True,
    "maxStoredCount": 300,
    "retentionDays": 14,
    "cooldownsSeconds": DEFAULT_COOLDOWNS,
    "categories": DEFAULT_CATEGORIES_CONFIG,
    "telegram": {
        "enabled": False,
        "botToken": "",
        "chatId": "",
        "timeoutSeconds": 3.0,
        "maxRetries": 2
    }
}

SEVERITY_LEVELS = {
    "info": 1,
    "warning": 2,
    "critical": 3
}

def sanitize_text(text: str) -> str:
    """Strip passwords, RTSP credentials, and API tokens from notification messages."""
    if not text:
        return ""
    import re
    # Mask URL credentials: http://user:pass@host -> http://user:***@host
    text = re.sub(r'://([^:]+):([^@]+)@', r'://\1:***@', text)
    # Mask CLI arguments: --password Secret123 -> --password ***
    text = re.sub(r'(--password\s+)[^\s]+', r'\1***', text, flags=re.IGNORECASE)
    # Mask bot tokens: 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11 -> [BOT_TOKEN_REDACTED]
    text = re.sub(r'\b\d{8,11}:[A-Za-z0-9_-]{20,50}\b', '[BOT_TOKEN_REDACTED]', text)
    return text

def mask_token(token: str) -> str:
    """Mask token string showing only first 4 and last 3 characters."""
    if not token or len(token) < 10:
        return "***"
    return f"{token[:4]}...{token[-3:]}"


class NotificationCenter:
    """
    Fleet-wide Notification supervisor for CamHUB.
    Consolidates camera events, throttles spam via cooldown grouping,
    persists alerts, and dispatches external alerts safely.
    """

    def __init__(self, config_provider, base_dir: str = None):
        self.config_provider = config_provider
        self.base_dir = base_dir or BASE_DIR
        self.storage_dir = os.path.join(self.base_dir, "notifications")
        os.makedirs(self.storage_dir, exist_ok=True)
        self.storage_file = os.path.join(self.storage_dir, "notifications.json")

        self.lock = threading.RLock()
        self.notifications: List[Dict[str, Any]] = []
        self._load_notifications()

        # Cooldown & deduplication tracker: (category, camera_id) -> dict(id, last_time, count)
        self.cooldown_tracker: Dict[Tuple[str, str], Dict[str, Any]] = {}

        # Telegram async dispatch queue & worker
        self.telegram_queue = queue.Queue(maxsize=50)
        self.running = True
        self.telegram_thread = threading.Thread(
            target=self._telegram_worker,
            name="CamHub-TelegramDispatcher",
            daemon=True
        )
        self.telegram_thread.start()

    def get_config(self) -> Dict[str, Any]:
        """Merge configured notification options with defaults."""
        full_cfg = self.config_provider()
        cfg = dict(DEFAULT_NOTIF_CONFIG)
        user_cfg = full_cfg.get("notifications", {})
        cfg.update(user_cfg)
        return cfg

    def _load_notifications(self):
        """Load stored notifications from disk."""
        if os.path.exists(self.storage_file):
            try:
                with open(self.storage_file, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        self.notifications = json.load(f)
            except Exception as e:
                logger.error(f"[NOTIF] Error reading notifications index: {e}")
                self.notifications = []
        else:
            self.notifications = []

    def _save_notifications(self):
        """Atomically persist notifications to disk."""
        with self.lock:
            try:
                tmp_file = f"{self.storage_file}.tmp.{os.getpid()}"
                with open(tmp_file, "w", encoding="utf-8") as f:
                    json.dump(self.notifications, f, indent=2)
                for _ in range(3):
                    try:
                        os.replace(tmp_file, self.storage_file)
                        break
                    except OSError:
                        time.sleep(0.05)
                else:
                    with open(self.storage_file, "w", encoding="utf-8") as f:
                        json.dump(self.notifications, f, indent=2)
                    if os.path.exists(tmp_file):
                        try:
                            os.remove(tmp_file)
                        except:
                            pass
            except Exception as e:
                logger.error(f"[NOTIF] Error saving notifications: {e}")

    def notify(
        self,
        category: str,
        camera_id: str,
        camera_name: str,
        severity: str,
        title: str,
        message: str,
        action_url: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Record a new notification or group/increment occurrence if within cooldown period.
        Returns the notification dict (or None if category is disabled).
        """
        cfg = self.get_config()
        if not cfg.get("enabled", True):
            return None

        # Verify category configuration
        cat_cfg = cfg.get("categories", {}).get(category, {})
        if not cat_cfg.get("enabled", True):
            return None

        # Severity filter check
        min_sev = cat_cfg.get("minSeverity", "info")
        if SEVERITY_LEVELS.get(severity, 1) < SEVERITY_LEVELS.get(min_sev, 1):
            return None

        clean_title = sanitize_text(title)
        clean_msg = sanitize_text(message)
        now_ts = int(time.time() * 1000)
        now_sec = time.time()

        # Cooldown check & deduplication
        cooldowns = cfg.get("cooldownsSeconds", DEFAULT_COOLDOWNS)
        cd_limit = cooldowns.get(category, DEFAULT_COOLDOWNS.get(category, 120.0))
        key = (category, camera_id)

        with self.lock:
            tracker = self.cooldown_tracker.get(key)
            if tracker and (now_sec - tracker["last_sec"]) < cd_limit:
                # Deduplicate: update existing notification
                notif_id = tracker["notif_id"]
                existing = next((n for n in self.notifications if n["id"] == notif_id), None)
                if existing:
                    existing["count"] = existing.get("count", 1) + 1
                    existing["lastOccurred"] = now_ts
                    existing["message"] = clean_msg
                    existing["acknowledged"] = False  # un-acknowledge on repeat
                    tracker["last_sec"] = now_sec
                    tracker["count"] += 1
                    self._save_notifications()
                    return existing

            # Cooldown passed or first occurrence: create new notification
            notif_id = f"notif_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
            notif_record = {
                "id": notif_id,
                "timestamp": now_ts,
                "isoTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "category": category,
                "severity": severity,
                "cameraId": camera_id,
                "cameraName": camera_name,
                "title": clean_title,
                "message": clean_msg,
                "actionUrl": action_url,
                "acknowledged": False,
                "acknowledgedAt": None,
                "count": 1,
                "lastOccurred": now_ts
            }

            self.notifications.insert(0, notif_record)
            # Cap maximum stored notifications
            max_stored = cfg.get("maxStoredCount", 300)
            if len(self.notifications) > max_stored:
                self.notifications = self.notifications[:max_stored]

            self.cooldown_tracker[key] = {
                "notif_id": notif_id,
                "last_sec": now_sec,
                "count": 1
            }
            self._save_notifications()

        # Enqueue external notification (Telegram) if enabled
        tg_cfg = cfg.get("telegram", {})
        if tg_cfg.get("enabled", False) and cat_cfg.get("telegram", True):
            self._dispatch_telegram(notif_record, tg_cfg)

        return notif_record

    def _dispatch_telegram(self, notif: Dict[str, Any], tg_cfg: Dict[str, Any]):
        """Safely enqueue notification to Telegram dispatch queue."""
        bot_token = tg_cfg.get("botToken", "").strip()
        chat_id = str(tg_cfg.get("chatId", "")).strip()

        if not bot_token or not chat_id:
            return

        icon_map = {
            "critical": "🚨",
            "warning": "⚠️",
            "info": "ℹ️"
        }
        icon = icon_map.get(notif["severity"], "🔔")

        msg_lines = [
            f"{icon} *CamHUB Alert:* {notif['title']}",
            f"*Severity:* `{notif['severity'].upper()}`",
            f"*Camera:* {notif['cameraName']} (`{notif['cameraId']}`)",
            f"*Time:* {notif['isoTime']}",
            f"*Detail:* {notif['message']}"
        ]
        if notif.get("count", 1) > 1:
            msg_lines.append(f"*Repeats:* {notif['count']} times")

        text = "\n".join(msg_lines)
        try:
            self.telegram_queue.put_nowait({
                "botToken": bot_token,
                "chatId": chat_id,
                "text": text,
                "timeout": tg_cfg.get("timeoutSeconds", 3.0),
                "retries": tg_cfg.get("maxRetries", 2)
            })
        except queue.Full:
            logger.warning("[NOTIF] Telegram dispatch queue full, dropped alert.")

    def _telegram_worker(self):
        """Asynchronous worker for executing Telegram webhook delivery."""
        while self.running:
            try:
                task = self.telegram_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if task is None or not self.running:
                break

            bot_token = task["botToken"]
            chat_id = task["chatId"]
            text = task["text"]
            timeout = task.get("timeout", 3.0)
            max_retries = task.get("retries", 2)

            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            payload = json.dumps({
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True
            }).encode("utf-8")

            req = Request(url, data=payload, headers={
                "Content-Type": "application/json",
                "User-Agent": "CamHUB-Notifier/1.0"
            })

            success = False
            for attempt in range(max_retries + 1):
                try:
                    with urlopen(req, timeout=timeout) as resp:
                        if resp.status == 200:
                            success = True
                            break
                except (HTTPError, URLError, Exception) as e:
                    if attempt < max_retries:
                        time.sleep(1.5 * (attempt + 1))
                    else:
                        logger.warning(f"[NOTIF] Failed to send Telegram alert after {max_retries + 1} attempts: {e}")

    def list_notifications(
        self,
        severity: Optional[str] = None,
        camera_id: Optional[str] = None,
        category: Optional[str] = None,
        unacknowledged_only: bool = False,
        limit: int = 100,
        since_ms: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Filter and retrieve stored notifications."""
        with self.lock:
            items = list(self.notifications)

        if severity:
            items = [i for i in items if i.get("severity") == severity]
        if camera_id:
            items = [i for i in items if i.get("cameraId") == camera_id]
        if category:
            items = [i for i in items if i.get("category") == category]
        if unacknowledged_only:
            items = [i for i in items if not i.get("acknowledged", False)]
        if since_ms:
            items = [i for i in items if i.get("timestamp", 0) >= since_ms]

        return items[:limit]

    def acknowledge(self, notification_id: Optional[str] = None, all_unread: bool = False) -> int:
        """Acknowledge one or all unread notifications."""
        now_ts = int(time.time() * 1000)
        ack_count = 0
        with self.lock:
            for n in self.notifications:
                if all_unread or (notification_id and n["id"] == notification_id):
                    if not n.get("acknowledged", False):
                        n["acknowledged"] = True
                        n["acknowledgedAt"] = now_ts
                        ack_count += 1
            if ack_count > 0:
                self._save_notifications()
        return ack_count

    def clear(self, notification_id: Optional[str] = None, all_notifications: bool = False) -> int:
        """Delete one or all notifications from memory and disk."""
        deleted = 0
        with self.lock:
            if all_notifications:
                deleted = len(self.notifications)
                self.notifications.clear()
                self.cooldown_tracker.clear()
            elif notification_id:
                initial = len(self.notifications)
                self.notifications = [n for n in self.notifications if n["id"] != notification_id]
                deleted = initial - len(self.notifications)

            if deleted > 0:
                self._save_notifications()
        return deleted

    def get_stats(self) -> Dict[str, Any]:
        """Return notification summary metrics."""
        with self.lock:
            items = list(self.notifications)

        unread = sum(1 for n in items if not n.get("acknowledged", False))
        by_sev = {"critical": 0, "warning": 0, "info": 0}
        by_cat = {}

        for n in items:
            s = n.get("severity", "info")
            if s in by_sev:
                by_sev[s] += 1
            c = n.get("category", "unknown")
            by_cat[c] = by_cat.get(c, 0) + 1

        cfg = self.get_config()
        tg_cfg = cfg.get("telegram", {})
        bot_tok = tg_cfg.get("botToken", "")

        return {
            "totalCount": len(items),
            "unreadCount": unread,
            "bySeverity": by_sev,
            "byCategory": by_cat,
            "telegramConfigured": bool(bot_tok and tg_cfg.get("chatId")),
            "telegramEnabled": tg_cfg.get("enabled", False),
            "botTokenMasked": mask_token(bot_tok) if bot_tok else ""
        }

    def simulate_event(
        self,
        category: str = "camera_offline",
        camera_id: str = "sim-1",
        camera_name: str = "Simulated Camera",
        severity: str = "warning",
        title: Optional[str] = None,
        message: Optional[str] = None
    ) -> Dict[str, Any]:
        """Generate a simulated notification for end-to-end testing."""
        default_titles = {
            "camera_offline": f"Camera '{camera_name}' is offline",
            "low_fps": f"Low frame rate on '{camera_name}'",
            "stream_frozen": f"Stream frozen on '{camera_name}'",
            "decoder_restart": f"Decoder restarted for '{camera_name}'",
            "motion_detected": f"Motion detected on '{camera_name}'",
            "storage_warning": "Storage threshold exceeded (83.9%)"
        }
        default_msgs = {
            "camera_offline": "Port closed. Decoder process is not responding.",
            "low_fps": "Stream FPS dropped to 0.4 FPS (target 15.0 FPS).",
            "stream_frozen": "Frame hash identical for > 8.0s. Feed frozen.",
            "decoder_restart": "Supervisor auto-recovery triggered restart (attempt 1/5).",
            "motion_detected": "Sustained activity confirmed (score: 42.5%, objects: 1 person).",
            "storage_warning": "Host disk usage at 83.9% (76.4 GB free). Warning threshold 80%."
        }

        t = title or default_titles.get(category, f"Simulated {category}")
        m = message or default_msgs.get(category, "Simulated test event for validation.")
        action_url = f"#cam-{camera_id}" if category != "storage_warning" else "#playback"

        return self.notify(
            category=category,
            camera_id=camera_id,
            camera_name=camera_name,
            severity=severity,
            title=t,
            message=m,
            action_url=action_url
        )

    def test_telegram_connection(self, bot_token: str, chat_id: str) -> Tuple[bool, str]:
        """Safely test Telegram bot credentials without leaking token in logs."""
        clean_token = bot_token.strip()
        clean_chat = chat_id.strip()

        if not clean_token or not clean_chat:
            return False, "Bot token and Chat ID are both required"

        url = f"https://api.telegram.org/bot{clean_token}/sendMessage"
        payload = json.dumps({
            "chat_id": clean_chat,
            "text": "🔔 *CamHUB Notification Test*\nYour Telegram bot is successfully connected to CamHUB!",
            "parse_mode": "Markdown"
        }).encode("utf-8")

        req = Request(url, data=payload, headers={
            "Content-Type": "application/json",
            "User-Agent": "CamHUB-Notifier/1.0"
        })

        try:
            with urlopen(req, timeout=4.0) as resp:
                if resp.status == 200:
                    return True, "Telegram test message sent successfully!"
                return False, f"Telegram returned HTTP {resp.status}"
        except HTTPError as he:
            try:
                err_data = json.loads(he.read().decode())
                return False, f"Telegram error: {err_data.get('description', he.reason)}"
            except:
                return False, f"Telegram HTTP error: {he.code} {he.reason}"
        except Exception as e:
            return False, f"Connection failed: {sanitize_text(str(e))}"

    def stop(self):
        """Stop background worker cleanly."""
        self.running = False
        try:
            self.telegram_queue.put_nowait(None)
        except queue.Full:
            pass
        self._save_notifications()

