import dataclasses
import importlib
import json
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

import click
import pytest
from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.test import Client

from dallinger.command_line.lib import launch
from dallinger.utils import get_base_url

docker_ssh = importlib.import_module("dallinger.command_line.docker_ssh")

TARGET = launch.LaunchTarget(
    app="myapp",
    server="lab",
    public_origin="https://myapp.x.org",
    ingress="cloudflare",
    ssh_prefix="ssh -i key.pem me@lab.example",
)


def reply(status, body):
    """curl's output: the body, then the status on its own line."""
    return f"{json.dumps(body)}\n{status}\n"


class FakeExecutor:
    def __init__(self, launch_replies=(), logs="", events=None, health="health=200"):
        self.launch_replies = list(launch_replies)
        self.logs = logs
        self.events = [] if events is None else events
        self.health = health

    def run_with_status(self, cmd):
        if "command -v curl" in cmd:
            self.events.append("health")
            return 0, self.health + "\n", ""
        self.events.append("launch")
        return self.launch_replies.pop(0)

    def run(self, cmd, raise_=True):
        return self.logs if "logs" in cmd else ""


@pytest.fixture
def no_sleep():
    with mock.patch("dallinger.deployment.time.sleep"):
        yield


@pytest.mark.skipif(shutil.which("curl") is None, reason="needs curl")
def test_launch_runs_curl_in_web_with_the_public_host(monkeypatch, tmp_path):
    """Run the real remote command locally; a fake ``docker`` runs its tail."""

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            proto = self.headers["X-Forwarded-Proto"]
            body = json.dumps({"recruitment_msg": f"{proto}://{self.headers['Host']}"})
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(
        launch, "FRONT_DOOR_LAUNCH_URL", f"http://127.0.0.1:{server.server_port}/"
    )
    docker = tmp_path / "docker"
    docker.write_text(
        '#!/bin/sh\nwhile [ "$1" != web ]; do shift; done\nshift\nexec "$@"\n'
    )
    docker.chmod(0o755)

    class LocalExecutor:
        def run_with_status(self, cmd):
            env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"}
            done = subprocess.run(
                ["bash", "-c", cmd], capture_output=True, text=True, env=env
            )
            return done.returncode, done.stdout, done.stderr

    try:
        data = launch.launch_from_server(LocalExecutor(), TARGET)
    finally:
        server.shutdown()
        server.server_close()
    assert data["recruitment_msg"] == "https://myapp.x.org"


@pytest.mark.parametrize(
    "not_sent",
    [
        (1, "", 'service "web" is not running\n'),
        (1, 'service "web" is not running\n', ""),
        (7, "\n000\n", "curl: (7) Failed to connect to frontdoor port 5000"),
    ],
    ids=["web-not-running", "web-not-running-on-stdout", "connection-refused"],
)
def test_only_an_undelivered_launch_is_sent_again(not_sent, no_sleep):
    executor = FakeExecutor(
        [not_sent, (0, reply(200, {"recruitment_msg": "open"}) + "\n\n", "")]
    )
    assert launch.launch_from_server(executor, TARGET) == {"recruitment_msg": "open"}
    assert executor.events == ["launch", "launch"]


def test_proxied_launch_headers_give_the_public_base_url():
    app = Flask(__name__)
    app.add_url_rule("/launch", "launch", get_base_url, methods=["POST"])
    response = Client(ProxyFix(app)).post(
        "/launch",
        base_url="http://frontdoor:5000",
        headers={"Host": "myapp.x.org", "X-Forwarded-Proto": "https"},
    )
    assert response.get_data(as_text=True) == "https://myapp.x.org"


