"""Per-app idle hibernation for docker-ssh experiments.

The public Caddy front door never receives the Docker socket. This module is
the private controller: it may start and stop only the expensive services in
its own Compose project, and it serves hibernation/wake/health state.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from urllib.request import Request, urlopen

STATE_AWAKE = "awake"
STATE_HIBERNATING = "hibernating"
STATE_WAKING = "waking"
HEALTH_PATH = "/health"
MARKER_HIBERNATING = "hibernating"
MARKER_WAKING = "waking"
HEALTH_CACHE_NAME = "health.json"
ACTIVITY_NAME = "last-activity"
ACCESS_LOG_NAME = "access.log"
STOPPABLE_SERVICES = frozenset({"web", "redis", "pgbouncer", "postgresql", "clock"})
STOPPABLE_PREFIXES = ("worker_",)
PROTECTED_SERVICES = frozenset({"frontdoor", "controller", "cloudflared"})
START_ORDER = {
    "postgresql": 0,
    "redis": 1,
    "pgbouncer": 2,
    "web": 3,
    "clock": 4,
}
DEFAULT_DOCKER_API_VERSION = "1.44"
DEFAULT_READY_TIMEOUT = 180.0
CLIENT_REQUEST_TIMEOUT = 3600.0
CONTAINER_READY_TIMEOUT = 30.0
ADMIN_PATHS = frozenset({"/hibernate", "/awaken", "/wake", "/state"})
logger = logging.getLogger(__name__)
SPINNER_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta http-equiv="refresh" content="2">
  <title>Starting experiment</title>
  <style>
    body { font-family: sans-serif; display: grid; place-items: center; min-height: 100vh; }
    .spinner { width: 2rem; height: 2rem; border: 3px solid #ccc; border-top-color: #333;
               border-radius: 50%; animation: spin 1s linear infinite; margin: 0 auto 1rem; }
    @keyframes spin { to { transform: rotate(360deg); } }
  </style>
</head>
<body>
  <div>
    <div class="spinner"></div>
    <p>This experiment is starting. The page will refresh automatically.</p>
  </div>
</body>
</html>
"""


def is_stoppable_service(name: str) -> bool:
    """Return whether a Compose service may be stopped for hibernation."""
    if name in PROTECTED_SERVICES:
        return False
    if name in STOPPABLE_SERVICES:
        return True
    return name.startswith(STOPPABLE_PREFIXES)


def start_priority(container: Mapping[str, Any]) -> int:
    """Return a start order that brings Postgres up before web."""
    service = str(
        (container.get("labels") or {}).get("com.docker.compose.service") or ""
    )
    if service.startswith(STOPPABLE_PREFIXES):
        return 5
    return START_ORDER.get(service, 9)


def select_project_containers(
    containers: Iterable[Mapping[str, Any]], project: str
) -> list[Mapping[str, Any]]:
    """Keep containers that belong to ``project`` and are stoppable."""
    selected = []
    for container in containers:
        labels = container.get("labels") or {}
        compose_project = str(labels.get("com.docker.compose.project") or "")
        if compose_project.lower() != str(project).lower():
            continue
        service = labels.get("com.docker.compose.service") or ""
        if is_stoppable_service(service):
            selected.append(container)
    return selected


