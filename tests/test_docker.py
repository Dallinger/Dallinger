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
    assert services["web"]["networks"]["app"] is None
    assert services["worker_1"]["networks"] == ["app"]
    assert services["pgbouncer"]["networks"]["app"]["aliases"] == [
        "dlgr-8c43a887_pgbouncer"
    ]
    assert result["networks"]["app"]["name"] == "dlgr-8c43a887_app"


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


def get_yaml(config):
    from dallinger.command_line.docker_ssh import get_docker_compose_yml

    yaml_contents = get_docker_compose_yml(
        config, "dlgr-8c43a887", "ghcr.io/dallinger/dallinger/bartlett1932", "foobar"
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


def test_get_connected_ssh_client_creates_missing_known_hosts(tmp_path, monkeypatch):
    import importlib

    docker_ssh = importlib.import_module("dallinger.command_line.docker_ssh")

    key_path = tmp_path / "server.pem"
    key_path.write_text("dummy")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(docker_ssh, "get_server_pem_path", lambda: key_path)

    class DummySpinner:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def ok(self, *_):
            pass

        def fail(self, *_):
            pass

        def stop(self):
            pass

        def start(self):
            pass

    monkeypatch.setattr(docker_ssh, "yaspin", lambda *args, **kwargs: DummySpinner())

    class DummyClient:
        def load_host_keys(self, filename):
            if not Path(filename).exists():
                raise IOError("missing")

        def set_missing_host_key_policy(self, policy):
            pass

        def load_system_host_keys(self):
            pass

        def connect(self, **kwargs):
            pass

        def save_host_keys(self, filename):
            assert Path(filename).exists()

    monkeypatch.setattr(docker_ssh.paramiko, "SSHClient", DummyClient)

    client = docker_ssh.get_connected_ssh_client("localhost:2222", user="root")
    assert isinstance(client, DummyClient)
    assert (tmp_path / ".ssh" / "known_hosts").exists()


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
    assert "docker container prune -f" in guidance
    assert "do not auto-prune volumes" in guidance
    assert "docker system prune -af --volumes" not in guidance


def test_docker_ssh_fixture_precondition_uses_pytest_fail():
    from dallinger.pytest_docker_ssh import _skip_or_fail

    with pytest.raises(pytest.fail.Exception):
        _skip_or_fail("missing dependency")


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
    from dallinger.docker.tools import get_required_dallinger_version

    requirements = tmp_path / "requirements.txt"
    requirements.write_text("dallinger==12.2.0a1\n")

    assert get_required_dallinger_version(str(tmp_path)) == ""


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

    from_env.assert_called_once_with(timeout=DOCKER_PUSH_TIMEOUT)
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
