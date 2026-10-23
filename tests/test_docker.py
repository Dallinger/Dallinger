import importlib
import io
import os
import re
import sys
import tempfile
import time
import warnings
from contextlib import nullcontext
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
    assert services["web"]["restart"] == "unless-stopped"
    assert services["frontdoor"]["restart"] == "unless-stopped"
    assert services["frontdoor"]["user"] == "${UID}:${GID}"
    assert services["frontdoor"]["environment"]["XDG_DATA_HOME"] == "/state/caddy-data"
    from dallinger.command_line.docker_ssh import CONTROLLER_IMAGE

    assert services["controller"]["image"] == CONTROLLER_IMAGE
    assert re.fullmatch(r"python:3\.\d+-alpine@sha256:[0-9a-f]{64}", CONTROLLER_IMAGE)
    assert services["controller"]["command"] == [
        "python",
        "/app/hibernation.py",
        "serve",
    ]
    assert (
        "./hibernation.py:/app/hibernation.py:ro" in services["controller"]["volumes"]
    )
    assert services["pgbouncer"]["healthcheck"]["test"][0] == "CMD-SHELL"


def test_controller_image_needs_a_from_line(tmp_path):
    from dallinger.command_line.docker_ssh import _read_controller_image

    dockerfile = tmp_path / "Dockerfile.controller"
    dockerfile.write_text("# comment\nFROM python:3.14-alpine@sha256:abc\n")
    assert _read_controller_image(dockerfile) == "python:3.14-alpine@sha256:abc"

    dockerfile.write_text("# FROM python:3.14-alpine\n")
    with pytest.raises(RuntimeError, match="FROM line"):
        _read_controller_image(dockerfile)
    with pytest.raises(RuntimeError, match="Dockerfile.controller"):
        _read_controller_image(None)


def test_tunnel_compose_has_isolated_postgres_and_no_published_ports():
    result = get_yaml({}, ingress="cloudflare")
    services = result["services"]
    dumped = yaml.safe_dump(result)

    assert services["postgresql"]["container_name"] == "dlgr-8c43a887_postgresql"
    assert "postgresql" in services
    assert "cloudflared" in services
    assert "frontdoor" in services
    assert "controller" in services
    assert services["frontdoor"]["networks"]["app"]["aliases"] == [
        "dlgr-8c43a887_frontdoor",
        "dlgr-8c43a887_web",
    ]
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
    assert services["web"]["restart"] == "unless-stopped"
    assert services["cloudflared"]["restart"] == "unless-stopped"
    assert services["frontdoor"]["user"] == "${UID}:${GID}"
    assert services["frontdoor"]["environment"]["XDG_DATA_HOME"] == "/state/caddy-data"
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
        ingress=ingress,
    )
    return yaml.safe_load(yaml_contents)


def test_postgres_services_disable_jit(tmp_path, stub_config):
    from dallinger.command_line.docker_ssh import DOCKER_COMPOSE_SERVER_TPL
    from dallinger.docker.tools import DockerComposeWrapper

    wrapper = DockerComposeWrapper(stub_config, None, str(tmp_path), str(tmp_path))
    with mock.patch(
        "dallinger.docker.tools.get_experiment_image_tag", return_value="tag"
    ):
        wrapper.copy_docker_compose_files()
    composes = [
        get_yaml({}, ingress="cloudflare"),
        yaml.safe_load(DOCKER_COMPOSE_SERVER_TPL.render(dozzle_base="")),
        yaml.safe_load((tmp_path / "docker-compose.yml").read_text()),
    ]
    for compose in composes:
        postgres = compose["services"]["postgresql"]
        assert postgres["command"] == "postgres -c jit=off"
        assert "pg_isready -h 127.0.0.1 " in postgres["healthcheck"]["test"][1]
        assert "start_period" in postgres["healthcheck"]


def test_compose_reads_the_database_password_from_the_app_env():
    result = get_yaml({})
    database_url = result["services"]["web"]["environment"]["DATABASE_URL"]
    assert "${POSTGRES_PASSWORD}" in database_url
    assert (
        "POSTGRESQL_PASSWORD=${POSTGRES_PASSWORD}"
        in (result["services"]["pgbouncer"]["environment"])
    )


def test_pgbouncer_allows_more_connections_than_its_defaults():
    pgbouncer = get_yaml({}, ingress="cloudflare")["services"]["pgbouncer"]
    assert "PGBOUNCER_MAX_CLIENT_CONN=10000" in pgbouncer["environment"]
    assert "PGBOUNCER_DEFAULT_POOL_SIZE=80" in pgbouncer["environment"]
    assert pgbouncer["ulimits"]["nofile"] == {"soft": 16384, "hard": 16384}


def test_pgbouncer_keeps_a_small_pool_on_the_shared_postgres():
    pgbouncer = get_yaml({}, ingress="classic")["services"]["pgbouncer"]
    assert "PGBOUNCER_MAX_CLIENT_CONN=10000" in pgbouncer["environment"]
    assert "PGBOUNCER_DEFAULT_POOL_SIZE=20" in pgbouncer["environment"]


@pytest.mark.parametrize("n, shares", [(1, 102), (3, 34), (100, 2)])
def test_worker_processes_get_low_cpu_weight(n, shares):
    """Each worker process gets its own container, weighted below the web server."""
    services = get_yaml({"worker_processes": n})["services"]
    workers = [name for name in services if name.startswith("worker_")]
    assert len(workers) == n
    assert {services[name]["cpu_shares"] for name in workers} == {shares}
    assert "cpu_shares" not in services["web"]


WEB_NOFILE = {"nofile": {"soft": 65536, "hard": 65536}}


@pytest.mark.parametrize("ingress", ["classic", "cloudflare"])
def test_web_container_can_hold_many_open_files(ingress):
    """Idle websockets must not exhaust the web container's file descriptors."""
    services = get_yaml({}, ingress=ingress)["services"]
    assert services["web"]["ulimits"] == WEB_NOFILE


def make_experiment_tmp_dir(tmp_path, name="exp"):
    """Create a minimal assembled experiment directory for tag hashing tests."""
    exp_dir = tmp_path / name
    (exp_dir / "static").mkdir(parents=True)
    (exp_dir / "requirements.txt").write_text("dallinger==12.3.0\n")
    (exp_dir / "prepare_docker_image.sh").write_text("#!/bin/sh\ntrue\n")
    (exp_dir / "experiment.py").write_text("class Exp:\n    pass\n")
    (exp_dir / "static" / "script.js").write_text("console.log('hi');\n")
    return exp_dir