class DockerEngine:
    """Tiny Docker Engine API client over a Unix socket."""

    def __init__(
        self,
        socket_path: str = "/var/run/docker.sock",
        api_version: str | None = None,
    ):
        self.socket_path = socket_path
        configured = (api_version or os.environ.get("DOCKER_API_VERSION") or "").lstrip(
            "v"
        )
        self.api_version = configured or self._negotiate_api_version()

    def engine_path(self, path: str) -> str:
        """Prefix an Engine path with a versioned API root."""
        if path.startswith("/v"):
            return path
        return f"/v{self.api_version}{path}"

    def _negotiate_api_version(self) -> str:
        """Pick a version the daemon accepts. Unversioned ``/version`` is required."""
        conn = _UnixHTTPConnection(self.socket_path)
        try:
            conn.request("GET", "/version", headers={"Host": "docker"})
            response = conn.getresponse()
            body = response.read()
            if response.status >= 400:
                raise RuntimeError(
                    f"Docker API GET /version returned HTTP {response.status}: "
                    f"{body.decode('utf-8', errors='replace')}"
                )
            payload = json.loads(body) if body else {}
            minimum = str(
                payload.get("MinAPIVersion") or DEFAULT_DOCKER_API_VERSION
            ).lstrip("v")
            return str(payload.get("ApiVersion") or minimum).lstrip("v")
        except Exception as exc:
            logger.warning("Could not negotiate Docker API version: %s", exc)
            return DEFAULT_DOCKER_API_VERSION
        finally:
            conn.close()

    def containers(self, all_: bool = True) -> list[dict[str, Any]]:
        query = "all=true" if all_ else "all=false"
        payload = self._request("GET", f"/containers/json?{query}")
        items = []
        for item in payload or []:
            items.append(
                {
                    "id": item.get("Id"),
                    "names": item.get("Names") or [],
                    "state": (item.get("State") or "").lower(),
                    "labels": item.get("Labels") or {},
                }
            )
        return items

    def stop(self, container_id: str) -> None:
        self._request("POST", f"/containers/{container_id}/stop", ignore_404=True)

    def start(self, container_id: str) -> None:
        self._request("POST", f"/containers/{container_id}/start", ignore_404=True)

    def inspect(self, container_id: str) -> dict[str, Any]:
        return self._request("GET", f"/containers/{container_id}/json") or {}

    def wait_until_running(self, container_id: str, timeout: float = 60.0) -> None:
        """Block until the container is running, or healthy if it has a check."""
        started = time.monotonic()
        last_error = None
        while True:
            try:
                state = self.inspect(container_id).get("State") or {}
                health = (state.get("Health") or {}).get("Status")
                if health == "healthy":
                    return
                if state.get("Running") and not state.get("Health"):
                    return
            except Exception as exc:
                last_error = exc
            if time.monotonic() - started >= timeout:
                detail = f": {last_error}" if last_error else ""
                raise RuntimeError(
                    f"Container {container_id} did not become ready{detail}"
                )
            time.sleep(0.5)

    def _request(self, method: str, path: str, ignore_404: bool = False) -> Any:
        conn = _UnixHTTPConnection(self.socket_path)
        try:
            conn.request(method, self.engine_path(path), headers={"Host": "docker"})
            response = conn.getresponse()
            body = response.read()
            if response.status == 404 and ignore_404:
                return None
            if response.status >= 400:
                if (
                    response.status == 400
                    and b"too old" in body
                    and not getattr(self, "_renegotiated", False)
                ):
                    self._renegotiated = True
                    self.api_version = self._negotiate_api_version()
                    return self._request(method, path, ignore_404=ignore_404)
                raise RuntimeError(
                    f"Docker API {method} {path} returned HTTP {response.status}: "
                    f"{body.decode('utf-8', errors='replace')}"
                )
            if not body:
                return None
            return json.loads(body)
        finally:
            conn.close()


class _UnixHTTPConnection:
    """HTTP connection over a Unix domain socket."""

    def __init__(self, socket_path: str):
        import http.client
        import socket as sockmod

        self._http_client = http.client
        self._socket_mod = sockmod
        self.socket_path = socket_path
        self.sock = None
        self.conn = None

    def request(self, method, path, headers=None):
        self.conn = self._http_client.HTTPConnection("docker")
        self.conn.sock = self._socket_mod.socket(
            self._socket_mod.AF_UNIX, self._socket_mod.SOCK_STREAM
        )
        self.conn.sock.connect(self.socket_path)
        self.conn.request(method, path, headers=headers or {})

    def getresponse(self):
        return self.conn.getresponse()

    def close(self):
        if self.conn is not None:
            self.conn.close()


