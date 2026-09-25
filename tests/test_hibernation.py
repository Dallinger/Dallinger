import json
import os
import threading
import time
from pathlib import Path

import pytest

from dallinger.hibernation import (
    SPINNER_HTML,
    STATE_HIBERNATING,
    STATE_WAKING,
    DockerEngine,
    HibernationController,
    idle_loop,
    is_loopback,
    is_stoppable_service,
    make_handler,
    select_project_containers,
    start_priority,
)


def test_wait_page_keeps_the_spinner_until_the_app_is_ready():
    assert "Getting ready, please wait..." in SPINNER_HTML
    assert 'id="hibernation-wait"' in SPINNER_HTML
    assert 'fetch("/health"' in SPINNER_HTML
    head, _, _rest = SPINNER_HTML.partition("<noscript>")
    assert 'http-equiv="refresh"' not in head


class FakeDocker:
    def __init__(self, containers):
        self._containers = containers
        self.stopped = []
        self.started = []

    def containers(self):
        return list(self._containers)

    def stop(self, container_id):
        self.stopped.append(container_id)
        for item in self._containers:
            if item["id"] == container_id:
                item["state"] = "exited"

    def start(self, container_id):
        self.started.append(container_id)
        for item in self._containers:
            if item["id"] == container_id:
                item["state"] = "running"

    def wait_until_running(self, container_id, timeout):
        self.started.append(f"wait:{container_id}")


def _container(service, project="demo", cid=None, extra_project=None):
    return {
        "id": cid or f"id-{service}",
        "state": "running",
        "labels": {
            "com.docker.compose.project": extra_project or project,
            "com.docker.compose.service": service,
        },
    }


def _controller(tmp_path, docker, **overrides):
    settings = dict(
        project="demo",
        state_dir=tmp_path,
        docker=docker,
        idle_enabled=True,
        idle_minutes=1,
        clock=lambda: 1_700_000_000,
        fetch_health=lambda url: {"status": "ok"},
    )
    settings.update(overrides)
    return HibernationController(**settings)


def test_stoppable_allowlist_protects_front_door_and_tunnel():
    assert is_stoppable_service("web")
    assert is_stoppable_service("worker_2")
    assert is_stoppable_service("postgresql")
    assert not is_stoppable_service("frontdoor")
    assert not is_stoppable_service("controller")
    assert not is_stoppable_service("cloudflared")


def test_select_project_containers_ignores_other_compose_projects():
    containers = [
        _container("web"),
        _container("frontdoor"),
        _container("web", extra_project="other", cid="other-web"),
        _container("worker_1"),
    ]
    selected = select_project_containers(containers, "demo")
    assert {item["id"] for item in selected} == {"id-web", "id-worker_1"}


def test_hibernate_stops_only_expensive_services(tmp_path):
    docker = FakeDocker(
        [
            _container("web"),
            _container("redis"),
            _container("frontdoor"),
            _container("controller"),
            _container("cloudflared"),
        ]
    )
    controller = _controller(tmp_path, docker)
    payload = controller.hibernate()
    assert payload["status"] == "hibernating"
    assert set(docker.stopped) == {"id-web", "id-redis"}
    assert "id-frontdoor" not in docker.stopped
    status, content_type, body = controller.health_response()
    assert status == 200
    assert content_type == "application/json"
    assert json.loads(body) == {"status": "hibernating"}


def test_idle_sleep_follows_the_access_log(tmp_path):
    docker = FakeDocker([_container("web")])
    now = [1_700_000_000]
    controller = _controller(tmp_path, docker, clock=lambda: now[0], idle_minutes=1)
    log = tmp_path / "access.log"
    log.write_text("{}\n")
    os.utime(log, (now[0] + 30, now[0] + 30))
    now[0] += 80
    assert controller.maybe_idle_hibernate() is False
    now[0] += 20
    assert controller.maybe_idle_hibernate() is True
    assert controller.current_state() == "hibernating"


def test_start_and_awaken_restart_the_quiet_period(tmp_path):
    docker = FakeDocker([_container("web")])
    now = [1_700_000_000]
    log = tmp_path / "access.log"
    log.write_text("{}\n")
    os.utime(log, (now[0] - 3600, now[0] - 3600))
    controller = _controller(tmp_path, docker, clock=lambda: now[0], idle_minutes=1)
    assert controller.maybe_idle_hibernate() is False
    now[0] += 61
    assert controller.maybe_idle_hibernate() is True
    controller.awaken()
    assert controller.maybe_idle_hibernate() is False


