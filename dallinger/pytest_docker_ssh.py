import os
import re
import shlex
import shutil
import socket
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest

EXPERIMENT_IMAGE = "ghcr.io/dallinger/dallinger/bartlett1932@sha256:0586d93bf49fd555031ffe7c40d1ace798ee3a2773e32d467593ce3de40f35b5"
SSH_USER = "root"
SSH_HOST = "localhost"
SSH_WAIT_SECONDS = 30
DOCKER_WAIT_SECONDS = 60


def _run_command(command, *, check=True, env=None, cwd=None, timeout=300):
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
        timeout=timeout,
    )
    if check and completed.returncode != 0:
        command_text = " ".join(shlex.quote(part) for part in command)
        raise RuntimeError(
            f"Command failed ({completed.returncode}): {command_text}\n"
            f"STDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )
    return completed


def _next_open_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@dataclass
class DockerSSHServer:
    container_name: str
    ssh_host: str
    ssh_port: int
    ssh_user: str
    ssh_key_path: Path
    home_dir: Path
    repo_root: Path
    experiment_dir: Path

    @property
    def server(self):
        return f"{self.ssh_host}:{self.ssh_port}"

    def _dallinger_env(self):
        env = os.environ.copy()
        env["HOME"] = str(self.home_dir)
        env["SKIP_PYTHON_VERSION_CHECK"] = "true"
        existing_pythonpath = env.get("PYTHONPATH")
        repo_root = str(self.repo_root)
        if existing_pythonpath:
            env["PYTHONPATH"] = f"{repo_root}:{existing_pythonpath}"
        else:
            env["PYTHONPATH"] = repo_root
        return env

    def run_dallinger(self, args, *, check=True, timeout=300):
        return _run_command(
            ["python3", "-m", "dallinger.command_line", *args],
            check=check,
            env=self._dallinger_env(),
            cwd=self.experiment_dir,
            timeout=timeout,
        )

    def run_ssh(self, command, *, check=True, timeout=120):
        ssh_command = [
            "ssh",
            "-p",
            str(self.ssh_port),
            "-i",
            str(self.ssh_key_path),
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            "LogLevel=ERROR",
            f"{self.ssh_user}@{self.ssh_host}",
            command,
        ]
        return _run_command(ssh_command, check=check, timeout=timeout)

    def ensure_remote_docker_ready(self):
        if self.run_ssh("docker info >/dev/null 2>&1", check=False).returncode == 0:
            return

        self.run_ssh(
            "nohup dockerd --storage-driver=vfs >/var/log/dockerd.log 2>&1 </dev/null &"
        )
        for _ in range(DOCKER_WAIT_SECONDS):
            if self.run_ssh("docker info >/dev/null 2>&1", check=False).returncode == 0:
                return
            time.sleep(1)

        dockerd_log = self.run_ssh(
            "tail -n 200 /var/log/dockerd.log || true", check=False
        )
        raise RuntimeError(
            "Remote Docker daemon failed to start.\n"
            f"STDOUT:\n{dockerd_log.stdout}\nSTDERR:\n{dockerd_log.stderr}"
        )

    def reset_remote_state(self):
        cleanup_command = (
            "docker compose -f ~/dallinger/docker-compose.yml down -v >/dev/null 2>&1 || true; "
            "docker ps -aq --filter 'name=^dlgr-' | xargs -r docker rm -f >/dev/null 2>&1 || true; "
            "docker network ls --filter 'name=^dallinger$' -q | xargs -r docker network rm >/dev/null 2>&1 || true; "
            "docker volume ls --filter 'name=^dlgr-' -q | xargs -r docker volume rm >/dev/null 2>&1 || true; "
            "rm -rf ~/dallinger >/dev/null 2>&1 || true"
        )
        self.run_ssh(cleanup_command, check=False)

    def add_server(self):
        self.run_dallinger(
            [
                "docker-ssh",
                "servers",
                "add",
                "--host",
                self.server,
                "--user",
                self.ssh_user,
            ]
        )
        self.ensure_remote_docker_ready()

    def remove_server(self):
        self.run_dallinger(
            ["docker-ssh", "servers", "remove", "--host", self.server], check=False
        )

    def list_apps(self):
        return self.run_dallinger(
            ["docker-ssh", "apps", "--server", self.server], check=False
        ).stdout

    def deploy_sandbox(self):
        result = self.run_dallinger(
            [
                "docker-ssh",
                "sandbox",
                "--server",
                self.server,
                "--local_build",
                "--verbose",
                "-c",
                "dashboard_password",
                "pytest-dashboard-password",
                "-c",
                "recruiter",
                "hotair",
                "-c",
                "auto_recruit",
                "false",
                "-c",
                "docker_image_name",
                EXPERIMENT_IMAGE,
            ],
            timeout=1200,
        )
        output = f"{result.stdout}\n{result.stderr}"
        match = re.search(r"Experiment (dlgr-[0-9a-f]{8}) started\.", output)
        if match:
            return match.group(1)

        for line in self.list_apps().splitlines():
            if line.startswith("dlgr-"):
                return line.strip()

        raise RuntimeError(
            "Could not determine deployed app id from deploy output or app list.\n"
            f"Deploy output:\n{output}"
        )

    def destroy_app(self, app_id):
        self.run_dallinger(
            ["docker-ssh", "destroy", "--server", self.server, "--app", app_id]
        )


@pytest.fixture(scope="session")
def docker_ssh_server(tmp_path_factory):
    if not os.environ.get("RUN_DOCKER"):
        pytest.skip("need RUN_DOCKER environment variable")
    if shutil.which("docker") is None:
        pytest.skip("docker executable not available")
    if shutil.which("python3") is None:
        pytest.skip("python3 executable not available")
    if shutil.which("ssh") is None:
        pytest.skip("ssh executable not available")
    if shutil.which("ssh-keygen") is None:
        pytest.skip("ssh-keygen executable not available")

    docker_info = _run_command(["docker", "info"], check=False)
    if docker_info.returncode != 0:
        pytest.skip("docker daemon not available")

    repo_root = Path(__file__).resolve().parents[1]
    experiment_dir = repo_root / "demos" / "dlgr" / "demos" / "bartlett1932"
    if not experiment_dir.exists():
        pytest.skip(f"Experiment directory not found: {experiment_dir}")

    tmp_root = tmp_path_factory.mktemp("docker-ssh-server")
    ssh_key_path = tmp_root / "id_ed25519"
    home_dir = tmp_root / "home"
    home_ssh_dir = home_dir / ".ssh"
    container_name = f"dallinger-ssh-target-pytest-{uuid.uuid4().hex[:8]}"
    ssh_port = _next_open_port()

    _run_command(["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(ssh_key_path)])

    run_target_command = [
        "docker",
        "run",
        "-d",
        "--name",
        container_name,
        "--hostname",
        container_name,
        "--privileged",
        "--cgroupns=host",
        "-p",
        f"{ssh_port}:22",
        "-p",
        "80:80",
        "-p",
        "443:443",
        "ubuntu:24.04",
        "sleep",
        "infinity",
    ]
    run_target = _run_command(run_target_command, check=False)
    if run_target.returncode != 0:
        if (
            "address already in use"
            in f"{run_target.stdout}\n{run_target.stderr}".lower()
        ):
            pytest.skip("docker-ssh fixture requires free local ports 80 and 443")
        raise RuntimeError(
            "Failed to start docker-ssh target container.\n"
            f"STDOUT:\n{run_target.stdout}\nSTDERR:\n{run_target.stderr}"
        )

    server = None
    try:
        _run_command(
            [
                "docker",
                "exec",
                container_name,
                "bash",
                "-lc",
                (
                    "apt-get update && "
                    "DEBIAN_FRONTEND=noninteractive apt-get install -y "
                    "openssh-server sudo curl wget ca-certificates"
                ),
            ],
            timeout=600,
        )
        _run_command(
            [
                "docker",
                "exec",
                container_name,
                "bash",
                "-lc",
                "mkdir -p /run/sshd /root/.ssh && chmod 700 /root/.ssh",
            ]
        )
        _run_command(
            ["docker", "cp", f"{ssh_key_path}.pub", f"{container_name}:/tmp/ci.pub"]
        )
        _run_command(
            [
                "docker",
                "exec",
                container_name,
                "bash",
                "-lc",
                (
                    "cat /tmp/ci.pub > /root/.ssh/authorized_keys && "
                    "chmod 600 /root/.ssh/authorized_keys && rm /tmp/ci.pub"
                ),
            ]
        )
        _run_command(
            [
                "docker",
                "exec",
                container_name,
                "bash",
                "-lc",
                (
                    "grep -q '^PermitRootLogin' /etc/ssh/sshd_config && "
                    "sed -i 's/^PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config || "
                    "echo 'PermitRootLogin prohibit-password' >> /etc/ssh/sshd_config"
                ),
            ]
        )
        _run_command(
            ["docker", "exec", "-d", container_name, "/usr/sbin/sshd", "-D", "-e"]
        )

        server = DockerSSHServer(
            container_name=container_name,
            ssh_host=SSH_HOST,
            ssh_port=ssh_port,
            ssh_user=SSH_USER,
            ssh_key_path=ssh_key_path,
            home_dir=home_dir,
            repo_root=repo_root,
            experiment_dir=experiment_dir,
        )
        for _ in range(SSH_WAIT_SECONDS):
            if server.run_ssh("echo ok", check=False).returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("SSH server did not become available in time.")

        home_ssh_dir.mkdir(parents=True, exist_ok=True)
        (home_ssh_dir / "known_hosts").touch()
        server_pem = home_ssh_dir / "server.pem"
        shutil.copyfile(ssh_key_path, server_pem)
        server_pem.chmod(0o600)
        (home_dir / ".dallingerconfig").write_text(
            "[Parameters]\n"
            f"server_pem = {server_pem}\n"
            f"docker_image_name = {EXPERIMENT_IMAGE}\n"
        )

        server.add_server()
        yield server
    finally:
        if server is not None:
            server.reset_remote_state()
            server.remove_server()
        _run_command(["docker", "rm", "-f", container_name], check=False)


@pytest.fixture
def fresh_docker_ssh_server(docker_ssh_server):
    docker_ssh_server.ensure_remote_docker_ready()
    docker_ssh_server.reset_remote_state()
    yield docker_ssh_server
    docker_ssh_server.ensure_remote_docker_ready()
    docker_ssh_server.reset_remote_state()
