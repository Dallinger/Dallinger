import pytest


@pytest.mark.docker
@pytest.mark.slow
def test_docker_ssh_fixture_sandbox_deploy_destroy(fresh_docker_ssh_server):
    app_id = fresh_docker_ssh_server.deploy_sandbox()

    assert app_id.startswith("dlgr-")
    deployed = fresh_docker_ssh_server.run_ssh(
        f"test -f ~/dallinger/caddy.d/{app_id}", check=False
    )
    assert deployed.returncode == 0

    fresh_docker_ssh_server.destroy_app(app_id)

    destroyed = fresh_docker_ssh_server.run_ssh(
        f"test -f ~/dallinger/caddy.d/{app_id}", check=False
    )
    assert destroyed.returncode != 0
