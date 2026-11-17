"""
CamHub Authentication, Session Management, RBAC Authorization & Origin Policy
Provides server-verified session/token authentication, PBKDF2-HMAC-SHA256 password hashing,
centralized endpoint permission enforcement, and strict CORS/Origin validation.
"""

import os
import re
import hmac
import json
import time
import hashlib
import secrets
import argparse
import threading
from http.cookies import SimpleCookie
from urllib.parse import urlparse
from typing import Dict, Any, Optional, Tuple, List, Set

PBKDF2_ITERATIONS = 200_000
SESSION_COOKIE_NAME = "camhub_session"
DEFAULT_SESSION_TTL_SECONDS = 7 * 86400  # 7 days

# Read-only API/proxy endpoints accessible to authenticated 'viewer' (and 'admin').
# Everything else under /api or /proxy defaults to requiring 'admin'.
_VIEWER_EXACT_GET_PATHS: Set[str] = {
    "/api/cameras",
    "/api/cameras/",
    "/proxy/stream",
    "/proxy/snapshot",
    "/proxy/metrics",
    "/api/health",
    "/api/services/status",
    "/api/recovery/status",
    "/api/recordings",
    "/api/recordings/storage",
    "/api/recordings/stream",
    "/api/recordings/download",
    "/api/storage/status",
    "/api/storage/report",
    "/api/ai/status",
    "/api/events",
    "/api/events/detail",
    "/api/events/stats",
    "/api/events/snapshot",
    "/api/notifications",
    "/api/notifications/stats",
    "/api/ptz/status",
    "/api/ptz/presets",
}

_VIEWER_REGEX_GET_PATHS = (
    re.compile(r"^/api/cameras/[^/]+/(metrics|snapshot|stream\.mjpg)$"),
    re.compile(r"^/proxy/(stream|snapshot|metrics)/[^/]+$"),
    re.compile(r"^/api/health/[^/]+$"),
)

_PUBLIC_EXACT_ROUTES: Set[Tuple[str, str]] = {
    ("GET", "/api/auth/session"),
    ("HEAD", "/api/auth/session"),
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/logout"),
    ("POST", "/api/auth/setup"),
}


def hash_password(password: str, iterations: int = PBKDF2_ITERATIONS) -> str:
    """Hash a plaintext password using PBKDF2-HMAC-SHA256 with a random 16-byte salt."""
    if not isinstance(password, str) or len(password) == 0:
        raise ValueError("Password must not be empty")
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a plaintext password against a PBKDF2-HMAC-SHA256 hash in constant time."""
    if not isinstance(password, str) or not isinstance(stored_hash, str):
        return False
    try:
        scheme, iter_str, salt_hex, hash_hex = stored_hash.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        iterations = int(iter_str)
        if iterations < 10_000 or iterations > 5_000_000:
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        computed = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(computed, expected)
    except Exception:
        return False


def hash_api_token(raw_token: str) -> str:
    """Hash an API token with SHA-256 so raw API tokens are never stored on disk."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _atomic_write_json(path: str, data: Dict[str, Any]) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    tmp_path = f"{path}.tmp.{os.getpid()}.{threading.get_ident()}"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.chmod(tmp_path, 0o600)
        except OSError:
            pass
        for _ in range(3):
            try:
                os.replace(tmp_path, path)
                break
            except OSError:
                time.sleep(0.03)
        else:
            os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def get_required_permission(method: str, raw_path: str) -> str:
    """
    Centralized route permission classifier.
    Returns one of:
      - 'public' : No authentication required (static web/ UI assets & login/session endpoints)
      - 'viewer' : Requires valid session/token with role in ('viewer', 'admin')
      - 'admin'  : Requires valid session/token with role == 'admin'
    """
    m = (method or "GET").upper()
    norm_path = raw_path or "/"
    if norm_path != "/" and norm_path.endswith("/") and norm_path != "/api/cameras/":
        norm_path = norm_path.rstrip("/")

    if (m, norm_path) in _PUBLIC_EXACT_ROUTES:
        return "public"

    is_api_or_proxy = (
        norm_path == "/api"
        or norm_path.startswith("/api/")
        or norm_path == "/proxy"
        or norm_path.startswith("/proxy/")
    )

    if not is_api_or_proxy:
        # Only GET and HEAD are public for static files inside web/; any other method requires admin
        if m in ("GET", "HEAD"):
            return "public"
        return "admin"

    # Inside /api/* or /proxy/*: only allowlisted GET/HEAD endpoints are accessible to viewer;
    # everything else (all POST/PUT/PATCH/DELETE + diagnostics + unknown API routes) requires admin.
    if m in ("GET", "HEAD"):
        if norm_path in _VIEWER_EXACT_GET_PATHS:
            return "viewer"
        for rx in _VIEWER_REGEX_GET_PATHS:
            if rx.match(norm_path):
                return "viewer"

    return "admin"