@pytest.mark.parametrize(
    "settings, replicas, shares", [({}, 1, 102), ({"worker_processes": 3}, 3, 34)]
)
def test_local_compose_runs_low_weight_worker_replicas(
    tmp_path, stub_config, settings, replicas, shares
):
    from dallinger.docker.tools import DockerComposeWrapper

    stub_config.extend(settings)
    exp_dir = make_experiment_tmp_dir(tmp_path)
    wrapper = DockerComposeWrapper(
        stub_config, mock.Mock(), str(tmp_path), str(exp_dir)
    )
    wrapper.copy_docker_compose_files()
    services = yaml.safe_load((exp_dir / "docker-compose.yml").read_text())["services"]
    assert services["worker"]["deploy"]["replicas"] == replicas
    assert services["worker"]["cpu_shares"] == shares
    assert "cpu_shares" not in services["web"]
    assert services["web"]["ulimits"] == WEB_NOFILE


def test_docker_worker_processes_falls_back_to_num_dynos_worker(stub_config):
    from dallinger.docker.tools import docker_worker_processes

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert docker_worker_processes(stub_config) == 1
    stub_config.extend({"num_dynos_worker": 3})
    with pytest.warns(FutureWarning, match="worker_processes"):
        assert docker_worker_processes(stub_config) == 3
    stub_config.extend({"worker_processes": 2})
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert docker_worker_processes(stub_config) == 2


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


def make_docker_debug_wrapper(config, exp_dir, environ):
    """Build the compose wrapper the way ``HerokuLocalDeployment.run`` does."""
    from dallinger.docker.tools import DockerComposeWrapper

    return DockerComposeWrapper(
        config,
        mock.Mock(),
        str(exp_dir),
        str(exp_dir),
        env={**os.environ, **environ},
    )


def test_docker_debug_containers_get_the_deployment_flask_secret_key(
    tmp_path, stub_config
):
    from dallinger.docker.deployment import DockerDebugDeployment
    from dallinger.docker.tools import _quote_dotenv_value

    exp_dir = make_experiment_tmp_dir(tmp_path)
    deployment = DockerDebugDeployment(mock.Mock(), False, False, None, {})
    dotenv_path = exp_dir / ".env"
    dotenv_path.touch()
    dotenv_path.chmod(0o644)
    make_docker_debug_wrapper(
        stub_config, exp_dir, deployment.environ
    ).copy_docker_compose_files()

    key = deployment.environ["FLASK_SECRET_KEY"]
    assert (
        f"FLASK_SECRET_KEY={_quote_dotenv_value(key)}"
        in dotenv_path.read_text().splitlines()
    )
    assert dotenv_path.stat().st_mode & 0o777 == 0o600
    compose = yaml.safe_load((exp_dir / "docker-compose.yml").read_text())
    for service in ("web", "worker", "clock"):
        environment = compose["services"][service]["environment"]
        assert environment["FLASK_SECRET_KEY"].startswith("${FLASK_SECRET_KEY:?")


def test_docker_debug_compose_calls_override_an_empty_host_secret_key(
    tmp_path, stub_config
):
    from dallinger.docker import tools

    with mock.patch.dict(os.environ, {"FLASK_SECRET_KEY": ""}):
        wrapper = make_docker_debug_wrapper(
            stub_config, tmp_path, {"FLASK_SECRET_KEY": "k"}
        )
    with (
        mock.patch.object(tools, "check_output") as check_output,
        mock.patch.object(tools, "call") as call,
    ):
        wrapper.run_compose(["up", "-d"])
        wrapper.stop()
    assert check_output.call_args.kwargs["env"]["FLASK_SECRET_KEY"] == "k"
    assert call.call_args.kwargs["env"]["FLASK_SECRET_KEY"] == "k"


def test_docker_debug_image_build_context_has_no_dotenv(tmp_path, stub_config):
    from dallinger.docker import tools

    exp_dir = make_experiment_tmp_dir(tmp_path)
    wrapper = make_docker_debug_wrapper(stub_config, exp_dir, {"FLASK_SECRET_KEY": "k"})
    dotenv_seen_by_build = []
    with (
        mock.patch.object(
            tools,
            "build_image",
            side_effect=lambda *args: dotenv_seen_by_build.append(
                (exp_dir / ".env").exists()
            ),
        ),
        mock.patch.object(wrapper, "run_compose", side_effect=RuntimeError),
        pytest.raises(RuntimeError),
    ):
        wrapper.start()
    assert dotenv_seen_by_build == [False]
    assert (exp_dir / ".env").exists()


def test_dotenv_quoting_keeps_compose_special_characters_literal():
    from dallinger.docker.tools import _quote_dotenv_value

    assert _quote_dotenv_value('a$b #"c\\') == '"a\\$b #\\"c\\\\"'


def test_docker_debug_dotenv_treats_a_none_secret_key_as_empty(tmp_path, stub_config):
    exp_dir = make_experiment_tmp_dir(tmp_path)
    wrapper = make_docker_debug_wrapper(
        stub_config, exp_dir, {"FLASK_SECRET_KEY": None}
    )
    wrapper.copy_docker_compose_files()
    assert 'FLASK_SECRET_KEY=""' in (exp_dir / ".env").read_text().splitlines()
    assert wrapper.env["FLASK_SECRET_KEY"] == ""


def test_custom_dockerfile_reinstalls_a_staged_local_wheel_without_base_image(
    tmp_path, capsys
):
    import docker

    from dallinger.docker import tools

    (tmp_path / "Dockerfile").write_text("FROM python:3.12\nCOPY . /experiment\n")
    (tmp_path / "requirements.txt").write_text("psynet\n")
    (tmp_path / "dallinger-1-py3-none-any.whl").write_bytes(b"wheel")
    client = mock.Mock()
    client.api.inspect_image.side_effect = docker.errors.ImageNotFound("missing")
    with (
        mock.patch("docker.client.from_env", return_value=client) as from_env,
        mock.patch.object(tools, "check_output") as check_output,
    ):
        tools.build_image(tmp_path, "exp", mock.Mock(), image_tag="t")
    from_env.assert_called_once_with(use_ssh_client=True)
    assert "Could not determine Dallinger version" not in capsys.readouterr().out
    build_args = check_output.call_args.args[0]
    assert f"{tools.RUNS_AS_SSH_USER_LABEL}=1" in build_args
    dockerfile = (tmp_path / "Dockerfile").read_text()
    assert tools.LOCAL_DALLINGER_WHEEL_SNIPPET in dockerfile
    assert "--force-reinstall --no-deps" in tools.LOCAL_DALLINGER_WHEEL_SNIPPET


