"""Per-app idle hibernation for docker-ssh experiments.

The public Caddy front door never receives the Docker socket. This module is
the private controller: it may start and stop only the expensive services in
its own Compose project, and it serves the wait page and parked ``/health``.

State lives in two marker files in the state directory, ``hibernating`` and
``waking``; the front door routes to this controller while either exists. An
app is hibernating only after ``hibernate`` or idle sleep. Idle time is
measured from when the front door last wrote its access log, which skips
``/health``.
"""

from __future__ import annotations

import http.client
import json
import logging
import os
import socket
import sys
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
DEFAULT_READY_TIMEOUT = 180.0
CLIENT_REQUEST_TIMEOUT = 3600.0
CONTAINER_READY_TIMEOUT = 30.0
ADMIN_PATHS = frozenset({"/hibernate", "/awaken"})
logger = logging.getLogger(__name__)
SPINNER_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Getting ready...</title>
  <noscript><meta http-equiv="refresh" content="3"></noscript>
  <style>
    body { font-family: sans-serif; display: grid; place-items: center; min-height: 100vh; margin: 0; }
    .spinner { width: 2rem; height: 2rem; border: 3px solid #ccc; border-top-color: #333;
               border-radius: 50%; animation: spin 1s linear infinite; margin: 0 auto 1rem; }
    @keyframes spin { to { transform: rotate(360deg); } }
  </style>
</head>
<body id="hibernation-wait">
  <div>
    <div class="spinner"></div>
    <p>Getting ready, please wait...</p>
  </div>
  <script>
    (function () {
      var PAGE = {cache: "no-store", headers: {Accept: "text/html"}};
      var reloading = false;
      var ticks = 0;
      function tick() {
        if (reloading) {
          return;
        }
        ticks += 1;
        fetch("/health", {cache: "no-store"})
          .then(function (response) { return response.json(); })
          .then(function (data) {
            var status = data && data.status;
            if (status === "hibernating" && ticks % 5 === 0) {
              return fetch(location.href, PAGE);
            }
            if (!status || status === "hibernating" || status === "waking") {
              return;
            }
            return fetch(location.href, PAGE)
              .then(function (response) { return response.text(); })
              .then(function (text) {
                if (text.indexOf('id="hibernation-wait"') === -1) {
                  reloading = true;
                  location.reload();
                }
              });
          })
          .catch(function () {})
          .then(function () {
            if (!reloading) {
              setTimeout(tick, 1000);
            }
          });
      }
      setTimeout(tick, 1000);
    })();
  </script>
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


class _UnixHTTPConnection(http.client.HTTPConnection):
    """HTTP connection over a Unix domain socket."""

    def __init__(self, socket_path: str):
        super().__init__("docker")
        self.socket_path = socket_path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self.socket_path)


