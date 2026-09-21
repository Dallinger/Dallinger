import importlib
import sys
from pathlib import Path
from unittest import mock

import pytest
import yaml


def test_get_docker_compose_yml_extra_config():
    """Make sure all values passed in config make their way to the
    web and worker container environment
    """
    result = get_yaml({"foo": "bar"})
    assert result["services"]["web"]["environment"]["foo"] == "bar"


def test_get_docker_compose_yml_core_config():
    """Make sure worker and web services have the necessary variables to run"""
    result = get_yaml({})
    assert "REDIS_URL" in result["services"]["worker_1"]["environment"]
    assert "DATABASE_URL" in result["services"]["worker_1"]["environment"]
    assert "HOME" in result["services"]["worker_1"]["environment"]


def test_get_docker_compose_yml_uses_app_scoped_redis():
    """Experiment containers should not resolve Redis through a shared alias."""
    result = get_yaml({})
    services = result["services"]

    assert (
        services["worker_1"]["environment"]["REDIS_URL"]
        == "redis://dlgr-8c43a887_redis:6379"
    )
    assert services["redis"]["networks"] == {
        "app": {"aliases": ["dlgr-8c43a887_redis"]}
    }
    assert services["web"]["networks"] == {"app": {"aliases": ["experiment-backend"]}}
    assert services["worker_1"]["networks"] == ["app"]
    assert services["pgbouncer"]["networks"]["app"]["aliases"] == [
        "dlgr-8c43a887_pgbouncer"
    ]
    assert result["networks"]["app"]["name"] == "dlgr-8c43a887_app"
    assert "frontdoor" in services
    assert "controller" in services
    assert services["frontdoor"]["networks"]["dallinger"]["aliases"] == [
        "dlgr-8c43a887_web"
    ]
    assert "/var/run/docker.sock" not in str(services["frontdoor"])
    assert services["controller"]["group_add"] == ["${DOCKER_GID}"]
    assert services["controller"]["user"] == "${UID}:${GID}"
    assert services["web"]["restart"] == "no"
    assert services["frontdoor"]["restart"] == "unless-stopped"
    assert services["frontdoor"]["user"] == "${UID}:${GID}"
    assert services["frontdoor"]["environment"]["XDG_DATA_HOME"] == "/state/caddy-data"
    assert "HIBERNATION_SECRET" not in services["frontdoor"].get("environment", {})
    assert services["controller"]["environment"]["HIBERNATION_MANIFEST_PATH"] == (
        "/app/deployment.json"
    )
    assert "./deployment.json:/app/deployment.json" in services["controller"]["volumes"]
    assert "ImportError" in services["controller"]["command"][-1]
    assert services["pgbouncer"]["healthcheck"]["test"][0] == "CMD-SHELL"


def test_hibernation_secret_is_json_quoted_in_compose():
    from dallinger.command_line.docker_ssh import get_docker_compose_yml

    secret = 'abc: "quoted"'
    for ingress in ("classic", "cloudflare"):
        yaml_contents = get_docker_compose_yml(
            {},
            "dlgr-8c43a887",
            "ghcr.io/dallinger/dallinger/bartlett1932",
            "foobar",
            ingress=ingress,
            hibernation_secret=secret,
        )
        result = yaml.safe_load(yaml_contents)
        assert (
            result["services"]["controller"]["environment"]["HIBERNATION_SECRET"]
            == secret
        )


def test_tunnel_compose_has_isolated_postgres_and_no_published_ports():
    result = get_yaml({}, ingress="cloudflare")
    services = result["services"]
    dumped = yaml.safe_dump(result)

    assert services["postgresql"]["container_name"] == "dlgr-8c43a887_postgresql"
    assert "postgresql" in services
    assert "cloudflared" in services
    assert "frontdoor" in services
    assert "controller" in services
    assert "dallinger" not in result.get("networks", {})
    assert "ports:" not in dumped
    assert services["web"]["networks"] == {"app": {"aliases": ["experiment-backend"]}}
    assert "/var/run/docker.sock" not in str(services["frontdoor"])
    assert any(
        "/var/run/docker.sock" in str(volume)
        for volume in services["controller"]["volumes"]
    )
    assert result["networks"]["app"]["name"] == "dlgr-8c43a887_app"
    assert services["controller"]["group_add"] == ["${DOCKER_GID}"]
    assert services["web"]["restart"] == "no"
    assert services["cloudflared"]["restart"] == "unless-stopped"
    assert services["frontdoor"]["user"] == "${UID}:${GID}"
    assert services["frontdoor"]["environment"]["XDG_DATA_HOME"] == "/state/caddy-data"
    assert "HIBERNATION_SECRET" not in services["frontdoor"].get("environment", {})
    assert "./deployment.json:/app/deployment.json" in services["controller"]["volumes"]
    assert services["cloudflared"]["environment"]["HOME"] == "/tmp"
    assert services["pgbouncer"]["healthcheck"]["test"][0] == "CMD-SHELL"
    assert services["pgbouncer"]["depends_on"]["postgresql"]["condition"] == (
        "service_healthy"
    )