def _quiet_build(tmp_path, monkeypatch, fake_docker_script, raises=nullcontext()):
    """Run a quiet ``build_image`` with a fake ``docker``; return its messages."""
    import docker

    from dallinger.command_line.utils import Output
    from dallinger.docker import tools

    fake_docker = tmp_path / "docker"
    fake_docker.write_text("#!/bin/sh\n" + fake_docker_script)
    fake_docker.chmod(0o755)
    monkeypatch.setattr(tools, "which", lambda name: str(fake_docker))
    monkeypatch.setattr(tools, "_BUILD_POLL_SECONDS", 0.05)
    # Redirected output, also under `pytest -s`.
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    (tmp_path / "Dockerfile").write_text("FROM python:3.12\n")
    messages = []
    client = mock.Mock()
    client.api.inspect_image.side_effect = docker.errors.ImageNotFound("missing")
    with (
        mock.patch("docker.client.from_env", return_value=client),
        mock.patch.object(tools, "get_base_image", return_value="base"),
        raises,
    ):
        tools.build_image(
            tmp_path,
            "exp",
            Output(blather=messages.append),
            image_tag="t",
            quiet=True,
        )
    return messages


@pytest.mark.parametrize("exit_code", [0, 1])
def test_quiet_build_keeps_docker_output_in_log_file(tmp_path, monkeypatch, exit_code):
    from dallinger.docker import tools

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(log_dir))
    messages = _quiet_build(
        tmp_path,
        monkeypatch,
        f"echo '#14 + ansi2html' >&2\nexit {exit_code}\n",
        pytest.raises(tools.BuildError) if exit_code else nullcontext(),
    )
    output = "".join(messages)
    assert messages[0] == (
        "Building image exp:t (custom Dockerfile; "
        "set DALLINGER_VERBOSE_BUILD=1 to show docker's output)...\n"
    )
    assert ("+ ansi2html" in output) == bool(exit_code)
    assert ("Built image: exp:" in output) == (not exit_code)
    if not exit_code:
        assert len(messages) == 2
    assert all(message.endswith("\n") for message in messages)
    kept_logs = list(log_dir.iterdir())
    assert len(kept_logs) == exit_code
    assert all("+ ansi2html" in log.read_text() for log in kept_logs)


def test_quiet_build_reports_slow_steps_and_duration(tmp_path, monkeypatch):
    # BuildKit's output lines give the seconds since their step started, so a
    # step whose output says 31.0 has been running for at least 30 s. The
    # later internal step must not hide it, nor docker exiting right away.
    messages = _quiet_build(
        tmp_path,
        monkeypatch,
        "echo '#5 [2/3] COPY . /experiment'\necho '#5 DONE 0.1s'\n"
        "echo '#6 [ 3/3] RUN pip install     -r requirements.txt'\n"
        "echo '#7 [internal] load build context'\n"
        "echo '#6 31.0 Collecting psynet'\n",
    )
    output = "".join(messages)
    assert output.count("Still on") == 1
    assert (
        "Still on step 3/3 after 30 s: RUN pip install -r requirements.txt\n" in output
    )
    assert re.fullmatch(r"Built image: exp:t \([12] s\)\.\n", messages[-1])
    assert "\r" not in output


def test_verbose_rebuild_streams_docker_output(tmp_path, monkeypatch):
    from dallinger.command_line.utils import Output
    from dallinger.docker import tools

    monkeypatch.setenv("DALLINGER_VERBOSE_BUILD", "1")
    messages = []
    with (
        mock.patch("docker.client.from_env"),
        mock.patch.object(tools, "get_base_image", return_value="base"),
        mock.patch.object(tools, "check_output") as check_output,
    ):
        tools.build_image(
            tmp_path, "exp", Output(blather=messages.append), image_tag="t", quiet=True
        )
    check_output.assert_called_once()
    assert messages[0] == "Rebuilding image exp:t...\n"
    assert re.fullmatch(r"Built image: exp:t \([12] s\)\.\n", messages[1])
    assert len(messages) == 2


@pytest.mark.parametrize(
    "requirements, tag, message",
    [
        ("dallinger==12.0.0\n", "12.0.0", ""),
        ("psynet\n", "latest", "Using latest"),
        ("dallinger==12.5.0a1\n", "latest", "12.5.0a1 is a pre-release"),
    ],
)
def test_generated_dockerfile_uses_the_pinned_base_image(
    tmp_path, capsys, requirements, tag, message
):
    import docker

    from dallinger.docker import tools

    (tmp_path / "requirements.txt").write_text(requirements)
    client = mock.Mock()
    client.api.inspect_image.side_effect = docker.errors.ImageNotFound("missing")
    with (
        mock.patch("docker.client.from_env", return_value=client),
        mock.patch.object(tools, "check_output"),
    ):
        tools.build_image(
            tmp_path, "exp", mock.Mock(), needs_chrome=True, image_tag="t"
        )
    dockerfile = (tmp_path / "Dockerfile").read_text()
    assert f"FROM ghcr.io/dallinger/dallinger-bot:{tag}" in dockerfile
    assert message in capsys.readouterr().out


def test_build_image_reuses_an_existing_image_without_resolving_the_base_image(
    tmp_path,
):
    from dallinger.command_line.utils import Output
    from dallinger.docker import tools

    client = mock.Mock()
    messages = []
    with (
        mock.patch("docker.client.from_env", return_value=client),
        mock.patch.object(tools, "get_base_image") as get_base_image,
        mock.patch.object(tools, "check_output") as check_output,
    ):
        name = tools.build_image(
            tmp_path,
            "exp",
            Output(blather=messages.append),
            force_build=False,
            image_tag="t",
        )
    assert name == "exp:t"
    assert messages == ["Image exp:t found\n"]
    get_base_image.assert_not_called()
    check_output.assert_not_called()


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


