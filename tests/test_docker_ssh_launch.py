import importlib
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
LAUNCHED = '{"status": "success", "recruitment_msg": "Recruitment is open"}\n200'


class FakeExecutor:
    def __init__(self, launch_replies=(), logs=""):
        self.launch_replies = list(launch_replies)
        self.logs = logs
        self.commands = []

    def run_with_status(self, cmd):
        self.commands.append(cmd)
        return self.launch_replies.pop(0)

    def run(self, cmd, raise_=True):
        self.commands.append(cmd)
        return self.logs if "logs" in cmd else ""


@pytest.fixture
def no_sleep():
    with mock.patch("dallinger.deployment.time.sleep"):
        yield


def test_launch_posts_to_the_front_door_with_public_headers(no_sleep):
    executor = FakeExecutor(
        [(1, "", 'service "web" is not running'), (0, LAUNCHED, "")]
    )

    data = launch.launch_from_server(executor, TARGET)

    assert data["recruitment_msg"] == "Recruitment is open"
    command = executor.commands[-1]
    assert command.startswith(
        "docker compose -f ~/dallinger/myapp/docker-compose.yml exec -T web curl"
    )
    assert '-H "Host: myapp.x.org"' in command
    assert '-H "X-Forwarded-Proto: https"' in command
    assert command.endswith("http://frontdoor:5000/launch")


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
    error = (0, '{"status": "error", "message": "boom"}\n500', "")
    executor = FakeExecutor([error] * MAX_ATTEMPTS)

    with pytest.raises(click.ClickException, match="recruitment has not started"):
        launch.launch_from_server(executor, TARGET)

    out = capsys.readouterr().out
    assert "ssh -i key.pem me@lab.example 'docker compose" in out
    assert "dallinger docker-ssh destroy --server lab --app myapp" in out


def test_public_check_warns_when_cloudflare_has_not_activated_the_tunnel(capsys):
    executor = FakeExecutor(
        logs="ERR Register tunnel error: Unauthorized: Tunnel not found"
    )
    pending = mock.Mock(status_code=530, text="error code: 1033")

    with mock.patch.object(launch.requests, "get", return_value=pending):
        assert launch.wait_for_public_url(executor, TARGET, timeout=0) is False

    out = capsys.readouterr().out
    assert "Waiting for the Cloudflare tunnel to connect" in out
    assert "Cloudflare has not activated the new tunnel yet" in out
    assert "'Tunnel not found'" in out
    assert "The app is running and launched" in out
    assert TARGET.check_command in out
    assert TARGET.destroy_command in out


def test_deploy_records_the_deployment_before_the_public_check(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    record = Path("deploy_logs/myapp.txt")
    checked = []

    def public_check(executor, target):
        checked.append(record.exists())
        return False

    class Executor(FakeExecutor):
        def __init__(self, *args, **kwargs):
            super().__init__()

    for name, value in {
        "Executor": Executor,
        "_check_app_slot": lambda *args: None,
        "remove_named_volume": lambda *args: None,
        "_app_secrets": lambda *args: {
            "FLASK_SECRET_KEY": "k",
            "POSTGRES_PASSWORD": "p",
        },
        "get_sftp": lambda *args, **kwargs: None,
        "load_api_token": lambda config: "token",
        "ensure_experiment_tunnel": lambda **kwargs: {
            "tunnel_id": "t",
            "connector_token": "secret",
        },
        "_install_tunnel_token": lambda *args: None,
        "_compose_environment": lambda *args: {},
        "_upload_app_stack": lambda *args, **kwargs: None,
        "_bring_up_app_containers": lambda *args, **kwargs: None,
        "launch_from_server": lambda executor, target: {"recruitment_msg": "open"},
        "wait_for_public_url": public_check,
    }.items():
        monkeypatch.setattr(docker_ssh, name, value)

    docker_ssh._deploy_cloudflare_in_mode(
        archive_path=None,
        config={
            "cloudflare_account_id": "acct",
            "cloudflare_zone_id": "zone",
            "cloudflare_dns_zone": "x.org",
        },
        config_options={},
        dashboard_password="pw",
        dashboard_user="admin",
        experiment_id="myapp",
        experiment_uuid="uuid",
        image_name="image",
        mode="sandbox",
        push_build=False,
        server="lab",
        server_info={"host": "lab.example"},
        update=False,
    )

    assert checked == [True]
    assert "pw" not in record.read_text()
