from pathlib import Path

import click
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


def get_yaml(config, uid=None, gid=None, home_dir=None):
    from dallinger.command_line.docker_ssh import get_docker_compose_yml

    yaml_contents = get_docker_compose_yml(
        config,
        "dlgr-8c43a887",
        "ghcr.io/dallinger/dallinger/bartlett1932",
        "foobar",
        uid=uid,
        gid=gid,
        home_dir=home_dir,
    )
    return yaml.safe_load(yaml_contents)


def test_num_dynos():
    """Make sure the correct number of worker services is created"""
    n = 3
    result = get_yaml({"num_dynos_worker": n})
    for i in range(n):
        assert f"worker_{i + 1}" in result["services"]


def test_get_docker_compose_yml_explicit_user_and_home():
    """Remote deployments should render deterministic uid/gid and home path."""
    result = get_yaml({}, uid="1001", gid="1002", home_dir="/home/ubuntu")
    assert result["services"]["web"]["user"] == "1001:1002"
    assert result["services"]["worker_1"]["user"] == "1001:1002"
    assert (
        result["services"]["web"]["volumes"][0]
        == "/home/ubuntu/dallinger-data/dlgr-8c43a887:/var/lib/dallinger"
    )


def test_get_docker_compose_yml_default_user_placeholders():
    """When no remote ids are provided, keep compose placeholders."""
    result = get_yaml({})
    assert result["services"]["web"]["user"] == "${UID}:${GID}"


def test_parse_remote_identity_output_with_step_markers():
    from dallinger.command_line.docker_ssh import parse_remote_identity_output

    output = "\n".join(
        (
            "STEP:identity:start",
            "uid=1000",
            "gid=1001",
            "home=/home/ubuntu",
            "STEP:identity:resolved",
        )
    )
    assert parse_remote_identity_output(output) == ("1000", "1001", "/home/ubuntu")


def test_parse_remote_identity_output_raises_for_missing_home():
    from dallinger.command_line.docker_ssh import parse_remote_identity_output

    output = "\n".join(("STEP:identity:start", "uid=1000", "gid=1001"))
    with pytest.raises(click.ClickException):
        parse_remote_identity_output(output)
