import dataclasses
import importlib
import json
import os
import re
import shutil
import socket
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

import click
import paramiko
import pytest
import requests
import urllib3
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
        self.health = [health] if isinstance(health, str) else list(health)

    def run_with_status(self, cmd):
        if "command -v curl" in cmd:
            self.events.append("health")
            health = self.health.pop(0) if len(self.health) > 1 else self.health[0]
            return 0, health + "\n", ""
        self.events.append("launch")
        result = self.launch_replies.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def run(self, cmd, raise_=True):
        return self.logs if "logs" in cmd else ""


class FakeClock:
    def __init__(self):
        self.now = 0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr(launch, "time", FakeClock())


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


SENT = ("Recruitment may have started", "Only if the logs show")


@pytest.mark.parametrize(
    "results, expected",
    [
        ([(0, reply(500, {"status": "error"}), "")], SENT),
        ([(28, "\n000\n", "curl: (28) Operation timed out")], SENT),
        ([(0, '["not", "an", "object"]\n200\n', "")], SENT),
        ([(1, "", "unexpected failure\n")], SENT),
        ([paramiko.SSHException("Connection reset")], SENT),
        (
            [(1, "", 'service "web" is not running\n')] * launch.MAX_ATTEMPTS,
            ("could not reach myapp from inside the server after", "Retry the launch:"),
        ),
    ],
    ids=[
        "http-500",
        "timeout",
        "2xx-not-json-object",
        "other-exit-1",
        "ssh-error",
        "never-delivered",
    ],
)
def test_a_failed_launch_is_not_resent_once_it_may_have_arrived(
    results, expected, no_sleep, capsys
):
    message, heading = expected
    executor = FakeExecutor(results)

    with pytest.raises(click.ClickException, match=message):
        launch.launch_from_server(executor, TARGET)

    assert executor.events == ["launch"] * len(results)
    out = capsys.readouterr().out
    assert heading in out
    assert TARGET.ssh(f"docker compose -f {TARGET.compose_file} logs web") in out
    assert TARGET.ssh(launch.internal_launch_command(TARGET)) in out
    assert TARGET.destroy_command in out


@pytest.mark.parametrize(
    "remote, local",
    [
        ("ls ~/dallinger", 'ssh lab "ls ~/dallinger"'),
        ('echo "$HOME"', "ssh lab 'echo \"$HOME\"'"),
    ],
)
def test_ssh_command_keeps_the_remote_command_intact(remote, local):
    assert launch.ssh_command("ssh lab", remote) == local


@pytest.mark.parametrize(
    "pem, port, expected",
    [
        ("/keys/key.pem", 2222, "ssh -p 2222 -i /keys/key.pem me@lab"),
        ("/my keys/key.pem", 22, "ssh -i '/my keys/key.pem' me@lab"),
    ],
)
def test_printed_ssh_commands_quote_the_key_path(pem, port, expected, monkeypatch):
    monkeypatch.setattr(docker_ssh, "get_server_pem_path", lambda: Path(pem))
    assert docker_ssh._ssh_prefix("lab", port, "me") == expected


def test_ssh_connections_have_a_connect_timeout(tmp_path, monkeypatch):
    key = tmp_path / "key.pem"
    paramiko.RSAKey.generate(1024).write_private_key_file(str(key))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(docker_ssh, "get_server_pem_path", lambda: key)
    with (
        mock.patch.object(docker_ssh.socket, "create_connection") as open_socket,
        mock.patch.object(paramiko.SSHClient, "connect") as connect,
        mock.patch.object(paramiko.SSHClient, "get_transport"),
    ):
        docker_ssh._connect_ssh_client("lab", "me")
    open_socket.assert_called_once_with(("lab", 22), docker_ssh.SSH_CONNECT_TIMEOUT)
    assert connect.call_args.kwargs["sock"] is open_socket.return_value
    assert "timeout" not in connect.call_args.kwargs


def test_a_refused_ssh_port_is_still_explained():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with pytest.raises(paramiko.ssh_exception.NoValidConnectionsError) as error:
        docker_ssh._open_ssh_socket("127.0.0.1", port)
    message = docker_ssh._ssh_failure_message(error.value, f"127.0.0.1:{port}", "me")
    assert f"nothing accepted the connection on port {port}" in message


