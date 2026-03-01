import pytest


@pytest.mark.docker
@pytest.mark.slow
def test_docker_ssh_fixture_sandbox_deploy_destroy(fresh_docker_ssh_server):
    app_id = fresh_docker_ssh_server.deploy_sandbox()

    assert app_id.startswith("dlgr-")
    assert app_id in fresh_docker_ssh_server.list_apps()

    fresh_docker_ssh_server.destroy_app(app_id)

    assert app_id not in fresh_docker_ssh_server.list_apps()