def test_intentional_sleep_wakes_on_visit(tmp_path):
    docker = FakeDocker([_container("web")])
    controller = _controller(tmp_path, docker)
    controller.hibernate()
    status, _, body = controller.handle_public_request()
    assert status == 200
    assert b"getting ready" in body.lower()
    controller.awaken()
    assert "id-web" in docker.started


def test_crash_returns_503_without_restart(tmp_path):
    docker = FakeDocker([_container("web")])
    controller = _controller(tmp_path, docker)
    status, _, body = controller.handle_public_request()
    assert status == 503
    assert json.loads(body)["status"] == "unavailable"
    assert docker.started == []
    assert docker.stopped == []


def test_waking_health_reports_waking_until_awaken_finishes(tmp_path):
    docker = FakeDocker([_container("web")])
    controller = _controller(tmp_path, docker)
    controller._write_state("waking")
    status, _type, body = controller.health_response()
    assert status == 200
    assert json.loads(body)["status"] == "waking"
    assert controller.current_state() == "waking"


def test_wait_until_running_waits_for_healthcheck():
    engine = DockerEngine()
    states = iter(
        [
            {"State": {"Running": True, "Health": {"Status": "starting"}}},
            {"State": {"Running": True, "Health": {"Status": "healthy"}}},
        ]
    )
    engine.inspect = lambda container_id: next(states)
    engine.wait_until_running("abc", timeout=2)


def test_awaken_waits_for_web_health_and_starts_postgres_first(tmp_path):
    docker = FakeDocker(
        [_container("web"), _container("redis"), _container("postgresql")]
    )
    calls = {"n": 0}

    def fetch(url):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("postgres still starting")
        return {"status": "ok"}

    controller = _controller(
        tmp_path, docker, fetch_health=fetch, poll_interval=0, ready_timeout=5
    )
    controller.hibernate()
    payload = controller.awaken()
    assert payload["status"] == "awake"
    assert controller.current_state() == "awake"
    assert docker.started[0] == "id-postgresql"
    assert docker.started.index("wait:id-postgresql") < docker.started.index("id-redis")
    assert docker.started.index("wait:id-redis") < docker.started.index("id-web")
    assert calls["n"] == 3


def test_awaken_timeout_returns_to_hibernating(tmp_path):
    docker = FakeDocker([_container("web")])

    def fetch(url):
        raise RuntimeError("down")

    controller = _controller(
        tmp_path, docker, fetch_health=fetch, poll_interval=0, ready_timeout=0
    )
    controller.hibernate()
    with pytest.raises(RuntimeError, match="did not become ready"):
        controller.awaken()
    assert controller.current_state() == "hibernating"


def test_concurrent_awaken_ends_awake_once(tmp_path):
    import threading

    docker = FakeDocker([_container("web")])
    controller = _controller(tmp_path, docker, poll_interval=0)
    controller.hibernate()
    errors = []

    def go():
        try:
            controller.awaken()
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=go) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert controller.current_state() == "awake"


def test_start_priority_orders_postgres_before_web():
    postgres = _container("postgresql")
    web = _container("web")
    assert start_priority(postgres) < start_priority(web)


def test_select_project_containers_matches_compose_lowercase_project():
    containers = [_container("web", extra_project="demoapp")]
    selected = select_project_containers(containers, "DemoApp")
    assert [item["id"] for item in selected] == ["id-web"]


def test_caddyfile_excludes_docker_socket_and_sends_health_to_controller():
    caddy = Path("dallinger/docker/ssh_templates/Caddyfile.frontdoor").read_text()
    assert "docker.sock" not in caddy
    assert "/health" in caddy
    assert "controller:8080" in caddy
    assert "experiment-backend:5000" in caddy
    assert "reverse_proxy web:5000" not in caddy
    assert "flush_interval -1" in caddy
    assert caddy.count("@parked") == 2
    assert "log_skip @health" in caddy
    assert f"try_files {STATE_HIBERNATING} {STATE_WAKING}" in caddy
    assert "handle_errors {" in caddy
    assert caddy.find("handle_errors") > caddy.find("flush_interval")
    assert "{>" not in caddy
    assert "header_up Connection" not in caddy
    assert "header_up Upgrade" not in caddy


