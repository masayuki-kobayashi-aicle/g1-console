"""Authentication for opening the console beyond loopback from the Jetson. Standard library only.

- The token is ~/.g1console/token (0600). It is generated on first use. Comparison is constant time.
- `/login?token=...` issues a cookie (HttpOnly, SameSite=Strict); afterwards the cookie or `Authorization: Bearer` is used.
- The `Host` header is allowed only for the listen addresses, loopback, and explicitly given names (DNS rebinding protection).
- For POST, if `Origin` is present only the one equal to `Host` is allowed.
- It is plain HTTP, so anyone sniffing the same LAN can leak the token. Motion safety does not rely on this token alone (see the README).
"""
import hmac
import ipaddress
import os
import secrets
import subprocess
import threading
import time
from http.cookies import SimpleCookie
from pathlib import Path

TOKEN_PATH = Path.home() / ".g1console" / "token"
COOKIE_NAME = "g1c_token"
LOOPBACK_NAMES = ("localhost", "127.0.0.1", "::1")
FAIL_LIMIT = 5  # this many failures
FAIL_WINDOW_S = 60.0  # within this many seconds
LOCKOUT_S = 30.0  # lock out for this many seconds
IP_CMD_TIMEOUT_S = 3.0


def load_or_create_token(path=TOKEN_PATH) -> str:
    """Read the token. If missing, generate it and save it with mode 0600."""
    path = Path(path)
    try:
        token = path.read_text(encoding="utf-8").strip()
        if token:
            return token
    except OSError:
        pass
    token = secrets.token_urlsafe(24)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(token + "\n")
    os.chmod(str(path), 0o600)
    return token


def iface_ipv4(name: str, run=subprocess.run) -> str:
    """Return the IPv4 address of a network interface (`ip -4 -o addr show dev NAME`). ValueError if unavailable."""
    if not name or name.startswith("-") or not all(c.isalnum() or c in "._-" for c in name):
        raise ValueError("Invalid interface name: %r" % name)
    try:
        done = run(["ip", "-4", "-o", "addr", "show", "dev", name], capture_output=True, text=True,
                   timeout=IP_CMD_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("Cannot get the IP address of %s: %s" % (name, exc)) from None
    for field in done.stdout.split():
        if "/" in field:
            try:
                return str(ipaddress.IPv4Interface(field).ip)
            except ValueError:
                continue
    raise ValueError("%s has no IPv4 address (is it connected?)" % name)


def parse_bind(value: str) -> str:
    """Validate a --bind value. IPv4 only. 0.0.0.0 (all interfaces) is rejected because it would also open on the robot's internal LAN on eth0."""
    try:
        addr = ipaddress.IPv4Address(value)
    except ValueError:
        raise ValueError("--bind must be an IPv4 address: %r" % value) from None
    if addr.is_unspecified:
        raise ValueError("Cannot listen on 0.0.0.0 (it would also open on the robot's internal LAN). Specify --bind-iface or an individual IP")
    return str(addr)


def is_loopback(addr: str) -> bool:
    try:
        return ipaddress.ip_address(addr).is_loopback
    except ValueError:
        return False


def host_only(header: str) -> str:
    """Host part (lowercase) of the `Host` header, without the port."""
    h = (header or "").strip().lower()
    if h.startswith("["):  # [::1]:18790
        return h[1:].split("]", 1)[0]
    return h.rsplit(":", 1)[0] if h.count(":") == 1 else h


class Auth:
    def __init__(self, token: str, allowed_hosts=(), required: bool = True):
        if required and not token:
            raise ValueError("token is empty")
        self.required = required  # False = do not require a token (only the Host and Origin checks remain)
        self._token = token or ""
        self._hosts = set(LOOPBACK_NAMES) | {h.lower() for h in allowed_hosts}
        self._lock = threading.Lock()
        self._fails = {}  # client ip -> [failure times ...]
        self._locked_until = {}

    def check_host(self, header: str) -> bool:
        return host_only(header) in self._hosts

    def check_origin(self, origin, host_header: str) -> bool:
        """Pass if there is no Origin (curl etc.). If there is, only the one equal to Host."""
        if not origin:
            return True
        netloc = origin.split("://", 1)[-1].rstrip("/")
        return netloc.lower() == (host_header or "").strip().lower()

    def _same(self, candidate: str) -> bool:
        return hmac.compare_digest(candidate.encode("utf-8"), self._token.encode("utf-8"))

    def authorized(self, headers) -> bool:
        """Whether the cookie or Bearer carries the correct token. Failures are not counted here (normal page loads must not count)."""
        if not self.required:
            return True
        bearer = headers.get("Authorization", "")
        if bearer.startswith("Bearer ") and self._same(bearer[len("Bearer "):].strip()):
            return True
        cookie = SimpleCookie()
        try:
            cookie.load(headers.get("Cookie", ""))
        except Exception:  # noqa: BLE001  treat a broken cookie as absent
            return False
        morsel = cookie.get(COOKIE_NAME)
        return bool(morsel) and self._same(morsel.value)

    def throttled(self, client: str, now=None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            return self._locked_until.get(client, 0.0) > now

    def verify(self, candidate: str, client: str, now=None) -> bool:
        """Check the login token. Repeated failures lock that client out for a while. While locked out, even the correct token is rejected."""
        now = time.monotonic() if now is None else now
        with self._lock:
            if self._locked_until.get(client, 0.0) > now:
                return False
            if self._same(candidate or ""):
                self._fails.pop(client, None)
                return True
            recent = [t for t in self._fails.get(client, []) if now - t < FAIL_WINDOW_S] + [now]
            self._fails[client] = recent
            if len(recent) >= FAIL_LIMIT:
                self._locked_until[client] = now + LOCKOUT_S
                self._fails.pop(client, None)
            return False

    def cookie_header(self) -> str:
        return "%s=%s; Path=/; HttpOnly; SameSite=Strict" % (COOKIE_NAME, self._token)
