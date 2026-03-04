import shutil
import time

import pytest


@pytest.mark.docker
@pytest.mark.slow
def test_docker_ssh_fixture_sandbox_deploy_destroy(fresh_docker_ssh_server):
    app_id = fresh_docker_ssh_server.deploy_sandbox()

    assert app_id.startswith("dlgr-")

    fresh_docker_ssh_server.destroy_app(app_id)


@pytest.mark.docker
@pytest.mark.slow
def test_docker_ssh_apps_lists_deployed_app(fresh_docker_ssh_server):
    app_id = fresh_docker_ssh_server.deploy_sandbox()

    apps_result = fresh_docker_ssh_server.run_apps_command(check=False)
    assert apps_result.returncode == 0

    deadline = time.time() + 30
    while time.time() < deadline:
        if app_id in fresh_docker_ssh_server.list_apps():
            break
        time.sleep(1)
    assert app_id in fresh_docker_ssh_server.list_apps()

    fresh_docker_ssh_server.destroy_app(app_id)


@pytest.mark.docker
@pytest.mark.slow
def test_docker_ssh_servers_list_includes_fixture_server(docker_ssh_server):
    result = docker_ssh_server.run_servers_list_command(check=False)
    output = f"{result.stdout}\n{result.stderr}"
    assert result.returncode == 0
    assert f"host: {docker_ssh_server.server}" in output
    assert f"user: {docker_ssh_server.ssh_user}" in output


@pytest.mark.docker
@pytest.mark.slow
def test_docker_ssh_destroy_missing_app_reports_error(fresh_docker_ssh_server):
    missing_app_id = "dlgr-deadbeef"
    result = fresh_docker_ssh_server.run_dallinger(
        [
            "docker-ssh",
            "destroy",
            "--server",
            fresh_docker_ssh_server.server,
            "--app",
            missing_app_id,
        ],
        check=False,
    )
    output = f"{result.stdout}\n{result.stderr}"
    assert result.returncode != 0
    assert f"App {missing_app_id} is not deployed" in output


@pytest.mark.docker
@pytest.mark.slow
def test_docker_ssh_update_refreshes_served_template(fresh_docker_ssh_server, tmp_path):
    original_experiment_dir = fresh_docker_ssh_server.experiment_dir
    copied_experiment_dir = tmp_path / "bartlett1932-copy"
    shutil.copytree(original_experiment_dir, copied_experiment_dir)
    template_path = (
        copied_experiment_dir / "templates" / "instructions" / "instruct-ready.html"
    )
    original_template = template_path.read_text()
    marker_before = "UPDATE-MARKER-BEFORE"
    marker_after = "UPDATE-MARKER-AFTER"
    template_path.write_text(f"{original_template}\n<!-- {marker_before} -->\n")
    fresh_docker_ssh_server.experiment_dir = copied_experiment_dir

    query = {
        "recruiter": "hotair",
        "assignmentId": "A1",
        "hitId": "H1",
        "workerId": "W1",
        "mode": "debug",
    }
    app_id = None
    try:
        app_id = fresh_docker_ssh_server.deploy_sandbox(docker_image_name=None)

        response_before = fresh_docker_ssh_server.fetch_experiment_page(
            app_id, "/instructions/instruct-ready", query=query
        )
        assert response_before.status_code == 200
        assert marker_before in response_before.text
        assert marker_after not in response_before.text

        template_path.write_text(f"{original_template}\n<!-- {marker_after} -->\n")
        update_result = fresh_docker_ssh_server.update_sandbox(
            app_id, docker_image_name=None
        )
        update_output = f"{update_result.stdout}\n{update_result.stderr}"
        assert (
            "Skipping experiment launch logic because we are in update mode."
            in update_output
        )

        deadline = time.time() + 90
        response_after = None
        while time.time() < deadline:
            response_after = fresh_docker_ssh_server.fetch_experiment_page(
                app_id, "/instructions/instruct-ready", query=query
            )
            if (
                response_after.status_code == 200
                and marker_after in response_after.text
                and marker_before not in response_after.text
            ):
                break
            time.sleep(2)

        assert response_after is not None
        assert response_after.status_code == 200
        assert marker_after in response_after.text
        assert marker_before not in response_after.text
    finally:
        if app_id is not None:
            fresh_docker_ssh_server.destroy_app(app_id)
        fresh_docker_ssh_server.experiment_dir = original_experiment_dir