def test_get_docker_compose_yml_env_vars_always_strings():
    """The docker-compose.yml file we generate should always have strings as
    values in the `environment` section of each service.
    """
    result = get_yaml({"foo": True, "bar": 2})
    assert result["services"]["worker_1"]["environment"]["foo"] == "True"
    assert result["services"]["worker_1"]["environment"]["bar"] == "2"


def test_get_docker_compose_yml_env_vars_escaping():
    """Environment vars with special character should be correctly escaped."""
    result = get_yaml(
        {
            "foo": r'" a quote and a \ backslash ',
            "bar": "Dollar signs should be escaped with another dollar sign: $1.50",
        }
    )
    assert (
        result["services"]["worker_1"]["environment"]["foo"]
        == r'" a quote and a \ backslash '
    )

    assert (
        result["services"]["worker_1"]["environment"]["bar"]
        == "Dollar signs should be escaped with another dollar sign: $$1.50"
    )


def test_add_image_name(tempdir):
    from dallinger.command_line.docker import add_image_name

    file = Path(tempdir) / "test.txt"

    file.write_text("")
    add_image_name(str(file), "foobar")
    assert "docker_image_name = foobar" in file.read_text()

    file.write_text("\ndocker_image_name = old_image_name\n")
    add_image_name(str(file), "new_image_name")
    assert "old_image_name" not in file.read_text()
    assert "docker_image_name = new_image_name" in file.read_text()

    file.write_text(
        "foo = bar\ndocker_image_base_name = the_base_image_name\nbar = foo"
    )
    add_image_name(str(file), "foobar_image")
    assert (
        file.read_text()
        == "foo = bar\ndocker_image_base_name = the_base_image_name\ndocker_image_name = foobar_image\nbar = foo"
    )