def test_printed_ssh_commands_use_the_users_alias_for_the_server(tmp_path, monkeypatch):
    key = tmp_path / "key.pem"

    def ssh_dash_g(args, **kwargs):
        # What `ssh -G lab` prints for "Host lab / HostName lab.example.org / ...".
        assert args == ["ssh", "-G", "--", "lab"]
        output = (
            "hostname lab.example.org\nport 22\nuser me@example.org\n"
            f"identityfile ~/.ssh/id_rsa\nidentityfile {key}\n"
        )
        return subprocess.CompletedProcess(args, 0, output, "")

    monkeypatch.setattr(docker_ssh.subprocess, "run", ssh_dash_g)
    monkeypatch.setattr(docker_ssh, "get_server_pem_path", lambda: key)

    assert docker_ssh._ssh_prefix("lab.example.org", 22, "me@example.org") == "ssh lab"
    assert docker_ssh._ssh_prefix("lab.example.org", 22, "you@example.org") == (
        f"ssh -i {key} -l you@example.org lab.example.org"
    )
    assert docker_ssh._ssh_prefix("10.0.0.1", 22, "me") == f"ssh -i {key} me@10.0.0.1"


@pytest.fixture
def deploy_dir(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(launch, "PUBLIC_CHECK_TIMEOUT", 0)
    return tmp_path


def public_check(events, *statuses, text="", headers=None):
    """Answer the public probe with ``statuses`` in turn, repeating the last."""
    statuses = list(statuses)

    def get(url, allow_redirects=True, **kwargs):
        assert allow_redirects is False
        events.append("check")
        status = statuses.pop(0) if len(statuses) > 1 else statuses[0]
        return mock.Mock(status_code=status, text=text, headers=headers or {})

    return mock.patch.object(launch.requests, "get", get)


CLOUDFLARE_PENDING = "Cloudflare has not activated the new tunnel yet (cloudflared logs say 'Tunnel not found')"


@pytest.mark.parametrize(
    "ingress, status, headers, reason",
    [
        ("cloudflare", 530, {}, CLOUDFLARE_PENDING),
        ("cloudflare", 404, {}, CLOUDFLARE_PENDING),
        ("classic", 502, {}, "Caddy may still be getting a TLS certificate"),
        ("classic", 302, {"location": "https://x.cloudflareaccess.com"}, "Access"),
        ("cloudflare", 302, {"location": "https://x.cloudflareaccess.com"}, "Access"),
        ("classic", 403, {"cf-mitigated": "challenge"}, "cf-mitigated: challenge"),
    ],
    ids=[
        "cloudflare-530",
        "cloudflare-404",
        "classic-502",
        "redirect",
        "cloudflare-redirect",
        "403",
    ],
)
def test_deploy_does_not_launch_when_the_public_url_never_answers(
    ingress, status, headers, reason, deploy_dir, capsys
):
    target = dataclasses.replace(TARGET, ingress=ingress)
    events = []
    executor = FakeExecutor(logs="ERR Unauthorized: Tunnel not found", events=events)

    with public_check(events, status, headers=headers):
        with pytest.raises(click.ClickException) as error:
            docker_ssh._record_then_launch(executor, target, ["notes"], "pw", False)

    assert events == ["health", "check"]
    assert Path("deploy_logs/myapp.txt").read_text() == "notes\n"
    assert "/health did not answer 2xx" in error.value.message
    assert reason in error.value.message
    assert ("Tunnel not found" in error.value.message) is (reason == CLOUDFLARE_PENDING)
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
    assert (cloudflared_logs in out) is (reason == CLOUDFLARE_PENDING)


def test_deploy_launches_once_the_public_url_answers(deploy_dir, capsys):
    events = []
    executor = FakeExecutor(
        [(0, reply(200, {"recruitment_msg": "open"}), "")], events=events
    )

    with public_check(events, 200):
        launch_data = docker_ssh._record_then_launch(
            executor, TARGET, ["notes"], "pw", False
        )
        assert events == ["health", "check", "launch"]
        assert launch_data["recruitment_msg"] == "open"
        assert "The experiment server is up." in capsys.readouterr().out

        assert docker_ssh._record_then_launch(executor, TARGET, ["n"], "pw", True) == {}
        assert events == ["health", "check", "launch"]
        assert "Not launching again" in capsys.readouterr().out


@pytest.mark.parametrize("show_summary", [True, False])
def test_no_summary_leaves_the_summary_to_the_caller(show_summary, deploy_dir, capsys):
    for command in docker_ssh.deploy, docker_ssh.sandbox:
        assert "show_summary" in {param.name for param in command.params}
    executor = FakeExecutor([(0, reply(200, {"recruitment_msg": "rmsg"}), "")])

    with public_check([], 200):
        launch_data = docker_ssh._record_then_launch(
            executor, TARGET, ["notes"], "s3cret", False, show_summary
        )

    assert launch_data["recruitment_msg"] == "rmsg"
    assert Path("deploy_logs/myapp.txt").read_text() == "notes\n"
    out = capsys.readouterr().out
    for text in "notes", "s3cret", "rmsg":
        assert (text in out) is show_summary


def test_no_summary_still_prints_the_summary_if_launching_fails(deploy_dir, capsys):
    executor = FakeExecutor()

    with public_check([], 530), pytest.raises(click.ClickException):
        docker_ssh._record_then_launch(
            executor, TARGET, ["notes"], "s3cret", False, show_summary=False
        )

    out = capsys.readouterr().out
    assert "notes" in out and "s3cret" in out


def test_public_wait_retries_errors_and_one_redirect_until_2xx(no_sleep):
    events = []
    with public_check(events, 530, 302, 530, 200):
        launch.wait_for_public_url(FakeExecutor(), TARGET)
    assert events == ["check"] * 4


def test_public_wait_does_not_launch_a_waking_app(no_sleep):
    events = []
    with public_check(events, 200, text='{"status": "waking"}'):
        with pytest.raises(click.ClickException, match="answered for a stopped app"):
            launch.wait_for_public_url(FakeExecutor(), TARGET)
    assert len(events) > 1


def test_public_wait_accepts_an_apps_own_health_body(no_sleep):
    events = []
    with public_check(events, 200, text='{"status": "ok", "ready": true}'):
        launch.wait_for_public_url(FakeExecutor(), TARGET)
    assert events == ["check"]


def test_public_wait_stops_early_on_a_second_redirect_in_a_row(no_sleep, capsys):
    events = []
    with public_check(
        events, 302, headers={"location": "https://x.cloudflareaccess.com"}
    ):
        with pytest.raises(click.ClickException, match="Access"):
            launch.wait_for_public_url(FakeExecutor(), TARGET)
    assert events == ["check"] * 2
    assert launch.time.now == launch.PUBLIC_CHECK_INTERVAL
    assert "redirected twice in a row" in capsys.readouterr().out


def test_public_wait_stops_early_on_a_second_hibernating_answer(no_sleep, capsys):
    awaken = f"awaken --server {TARGET.server} --app {TARGET.app}"
    states = ["hibernating", "waking", "hibernating", "ok"]
    bodies = [f'{{"status": "{state}"}}' for state in states]
    with mock.patch.object(launch, "_probe", lambda *a: (200, bodies.pop(0))):
        launch.wait_for_public_url(FakeExecutor(), TARGET)
    assert not bodies

    events = []
    with public_check(events, 200, text='{"status": "hibernating"}'):
        with pytest.raises(click.ClickException, match=re.escape(awaken)):
            launch.wait_for_public_url(FakeExecutor(), TARGET)
    assert events == ["check"] * 2
    assert f"dallinger docker-ssh {awaken}" in capsys.readouterr().out


@pytest.mark.parametrize(
    "error, name",
    [
        (
            requests.exceptions.SSLError("HTTPSConnectionPool(...): " + "x" * 200),
            "SSLError",
        ),
        (
            requests.exceptions.ConnectionError(
                urllib3.exceptions.MaxRetryError(
                    None,
                    "/health",
                    urllib3.exceptions.NewConnectionError(None, "refused"),
                )
            ),
            "ConnectionError (NewConnectionError)",
        ),
    ],
)
def test_progress_lines_name_the_request_error(error, name, no_sleep, capsys):
    def get(url, **kwargs):
        if launch.time.now < launch.PROGRESS_INTERVAL + 10:
            raise error
        return mock.Mock(status_code=200, text="", headers={})

    with mock.patch.object(launch.requests, "get", get):
        launch.wait_for_public_url(FakeExecutor(), TARGET)
    assert f"Still waiting after 60 s: {name}\n" in capsys.readouterr().out


def test_internal_health_retries_while_the_app_starts(no_sleep):
    executor = FakeExecutor(health=["health=000", "health=502", "health=200"])
    launch.check_internal_health(executor, TARGET)
    assert executor.events == ["health"] * 3


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
