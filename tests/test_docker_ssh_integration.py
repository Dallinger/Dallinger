import json
import shutil
import time

import pytest

_SECRET_KEY_PARTS = ("token", "password", "secret", "credential")


@pytest.mark.docker
@pytest.mark.slow
@pytest.mark.docker_ssh_smoke
def test_docker_ssh_fixture_sandbox_deploy_destroy(fresh_docker_ssh_server):
    app_id = fresh_docker_ssh_server.deploy_sandbox()

    assert app_id.startswith("dlgr-")

    fresh_docker_ssh_server.destroy_app(app_id)


@pytest.mark.docker
@pytest.mark.slow
@pytest.mark.docker_ssh_smoke
def test_docker_ssh_apps_lists_deployed_app(fresh_docker_ssh_server):
    app_id = fresh_docker_ssh_server.deploy_sandbox()

    deadline = time.time() + 30
    while time.time() < deadline:
        if app_id in fresh_docker_ssh_server.list_apps():
            break
        time.sleep(1)
    assert app_id in fresh_docker_ssh_server.list_apps()

    fresh_docker_ssh_server.destroy_app(app_id)


@pytest.mark.docker
@pytest.mark.slow
@pytest.mark.docker_ssh_smoke
def test_docker_ssh_servers_list_includes_fixture_server(docker_ssh_server):
    result = docker_ssh_server.run_servers_list_command(check=False)
    output = f"{result.stdout}\n{result.stderr}"
    assert result.returncode == 0
    assert f"host: {docker_ssh_server.server}" in output
    assert f"user: {docker_ssh_server.ssh_user}" in output


@pytest.mark.docker
@pytest.mark.slow
@pytest.mark.docker_ssh_smoke
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
@pytest.mark.docker_ssh_smoke
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
    before_template = original_template.replace(
        "<h1>Instructions</h1>",
        f"<h1>Instructions {marker_before}</h1>",
        1,
    )
    assert before_template != original_template
    template_path.write_text(before_template)
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
        app_id = fresh_docker_ssh_server.deploy_sandbox()

        response_before = fresh_docker_ssh_server.fetch_experiment_page(
            app_id, "/instructions/instruct-ready", query=query
        )
        assert response_before.status_code == 200
        assert marker_before in response_before.text
        assert marker_after not in response_before.text

        after_template = original_template.replace(
            "<h1>Instructions</h1>",
            f"<h1>Instructions {marker_after}</h1>",
            1,
        )
        assert after_template != original_template
        template_path.write_text(after_template)
        update_result = fresh_docker_ssh_server.update_sandbox(app_id)
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


def _manifest_keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _manifest_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _manifest_keys(item)


def _assert_web_stopped(server, app_id):
    result = server.run_ssh(
        f"docker ps -q --filter status=running --filter name=^{app_id}[-_]web[-_]",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert not result.stdout.strip(), result.stdout


def _parked_health(server, app_id):
    deadline = time.time() + 30
    response = None
    while time.time() < deadline:
        response = server.fetch_experiment_page(app_id, "/health")
        if response.status_code == 200:
            payload = response.json()
            if payload.get("status") == "hibernating":
                return payload
        time.sleep(1)
    status = getattr(response, "status_code", None)
    body = getattr(response, "text", "")
    raise AssertionError(f"/health did not report hibernating ({status}): {body}")


@pytest.mark.docker
@pytest.mark.slow
@pytest.mark.docker_ssh_smoke
def test_docker_ssh_hibernate_keeps_health_without_waking_web(fresh_docker_ssh_server):
    """Classic deploy writes a manifest, and /health does not wake a parked app."""
    server = fresh_docker_ssh_server
    app_id = None
    try:
        app_id = server.deploy_sandbox()
        manifest_raw = server.run_ssh(f"cat ~/dallinger/{app_id}/deployment.json")
        manifest = json.loads(manifest_raw.stdout)
        assert manifest["ingress"] == "classic"
        assert manifest["public_origin"].startswith("https://")
        assert app_id in manifest["public_origin"]
        lowered_keys = [key.lower() for key in _manifest_keys(manifest)]
        assert not any(
            part in key for key in lowered_keys for part in _SECRET_KEY_PARTS
        )

        server.run_dallinger(
            ["docker-ssh", "hibernate", "--server", server.server, "--app", app_id],
            timeout=180,
        )
        first = _parked_health(server, app_id)
        second = server.fetch_experiment_page(app_id, "/health")
        assert second.status_code == 200
        assert second.json().get("status") == "hibernating"
        assert first["status"] == "hibernating"
        _assert_web_stopped(server, app_id)

        server.run_dallinger(
            ["docker-ssh", "awaken", "--server", server.server, "--app", app_id],
            timeout=300,
        )
        query = {
            "recruiter": "hotair",
            "assignmentId": "A1",
            "hitId": "H1",
            "workerId": "W1",
            "mode": "debug",
        }
        deadline = time.time() + 60
        instructions = None
        while time.time() < deadline:
            instructions = server.fetch_experiment_page(
                app_id, "/instructions/instruct-ready", query=query
            )
            if instructions.status_code == 200 and "Instructions" in instructions.text:
                break
            time.sleep(2)
        assert instructions is not None
        assert instructions.status_code == 200
        assert "Instructions" in instructions.text
    finally:
        if app_id is not None:
            server.destroy_app(app_id)