@pytest.mark.parametrize(
    "result",
    [
        (0, reply(500, {"status": "error"}), ""),
        (28, "\n000\n", "curl: (28) Operation timed out"),
        (0, '["not", "an", "object"]\n200\n', ""),
        (1, "", "unexpected failure\n"),
    ],
    ids=["http-500", "timeout", "2xx-not-json-object", "other-exit-1"],
)
def test_a_launch_that_reached_the_app_is_sent_once(result, capsys):
    executor = FakeExecutor([result])

    with pytest.raises(click.ClickException, match="Recruitment may have started"):
        launch.launch_from_server(executor, TARGET)

    assert executor.events == ["launch"]
    out = capsys.readouterr().out
    assert TARGET.ssh(f"docker compose -f {TARGET.compose_file} logs web") in out
    assert TARGET.ssh(launch.internal_launch_command(TARGET)) in out
    assert TARGET.destroy_command in out


def test_ssh_command_leaves_tilde_for_the_server():
    assert launch.ssh_command("ssh lab", "ls ~/dallinger") == 'ssh lab "ls ~/dallinger"'


@pytest.fixture
def deploy_dir(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(launch, "PUBLIC_CHECK_TIMEOUT", 0)
    return tmp_path


def public_check(events, status, text=""):
    def get(*args, **kwargs):
        events.append("check")
        return mock.Mock(status_code=status, text=text)

    return mock.patch.object(launch.requests, "get", get)


CLOUDFLARE_PENDING = "Cloudflare has not activated the new tunnel yet (cloudflared logs say 'Tunnel not found')"


@pytest.mark.parametrize(
    "ingress, status, text, reason",
    [
        ("cloudflare", 530, "error code: 1033", CLOUDFLARE_PENDING),
        ("cloudflare", 404, "", CLOUDFLARE_PENDING),
        ("classic", 502, "", "Caddy may still be getting a TLS certificate"),
    ],
    ids=["cloudflare-530", "cloudflare-404", "classic-502"],
)
def test_deploy_does_not_launch_when_the_public_url_never_answers(
    ingress, status, text, reason, deploy_dir, capsys
):
    target = dataclasses.replace(TARGET, ingress=ingress)
    events = []
    executor = FakeExecutor(logs="ERR Unauthorized: Tunnel not found", events=events)

    with public_check(events, status, text):
        with pytest.raises(click.ClickException) as error:
            docker_ssh._record_then_launch(executor, target, ["notes"], "pw", False)

    assert events == ["health", "check"]
    assert Path("deploy_logs/myapp.txt").read_text() == "notes\n"
    assert "was not launched" in error.value.message
    assert reason in error.value.message
    out = capsys.readouterr().out
    assert "(expect 2xx)" in out
    for command in (
        target.check_command,
        target.ssh(launch.internal_launch_command(target)),
        target.destroy_command,
    ):
        assert command in out
    cloudflared_logs = target.ssh(
        f"docker compose -f {target.compose_file} logs cloudflared"
    )
    assert (cloudflared_logs in out) is (ingress == "cloudflare")


def test_deploy_launches_once_the_public_url_answers(deploy_dir, capsys):
    events = []
    executor = FakeExecutor(
        [(0, reply(200, {"recruitment_msg": "open"}), "")], events=events
    )

    with public_check(events, 200):
        docker_ssh._record_then_launch(executor, TARGET, ["notes"], "pw", False)
        assert events == ["health", "check", "launch"]
        assert "The app answers /health inside the server." in capsys.readouterr().out

        docker_ssh._record_then_launch(executor, TARGET, ["notes"], "pw", True)
        assert events == ["health", "check", "launch"]


@pytest.mark.parametrize(
    "health, message",
    [
        ("curl-missing", "curl is not installed"),
        ("health=404", "no /health endpoint.*Rebuild the image"),
        ("health=503", "answered HTTP 503"),
    ],
)
def test_deploy_stops_early_unless_the_app_answers_health_inside(
    health, message, deploy_dir, no_sleep, capsys
):
    events = []
    executor = FakeExecutor(events=events, health=health)

    with public_check(events, 200):
        with pytest.raises(click.ClickException, match=message):
            docker_ssh._record_then_launch(executor, TARGET, ["notes"], "pw", False)

    assert set(events) == {"health"}
    assert Path("deploy_logs/myapp.txt").exists()
    assert TARGET.destroy_command in capsys.readouterr().out
