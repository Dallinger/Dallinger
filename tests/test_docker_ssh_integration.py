import pytest


@pytest.mark.docker
@pytest.mark.slow
def test_docker_ssh_fixture_sandbox_deploy_destroy(fresh_docker_ssh_server):
    app_id = fresh_docker_ssh_server.deploy_sandbox()

    assert app_id.startswith("dlgr-")

    fresh_docker_ssh_server.destroy_app(app_id)


@pytest.mark.docker
@pytest.mark.slow
def test_docker_ssh_apps_lists_caddy_entries(fresh_docker_ssh_server):
    app_id = "dlgr-deadbeef"
    fresh_docker_ssh_server.run_ssh(
        "mkdir -p ~/dallinger/caddy.d && "
        f"printf 'example config' > ~/dallinger/caddy.d/{app_id}"
    )

    apps_result = fresh_docker_ssh_server.run_apps_command(check=False)
    assert apps_result.returncode == 0
    assert app_id in fresh_docker_ssh_server.list_apps()