def test_split_ssh_host_port():
    from dallinger.command_line.docker_ssh import split_ssh_host_port

    assert split_ssh_host_port("example.com") == ("example.com", 22)
    assert split_ssh_host_port("localhost:2222") == ("localhost", 2222)
    assert split_ssh_host_port("::1") == ("::1", 22)
    assert split_ssh_host_port("[::1]:2200") == ("::1", 2200)
    assert split_ssh_host_port("[::1]") == ("::1", 22)


@pytest.mark.parametrize(
    "host",
    [
        "",
        ":2222",
        "example.com:abc",
        "example.com:70000",
        "[::1]:abc",
        "[::1]:70000",
        "[::1",
        "example.com:22:33",
    ],
)
def test_split_ssh_host_port_rejects_invalid_host_formats(host):
    import click

    from dallinger.command_line.docker_ssh import split_ssh_host_port

    with pytest.raises(click.UsageError):
        split_ssh_host_port(host)


def test_is_loopback_host():
    from dallinger.command_line.docker_ssh import is_loopback_host

    assert is_loopback_host("localhost")
    assert is_loopback_host("127.0.0.1")
    assert is_loopback_host("127.0.0.2")
    assert not is_loopback_host("203.0.113.10")
    assert not is_loopback_host("example.com")


def test_get_connected_ssh_client_reuses_one_quiet_connection(
    tmp_path, monkeypatch, capsys
):
    import importlib

    docker_ssh = importlib.import_module("dallinger.command_line.docker_ssh")

    key_path = tmp_path / "server.pem"
    key_path.write_text("dummy")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(docker_ssh, "get_server_pem_path", lambda: key_path)

    class DummyClient:
        def __init__(self):
            self.transport = mock.Mock()
            self.closed = False

        def close(self):
            self.closed = True

        def load_host_keys(self, filename):
            if not Path(filename).exists():
                raise IOError("missing")

        def set_missing_host_key_policy(self, policy):
            pass

        def load_system_host_keys(self):
            pass

        def connect(self, **kwargs):
            pass

        def get_transport(self):
            return self.transport

        def save_host_keys(self, filename):
            assert Path(filename).exists()

    monkeypatch.setattr(docker_ssh.paramiko, "SSHClient", DummyClient)

    client = docker_ssh.get_connected_ssh_client("localhost:2222", user="root")
    assert isinstance(client, DummyClient)
    assert (tmp_path / ".ssh" / "known_hosts").exists()
    assert docker_ssh.get_connected_ssh_client("localhost:2222", user="root") is client
    assert capsys.readouterr().out == "Connecting to localhost:2222...\nConnected.\n"

    local = docker_ssh.get_connected_ssh_client("localhost")
    assert local is not client
    assert docker_ssh.get_connected_ssh_client(
        "localhost:22", docker_ssh.getuser()
    ) is (local)

    executor = docker_ssh.Executor("localhost:2222", user="root")
    client.transport.is_active.return_value = False
    assert executor.client is not client
    assert client.closed
    assert executor.client is docker_ssh.get_connected_ssh_client(
        "localhost:2222", "root"
    )


def _client_refusing_sessions(docker_ssh, error, connection_dies):
    """A client whose open_session fails, optionally taking the connection down."""
    client = mock.Mock()
    transport = client.get_transport.return_value

    def open_session():
        transport.is_active.return_value = not connection_dies
        raise error

    transport.open_session.side_effect = open_session
    return client


def test_run_with_status_reconnects_once_when_connection_died(monkeypatch):
    docker_ssh = importlib.import_module("dallinger.command_line.docker_ssh")
    SSHException = docker_ssh.paramiko.SSHException
    dead = _client_refusing_sessions(docker_ssh, SSHException("dropped"), True)
    clients = [dead, mock.Mock()]
    monkeypatch.setattr(docker_ssh, "_connect_ssh_client", lambda *a: clients.pop(0))
    monkeypatch.setattr(
        docker_ssh.Executor, "_drain_channel", staticmethod(lambda ch: (0, "ok", ""))
    )

    assert docker_ssh.Executor("example.com").run_with_status("true") == (0, "ok", "")
    dead.close.assert_called_once()


def test_forgetting_a_stale_client_keeps_its_replacement_until_close(monkeypatch):
    docker_ssh = importlib.import_module("dallinger.command_line.docker_ssh")
    old, new = mock.Mock(), mock.Mock()
    connect = mock.Mock(side_effect=[old, new])
    monkeypatch.setattr(docker_ssh, "_connect_ssh_client", connect)
    executor = docker_ssh.Executor("example.com")
    old.get_transport.return_value.is_active.return_value = False
    assert executor.client is new

    docker_ssh._forget_ssh_client("example.com", None, old)
    assert executor.client is new
    new.close.assert_not_called()

    executor.close()
    new.close.assert_called_once()
    assert connect.call_count == 2


def test_run_with_status_keeps_a_live_connection_that_refuses_a_channel(monkeypatch):
    docker_ssh = importlib.import_module("dallinger.command_line.docker_ssh")
    refused = docker_ssh.paramiko.ChannelException(2, "MaxSessions")
    busy = _client_refusing_sessions(docker_ssh, refused, False)
    connect = mock.Mock(return_value=busy)
    monkeypatch.setattr(docker_ssh, "_connect_ssh_client", connect)

    with pytest.raises(docker_ssh.paramiko.ChannelException):
        docker_ssh.Executor("example.com").run_with_status("true")
    busy.close.assert_not_called()
    connect.assert_called_once()


def test_run_with_status_does_not_retry_a_failed_reconnect(monkeypatch):
    docker_ssh = importlib.import_module("dallinger.command_line.docker_ssh")
    closed = mock.Mock()
    login_failed = docker_ssh.paramiko.AuthenticationException("denied")
    connect = mock.Mock(side_effect=[closed, login_failed])
    monkeypatch.setattr(docker_ssh, "_connect_ssh_client", connect)
    executor = docker_ssh.Executor("example.com")
    closed.get_transport.return_value.is_active.return_value = False

    with pytest.raises(docker_ssh.paramiko.AuthenticationException):
        executor.run_with_status("true")
    assert connect.call_count == 2