class HibernationController:
    """Project-scoped hibernation state machine."""

    def __init__(
        self,
        *,
        project: str,
        state_dir: Path,
        docker: Any,
        web_origin: str = "http://experiment-backend:5000",
        idle_enabled: bool = False,
        idle_minutes: int = 60,
        secret: str = "",
        clock: Callable[[], float] = time.time,
        fetch_health: Callable[[str], dict[str, Any]] | None = None,
        ready_timeout: float = DEFAULT_READY_TIMEOUT,
        poll_interval: float = 1.0,
        manifest_path: Path | None = None,
    ):
        self.project = str(project).lower()
        self.state_dir = Path(state_dir)
        self.manifest_path = Path(manifest_path) if manifest_path else None
        self.docker = docker
        self.web_origin = web_origin.rstrip("/")
        self.idle_enabled = idle_enabled
        self.idle_minutes = max(int(idle_minutes), 1)
        self.secret = secret
        self.clock = clock
        self.fetch_health = fetch_health or _fetch_health
        self.ready_timeout = max(float(ready_timeout), 0.0)
        self.poll_interval = max(float(poll_interval), 0.0)
        self.lock = threading.RLock()
        self._log_offset = 0
        self._log_buf = ""
        self._latest_activity: float | None = None
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._latest_activity = self._read_activity()
        if self._marker(MARKER_WAKING).exists():
            # A controller restart left a wake in progress. Visitors can retry
            # from hibernating, or we mark awake if the backend is already up.
            if self._backend_looks_down():
                self._write_state(STATE_HIBERNATING)
            else:
                self._write_state(STATE_AWAKE)
        elif not self._marker(MARKER_HIBERNATING).exists():
            if self._has_prior_runtime() and self._backend_looks_down():
                self._write_state(STATE_HIBERNATING)
            else:
                self._write_state(STATE_AWAKE)

    def current_state(self) -> str:
        if self._marker(MARKER_WAKING).exists():
            return STATE_WAKING
        if self._marker(MARKER_HIBERNATING).exists():
            return STATE_HIBERNATING
        return STATE_AWAKE

    def authorize(self, provided: str | None) -> bool:
        if not self.secret:
            return True
        return hmac.compare_digest(str(provided or ""), str(self.secret))

    def hibernate(self) -> dict[str, Any]:
        with self.lock:
            cache = self._cache_health()
            self._write_state(STATE_HIBERNATING, health=cache)
            self._stop_expensive()
            return {"status": STATE_HIBERNATING, "health": cache}

    def awaken(self) -> dict[str, Any]:
        with self.lock:
            if self.current_state() != STATE_AWAKE:
                self._write_state(STATE_WAKING)
                try:
                    self._start_expensive()
                    self._wait_until_ready()
                    self._write_state(STATE_AWAKE)
                    # Restart the quiet period. The access log still shows
                    # the old request that caused the sleep, and a CLI awaken
                    # does not add a new one. Persist it so a controller
                    # restart does not treat that old request as current.
                    self._remember_activity(self.clock())
                except Exception:
                    self._write_state(STATE_HIBERNATING)
                    raise
            return {"status": STATE_AWAKE}

    def handle_public_request(self, path: str) -> tuple[int, str, bytes]:
        """Return status, content-type, body for a front-door fallback request."""
        state = self.current_state()
        if path.rstrip("/") == HEALTH_PATH or path.startswith(HEALTH_PATH + "?"):
            return self.health_response()
        if state == STATE_HIBERNATING:
            threading.Thread(target=self.awaken, daemon=True).start()
            return 200, "text/html; charset=utf-8", SPINNER_HTML.encode()
        if state == STATE_WAKING:
            self._resume_awaken_if_stuck()
            return 200, "text/html; charset=utf-8", SPINNER_HTML.encode()
        return (
            503,
            "application/json",
            json.dumps({"status": "unavailable"}).encode(),
        )

    def health_response(self) -> tuple[int, str, bytes]:
        state = self.current_state()
        if state == STATE_HIBERNATING:
            payload = self._read_health_cache()
            payload["status"] = STATE_HIBERNATING
            return 200, "application/json", json.dumps(payload).encode()
        if state == STATE_WAKING:
            try:
                payload = self.fetch_health(f"{self.web_origin}{HEALTH_PATH}")
            except Exception:
                payload = self._read_health_cache()
                payload["status"] = STATE_WAKING
                return 200, "application/json", json.dumps(payload).encode()
            # Do not wait on awaken()'s lock: /health must stay cheap while
            # _wait_until_ready holds it. Promote only if the lock is free.
            if self.lock.acquire(blocking=False):
                try:
                    if self.current_state() == STATE_WAKING:
                        self._write_state(STATE_AWAKE)
                finally:
                    self.lock.release()
            return 200, "application/json", json.dumps(payload).encode()
        try:
            payload = self.fetch_health(f"{self.web_origin}{HEALTH_PATH}")
            return 200, "application/json", json.dumps(payload).encode()
        except Exception:
            return (
                503,
                "application/json",
                json.dumps({"status": "unavailable"}).encode(),
            )

    def _resume_awaken_if_stuck(self) -> None:
        """Restart a leftover wake if no awaken() thread holds the lock."""
        if not self._backend_looks_down():
            return
        if not self.lock.acquire(blocking=False):
            return
        self.lock.release()
        threading.Thread(target=self.awaken, daemon=True).start()

    def maybe_idle_hibernate(self, now: float | None = None) -> bool:
        """Hibernate when idle auto-sleep is enabled and the quiet period elapsed."""
        if not self.idle_enabled:
            return False
        if self.current_state() != STATE_AWAKE:
            return False
        last = self.last_activity(now)
        age_minutes = ((now or self.clock()) - last) / 60.0
        if age_minutes < self.idle_minutes:
            return False
        self.hibernate()
        return True

    def _activity_path(self) -> Path:
        return self.state_dir / ACTIVITY_NAME

    def _read_activity(self) -> float | None:
        """Return the persisted quiet-period start, if any."""
        try:
            return float(self._activity_path().read_text().strip())
        except (OSError, ValueError):
            return None

    def _remember_activity(self, timestamp: float) -> None:
        """Record activity in memory and on disk."""
        self._latest_activity = timestamp
        try:
            self._activity_path().write_text(f"{timestamp}\n")
        except OSError as exc:
            logger.warning("Could not store hibernation activity time: %s", exc)

    def last_activity(self, now: float | None = None) -> float:
        """Latest non-health access-log timestamp, else controller start mtime."""
        self._consume_access_log()
        if self._latest_activity is not None:
            return self._latest_activity
        return self.state_dir.stat().st_mtime

    def _web_running(self) -> bool:
        """Return whether the Compose ``web`` service is running.

        Postgres or Redis coming up during a failed wake is not enough: Caddy
        proxies to ``web``, so a leftover waking marker must not become awake
        until that backend is up.
        """
        for container in select_project_containers(
            self.docker.containers(), self.project
        ):
            service = str(
                (container.get("labels") or {}).get("com.docker.compose.service") or ""
            )
            if (
                service == "web"
                and str(container.get("state") or "").lower() == "running"
            ):
                return True
        return False

    def _backend_looks_down(self) -> bool:
        """Return whether the public web backend looks down, without failing startup."""
        try:
            return not self._web_running()
        except Exception as exc:
            logger.warning("Could not inspect project containers at startup: %s", exc)
            return False

    def _has_prior_runtime(self) -> bool:
        """Return whether this state dir has evidence of a previous run."""
        if (self.state_dir / HEALTH_CACHE_NAME).exists():
            return True
        log_path = self.state_dir / ACCESS_LOG_NAME
        try:
            return log_path.exists() and log_path.stat().st_size > 0
        except OSError:
            return False

    def _stop_expensive(self) -> None:
        for container in select_project_containers(
            self.docker.containers(), self.project
        ):
            self.docker.stop(container["id"])

    def _start_expensive(self) -> None:
        containers = select_project_containers(self.docker.containers(), self.project)
        waiter = getattr(self.docker, "wait_until_running", None)
        timeout = min(
            CONTAINER_READY_TIMEOUT, self.ready_timeout or CONTAINER_READY_TIMEOUT
        )
        for container in sorted(containers, key=start_priority):
            self.docker.start(container["id"])
            if waiter is not None:
                waiter(container["id"], timeout=timeout)

    def _wait_until_ready(self) -> None:
        """Block until the experiment web health endpoint answers."""
        started = time.monotonic()
        last_error = None
        while True:
            try:
                self.fetch_health(f"{self.web_origin}{HEALTH_PATH}")
                return
            except Exception as exc:
                last_error = exc
            if time.monotonic() - started >= self.ready_timeout:
                break
            if self.poll_interval:
                time.sleep(self.poll_interval)
        detail = f": {last_error}" if last_error else ""
        raise RuntimeError(
            f"Experiment {self.project} did not become ready after awaken{detail}"
        )

    def _consume_access_log(self) -> None:
        """Parse only newly appended Caddy JSON access-log bytes."""
        log_path = self.state_dir / ACCESS_LOG_NAME
        if not log_path.exists():
            self._log_offset = 0
            self._log_buf = ""
            return
        size = log_path.stat().st_size
        if size < self._log_offset:
            self._log_offset = 0
            self._log_buf = ""
        with log_path.open("rb") as handle:
            handle.seek(self._log_offset)
            chunk = handle.read()
            self._log_offset = handle.tell()
        text = self._log_buf + chunk.decode("utf-8", errors="replace")
        lines = text.split("\n")
        self._log_buf = lines[-1]
        for line in lines[:-1]:
            ts = _access_log_timestamp(line)
            if ts is None:
                continue
            if self._latest_activity is None:
                self._latest_activity = ts
            else:
                self._latest_activity = max(self._latest_activity, ts)

    def _cache_health(self) -> dict[str, Any]:
        try:
            payload = self.fetch_health(f"{self.web_origin}{HEALTH_PATH}")
        except Exception:
            payload = {"status": STATE_HIBERNATING}
        (self.state_dir / HEALTH_CACHE_NAME).write_text(json.dumps(payload))
        return payload

    def _read_health_cache(self) -> dict[str, Any]:
        path = self.state_dir / HEALTH_CACHE_NAME
        if not path.exists():
            return {"status": self.current_state()}
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            return {"status": self.current_state()}
        if isinstance(data, dict):
            return data
        return {"status": self.current_state()}

    def _write_state(self, state: str, health: dict[str, Any] | None = None) -> None:
        hibernating = self._marker(MARKER_HIBERNATING)
        waking = self._marker(MARKER_WAKING)
        if state == STATE_HIBERNATING:
            hibernating.write_text("")
            if waking.exists():
                waking.unlink()
        elif state == STATE_WAKING:
            waking.write_text("")
            if hibernating.exists():
                hibernating.unlink()
        else:
            if hibernating.exists():
                hibernating.unlink()
            if waking.exists():
                waking.unlink()
        self._sync_manifest_state(state)
        if health is not None:
            (self.state_dir / HEALTH_CACHE_NAME).write_text(json.dumps(health))

    def _marker(self, name: str) -> Path:
        return self.state_dir / name

    def _sync_manifest_state(self, state: str) -> None:
        """Keep sibling deployment.json in sync with live markers."""
        manifest_path = self.manifest_path
        if manifest_path is None:
            manifest_path = self.state_dir.parent / "deployment.json"
        if not manifest_path.is_file():
            return
        try:
            payload = json.loads(manifest_path.read_text())
            if not isinstance(payload, dict):
                return
            hibernation = payload.get("hibernation")
            if not isinstance(hibernation, dict):
                hibernation = {}
                payload["hibernation"] = hibernation
            hibernation["state"] = state
            manifest_path.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n"
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
            logger.warning(
                "Could not update %s hibernation state: %s", manifest_path, exc
            )


