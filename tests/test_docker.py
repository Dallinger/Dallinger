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