def test_failing_remote_command_stops_spinner_before_error(monkeypatch, capsys):
    docker_ssh = importlib.import_module("dallinger.command_line.docker_ssh")

    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    spinner = mock.MagicMock()
    spinner.stop.side_effect = lambda: print("<spinner cleared>")
    monkeypatch.setattr(docker_ssh, "yaspin", lambda **kwargs: spinner)
    monkeypatch.setattr(docker_ssh, "get_connected_ssh_client", mock.Mock())
    executor = docker_ssh.Executor("example.com")
    monkeypatch.setattr(executor, "run_with_status", lambda cmd: (1, "", "boom"))

    with pytest.raises(docker_ssh.ExecuteException):
        with docker_ssh._spinner(text="Restarting Dozzle"):
            executor.run("docker compose restart dozzle")
    assert capsys.readouterr().out.startswith("<spinner cleared>\nError: exit code")


@pytest.mark.parametrize("key_format", ["TraditionalOpenSSL", "OpenSSH"])
def test_get_connected_ssh_client_rejects_dsa_key(tmp_path, monkeypatch, key_format):
    import click
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import dsa, ed25519

    docker_ssh = importlib.import_module("dallinger.command_line.docker_ssh")

    def write_key(private_key, name, key_format):
        path = tmp_path / name
        path.write_bytes(
            private_key.private_bytes(
                serialization.Encoding.PEM,
                getattr(serialization.PrivateFormat, key_format),
                serialization.NoEncryption(),
            )
        )
        return path

    dsa_path = write_key(dsa.generate_private_key(key_size=1024), "dsa.pem", key_format)
    monkeypatch.setattr(docker_ssh, "get_server_pem_path", lambda: dsa_path)
    monkeypatch.setattr(docker_ssh.paramiko, "SSHClient", mock.Mock())

    with pytest.raises(click.ClickException, match="#replacing-a-dsa-key"):
        docker_ssh.get_connected_ssh_client("example.com", user="root")
    docker_ssh.paramiko.SSHClient.assert_not_called()
    assert not docker_ssh._is_dsa_key(
        write_key(ed25519.Ed25519PrivateKey.generate(), "ed25519.pem", "OpenSSH")
    )


def _docker_connection_error():
    """Return the error docker-py raises when its SSH connection breaks."""
    import docker.errors
    import requests
    import urllib3.exceptions

    try:
        try:
            raise requests.exceptions.ConnectionError(
                urllib3.exceptions.ProtocolError(
                    "Connection aborted.", BrokenPipeError(32, "Broken pipe")
                )
            )
        except requests.exceptions.ConnectionError as exc:
            raise docker.errors.DockerException(
                f"Error while fetching server API version: {exc}"
            ) from exc
    except docker.errors.DockerException as exc:
        return exc


def _unknown_host(**kwargs):
    import socket

    import paramiko

    no_such_host = socket.gaierror(socket.EAI_NONAME, "Name or service not known")
    with mock.patch("socket.getaddrinfo", side_effect=no_such_host):
        paramiko.SSHClient().connect("host.example", timeout=1)


def _refused_connection(**kwargs):
    import socket

    import paramiko

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    paramiko.SSHClient().connect("127.0.0.1", port=port, timeout=5)


@pytest.mark.parametrize(
    "error, expected",
    [
        (
            "auth",
            "Error: Couldn't log in to host.example:2200 over SSH as alice. Check "
            "that `ssh -i /keys/lab.pem -p 2200 alice@host.example` works without "
            "asking for a password, with the key in the server_pem setting.",
        ),
        (
            "unknown",
            "Error: Couldn't connect to host.example:2200 over SSH: can't find a "
            "host called host.example.",
        ),
        (
            "docker",
            "Error: Couldn't reach Docker on host.example:2200 over SSH "
            "(Broken pipe; see any message from ssh above).",
        ),
        ("local-docker", None),
        (
            "refused",
            "Error: Couldn't connect to host.example:2200 over SSH: nothing "
            "accepted the connection on port 2200.",
        ),
        ("other", None),
    ],
)
def test_deploy_reports_ssh_failures_in_one_line(monkeypatch, error, expected):
    import paramiko
    from click.testing import CliRunner

    docker_ssh = importlib.import_module("dallinger.command_line.docker_ssh")
    failures = {
        "auth": paramiko.AuthenticationException("Authentication failed."),
        "docker": _docker_connection_error(),
        "refused": _refused_connection,
        "unknown": _unknown_host,
        "other": paramiko.SSHException("Channel closed."),
    }
    failures["local-docker"] = failures["docker"]
    monkeypatch.setattr(docker_ssh, "get_server_pem_path", lambda: "/keys/lab.pem")
    args = ["--local_build"] if error == "local-docker" else []
    server = {"host": "host.example:2200", "user": "alice"}
    monkeypatch.setattr(docker_ssh, "CONFIGURED_HOSTS", {"host.example:2200": server})
    monkeypatch.setattr(
        docker_ssh, "get_configured_hosts", lambda: {"host.example:2200": server}
    )
    monkeypatch.setattr(
        docker_ssh, "_deploy_in_mode", mock.Mock(side_effect=failures[error])
    )

    result = CliRunner().invoke(
        docker_ssh.deploy, ["--server", "host.example:2200", *args]
    )

    assert result.exit_code == 1
    if expected is None:
        assert result.exception is failures[error]
    else:
        assert expected in result.output
        assert "Traceback" not in result.output


def test_first_ssh_login_failure_is_one_error_line(monkeypatch):
    import click
    import paramiko

    docker_ssh = importlib.import_module("dallinger.command_line.docker_ssh")
    denied = mock.Mock(side_effect=paramiko.AuthenticationException("denied"))
    monkeypatch.setattr(docker_ssh, "get_connected_ssh_client", denied)
    monkeypatch.setattr(docker_ssh, "get_server_pem_path", lambda: "/keys/lab.pem")

    with pytest.raises(click.ClickException) as error:
        docker_ssh.ensure_remote_host_in_known_hosts("pc.example", "ab1@uni.example")

    assert error.value.message == (
        "Couldn't log in to pc.example over SSH as ab1@uni.example. Check that "
        "`ssh -i /keys/lab.pem -l ab1@uni.example pc.example` works without "
        "asking for a password, with the key in the server_pem setting."
    )


def test_nip_io_dns_host_of_an_unknown_server_is_one_error_line():
    import click

    from dallinger.command_line.docker_ssh import get_dns_host

    with pytest.raises(click.ClickException, match="Can't find the IP address"):
        get_dns_host("no-such-server.invalid")