class DockerEngine:
    """Tiny Docker Engine API client over a Unix socket.

    Paths are unversioned, so the daemon answers with its own API version.
    The controller reads only ids, states, labels, and health status.
    """

    def __init__(self, socket_path: str = "/var/run/docker.sock"):
        self.socket_path = socket_path

    def containers(self) -> list[dict[str, Any]]:
        return [
            {
                "id": item.get("Id"),
                "state": (item.get("State") or "").lower(),
                "labels": item.get("Labels") or {},
            }
            for item in self._request("GET", "/containers/json?all=true") or []
        ]

    def stop(self, container_id: str) -> None:
        # Give Postgres time to shut down cleanly instead of Docker's 10 s.
        self._request("POST", f"/containers/{container_id}/stop?t=30", ignore_404=True)

    def start(self, container_id: str) -> None:
        self._request("POST", f"/containers/{container_id}/start", ignore_404=True)

    def inspect(self, container_id: str) -> dict[str, Any]:
        return self._request("GET", f"/containers/{container_id}/json") or {}

    def wait_until_running(self, container_id: str, timeout: float) -> None:
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
            conn.request(method, path, headers={"Host": "docker"})
            response = conn.getresponse()
            body = response.read()
        finally:
            conn.close()
        if response.status == 404 and ignore_404:
            return None
        if response.status >= 400:
            raise RuntimeError(
                f"Docker API {method} {path} returned HTTP {response.status}: "
                f"{body.decode('utf-8', errors='replace')}"
            )
        return json.loads(body) if body else None


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
        clock: Callable[[], float] = time.time,
        fetch_health: Callable[[str], dict[str, Any]] | None = None,
        ready_timeout: float = DEFAULT_READY_TIMEOUT,
        poll_interval: float = 1.0,
    ):
        self.project = str(project).lower()
        self.state_dir = Path(state_dir)
        self.docker = docker
        self.web_origin = web_origin.rstrip("/")
        self.idle_enabled = idle_enabled
        self.idle_minutes = max(int(idle_minutes), 1)
        self.clock = clock
        self.fetch_health = fetch_health or _fetch_health
        self.ready_timeout = max(float(ready_timeout), 0.0)
        self.poll_interval = max(float(poll_interval), 0.0)
        self.lock = threading.RLock()
        self._wake_guard = threading.Lock()
        self._wake_thread: threading.Thread | None = None
        self.state_dir.mkdir(parents=True, exist_ok=True)
        # The quiet period restarts when the controller starts and when the
        # app wakes, so an update or reboot never sleeps an app at once.
        self._quiet_since = self.clock()
        if self._marker(STATE_WAKING).exists():
            # The wake that wrote this marker died with the old controller.
            # The next visitor or ``awaken`` retries it.
            self._write_state(STATE_HIBERNATING)

    def current_state(self) -> str:
        if self._marker(STATE_WAKING).exists():
            return STATE_WAKING
        if self._marker(STATE_HIBERNATING).exists():
            return STATE_HIBERNATING
        return STATE_AWAKE

    def hibernate(self) -> dict[str, Any]:
        with self.lock:
            self._write_state(STATE_HIBERNATING)
            containers = sorted(self._project_containers(), key=start_priority)
            for container in reversed(containers):
                self.docker.stop(container["id"])
            return {"status": STATE_HIBERNATING}

    def awaken(self) -> dict[str, Any]:
        with self.lock:
            if self.current_state() != STATE_AWAKE:
                self._write_state(STATE_WAKING)
                try:
                    self._start_expensive()
                    self._wait_until_ready()
                except Exception:
                    # ``--update`` may have cleared the markers meanwhile.
                    if self._marker(STATE_WAKING).exists():
                        self._write_state(STATE_HIBERNATING)
                    raise
                self._write_state(STATE_AWAKE)
                self._quiet_since = self.clock()
            return {"status": STATE_AWAKE}

    def handle_public_request(
        self, method: str = "GET", accept: str = "text/html"
    ) -> tuple[int, str, bytes]:
        """Answer a visitor the front door routed here while the app is parked.

        Page loads get the wait page. Other requests (API calls, form posts)
        get a JSON 503, so clients do not mistake the wait page for data.
        """
        state = self.current_state()
        if state == STATE_AWAKE:
            return 503, "application/json", b'{"status":"unavailable"}'
        if state == STATE_HIBERNATING:
            self._wake_in_background()
        if method == "GET" and "text/html" in accept:
            return 200, "text/html; charset=utf-8", SPINNER_HTML.encode()
        return 503, "application/json", json.dumps({"status": state}).encode()

    def _wake_in_background(self) -> None:
        """Start one background wake; later visitors do not start more."""
        with self._wake_guard:
            if self._wake_thread is None or not self._wake_thread.is_alive():
                self._wake_thread = threading.Thread(
                    target=self._awaken_logging_errors, daemon=True
                )
                self._wake_thread.start()

    def _awaken_logging_errors(self) -> None:
        try:
            self.awaken()
        except Exception:
            logger.exception("Waking %s failed; the next visitor retries", self.project)

    def health_response(self) -> tuple[int, str, bytes]:
        state = self.current_state()
        if state != STATE_AWAKE:
            return 200, "application/json", json.dumps({"status": state}).encode()
        try:
            payload = self.fetch_health(f"{self.web_origin}{HEALTH_PATH}")
        except Exception:
            return 503, "application/json", b'{"status":"unavailable"}'
        return 200, "application/json", json.dumps(payload).encode()

    def maybe_idle_hibernate(self) -> bool:
        """Hibernate when idle sleep is enabled and the quiet period elapsed."""
        if not self.idle_enabled:
            return False
        with self.lock:
            if self.current_state() != STATE_AWAKE:
                return False
            if (self.clock() - self.last_activity()) / 60.0 < self.idle_minutes:
                return False
            self.hibernate()
            return True

    def last_activity(self) -> float:
        """Latest non-health request seen by the front door, or quiet-period start."""
        try:
            logged = (self.state_dir / ACCESS_LOG_NAME).stat().st_mtime
        except OSError:
            logged = 0.0
        return max(logged, self._quiet_since)

    def _project_containers(self) -> list[Mapping[str, Any]]:
        return select_project_containers(self.docker.containers(), self.project)

    def _start_expensive(self) -> None:
        timeout = min(
            CONTAINER_READY_TIMEOUT, self.ready_timeout or CONTAINER_READY_TIMEOUT
        )
        for container in sorted(self._project_containers(), key=start_priority):
            self.docker.start(container["id"])
            self.docker.wait_until_running(container["id"], timeout=timeout)

    def _wait_until_ready(self) -> None:
        """Block until the experiment web health endpoint answers."""
        started = time.monotonic()
        while True:
            try:
                self.fetch_health(f"{self.web_origin}{HEALTH_PATH}")
                return
            except Exception as exc:
                if time.monotonic() - started >= self.ready_timeout:
                    raise RuntimeError(
                        f"Experiment {self.project} did not become ready "
                        f"after awaken: {exc}"
                    ) from exc
            time.sleep(self.poll_interval)

    def _write_state(self, state: str) -> None:
        for marker in (STATE_HIBERNATING, STATE_WAKING):
            path = self._marker(marker)
            if marker == state:
                path.write_text("")
            elif path.exists():
                path.unlink()

    def _marker(self, name: str) -> Path:
        return self.state_dir / name


