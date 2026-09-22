import json
import threading
import time
from pathlib import Path

import pytest

from dallinger.hibernation import (
    SPINNER_HTML,
    DockerEngine,
    HibernationController,
    idle_loop,
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

    def containers(self, all_=True):
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

    def wait_until_running(self, container_id, timeout=60.0):
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
        secret="s3cret",
        clock=lambda: 1_700_000_000,
        fetch_health=lambda url: {"status": "ok", "n": 1},
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


def test_hibernate_stops_only_expensive_services_and_caches_health(tmp_path):
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
    assert json.loads(body)["status"] == "hibernating"
    assert json.loads(body)["n"] == 1


def test_health_probes_do_not_count_as_activity(tmp_path):
    docker = FakeDocker([_container("web")])
    now = 1_700_000_060
    log = tmp_path / "access.log"
    log.write_text(
        json.dumps({"ts": 1_700_000_000, "request": {"uri": "/ad"}})
        + "\n"
        + json.dumps({"ts": now, "request": {"uri": "/health"}})
        + "\n"
        + json.dumps({"ts": now, "request": {"uri": "/health/?probe=1"}})
        + "\n"
    )
    controller = _controller(tmp_path, docker, clock=lambda: now, idle_minutes=1)
    assert controller.last_activity(now) == 1_700_000_000
    assert controller.maybe_idle_hibernate(now) is True
    assert controller.current_state() == "hibernating"


def test_awaken_restarts_the_idle_quiet_period(tmp_path):
    docker = FakeDocker([_container("web")])
    now = 1_700_000_060
    (tmp_path / "access.log").write_text(
        json.dumps({"ts": 1_700_000_000, "request": {"uri": "/ad"}}) + "\n"
    )
    controller = _controller(tmp_path, docker, clock=lambda: now, idle_minutes=1)
    controller.hibernate()
    controller.awaken()
    assert controller.maybe_idle_hibernate(now) is False
    assert controller.current_state() == "awake"


def test_controller_restart_keeps_an_old_access_log_idle(tmp_path):
    docker = FakeDocker([_container("web")])
    now = 1_700_000_060
    (tmp_path / "access.log").write_text(
        json.dumps({"ts": 1_700_000_000, "request": {"uri": "/ad"}}) + "\n"
    )
    _controller(tmp_path, docker, clock=lambda: now, idle_minutes=1)
    restarted = _controller(tmp_path, docker, clock=lambda: now, idle_minutes=1)
    assert restarted.maybe_idle_hibernate(now) is True
    assert restarted.current_state() == "hibernating"


def test_awaken_quiet_period_survives_controller_restart(tmp_path):
    docker = FakeDocker([_container("web")])
    now = 1_700_000_060
    (tmp_path / "access.log").write_text(
        json.dumps({"ts": 1_700_000_000, "request": {"uri": "/ad"}}) + "\n"
    )
    controller = _controller(tmp_path, docker, clock=lambda: now, idle_minutes=1)
    controller.hibernate()
    controller.awaken()
    restarted = _controller(tmp_path, docker, clock=lambda: now, idle_minutes=1)
    assert restarted.maybe_idle_hibernate(now) is False
    assert restarted.current_state() == "awake"


def test_recent_non_health_traffic_prevents_idle_sleep(tmp_path):
    docker = FakeDocker([_container("web")])
    now = 1_700_000_030
    (tmp_path / "access.log").write_text(
        json.dumps({"ts": now, "request": {"uri": "/dashboard"}}) + "\n"
    )
    controller = _controller(tmp_path, docker, clock=lambda: now, idle_minutes=1)
    assert controller.maybe_idle_hibernate(now) is False
    assert controller.current_state() == "awake"


def test_intentional_sleep_wakes_on_visit(tmp_path):
    docker = FakeDocker([_container("web")])
    controller = _controller(tmp_path, docker)
    controller.hibernate()
    status, _, body = controller.handle_public_request("/ad")
    assert status == 200
    assert b"starting" in body.lower()
    controller.awaken()
    assert "id-web" in docker.started


def test_crash_returns_503_without_restart(tmp_path):
    docker = FakeDocker([_container("web")])
    controller = _controller(tmp_path, docker)
    status, _, body = controller.handle_public_request("/ad")
    assert status == 503
    assert json.loads(body)["status"] == "unavailable"
    assert docker.started == []
    assert docker.stopped == []


def test_waking_health_becomes_awake_when_backend_responds(tmp_path):
    docker = FakeDocker([_container("web")])
    controller = _controller(tmp_path, docker)
    controller._write_state("waking")
    status, _type, body = controller.health_response()
    assert status == 200
    assert json.loads(body)["status"] == "ok"
    assert controller.current_state() == "awake"


def test_waking_health_does_not_wait_on_awaken_lock(tmp_path):
    docker = FakeDocker([_container("web")])
    controller = _controller(tmp_path, docker)
    controller._write_state("waking")
    held = threading.Event()
    release = threading.Event()

    def holder():
        controller.lock.acquire()
        held.set()
        release.wait(5)
        controller.lock.release()

    holder_thread = threading.Thread(target=holder)
    holder_thread.start()
    assert held.wait(1)
    result = {}

    def probe():
        result["resp"] = controller.health_response()

    probe_thread = threading.Thread(target=probe)
    probe_thread.start()
    probe_thread.join(2)
    try:
        assert not probe_thread.is_alive()
        status, _, body = result["resp"]
        assert status == 200
        assert json.loads(body)["status"] == "ok"
        assert controller.current_state() == "waking"
    finally:
        release.set()
        holder_thread.join(2)


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


def test_docker_engine_prefixes_api_version():
    engine = DockerEngine(api_version="1.41")
    assert engine.engine_path("/containers/json") == "/v1.41/containers/json"


def test_docker_engine_negotiates_api_version(monkeypatch):
    monkeypatch.delenv("DOCKER_API_VERSION", raising=False)
    monkeypatch.setattr(DockerEngine, "_negotiate_api_version", lambda self: "1.51")
    engine = DockerEngine()
    assert engine.engine_path("/containers/json") == "/v1.51/containers/json"


def test_docker_engine_renegotiates_when_version_is_too_old(monkeypatch):
    engine = DockerEngine(api_version="1.41")
    engine._negotiate_api_version = lambda: "1.52"
    responses = iter(
        [
            (
                400,
                b'{"message":"client version 1.41 is too old. Minimum supported API version is 1.44"}',
            ),
            (200, b"[]"),
        ]
    )

    class FakeConn:
        def request(self, method, path, headers=None):
            return None

        def getresponse(self):
            status, body = next(responses)

            class Resp:
                def read(self_inner):
                    return body

            resp = Resp()
            resp.status = status
            return resp

        def close(self):
            return None

    monkeypatch.setattr(
        "dallinger.hibernation._UnixHTTPConnection", lambda socket_path: FakeConn()
    )
    payload = engine._request("GET", "/containers/json?all=true")
    assert payload == []
    assert engine.api_version == "1.52"


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
    assert caddy.count("@parked") == 3
    assert "handle_errors {" in caddy
    assert caddy.find("handle_errors") > caddy.find("flush_interval")
    assert "{>" not in caddy
    assert "X-Hibernation-Secret" not in caddy
    assert "header_up Connection" not in caddy
    assert "header_up Upgrade" not in caddy


def test_write_state_updates_sibling_deployment_manifest(tmp_path):
    app_dir = tmp_path / "demo"
    state_dir = app_dir / "state"
    state_dir.mkdir(parents=True)
    manifest = app_dir / "deployment.json"
    manifest.write_text(
        json.dumps({"app": "demo", "hibernation": {"state": "awake"}}) + "\n"
    )
    docker = FakeDocker([_container("web")])
    controller = _controller(state_dir, docker)
    controller.hibernate()
    assert json.loads(manifest.read_text())["hibernation"]["state"] == "hibernating"
    controller.awaken()
    assert json.loads(manifest.read_text())["hibernation"]["state"] == "awake"


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


def test_controller_marks_hibernating_after_reboot_with_backend_down(tmp_path):
    (tmp_path / "access.log").write_text("{}\n")
    docker = FakeDocker([_container("web")])
    docker._containers[0]["state"] = "exited"
    controller = _controller(tmp_path, docker)
    assert controller.current_state() == "hibernating"


def test_controller_marks_hibernating_after_reboot_when_only_postgres_is_up(tmp_path):
    (tmp_path / "access.log").write_text("{}\n")
    docker = FakeDocker([_container("web"), _container("postgresql")])
    docker._containers[0]["state"] = "exited"
    controller = _controller(tmp_path, docker)
    assert controller.current_state() == "hibernating"


def test_leftover_waking_marker_becomes_hibernating_when_backend_down(tmp_path):
    (tmp_path / "waking").write_text("")
    docker = FakeDocker([_container("web")])
    docker._containers[0]["state"] = "exited"
    controller = _controller(tmp_path, docker)
    assert controller.current_state() == "hibernating"


def test_leftover_waking_marker_becomes_awake_when_backend_up(tmp_path):
    (tmp_path / "waking").write_text("")
    docker = FakeDocker([_container("web")])
    controller = _controller(tmp_path, docker)
    assert controller.current_state() == "awake"


def test_leftover_waking_marker_stays_hibernating_when_only_postgres_is_up(tmp_path):
    (tmp_path / "waking").write_text("")
    docker = FakeDocker([_container("web"), _container("postgresql")])
    docker._containers[0]["state"] = "exited"
    controller = _controller(tmp_path, docker)
    assert controller.current_state() == "hibernating"


def test_waking_public_request_resumes_when_backend_down(tmp_path):
    docker = FakeDocker([_container("web")])
    controller = _controller(tmp_path, docker)
    docker._containers[0]["state"] = "exited"
    controller._write_state("waking")
    status, _, body = controller.handle_public_request("/ad")
    assert status == 200
    assert b"starting" in body.lower()
    for _ in range(40):
        if "id-web" in docker.started:
            break
        time.sleep(0.05)
    assert "id-web" in docker.started


def test_waking_public_request_resumes_when_only_postgres_is_up(tmp_path):
    docker = FakeDocker([_container("web"), _container("postgresql")])
    controller = _controller(tmp_path, docker)
    docker._containers[0]["state"] = "exited"
    controller._write_state("waking")
    status, _, body = controller.handle_public_request("/ad")
    assert status == 200
    assert b"starting" in body.lower()
    for _ in range(40):
        if "id-web" in docker.started:
            break
        time.sleep(0.05)
    assert "id-web" in docker.started


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


def test_authorize_rejects_wrong_secret_without_raising(tmp_path):
    controller = _controller(tmp_path, FakeDocker([_container("web")]))
    assert controller.authorize("s3cret") is True
    assert controller.authorize("nope") is False
    assert controller.authorize("") is False


def test_empty_access_log_does_not_count_as_prior_runtime(tmp_path):
    (tmp_path / "access.log").write_bytes(b"")
    docker = FakeDocker([_container("web")])
    docker._containers[0]["state"] = "exited"
    controller = _controller(tmp_path, docker)
    assert controller.current_state() == "awake"


def test_controller_stays_awake_when_docker_inspect_fails(tmp_path):
    (tmp_path / "access.log").write_text("{}\n")

    class BoomDocker(FakeDocker):
        def containers(self, all_=True):
            raise RuntimeError("client version 1.41 is too old")

    controller = _controller(tmp_path, BoomDocker([_container("web")]))
    assert controller.current_state() == "awake"


def test_write_state_updates_explicit_manifest_path(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    manifest = tmp_path / "elsewhere" / "deployment.json"
    manifest.parent.mkdir()
    manifest.write_text(
        json.dumps({"app": "demo", "hibernation": {"state": "awake"}}) + "\n"
    )
    docker = FakeDocker([_container("web")])
    controller = _controller(state_dir, docker, manifest_path=manifest)
    controller.hibernate()
    assert json.loads(manifest.read_text())["hibernation"]["state"] == "hibernating"


def test_admin_routes_require_secret_public_routes_do_not(tmp_path):
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
            urlopen(
                Request(f"{origin}/hibernate", data=b"{}", method="POST"), timeout=2
            )
        assert err.value.code == 403
        with urlopen(f"{origin}/health", timeout=2) as response:
            assert response.status == 200
        request = Request(f"{origin}/state", headers={"X-Hibernation-Secret": "s3cret"})
        with urlopen(request, timeout=2) as response:
            assert json.loads(response.read())["status"] == "hibernating"
        with urlopen(f"{origin}/ad", timeout=2) as response:
            assert response.status == 200
            assert b"starting" in response.read().lower()
    finally:
        server.shutdown()
        server.server_close()