def test_option_update_parses_as_boolean():
    import click
    from click.testing import CliRunner

    from dallinger.command_line.docker_ssh import option_update

    @click.command()
    @option_update
    def cmd(update):
        click.echo(f"{update!r}:{type(update).__name__}")

    runner = CliRunner()
    result_default = runner.invoke(cmd, [])
    assert result_default.exit_code == 0
    assert "False:bool" in result_default.output

    result_update = runner.invoke(cmd, ["--update"])
    assert result_update.exit_code == 0
    assert "True:bool" in result_update.output


def test_get_sftp_sets_working_directory_to_remote_home(monkeypatch):
    import importlib

    docker_ssh = importlib.import_module("dallinger.command_line.docker_ssh")

    class DummyStdout:
        def read(self):
            return b"/home/tester\n"

    class DummySFTP:
        changed_to = None

        def chdir(self, path):
            self.changed_to = path

    class DummyClient:
        def __init__(self):
            self.sftp = DummySFTP()

        def open_sftp(self):
            return self.sftp

        def exec_command(self, command):
            assert command == 'printf %s "$HOME"'
            return None, DummyStdout(), None

    client = DummyClient()
    monkeypatch.setattr(
        docker_ssh, "get_connected_ssh_client", lambda host, user=None: client
    )

    sftp = docker_ssh.get_sftp("localhost")
    assert sftp is client.sftp
    assert sftp.changed_to == "/home/tester"


def test_get_sftp_propagates_exec_command_failure(monkeypatch):
    import importlib

    docker_ssh = importlib.import_module("dallinger.command_line.docker_ssh")

    class DummyClient:
        def open_sftp(self):
            return object()

        def exec_command(self, command):
            raise OSError("channel closed")

    monkeypatch.setattr(
        docker_ssh, "get_connected_ssh_client", lambda host, user=None: DummyClient()
    )

    with pytest.raises(OSError, match="channel closed"):
        docker_ssh.get_sftp("localhost")


def test_set_dozzle_password_skips_restart_when_not_running():
    import importlib

    docker_ssh = importlib.import_module("dallinger.command_line.docker_ssh")
    executor = mock.Mock()

    def run_side_effect(command, raise_=True):
        if "test -f ~/dallinger/.env.json" in command:
            return ""
        if "docker ps --filter name=^dozzle$" in command:
            return ""
        return ""

    executor.run.side_effect = run_side_effect
    sftp = mock.Mock()

    docker_ssh.set_dozzle_password(executor, sftp, "secret-password")

    assert sftp.putfo.call_count == 2
    executor.restart_dozzle.assert_not_called()


def test_ensure_postgres_schema_permissions_grants_create():
    import importlib

    docker_ssh = importlib.import_module("dallinger.command_line.docker_ssh")
    executor = mock.Mock()

    docker_ssh.ensure_postgres_schema_permissions(executor, "dlgr-abcdef12")

    assert executor.run.call_count == 1
    command = executor.run.call_args[0][0]
    assert 'psql -U dallinger -d "dlgr-abcdef12"' in command
    assert "GRANT USAGE, CREATE ON SCHEMA public TO" in command


def test_is_remote_disk_full_error_detects_common_markers():
    from dallinger.command_line.docker_ssh import _is_remote_disk_full_error

    assert _is_remote_disk_full_error("no space left on device")
    assert _is_remote_disk_full_error("psycopg2.errors.DiskFull")
    assert _is_remote_disk_full_error("Error response from daemon: disk full")
    assert not _is_remote_disk_full_error("authentication failed")


def test_get_remote_disk_full_guidance_recommends_safe_cleanup_only():
    from dallinger.command_line.docker_ssh import get_remote_disk_full_guidance

    guidance = get_remote_disk_full_guidance("example.org")
    assert (
        "Remote Docker host 'example.org' appears to be out of disk space." in guidance
    )
    assert "docker image prune -af" in guidance
    assert "docker container prune -f --filter label!=com.docker.compose.project" in (
        guidance
    )
    assert "do not auto-prune volumes" in guidance
    assert "docker system prune -af --volumes" not in guidance


def test_executor_drain_channel_reads_stdout_and_stderr_concurrently():
    """_drain_channel must drain both streams before calling recv_exit_status.

    FakeChannel simulates the SSH deadlock: recv_exit_status() blocks until
    stderr has been read (because the remote process is stuck writing to a full
    buffer). A sequential implementation that calls recv_exit_status() first
    would deadlock; _drain_channel must drain both streams concurrently first.
    """
    import threading

    from dallinger.command_line.docker_ssh import Executor

    stderr_drained = threading.Event()

    class FakeChannel:
        def recv(self, _size):
            return b""

        def recv_stderr(self, _size):
            if not stderr_drained.is_set():
                stderr_drained.set()
                return b"big stderr output"
            return b""

        def recv_exit_status(self):
            if not stderr_drained.wait(timeout=1.0):
                raise TimeoutError(
                    "deadlock: recv_exit_status called before stderr was drained"
                )
            return 0

    status, stdout, stderr = Executor._drain_channel(FakeChannel())
    assert status == 0
    assert stderr == "big stderr output"


def test_get_required_dallinger_version_prerelease_falls_back_to_latest(tmp_path):
    from dallinger.docker.tools import LATEST_VERSION, get_required_dallinger_version

    requirements = tmp_path / "requirements.txt"
    requirements.write_text("dallinger==12.2.0a1\n")

    assert get_required_dallinger_version(str(tmp_path)) == LATEST_VERSION


def test_get_required_dallinger_version_follows_includes_and_options(tmp_path):
    from dallinger.docker.tools import get_required_dallinger_version

    (tmp_path / "constraints.txt").write_text(
        "# pinned\ndallinger==7.2.0 \\\n    --hash=sha256:abc  # trailing comment\n"
    )
    (tmp_path / "requirements.txt").write_text(
        "-e ./local-package\n\n--index-url https://example.org\nrequests\n-c constraints.txt\n"
    )

    assert get_required_dallinger_version(str(tmp_path)) == "7.2.0"


def test_get_required_dallinger_version_from_wheel_file(tmp_path):
    from dallinger.docker.tools import get_required_dallinger_version

    (tmp_path / "requirements.txt").write_text(
        "file:dallinger-7.3.0-py3-none-any.whl\n"
    )

    assert get_required_dallinger_version(str(tmp_path)) == "7.3.0"