def test_hibernate_writes_marker_before_stopping_containers(tmp_path):
    docker = FakeDocker([_container("web")])
    controller = _controller(tmp_path, docker)
    marker_during_stop = {}

    def stop(container_id):
        marker_during_stop["present"] = (tmp_path / "hibernating").exists()
        docker.__class__.stop(docker, container_id)

    docker.stop = stop
    controller.hibernate()
    assert marker_during_stop["present"] is True
    assert controller.current_state() == "hibernating"


def test_controller_start_does_not_infer_sleep_from_a_down_backend(tmp_path):
    docker = FakeDocker([_container("web")])
    docker._containers[0]["state"] = "exited"
    controller = _controller(tmp_path, docker)
    assert controller.current_state() == "awake"
    status, _, _ = controller.handle_public_request()
    assert status == 503


def test_leftover_waking_marker_becomes_hibernating(tmp_path):
    (tmp_path / "waking").write_text("")
    docker = FakeDocker([_container("web")])
    controller = _controller(tmp_path, docker)
    assert controller.current_state() == "hibernating"


def test_idle_loop_keeps_running_after_check_failure():
    calls = {"n": 0}

    class Boom:
        def maybe_idle_hibernate(self):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("docker blip")

    stop = threading.Event()
    thread = threading.Thread(target=idle_loop, args=(Boom(), 0.01, stop), daemon=True)
    thread.start()
    deadline = time.time() + 2
    while calls["n"] < 2 and time.time() < deadline:
        time.sleep(0.01)
    stop.set()
    thread.join(1)
    assert calls["n"] >= 2


def test_only_loopback_callers_are_admins():
    assert is_loopback("127.0.0.1")
    assert is_loopback("::1")
    assert not is_loopback("172.18.0.5")


def test_admin_routes_need_post_public_routes_do_not(tmp_path):
    import threading
    from http.server import ThreadingHTTPServer
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen

    docker = FakeDocker([_container("web")])
    controller = _controller(tmp_path, docker)
    controller.hibernate()
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(controller))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    origin = f"http://{host}:{port}"
    try:
        with pytest.raises(HTTPError) as err:
            urlopen(f"{origin}/hibernate", timeout=2)
        assert err.value.code == 403
        with urlopen(f"{origin}/health", timeout=2) as response:
            assert response.status == 200
        page = Request(f"{origin}/ad", headers={"Accept": "text/html"})
        with urlopen(page, timeout=2) as response:
            assert response.status == 200
            assert response.headers["Cache-Control"] == "no-store"
            assert b"getting ready" in response.read().lower()
        controller._wake_thread.join(2)
        controller.hibernate()
        with pytest.raises(HTTPError) as err:
            urlopen(Request(f"{origin}/response", data=b"{}", method="POST"), timeout=2)
        assert err.value.code == 503
        assert err.value.headers["Retry-After"] == "5"
        assert json.loads(err.value.read())["status"] == "hibernating"
        controller._wake_thread.join(2)
        controller.hibernate()
        request = Request(
            f"{origin}/awaken",
            data=b"{}",
            method="POST",
        )
        with urlopen(request, timeout=2) as response:
            assert json.loads(response.read())["status"] == "awake"
    finally:
        server.shutdown()
        server.server_close()


def test_failed_admin_action_returns_json_error(tmp_path):
    from http.server import ThreadingHTTPServer
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen

    controller = _controller(
        tmp_path,
        FakeDocker([_container("web")]),
        fetch_health=lambda url: (_ for _ in ()).throw(RuntimeError("down")),
        ready_timeout=0,
    )
    controller.hibernate()
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(controller))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    host, port = server.server_address
    try:
        with pytest.raises(HTTPError) as err:
            urlopen(
                Request(f"http://{host}:{port}/awaken", data=b"{}", method="POST"),
                timeout=5,
            )
        assert err.value.code == 500
        assert "did not become ready" in json.loads(err.value.read())["error"]
    finally:
        server.shutdown()
        server.server_close()


def test_failed_wake_keeps_markers_cleared_by_an_update(tmp_path):
    def fetch(url):
        for marker in ("waking", "hibernating"):
            (tmp_path / marker).unlink(missing_ok=True)
        raise RuntimeError("down")

    controller = _controller(
        tmp_path, FakeDocker([_container("web")]), fetch_health=fetch, ready_timeout=0
    )
    controller.hibernate()
    with pytest.raises(RuntimeError):
        controller.awaken()
    assert controller.current_state() == "awake"


def test_hibernate_stops_web_before_postgres(tmp_path):
    docker = FakeDocker([_container("postgresql"), _container("web")])
    _controller(tmp_path, docker).hibernate()
    assert docker.stopped == ["id-web", "id-postgresql"]