def _fetch_health(url: str) -> dict[str, Any]:
    request = Request(url, method="GET")
    with urlopen(request, timeout=5) as response:
        raw = response.read().decode("utf-8")
    data = json.loads(raw) if raw else {}
    if not isinstance(data, dict):
        return {"status": "ok"}
    return data


def _access_log_timestamp(line: str) -> float | None:
    """Parse a Caddy JSON access log line, ignoring /health."""
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return None
    request = event.get("request") or {}
    uri = str(request.get("uri") or request.get("url") or "")
    path = uri.split("?", 1)[0].rstrip("/")
    if path == HEALTH_PATH:
        return None
    ts = event.get("ts") or event.get("timestamp")
    if isinstance(ts, (int, float)):
        return float(ts)
    return None


def idle_loop(
    controller: HibernationController,
    interval: float = 30.0,
    stop: threading.Event | None = None,
) -> None:
    """Poll idle timing until ``stop`` is set."""
    halt = stop or threading.Event()
    while not halt.wait(interval):
        try:
            controller.maybe_idle_hibernate()
        except Exception:
            logger.exception("Idle hibernation check failed")


def make_handler(controller: HibernationController):
    """Return a BaseHTTPRequestHandler bound to ``controller``."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self._handle()

        def do_POST(self):  # noqa: N802
            self._handle()

        def log_message(self, format, *args):
            return

        def _handle(self):
            path = self.path.split("?", 1)[0].rstrip("/") or "/"
            admin = path in ADMIN_PATHS
            if admin and not controller.authorize(
                self.headers.get("X-Hibernation-Secret")
            ):
                self._write(403, "application/json", b'{"error":"forbidden"}')
                return
            if path == "/health":
                status, content_type, body = controller.health_response()
                self._write(status, content_type, body)
                return
            if path == "/hibernate" and self.command == "POST":
                payload = controller.hibernate()
                self._write(200, "application/json", json.dumps(payload).encode())
                return
            if path in {"/awaken", "/wake"} and self.command in {"GET", "POST"}:
                payload = controller.awaken()
                if self.headers.get("Accept", "").startswith("text/html"):
                    self._write(200, "text/html; charset=utf-8", SPINNER_HTML.encode())
                    return
                self._write(200, "application/json", json.dumps(payload).encode())
                return
            if path == "/state":
                self._write(
                    200,
                    "application/json",
                    json.dumps({"status": controller.current_state()}).encode(),
                )
                return
            status, content_type, body = controller.handle_public_request(self.path)
            self._write(status, content_type, body)

        def _write(self, status, content_type, body):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def controller_from_env() -> HibernationController:
    """Build a controller from hibernation environment variables."""
    manifest = os.environ.get("HIBERNATION_MANIFEST_PATH", "").strip()
    return HibernationController(
        project=os.environ.get("COMPOSE_PROJECT_NAME")
        or os.environ.get("HIBERNATION_PROJECT")
        or "",
        state_dir=Path(os.environ.get("HIBERNATION_STATE_DIR", "/state")),
        docker=DockerEngine(os.environ.get("DOCKER_SOCKET", "/var/run/docker.sock")),
        web_origin=os.environ.get("WEB_ORIGIN", "http://experiment-backend:5000"),
        idle_enabled=os.environ.get("IDLE_ENABLED", "").lower() in {"1", "true", "yes"},
        idle_minutes=int(os.environ.get("IDLE_MINUTES", "60") or "60"),
        secret=os.environ.get("HIBERNATION_SECRET", ""),
        manifest_path=Path(manifest) if manifest else None,
    )


def serve_from_env() -> None:
    """Serve the controller configured from the process environment."""
    serve_controller(controller_from_env())


def serve_controller(
    controller: HibernationController, host: str = "0.0.0.0", port: int = 8080
):
    """Run the controller HTTP server and idle loop."""
    stop = threading.Event()
    thread = threading.Thread(
        target=idle_loop, args=(controller, 30.0, stop), daemon=True
    )
    thread.start()
    server = ThreadingHTTPServer((host, port), make_handler(controller))
    try:
        server.serve_forever()
    finally:
        stop.set()
        server.server_close()


def client_request(
    action: str, secret: str, origin: str = "http://127.0.0.1:8080"
) -> dict[str, Any]:
    """Call the in-container controller HTTP API."""
    path = {"hibernate": "/hibernate", "awaken": "/awaken", "state": "/state"}[action]
    method = "GET" if action == "state" else "POST"
    request = Request(
        f"{origin}{path}",
        method=method,
        headers={"X-Hibernation-Secret": secret, "Content-Type": "application/json"},
        data=b"{}" if method == "POST" else None,
    )
    with urlopen(request, timeout=CLIENT_REQUEST_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8") or "{}")
