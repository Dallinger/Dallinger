import importlib
import json
from unittest import mock

import click
import docker
import pytest

docker_ssh_module = importlib.import_module("dallinger.command_line.docker_ssh")


def _client(registry_data=None, registry_error=None, push_result=None):
    client = mock.Mock()
    if registry_error is not None:
        client.images.get_registry_data.side_effect = registry_error
    else:
        client.images.get_registry_data.return_value = registry_data
    client.images.push.return_value = push_result
    return client


def _push_output(payload):
    return "\r\n".join([json.dumps({"status": "Pushing"}), json.dumps(payload), ""])


class TestImageUsableFromRegistry:
    def test_image_on_registry_is_usable(self, capsys):
        client = _client(registry_data=mock.Mock())

        assert docker_ssh_module._image_usable_from_registry(client, "img:1") is True
        assert "found on remote registry" in capsys.readouterr().out
        client.images.push.assert_not_called()

    def test_registry_error_falls_back_to_building(self, capsys):
        client = _client(registry_error=docker.errors.APIError("registry down"))

        assert docker_ssh_module._image_usable_from_registry(client, "img:1") is False
        assert "Error checking remote image" in capsys.readouterr().out

    def test_missing_image_is_pushed(self, capsys):
        client = _client(
            registry_error=docker.errors.ImageNotFound("nope"),
            push_result=_push_output({"status": "Pushed"}),
        )

        assert docker_ssh_module._image_usable_from_registry(client, "img:1") is True
        assert "pushed to remote registry" in capsys.readouterr().out

    def test_unpushable_image_aborts(self, capsys):
        client = _client(
            registry_error=docker.errors.ImageNotFound("nope"),
            push_result=_push_output({"error": "no such image"}),
        )

        with pytest.raises(click.Abort):
            docker_ssh_module._image_usable_from_registry(client, "img:1")

        assert "Could not find image img:1" in capsys.readouterr().out


def test_deploy_failure_is_not_reported_as_a_registry_error(monkeypatch, capsys):
    """A command that aborts must not be retried as though the registry failed."""
    deployed_with = []

    @docker_ssh_module.build_and_push_image
    def deploy(**kwargs):
        deployed_with.append(kwargs["image_name"])
        raise click.Abort()

    monkeypatch.setattr(docker_ssh_module, "get_experiment_files", lambda path: [])
    monkeypatch.setattr(
        docker_ssh_module,
        "get_config",
        lambda load=False: {"docker_image_name": "img:1"},
    )
    monkeypatch.setattr(
        docker, "from_env", lambda **kwargs: _client(registry_data=mock.Mock())
    )

    with pytest.raises(click.Abort):
        deploy(app_name="app", server="server", local_build=True)

    assert deployed_with == ["img:1"]
    assert "Error checking remote image" not in capsys.readouterr().out