class AuthManager:
    """
    Server-side authentication & authorization manager.
    - Stores only PBKDF2 password hashes and SHA-256 API token digests.
    - Verifies sessions against an active server session store AND an HMAC-SHA256 signature.
    - Never trusts X-CamHub-Role, unverified Bearer strings, or loopback IP addresses.
    """

    def __init__(
        self,
        base_dir: str,
        config_provider=None,
        auth_file: Optional[str] = None,
        session_ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS,
    ):
        self.base_dir = os.path.abspath(base_dir)
        self.config_provider = config_provider or (lambda: {})
        self.config_dir = os.path.join(self.base_dir, "config")
        os.makedirs(self.config_dir, exist_ok=True)
        self.auth_file = os.path.abspath(auth_file or os.path.join(self.config_dir, "auth_config.json"))
        self.bootstrap_token_file = os.path.join(self.config_dir, "auth_bootstrap.token")
        self.session_ttl_seconds = session_ttl_seconds

        self._lock = threading.RLock()
        self._secret_key: bytes = b""
        self._users: Dict[str, Dict[str, Any]] = {}
        self._api_tokens: List[Dict[str, str]] = []
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._login_attempts: Dict[str, List[float]] = {}
        self._bootstrap_token: Optional[str] = None

        self._load_or_init()

    def _load_or_init(self) -> None:
        with self._lock:
            disk_data: Dict[str, Any] = {}
            if os.path.exists(self.auth_file):
                try:
                    with open(self.auth_file, "r", encoding="utf-8") as f:
                        loaded = json.load(f)
                        if isinstance(loaded, dict):
                            disk_data = loaded
                except Exception:
                    disk_data = {}

            env_secret = os.environ.get("CAMHUB_AUTH_SECRET", "").strip()
            secret_hex = env_secret or disk_data.get("secretKey", "")
            dirty = False
            if not secret_hex or len(secret_hex) < 32:
                secret_hex = secrets.token_hex(32)
                dirty = True
            self._secret_key = secret_hex.encode("utf-8")

            users = disk_data.get("users", {})
            if isinstance(users, dict):
                self._users = dict(users)
            else:
                self._users = {}

            api_tokens = disk_data.get("apiTokens", [])
            if isinstance(api_tokens, list):
                self._api_tokens = list(api_tokens)
            else:
                self._api_tokens = []

            # Support environment variable user/token provisioning without storing plaintext
            env_admin_pw = os.environ.get("CAMHUB_ADMIN_PASSWORD", "")
            if env_admin_pw and "admin" not in self._users:
                self._users["admin"] = {
                    "username": "admin",
                    "role": "admin",
                    "passwordHash": hash_password(env_admin_pw),
                    "createdAt": int(time.time()),
                }
                dirty = True

            env_viewer_pw = os.environ.get("CAMHUB_VIEWER_PASSWORD", "")
            if env_viewer_pw and "viewer" not in self._users:
                self._users["viewer"] = {
                    "username": "viewer",
                    "role": "viewer",
                    "passwordHash": hash_password(env_viewer_pw),
                    "createdAt": int(time.time()),
                }
                dirty = True

            env_admin_tok = os.environ.get("CAMHUB_ADMIN_API_TOKEN", "").strip()
            if env_admin_tok:
                self._register_memory_token("env_admin", "admin", env_admin_tok)

            env_viewer_tok = os.environ.get("CAMHUB_VIEWER_API_TOKEN", "").strip()
            if env_viewer_tok:
                self._register_memory_token("env_viewer", "viewer", env_viewer_tok)

            if dirty or not os.path.exists(self.auth_file):
                self._save_locked(secret_hex)

            if self.is_setup_required():
                self._ensure_bootstrap_token_locked()
            else:
                self._clear_bootstrap_token_locked()

    def _register_memory_token(self, name: str, role: str, raw_token: str) -> None:
        digest = hash_api_token(raw_token)
        if not any(hmac.compare_digest(t.get("tokenHash", ""), digest) for t in self._api_tokens):
            self._api_tokens.append({
                "name": name,
                "role": role,
                "tokenHash": digest,
                "ephemeral": True,
            })

    def _save_locked(self, secret_hex: Optional[str] = None) -> None:
        persisted_tokens = [t for t in self._api_tokens if not t.get("ephemeral")]
        payload = {
            "secretKey": secret_hex or self._secret_key.decode("utf-8"),
            "users": self._users,
            "apiTokens": persisted_tokens,
        }
        _atomic_write_json(self.auth_file, payload)

    def _ensure_bootstrap_token_locked(self) -> str:
        if os.path.exists(self.bootstrap_token_file):
            try:
                with open(self.bootstrap_token_file, "r", encoding="utf-8") as f:
                    existing = f.read().strip()
                if len(existing) >= 16:
                    self._bootstrap_token = existing
                    return existing
            except OSError:
                pass
        tok = secrets.token_urlsafe(24)
        self._bootstrap_token = tok
        try:
            with open(self.bootstrap_token_file, "w", encoding="utf-8") as f:
                f.write(tok + "\n")
            try:
                os.chmod(self.bootstrap_token_file, 0o600)
            except OSError:
                pass
        except OSError:
            pass
        return tok

    def _clear_bootstrap_token_locked(self) -> None:
        self._bootstrap_token = None
        if os.path.exists(self.bootstrap_token_file):
            try:
                os.remove(self.bootstrap_token_file)
            except OSError:
                pass

    def is_setup_required(self) -> bool:
        with self._lock:
            has_admin = any(u.get("role") == "admin" for u in self._users.values())
            has_admin_token = any(t.get("role") == "admin" for t in self._api_tokens)
            return not (has_admin or has_admin_token)

    def set_user(self, username: str, password: str, role: str = "viewer") -> None:
        uname = (username or "").strip()
        if not uname or not re.match(r"^[A-Za-z0-9_.-]{2,64}$", uname):
            raise ValueError("Invalid username (use 2-64 alphanumeric, '_', '.', or '-' characters)")
        if role not in ("admin", "viewer"):
            raise ValueError("Role must be 'admin' or 'viewer'")
        if not isinstance(password, str) or len(password) < 8:
            raise ValueError("Password must be at least 8 characters")

        with self._lock:
            self._users[uname] = {
                "username": uname,
                "role": role,
                "passwordHash": hash_password(password),
                "updatedAt": int(time.time()),
            }
            self._save_locked()
            if not self.is_setup_required():
                self._clear_bootstrap_token_locked()

    def create_api_token(self, name: str, role: str = "viewer", persist: bool = True) -> str:
        if role not in ("admin", "viewer"):
            raise ValueError("Role must be 'admin' or 'viewer'")
        raw_token = f"ch_{secrets.token_urlsafe(32)}"
        entry = {
            "name": (name or role).strip(),
            "role": role,
            "tokenHash": hash_api_token(raw_token),
            "createdAt": int(time.time()),
        }
        if not persist:
            entry["ephemeral"] = True
        with self._lock:
            self._api_tokens.append(entry)
            if persist:
                self._save_locked()
            if not self.is_setup_required():
                self._clear_bootstrap_token_locked()
        return raw_token

    def complete_initial_setup(
        self,
        bootstrap_token: str,
        admin_password: str,
        admin_username: str = "admin",
        viewer_password: Optional[str] = None,
        client_key: str = "unknown",
    ) -> Tuple[bool, int, Dict[str, Any]]:
        if not self._check_rate_limit(client_key):
            return False, 429, {"error": "Too many attempts. Please wait before retrying."}

        with self._lock:
            if not self.is_setup_required():
                return False, 409, {"error": "Initial setup has already been completed"}
            expected = self._bootstrap_token or self._ensure_bootstrap_token_locked()
            provided = (bootstrap_token or "").strip()
            if not provided or not hmac.compare_digest(provided, expected):
                self._record_failed_attempt(client_key)
                return False, 403, {
                    "error": "Invalid bootstrap token. Read token from config/auth_bootstrap.token on the host."
                }
            try:
                self.set_user(admin_username, admin_password, role="admin")
                if viewer_password:
                    self.set_user("viewer", viewer_password, role="viewer")
            except ValueError as ve:
                return False, 400, {"error": str(ve)}

            session = self._issue_session_locked(admin_username.strip(), "admin")
            return True, 200, session

    def _check_rate_limit(self, client_key: str, window_sec: float = 60.0, max_failures: int = 10) -> bool:
        now = time.time()
        with self._lock:
            attempts = [t for t in self._login_attempts.get(client_key, []) if (now - t) < window_sec]
            self._login_attempts[client_key] = attempts
            return len(attempts) < max_failures

    def _record_failed_attempt(self, client_key: str) -> None:
        now = time.time()
        with self._lock:
            self._login_attempts.setdefault(client_key, []).append(now)

    def _sign_session_id(self, session_id: str) -> str:
        sig = hmac.new(self._secret_key, session_id.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"{session_id}.{sig}"

    def _issue_session_locked(self, username: str, role: str) -> Dict[str, Any]:
        now = time.time()
        # Prune expired sessions opportunistically
        self._sessions = {sid: s for sid, s in self._sessions.items() if s["expiresAt"] > now}

        session_id = secrets.token_urlsafe(24)
        expires_at = now + self.session_ttl_seconds
        self._sessions[session_id] = {
            "username": username,
            "role": role,
            "createdAt": int(now),
            "expiresAt": int(expires_at),
        }
        token = self._sign_session_id(session_id)
        return {
            "authenticated": True,
            "username": username,
            "role": role,
            "token": token,
            "expiresAt": int(expires_at * 1000),
            "maxAgeSeconds": int(self.session_ttl_seconds),
        }

    def authenticate_credentials(
        self, username: str, password: str, client_key: str = "unknown"
    ) -> Tuple[bool, int, Dict[str, Any]]:
        if not self._check_rate_limit(client_key):
            return False, 429, {"error": "Too many failed login attempts. Try again later."}

        uname = (username or "").strip()
        pw = password if isinstance(password, str) else ""

        with self._lock:
            user = self._users.get(uname)
            if not user or not verify_password(pw, user.get("passwordHash", "")):
                self._record_failed_attempt(client_key)
                return False, 401, {"error": "Invalid username or password"}

            role = user.get("role", "viewer")
            if role not in ("admin", "viewer"):
                role = "viewer"
            session = self._issue_session_locked(uname, role)
            return True, 200, session

    def verify_token(self, raw_token: str) -> Optional[Dict[str, Any]]:
        """Verify either a signed server session token or a registered API token."""
        if not raw_token or not isinstance(raw_token, str):
            return None
        tok = raw_token.strip()
        if not tok:
            return None

        now = time.time()
        with self._lock:
            # 1. Signed server session token: <session_id>.<hmac_hex>
            if "." in tok:
                session_id, sig = tok.split(".", 1)
                expected_sig = hmac.new(self._secret_key, session_id.encode("utf-8"), hashlib.sha256).hexdigest()
                if hmac.compare_digest(sig, expected_sig):
                    sess = self._sessions.get(session_id)
                    if sess:
                        if sess["expiresAt"] > now:
                            return {
                                "authenticated": True,
                                "username": sess["username"],
                                "role": sess["role"],
                                "sessionId": session_id,
                                "authType": "session",
                            }
                        else:
                            self._sessions.pop(session_id, None)
                            return None

            # 2. Registered API token (hashed SHA-256 comparison)
            digest = hash_api_token(tok)
            for entry in self._api_tokens:
                stored = entry.get("tokenHash", "")
                if stored and hmac.compare_digest(digest, stored):
                    role = entry.get("role", "viewer")
                    return {
                        "authenticated": True,
                        "username": entry.get("name", role),
                        "role": role if role in ("admin", "viewer") else "viewer",
                        "sessionId": None,
                        "authType": "api_token",
                    }

        return None

    def extract_request_principal(self, headers) -> Optional[Dict[str, Any]]:
        """
        Extract and verify authentication strictly from server-verified credentials:
          1. Authorization: Bearer <verified_token>
          2. Cookie: camhub_session=<verified_token>
        Explicitly ignores X-CamHub-Role, arbitrary Bearer tokens, and client IP.
        """
        if headers is None:
            return None

        # 1. Check Authorization Bearer header
        auth_hdr = headers.get("Authorization", "")
        if auth_hdr:
            parts = auth_hdr.strip().split(" ", 1)
            if len(parts) == 2 and parts[0].lower() == "bearer":
                candidate = parts[1].strip()
                principal = self.verify_token(candidate)
                if principal:
                    return principal
                # If an explicit Authorization header was supplied and invalid, do NOT fall back
                return None

        # 2. Check HttpOnly session cookie
        cookie_hdr = headers.get("Cookie", "")
        if cookie_hdr:
            try:
                cookie = SimpleCookie()
                cookie.load(cookie_hdr)
                if SESSION_COOKIE_NAME in cookie:
                    candidate = cookie[SESSION_COOKIE_NAME].value
                    return self.verify_token(candidate)
            except Exception:
                return None

        return None

    def revoke_request_session(self, headers) -> bool:
        """Invalidate active server session on logout."""
        principal = self.extract_request_principal(headers)
        if not principal:
            return False
        sid = principal.get("sessionId")
        if not sid:
            return False
        with self._lock:
            return self._sessions.pop(sid, None) is not None

    def build_session_cookie(self, token: str, max_age: int, is_secure: bool = False) -> str:
        parts = [
            f"{SESSION_COOKIE_NAME}={token}",
            "Path=/",
            f"Max-Age={max_age}",
            "HttpOnly",
            "SameSite=Lax",
        ]
        if is_secure:
            parts.append("Secure")
        return "; ".join(parts)

    def build_clear_cookie(self, is_secure: bool = False) -> str:
        parts = [
            f"{SESSION_COOKIE_NAME}=",
            "Path=/",
            "Max-Age=0",
            "HttpOnly",
            "SameSite=Lax",
        ]
        if is_secure:
            parts.append("Secure")
        return "; ".join(parts)

    def get_allowed_origins(self) -> Set[str]:
        origins: Set[str] = set()
        cfg = self.config_provider() or {}
        sec_cfg = cfg.get("security", {})
        for item in sec_cfg.get("allowedOrigins", []):
            if isinstance(item, str) and item.strip():
                origins.add(item.strip().rstrip("/").lower())
        env_origins = os.environ.get("CAMHUB_ALLOWED_ORIGINS", "")
        for item in env_origins.split(","):
            if item.strip():
                origins.add(item.strip().rstrip("/").lower())
        return origins

    def is_origin_allowed(self, origin: str, headers) -> bool:
        """
        Validate Origin header against:
          1. Same-origin Host (and X-Forwarded-Host when behind a reverse proxy)
          2. Explicitly configured security.allowedOrigins / CAMHUB_ALLOWED_ORIGINS
        Wildcard '*' is never trusted.
        """
        if not origin:
            return True
        norm_origin = origin.strip().rstrip("/").lower()
        parsed = urlparse(norm_origin)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return False

        if norm_origin in self.get_allowed_origins():
            return True

        # Check same-origin against Host / X-Forwarded-Host
        cfg = self.config_provider() or {}
        trust_proxy = cfg.get("security", {}).get("trustProxyHeaders", True)

        candidate_hosts = set()
        host_hdr = (headers.get("Host") or "").strip().lower() if headers else ""
        if host_hdr:
            candidate_hosts.add(host_hdr)
        if trust_proxy and headers:
            xf_host = (headers.get("X-Forwarded-Host") or "").split(",")[0].strip().lower()
            if xf_host:
                candidate_hosts.add(xf_host)

        if parsed.netloc.lower() in candidate_hosts:
            return True

        return False


def _cli_main():
    parser = argparse.ArgumentParser(description="CamHUB Auth Configuration Utility")
    parser.add_argument("--base-dir", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_user = sub.add_parser("set-user", help="Create or update a CamHUB user password")
    p_user.add_argument("--username", required=True)
    p_user.add_argument("--password", required=True)
    p_user.add_argument("--role", choices=["admin", "viewer"], default="viewer")

    p_tok = sub.add_parser("create-token", help="Create a server-verified API token")
    p_tok.add_argument("--name", required=True)
    p_tok.add_argument("--role", choices=["admin", "viewer"], default="viewer")

    args = parser.parse_args()
    mgr = AuthManager(base_dir=args.base_dir)
    if args.cmd == "set-user":
        mgr.set_user(args.username, args.password, role=args.role)
        print(f"Updated user '{args.username}' with role '{args.role}'.")
    elif args.cmd == "create-token":
        tok = mgr.create_api_token(args.name, role=args.role, persist=True)
        print(f"Created {args.role} API token '{args.name}': {tok}")


if __name__ == "__main__":
    _cli_main()