def test_get_required_dallinger_version_windows_file(tmp_path):
    from dallinger.docker.tools import get_required_dallinger_version

    (tmp_path / "requirements.txt").write_bytes(
        "\ufeffdallinger==7.2.0\r\n    # via -r requirements.txt\r\n".encode()
    )

    assert get_required_dallinger_version(str(tmp_path)) == "7.2.0"


def test_get_required_dallinger_version_utf16_file(tmp_path):
    from dallinger.docker.tools import get_required_dallinger_version

    (tmp_path / "requirements.txt").write_text(
        "dallinger==7.2.0\r\n", encoding="utf-16"
    )

    assert get_required_dallinger_version(str(tmp_path)) == "7.2.0"


def test_get_required_dallinger_version_follows_requirement_include(tmp_path):
    from dallinger.docker.tools import get_required_dallinger_version

    (tmp_path / "base.txt").write_text("dallinger==7.2.0\n")
    (tmp_path / "requirements.txt").write_text("requests\n-r base.txt\n")

    assert get_required_dallinger_version(str(tmp_path)) == "7.2.0"


def test_get_required_dallinger_version_include_cycle(tmp_path):
    from dallinger.docker.tools import get_required_dallinger_version

    (tmp_path / "base.txt").write_text("-r requirements.txt\n")
    (tmp_path / "requirements.txt").write_text("-r base.txt\n")

    with pytest.raises(ValueError, match="cycle"):
        get_required_dallinger_version(str(tmp_path))


@pytest.mark.parametrize(
    "line",
    ["dallinger == 7.2.0", 'dallinger==7.2.0 ; python_version>="3.10"'],
)
def test_get_required_dallinger_version_parses_specifier(tmp_path, line):
    from dallinger.docker.tools import get_required_dallinger_version

    (tmp_path / "requirements.txt").write_text(line + "\n")

    assert get_required_dallinger_version(str(tmp_path)) == "7.2.0"


def test_docker_tools_import_without_pip():
    """``dallinger.docker.tools`` must import in environments without pip, e.g. uv."""
    import subprocess
    import sys

    code = "import sys; sys.modules['pip'] = None; import dallinger.docker.tools"
    subprocess.run([sys.executable, "-c", code], check=True)


def test_get_required_dallinger_version_dev_release_falls_back_to_latest(tmp_path):
    from dallinger.docker.tools import LATEST_VERSION, get_required_dallinger_version

    requirements = tmp_path / "requirements.txt"
    requirements.write_text("dallinger==12.2.0.dev1\n")

    assert get_required_dallinger_version(str(tmp_path)) == LATEST_VERSION


def test_push_image_retries_connection_error_and_succeeds():
    import requests

    from dallinger.command_line.docker import DOCKER_PUSH_TIMEOUT, push_image

    fake_digest = "sha256:abc123"
    call_count = 0

    def fake_push(image, stream=False, decode=False):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise requests.exceptions.ConnectionError("connection reset")
        return iter([{"status": "Pushing"}, {"aux": {"Digest": fake_digest}}])

    fake_image = mock.Mock()
    fake_image.attrs = {"RepoDigests": [f"registry/exp@{fake_digest}"]}
    fake_client = mock.Mock()
    fake_client.images.push.side_effect = fake_push
    fake_client.images.get.return_value = fake_image

    with (
        mock.patch("docker.client.from_env", return_value=fake_client) as from_env,
        mock.patch("time.sleep"),
    ):
        result = push_image("registry/exp:tag")

    from_env.assert_called_once_with(timeout=DOCKER_PUSH_TIMEOUT, use_ssh_client=True)
    assert fake_client.images.push.call_count == 2
    assert result == f"registry/exp@{fake_digest}"


def test_push_image_retries_urllib3_read_timeout_and_succeeds():
    import urllib3.exceptions

    from dallinger.command_line.docker import DOCKER_PUSH_TIMEOUT, push_image

    fake_digest = "sha256:abc123"
    call_count = 0

    def fake_push(image, stream=False, decode=False):
        nonlocal call_count
        call_count += 1
        if call_count == 1:

            def failing_stream():
                yield {"status": "Pushing"}
                raise urllib3.exceptions.ReadTimeoutError(None, None, "timed out")

            return failing_stream()
        return iter([{"status": "Pushing"}, {"aux": {"Digest": fake_digest}}])

    fake_image = mock.Mock()
    fake_image.attrs = {"RepoDigests": [f"registry/exp@{fake_digest}"]}
    fake_client = mock.Mock()
    fake_client.images.push.side_effect = fake_push
    fake_client.images.get.return_value = fake_image

    with (
        mock.patch("docker.client.from_env", return_value=fake_client) as from_env,
        mock.patch("time.sleep"),
    ):
        result = push_image("registry/exp:tag")

    from_env.assert_called_once_with(timeout=DOCKER_PUSH_TIMEOUT, use_ssh_client=True)
    assert fake_client.images.push.call_count == 2
    assert result == f"registry/exp@{fake_digest}"


def test_push_image_does_not_retry_click_abort():
    import click

    from dallinger.command_line.docker import push_image

    def fake_push(image, stream=False, decode=False):
        return iter([{"error": "denied: permission denied"}])

    fake_client = mock.Mock()
    fake_client.images.push.side_effect = fake_push

    with (
        mock.patch("docker.client.from_env", return_value=fake_client),
        mock.patch("time.sleep"),
    ):
        with pytest.raises(click.exceptions.Abort):
            push_image("registry/exp:tag")

    assert fake_client.images.push.call_count == 1


def test_docker_ssh_server_teardown_runs_local_cleanup_after_ssh_timeout():
    import subprocess
    from pathlib import Path

    from dallinger.pytest_docker_ssh import _teardown_docker_ssh_server

    container_name = "dallinger-ssh-target-pytest-test"
    docker_data_volume = f"{container_name}-docker-data"
    tmp_root = Path("/tmp/fake-teardown-test")

    server = mock.Mock()
    server.reset_remote_state.side_effect = subprocess.TimeoutExpired(["ssh"], 120)

    run_command_calls = []

    def fake_run_command(cmd, **kwargs):
        run_command_calls.append(list(cmd))
        result = mock.Mock()
        result.returncode = 0
        return result

    with (
        mock.patch(
            "dallinger.pytest_docker_ssh._run_command", side_effect=fake_run_command
        ),
        mock.patch("shutil.rmtree"),
    ):
        _teardown_docker_ssh_server(
            server, container_name, docker_data_volume, tmp_root
        )

    assert ["docker", "rm", "-f", container_name] in run_command_calls
    assert ["docker", "volume", "rm", "-f", docker_data_volume] in run_command_calls
    server.remove_server.assert_called_once()