def _fetch_health(url: str) -> dict[str, Any]:
    with urlopen(Request(url, method="GET"), timeout=5) as response:
        raw = response.read().decode("utf-8")
    data = json.loads(raw) if raw else {}
    return data if isinstance(data, dict) else {"status": "ok"}


def is_loopback(host: str) -> bool:
    """Return whether a request came from inside the controller container.

    Admin calls arrive through ``docker compose exec controller``. The front
    door and the experiment containers reach the controller from their own
    addresses on the app network, so they cannot hibernate or wake the app.
    """
    return host in {"127.0.0.1", "::1"}


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

        do_PUT = do_PATCH = do_DELETE = do_POST

        def log_message(self, format, *args):
            return

        def _handle(self):
            path = self.path.split("?", 1)[0].rstrip("/") or "/"
            if path in ADMIN_PATHS:
                if self.command != "POST" or not is_loopback(self.client_address[0]):
                    self._write(403, "application/json", b'{"error":"forbidden"}')
                    return
                action = (
                    controller.hibernate if path == "/hibernate" else controller.awaken
                )
                try:
                    payload = action()
                except Exception as exc:
                    logger.exception("%s failed", path)
                    self._write(
                        500,
                        "application/json",
                        json.dumps({"error": str(exc)}).encode(),
                    )
                    return
                self._write(200, "application/json", json.dumps(payload).encode())
            elif path == HEALTH_PATH:
                self._write(*controller.health_response())
            else:
                self._write(
                    *controller.handle_public_request(
                        self.command, self.headers.get("Accept", "")
                    )
                )

        def _write(self, status, content_type, body):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            if status == 503:
                self.send_header("Retry-After", "5")
            self.end_headers()
            self.wfile.write(body)

    return Handler


def controller_from_env() -> HibernationController:
    """Build a controller from the environment the Compose file sets."""
    return HibernationController(
        project=os.environ["COMPOSE_PROJECT_NAME"],
        state_dir=Path("/state"),
        docker=DockerEngine(),
        idle_enabled=os.environ.get("IDLE_ENABLED", "").lower() == "true",
        idle_minutes=int(os.environ.get("IDLE_MINUTES") or 60),
    )


def serve_from_env() -> None:
    """Serve the controller configured from the process environment."""
    serve_controller(controller_from_env())


def serve_controller(
    controller: HibernationController, host: str = "0.0.0.0", port: int = 8080
):
    """Run the controller HTTP server and idle loop."""
    stop = threading.Event()
    threading.Thread(
        target=idle_loop, args=(controller, 30.0, stop), daemon=True
    ).start()
    server = ThreadingHTTPServer((host, port), make_handler(controller))
    try:
        server.serve_forever()
    finally:
        stop.set()
        server.server_close()


def client_request(action: str) -> dict[str, Any]:
    """POST ``hibernate`` or ``awaken`` to the controller in this container."""
    request = Request(
        f"http://127.0.0.1:8080/{action}",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=b"{}",
    )
    with urlopen(request, timeout=CLIENT_REQUEST_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8") or "{}")


if __name__ == "__main__":
    # The controller container runs this file directly: ``serve`` starts the
    # controller, and ``hibernate``/``awaken`` (via ``docker compose exec``)
    # call it. It uses only the standard library, so it does not depend on
    # the Dallinger version inside the experiment image.
    if sys.argv[1] == "serve":
        serve_from_env()
    else:
        print(json.dumps(client_request(sys.argv[1])))