def test_deploy_heroku_docker_pushes_without_reassembling(tmp_path):
    docker_cli = importlib.import_module("dallinger.command_line.docker")

    class StopAfterPush(Exception):
        pass

    config = mock.Mock()
    config.get.side_effect = lambda key, default=None: {
        "mode": "debug",
        "docker_image_base_name": "registry/exp",
        "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    }.get(key, default)

    fake_tools = mock.Mock()
    fake_tools.build_image.return_value = "registry/exp:tag"
    fake_tools.docker_tag_from_experiment_id.side_effect = lambda experiment_id: (
        experiment_id
    )

    with (
        mock.patch.object(docker_cli, "get_config", return_value=config),
        mock.patch.object(docker_cli, "get_experiment_files", return_value=mock.Mock()),
        mock.patch.object(
            docker_cli, "setup_experiment", return_value=("uid", str(tmp_path))
        ) as setup,
        mock.patch.dict(sys.modules, {"dallinger.docker.tools": fake_tools}),
        mock.patch.object(
            docker_cli, "push_image", side_effect=StopAfterPush
        ) as push_image,
    ):
        with pytest.raises(StopAfterPush):
            docker_cli.deploy_heroku_docker(log=mock.Mock(), verbose=False)

    setup.assert_called_once()
    fake_tools.build_image.assert_called_once_with(
        str(tmp_path),
        "registry/exp",
        mock.ANY,
        force_build=True,
        image_tag="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    )
    push_image.assert_called_once_with("registry/exp:tag")


def get_yaml(config, ingress="classic"):
    from dallinger.command_line.docker_ssh import get_docker_compose_yml

    yaml_contents = get_docker_compose_yml(
        config,
        "dlgr-8c43a887",
        "ghcr.io/dallinger/dallinger/bartlett1932",
        "foobar",
        ingress=ingress,
    )
    return yaml.safe_load(yaml_contents)


def test_num_dynos():
    """Make sure the correct number of worker services is created"""
    n = 3
    result = get_yaml({"num_dynos_worker": n})
    for i in range(n):
        assert f"worker_{i + 1}" in result["services"]


def make_experiment_tmp_dir(tmp_path, name="exp"):
    """Create a minimal assembled experiment directory for tag hashing tests."""
    exp_dir = tmp_path / name
    (exp_dir / "static").mkdir(parents=True)
    (exp_dir / "requirements.txt").write_text("dallinger==12.3.0\n")
    (exp_dir / "prepare_docker_image.sh").write_text("#!/bin/sh\ntrue\n")
    (exp_dir / "experiment.py").write_text("class Exp:\n    pass\n")
    (exp_dir / "static" / "script.js").write_text("console.log('hi');\n")
    return exp_dir


def test_deps_image_tag_ignores_experiment_code(tmp_path):
    """Local docker debug hashes only dependency inputs.

    experiment.py is bind-mounted, so a code-only change must keep the same
    tag. SSH/Heroku-docker deploys do not use this hash.
    """
    from dallinger.docker.tools import get_experiment_image_tag

    exp_dir = make_experiment_tmp_dir(tmp_path)
    tag_before = get_experiment_image_tag(str(exp_dir))
    (exp_dir / "experiment.py").write_text("class Exp:\n    variant = 'other'\n")
    (exp_dir / "static" / "script.js").write_text("console.log('changed');\n")
    assert get_experiment_image_tag(str(exp_dir)) == tag_before


def test_deps_image_tag_changes_when_requirements_change(tmp_path):
    from dallinger.docker.tools import get_experiment_image_tag

    exp_dir = make_experiment_tmp_dir(tmp_path)
    tag_before = get_experiment_image_tag(str(exp_dir))
    (exp_dir / "requirements.txt").write_text("dallinger==12.4.0\n")
    assert get_experiment_image_tag(str(exp_dir)) != tag_before


def test_deps_image_tag_changes_when_prepare_script_changes(tmp_path):
    from dallinger.docker.tools import get_experiment_image_tag

    exp_dir = make_experiment_tmp_dir(tmp_path)
    tag_before = get_experiment_image_tag(str(exp_dir))
    (exp_dir / "prepare_docker_image.sh").write_text("#!/bin/sh\necho other\n")
    assert get_experiment_image_tag(str(exp_dir)) != tag_before


def test_deploy_image_tag_is_unique_per_launch():
    """Copied-in deploys must not share a tag across launches."""
    from dallinger.docker.tools import docker_tag_from_experiment_id

    lucid = docker_tag_from_experiment_id("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    prolific = docker_tag_from_experiment_id("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    assert lucid != prolific
    assert lucid == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def test_deploy_image_tag_sanitizes_invalid_docker_characters():
    from dallinger.docker.tools import docker_tag_from_experiment_id

    assert docker_tag_from_experiment_id("exp=id:with/slash") == "exp-id-with-slash"


def test_frontdoor_caddyfile_validates_on_caddy_2_10():
    import json
    import shutil
    import subprocess

    caddyfile = Path("dallinger/docker/ssh_templates/Caddyfile.frontdoor")
    text = caddyfile.read_text()
    assert "{>" not in text
    assert "X-Hibernation-Secret" not in text
    assert "header_up Connection" not in text
    assert "header_up Upgrade" not in text
    if not shutil.which("docker"):
        pytest.skip("docker is required to validate the front-door Caddyfile")
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{caddyfile.resolve()}:/etc/caddy/Caddyfile:ro",
            "caddy:2.10.2",
            "caddy",
            "adapt",
            "--config",
            "/etc/caddy/Caddyfile",
            "--validate",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    adapted = json.dumps(json.loads(result.stdout))
    assert "{>" not in adapted
    assert "X-Hibernation-Secret" not in adapted
    assert "{http.request.header.Connection}" not in adapted
    assert "{http.request.header.Upgrade}" not in adapted


def test_frontdoor_caddy_forwards_upgrade_headers(tmp_path):
    import json
    import os
    import shutil
    import subprocess
    import time
    import urllib.request

    if not shutil.which("docker"):
        pytest.skip("docker is required to exercise front-door Upgrade headers")

    echo = tmp_path / "echo.py"
    echo.write_text(
        "from http.server import BaseHTTPRequestHandler, HTTPServer\n"
        "import json\n"
        "import os\n"
        "\n"
        "class H(BaseHTTPRequestHandler):\n"
        "    def do_GET(self):\n"
        "        body = json.dumps(dict(self.headers)).encode()\n"
        "        self.send_response(200)\n"
        "        self.send_header('Content-Type', 'application/json')\n"
        "        self.send_header('Content-Length', str(len(body)))\n"
        "        self.end_headers()\n"
        "        self.wfile.write(body)\n"
        "\n"
        "    def log_message(self, *args):\n"
        "        return\n"
        "\n"
        "HTTPServer(('0.0.0.0', int(os.environ.get('PORT', '5000'))), H).serve_forever()\n"
    )
    state = tmp_path / "state"
    state.mkdir()
    caddyfile = Path("dallinger/docker/ssh_templates/Caddyfile.frontdoor").resolve()
    suffix = str(os.getpid())
    net = f"dlgr-caddy-{suffix}"
    names = {
        "experiment-backend": f"dlgr-web-{suffix}",
        "controller": f"dlgr-ctrl-{suffix}",
        "frontdoor": f"dlgr-fd-{suffix}",
    }
    created = []
    try:
        create = subprocess.run(
            ["docker", "network", "create", net], capture_output=True, text=True
        )
        if create.returncode != 0:
            pytest.skip(create.stderr or create.stdout)
        for alias, port in (("experiment-backend", "5000"), ("controller", "8080")):
            started = subprocess.run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--rm",
                    "--name",
                    names[alias],
                    "--network",
                    net,
                    "--network-alias",
                    alias,
                    "-e",
                    f"PORT={port}",
                    "-v",
                    f"{echo}:/echo.py:ro",
                    "python:3.12-alpine",
                    "python",
                    "/echo.py",
                ],
                capture_output=True,
                text=True,
            )
            if started.returncode != 0:
                pytest.skip(started.stderr or started.stdout)
            created.append(names[alias])
        started = subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--rm",
                "--name",
                names["frontdoor"],
                "--network",
                net,
                "-p",
                "127.0.0.1::5000",
                "-v",
                f"{caddyfile}:/etc/caddy/Caddyfile:ro",
                "-v",
                f"{state}:/state",
                "caddy:2.10.2",
            ],
            capture_output=True,
            text=True,
        )
        if started.returncode != 0:
            pytest.skip(started.stderr or started.stdout)
        created.append(names["frontdoor"])
        mapped = subprocess.check_output(
            ["docker", "port", names["frontdoor"], "5000"], text=True
        ).strip()
        listen = mapped.split("->")[-1].strip()
        if listen.startswith("0.0.0.0:"):
            listen = "127.0.0.1:" + listen.split(":")[-1]
        request = urllib.request.Request(
            f"http://{listen}/ad",
            headers={
                "Connection": "Upgrade",
                "Upgrade": "websocket",
                "Sec-WebSocket-Version": "13",
                "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==",
            },
        )
        payload = None
        for _ in range(20):
            try:
                with urllib.request.urlopen(request, timeout=2) as response:
                    payload = json.loads(response.read())
                    break
            except Exception:
                time.sleep(0.25)
        assert payload is not None
        dumped = json.dumps(payload)
        assert "{>" not in dumped
        headers = {str(key).lower(): str(value) for key, value in payload.items()}
        assert headers.get("upgrade") != "{>Upgrade}"
        assert headers.get("connection") != "{>Connection}"
    finally:
        for name in created:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        subprocess.run(["docker", "network", "rm", net], capture_output=True)


