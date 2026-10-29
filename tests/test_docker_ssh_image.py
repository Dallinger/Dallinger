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


def test_image_found_by_the_caller_is_reused_without_a_docker_client(monkeypatch):
    from_env = mock.Mock()
    monkeypatch.setattr(docker, "from_env", from_env)

    with docker_ssh_module._built_image(
        {"docker_image_name": "img:1"},
        [],
        "app",
        "lab",
        False,
        False,
        image_usable=True,
    ) as image_name:
        assert image_name == "img:1"
    from_env.assert_not_called()


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


@pytest.mark.parametrize("remove", ["dlgr-1", None], ids=["new-app", "update"])
def test_failed_new_deploy_removes_the_image_it_built(monkeypatch, capsys, remove):
    client = _client()
    config = mock.Mock()
    config.get.side_effect = lambda key, default=None: {
        "id": "a" * 8,
        "docker_image_base_name": "ghcr.io/org/exp",
    }.get(key)
    config.as_dict.return_value = {}
    monkeypatch.setattr(docker, "from_env", lambda **kwargs: client)
    monkeypatch.setattr(
        docker_ssh_module, "setup_experiment", lambda *a, **k: ("id", "/tmp/x")
    )
    with (
        mock.patch("dallinger.docker.tools.build_image", return_value="built:1"),
        mock.patch("dallinger.command_line.docker.push_image", return_value="pushed"),
        pytest.raises(click.Abort),
        docker_ssh_module._built_image(
            config, [], None, "lab", True, False, remove_for_app=remove
        ) as image_name,
    ):
        assert image_name == "pushed"
        raise click.Abort()

    if remove:
        client.images.remove.assert_called_once_with("built:1")
        assert "Removed the image built:1 built for this deploy." in (
            capsys.readouterr().out
        )
    else:
        client.images.remove.assert_not_called()


@pytest.mark.parametrize(
    "local_build, explanation",
    [
        (False, "container 5e8d is using its referenced image f3aa"),
        (True, "container 5e8d is using its referenced image f3aa"),
        (False, "image has dependent child images"),
    ],
    ids=["remote", "local", "not-a-container"],
)
def test_aborted_build_cleanup_explains_an_image_a_container_uses(
    monkeypatch, capsys, local_build, explanation
):
    client = _client()
    client.images.remove.side_effect = docker.errors.APIError(
        "conflict", response=mock.Mock(status_code=409), explanation=explanation
    )
    monkeypatch.setattr(docker_ssh_module, "_executor_for_server", mock.Mock())
    monkeypatch.setattr(
        docker_ssh_module, "image_pinned_by_other_apps", lambda *a, **k: False
    )

    docker_ssh_module._remove_aborted_build(
        client, "built:1", "lab", local_build, "app"
    )

    output = capsys.readouterr().out
    in_use = "container" in explanation
    assert ("because a container still uses it" in output) is in_use
    assert explanation in output or in_use
    destroy_hint = "`dallinger docker-ssh destroy --server lab --app app`"
    assert (destroy_hint in output) is (in_use and not local_build)


def test_aborted_build_cleanup_keeps_an_image_another_app_uses(monkeypatch, capsys):
    client = _client()
    monkeypatch.setattr(docker_ssh_module, "_executor_for_server", mock.Mock())
    monkeypatch.setattr(
        docker_ssh_module, "image_pinned_by_other_apps", lambda *a, **k: True
    )

    docker_ssh_module._remove_aborted_build(client, "built:1", "lab", False, "app")

    client.images.remove.assert_not_called()
    assert "because another app on the server uses it" in capsys.readouterr().out
