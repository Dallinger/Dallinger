import importlib
import json
import os
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
from dallinger.deployment import MAX_ATTEMPTS
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
    return json.dumps({"status": status, "body": json.dumps(body)})


class FakeExecutor:
    def __init__(self, launch_replies=(), logs="", events=None):
        self.launch_replies = list(launch_replies)
        self.logs = logs
        self.events = [] if events is None else events

    def run_with_status(self, cmd):
        self.events.append("launch")
        return self.launch_replies.pop(0)

    def run(self, cmd, raise_=True):
        return self.logs if "logs" in cmd else ""


@pytest.fixture
def no_sleep():
    with mock.patch("dallinger.deployment.time.sleep"):
        yield


def test_launch_runs_python_in_web_with_the_public_host(monkeypatch, tmp_path):
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


def test_a_reported_response_is_not_sent_again(no_sleep):
    executor = FakeExecutor(
        [
            (1, "", 'service "web" is not running\n'),
            (1, reply(200, {"recruitment_msg": "open"}) + "\n\n", ""),
        ]
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


def test_failed_launch_explains_how_to_retry_or_destroy(no_sleep, capsys):
    error = (0, reply(500, {"status": "error", "message": "boom"}), "")
    executor = FakeExecutor([error] * MAX_ATTEMPTS)

    with pytest.raises(click.ClickException, match="recruitment has not started"):
        launch.launch_from_server(executor, TARGET)

    out = capsys.readouterr().out
    assert "ssh -i key.pem me@lab.example 'docker compose" in out
    assert "dallinger docker-ssh destroy --server lab --app myapp" in out


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


def test_deploy_does_not_launch_when_the_public_url_never_answers(deploy_dir, capsys):
    events = []
    executor = FakeExecutor(logs="ERR Unauthorized: Tunnel not found", events=events)

    with public_check(events, 530, "error code: 1033"):
        with pytest.raises(click.ClickException) as error:
            docker_ssh._record_then_launch(executor, TARGET, ["notes"], "pw", False)

    assert events == ["check"]
    assert Path("deploy_logs/myapp.txt").read_text() == "notes\n"
    assert "was not launched" in error.value.message
    assert "Cloudflare has not activated the new tunnel yet" in error.value.message
    assert "'Tunnel not found'" in error.value.message
    out = capsys.readouterr().out
    for command in (
        TARGET.check_command,
        TARGET.ssh(f"docker compose -f {TARGET.compose_file} logs cloudflared"),
        TARGET.ssh(launch.internal_launch_command(TARGET)),
        TARGET.destroy_command,
    ):
        assert command in out


def test_deploy_launches_once_the_public_url_answers(deploy_dir):
    events = []
    executor = FakeExecutor(
        [(0, reply(200, {"recruitment_msg": "open"}), "")], events=events
    )

    with public_check(events, 200):
        docker_ssh._record_then_launch(executor, TARGET, ["notes"], "pw", False)
        assert events == ["check", "launch"]

        docker_ssh._record_then_launch(executor, TARGET, ["notes"], "pw", True)
        assert events == ["check", "launch"]