def test_frontdoor_caddy_returns_503_when_backend_alias_is_absent(tmp_path):
    import json
    import os
    import shutil
    import subprocess
    import time
    import urllib.error
    import urllib.request

    if not shutil.which("docker"):
        pytest.skip("docker is required to exercise a missing backend alias")

    state = tmp_path / "state"
    state.mkdir()
    caddyfile = Path("dallinger/docker/ssh_templates/Caddyfile.frontdoor").resolve()
    suffix = f"{os.getpid()}-absent"
    net = f"dlgr-caddy-{suffix}"
    name = f"dlgr-fd-{suffix}"
    try:
        create = subprocess.run(
            ["docker", "network", "create", net], capture_output=True, text=True
        )
        if create.returncode != 0:
            pytest.skip(create.stderr or create.stdout)
        started = subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--rm",
                "--name",
                name,
                "--network",
                net,
                "-p",
                "127.0.0.1::5000",
                "-v",
                f"{caddyfile}:/etc/caddy/Caddyfile:ro",
                "-v",
                f"{state}:/state",
                "caddy:2.10.2",
            ],
            capture_output=True,
            text=True,
        )
        if started.returncode != 0:
            pytest.skip(started.stderr or started.stdout)
        mapped = subprocess.check_output(["docker", "port", name, "5000"], text=True)
        listen = mapped.strip().split("->")[-1].strip()
        if listen.startswith("0.0.0.0:"):
            listen = "127.0.0.1:" + listen.split(":")[-1]
        error = None
        for _ in range(20):
            try:
                urllib.request.urlopen(f"http://{listen}/ad", timeout=5)
            except urllib.error.HTTPError as exc:
                error = exc
                break
            except Exception:
                time.sleep(0.25)
        assert error is not None
        assert error.code == 503
        assert json.loads(error.read())["status"] == "unavailable"
        stats = subprocess.check_output(
            ["docker", "stats", name, "--no-stream", "--format", "{{.MemUsage}}"],
            text=True,
        )
        used = stats.split("/", 1)[0]
        assert "GiB" not in used
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        subprocess.run(["docker", "network", "rm", net], capture_output=True)


