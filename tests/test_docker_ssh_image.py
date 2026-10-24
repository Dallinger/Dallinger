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


def test_registry_image_is_deployed_without_building(monkeypatch):
    setup = mock.Mock()
    monkeypatch.setattr(docker_ssh_module, "setup_experiment", setup)
    monkeypatch.setattr(
        docker, "from_env", lambda **kwargs: _client(registry_data=mock.Mock())
    )

    image_name = docker_ssh_module._build_and_push_image(
        {"docker_image_name": "img:1"},
        [],
        "app",
        "server",
        local_build=True,
        push_build=False,
    )

    assert image_name == "img:1"
    setup.assert_not_called()


class TestImageBaseName:
    @pytest.mark.parametrize(
        "app, expected",
        [
            ("bartlett1932", "bartlett1932"),
            ("My_Study", "my_study"),
            ("a..b._c---d___e.", "a-b-c---d-e"),
        ],
    )
    def test_server_only_image_is_named_after_the_app(self, app, expected):
        assert docker_ssh_module._image_base_name({}, app, push=False) == expected

    def test_configured_name_wins(self):
        config = {"docker_image_base_name": "ghcr.io/org/exp"}

        assert docker_ssh_module._image_base_name(config, "app", push=True) == (
            "ghcr.io/org/exp"
        )

    @pytest.mark.parametrize(
        "app, push",
        [("app", True), ("---", False), ("日本語", False), ("a" * 256, False)],
    )
    def test_image_needs_the_setting(self, app, push):
        with pytest.raises(click.ClickException, match="docker_image_base_name"):
            docker_ssh_module._image_base_name({}, app, push=push)