FRONTDOOR_CADDYFILE = (
    Path(__file__).parents[1] / "dallinger/docker/ssh_templates/Caddyfile.frontdoor"
)
ECHO_SERVER = """
import json, os
from http.server import BaseHTTPRequestHandler, HTTPServer

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"from": os.environ["ROLE"], **dict(self.headers)}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass

HTTPServer(("0.0.0.0", int(os.environ["PORT"])), H).serve_forever()
"""


def _docker(*args):
    """Run docker; skip if Docker is unavailable, fail if the command fails."""
    import shutil
    import subprocess

    if (
        not shutil.which("docker")
        or subprocess.run(["docker", "info"], capture_output=True).returncode
    ):
        pytest.skip("Docker is not available")
    result = subprocess.run(["docker", *args], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr or result.stdout
    return result.stdout.strip()


def test_frontdoor_caddyfile_validates_on_caddy_2_10():
    import shutil

    if not shutil.which("docker"):
        pytest.skip("docker is required to validate the front-door Caddyfile")
    caddyfile = FRONTDOOR_CADDYFILE.resolve()
    _docker(
        *("run", "--rm", "-v", f"{caddyfile}:/etc/caddy/Caddyfile:ro", "caddy:2.10.2"),
        *("caddy", "validate", "--config", "/etc/caddy/Caddyfile"),
    )


@pytest.fixture
def frontdoor(tmp_path):
    """Run the front-door Caddyfile in front of echo servers for web and controller.

    Yields a ``get(path, **headers)`` helper and the state directory.
    """
    import json
    import os
    import shutil
    import subprocess
    import urllib.error
    import urllib.request

    from dallinger.command_line.docker_ssh import CONTROLLER_IMAGE

    if not shutil.which("docker"):
        pytest.skip("docker is required to exercise the front door")
    (tmp_path / "echo.py").write_text(ECHO_SERVER)
    state = tmp_path / "state"
    state.mkdir()
    net = f"dlgr-fd-test-{os.getpid()}"
    names = []
    try:
        _docker("network", "create", net)
        for alias, port, role in (
            ("experiment-backend", "5000", "web"),
            ("controller", "8080", "controller"),
        ):
            names.append(f"{net}-{role}")
            _docker(
                *("run", "-d", "--rm", "--name", names[-1], "--network", net),
                *("--network-alias", alias, "-e", f"PORT={port}", "-e", f"ROLE={role}"),
                *("-v", f"{tmp_path / 'echo.py'}:/echo.py:ro", CONTROLLER_IMAGE),
                *("python", "/echo.py"),
            )
        names.append(f"{net}-frontdoor")
        _docker(
            *("run", "-d", "--rm", "--name", names[-1], "--network", net),
            *("-p", "127.0.0.1::5000", "-v", f"{state}:/state"),
            # Run as the caller, as Compose does, so the access log is readable.
            *("--user", f"{os.getuid()}:{os.getgid()}", "-e", "HOME=/state"),
            *("-e", "XDG_CONFIG_HOME=/state/caddy-config"),
            *("-e", "XDG_DATA_HOME=/state/caddy-data"),
            *("-v", f"{FRONTDOOR_CADDYFILE.resolve()}:/etc/caddy/Caddyfile:ro"),
            "caddy:2.10.2",
        )
        listen = _docker("port", names[-1], "5000").splitlines()[0]

        def get(path, **headers):
            request = urllib.request.Request(f"http://{listen}{path}", headers=headers)
            for _ in range(40):
                try:
                    with urllib.request.urlopen(request, timeout=2) as response:
                        return response.status, json.loads(response.read())
                except urllib.error.HTTPError as exc:
                    return exc.code, json.loads(exc.read())
                except Exception:
                    time.sleep(0.25)
            raise AssertionError(f"front door never answered {path}")

        _eventually(get, "/ad", lambda result: result[0] == 200)
        # The controller may start after web; wait until parked routing works.
        (state / "hibernating").write_text("")
        _eventually(get, "/ad", lambda result: result[1].get("from") == "controller")
        (state / "hibernating").unlink()
        yield get, state, names
    finally:
        for name in names:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        subprocess.run(["docker", "network", "rm", net], capture_output=True)


def _eventually(get, path, predicate):
    """Return ``get(path)`` once ``predicate`` holds; bind mounts can lag file changes."""
    for _ in range(40):
        result = get(path)
        if predicate(result):
            break
        time.sleep(0.25)
    return result


def test_frontdoor_routes_awake_parked_and_missing_backend(frontdoor):
    get, state, names = frontdoor
    # cloudflared appends the real address to whatever the participant sent.
    status, body = get(
        "/ad",
        **{"X-Forwarded-Proto": "https", "X-Forwarded-For": "6.6.6.6, 203.0.113.9"},
    )
    assert (status, body["from"]) == (200, "web")
    assert body["X-Forwarded-Proto"] == "https"
    assert body["X-Forwarded-For"] == "203.0.113.9"
    log = state / "access.log"
    time.sleep(0.5)  # Caddy may write the access line just after responding.
    logged = log.read_text()
    assert '"/ad"' in logged
    get("/health")
    time.sleep(0.5)
    assert log.read_text() == logged

    (state / "hibernating").write_text("")
    status, body = _eventually(
        get, "/health", lambda result: result[1].get("from") == "controller"
    )
    assert body["from"] == "controller"
    assert get("/ad")[1]["from"] == "controller"

    (state / "hibernating").unlink()
    _docker("rm", "-f", names[0])
    unavailable = (503, {"status": "unavailable"})
    assert _eventually(get, "/ad", lambda result: result == unavailable) == unavailable


def test_controller_project_matches_compose_normalization():
    from dallinger.command_line.docker_ssh import get_docker_compose_yml

    services = yaml.safe_load(
        get_docker_compose_yml({}, "My.App", "img", ingress="cloudflare")
    )["services"]
    assert services["controller"]["environment"]["COMPOSE_PROJECT_NAME"] == "myapp"