def test_frontdoor_caddy_sends_parked_health_to_controller(tmp_path):
    import json
    import os
    import shutil
    import subprocess
    import time
    import urllib.request

    if not shutil.which("docker"):
        pytest.skip("docker is required to exercise parked /health routing")

    echo = tmp_path / "echo.py"
    echo.write_text(
        "from http.server import BaseHTTPRequestHandler, HTTPServer\n"
        "import json, os\n"
        "class H(BaseHTTPRequestHandler):\n"
        "    def do_GET(self):\n"
        "        body = json.dumps({'from': os.environ['ROLE']}).encode()\n"
        "        self.send_response(200)\n"
        "        self.send_header('Content-Type', 'application/json')\n"
        "        self.send_header('Content-Length', str(len(body)))\n"
        "        self.end_headers()\n"
        "        self.wfile.write(body)\n"
        "    def log_message(self, *args):\n"
        "        return\n"
        "HTTPServer(('0.0.0.0', int(os.environ['PORT'])), H).serve_forever()\n"
    )
    state = tmp_path / "state"
    state.mkdir()
    (state / "hibernating").write_text("")
    caddyfile = Path("dallinger/docker/ssh_templates/Caddyfile.frontdoor").resolve()
    suffix = f"{os.getpid()}-parked"
    net = f"dlgr-caddy-{suffix}"
    names = {
        "web": f"dlgr-web-{suffix}",
        "controller": f"dlgr-ctl-{suffix}",
        "frontdoor": f"dlgr-fd-{suffix}",
    }
    created = []
    try:
        create = subprocess.run(
            ["docker", "network", "create", net], capture_output=True, text=True
        )
        if create.returncode != 0:
            pytest.skip(create.stderr or create.stdout)
        for alias, port, role in (
            ("experiment-backend", "5000", "web"),
            ("controller", "8080", "controller"),
        ):
            started = subprocess.run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--rm",
                    "--name",
                    names["web" if alias == "experiment-backend" else "controller"],
                    "--network",
                    net,
                    "--network-alias",
                    alias,
                    "-e",
                    f"PORT={port}",
                    "-e",
                    f"ROLE={role}",
                    "-v",
                    f"{echo}:/echo.py:ro",
                    "python:3.12-alpine",
                    "python",
                    "/echo.py",
                ],
                capture_output=True,
                text=True,
            )
            if started.returncode != 0:
                pytest.skip(started.stderr or started.stdout)
            created.append(
                names["web" if alias == "experiment-backend" else "controller"]
            )
        started = subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--rm",
                "--name",
                names["frontdoor"],
                "--network",
                net,
                "-p",
                "127.0.0.1::5000",
                "-v",
                f"{caddyfile}:/etc/caddy/Caddyfile:ro",
                "-v",
                f"{state}:/state",
                "caddy:2.10.2",
            ],
            capture_output=True,
            text=True,
        )
        if started.returncode != 0:
            pytest.skip(started.stderr or started.stdout)
        created.append(names["frontdoor"])
        mapped = subprocess.check_output(
            ["docker", "port", names["frontdoor"], "5000"], text=True
        ).strip()
        listen = mapped.split("->")[-1].strip()
        if listen.startswith("0.0.0.0:"):
            listen = "127.0.0.1:" + listen.split(":")[-1]
        payload = None
        for _ in range(20):
            try:
                with urllib.request.urlopen(
                    f"http://{listen}/health", timeout=2
                ) as response:
                    payload = json.loads(response.read())
                    break
            except Exception:
                time.sleep(0.25)
        assert payload == {"from": "controller"}
    finally:
        for name in created:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        subprocess.run(["docker", "network", "rm", net], capture_output=True)
