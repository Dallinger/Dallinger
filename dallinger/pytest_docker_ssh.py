import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest
import requests

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
    python_executable: str

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
            [
                self.python_executable,
                "-c",
                "import sys; from dallinger.command_line import dallinger; sys.exit(dallinger())",
                *args,
            ],
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

        start_command = (
            "nohup dockerd --storage-driver=vfs >/var/log/dockerd.log 2>&1 </dev/null &"
        )
        self.run_ssh(start_command)
        for _ in range(DOCKER_WAIT_SECONDS):
            if self.run_ssh("docker info >/dev/null 2>&1", check=False).returncode == 0:
                return
            time.sleep(1)

        # In restricted container runtimes, nftables often cannot create NAT
        # chains. Retry using legacy iptables userspace if available.
        self.run_ssh("pkill -f dockerd >/dev/null 2>&1 || true", check=False)
        self.run_ssh(
            (
                "update-alternatives --set iptables /usr/sbin/iptables-legacy >/dev/null 2>&1 || true; "
                "update-alternatives --set ip6tables /usr/sbin/ip6tables-legacy >/dev/null 2>&1 || true"
            ),
            check=False,
        )
        self.run_ssh(start_command)
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

    def run_apps_command(self, *, check=True):
        return self.run_dallinger(
            ["docker-ssh", "apps", "--server", self.server], check=check
        )

    def run_servers_list_command(self, *, check=True):
        return self.run_dallinger(["docker-ssh", "servers", "list"], check=check)

    def _collect_remote_diagnostics(self):
        diagnostics = []
        commands = (
            ("docker ps -a", "docker ps -a"),
            (
                'for c in $(docker ps -aq); do echo "===== $c ====="; docker logs "$c" || true; done',
                "docker container logs",
            ),
            ("tail -n 200 /var/log/dockerd.log || true", "dockerd log tail"),
        )
        for command, label in commands:
            result = self.run_ssh(command, check=False, timeout=180)
            diagnostics.append(
                f"--- {label} (exit {result.returncode}) ---\n"
                f"{result.stdout}\n{result.stderr}"
            )
        return "\n".join(diagnostics)

    def list_apps(self):
        result = self.run_apps_command(check=False)
        output = f"{result.stdout}\n{result.stderr}"
        return sorted(set(re.findall(r"\bdlgr-[0-9a-f]{8}\b", output)))

    def _sandbox_args(
        self, app_id, *, update=False, docker_image_name=EXPERIMENT_IMAGE
    ):
        args = [
            "docker-ssh",
            "sandbox",
            "--server",
            self.server,
            "--app",
            app_id,
            "--dns-host",
            "nip.io",
            "--local_build",
            "-c",
            "dashboard_password",
            "pytest-dashboard-password",
            "-c",
            "recruiter",
            "hotair",
            "-c",
            "auto_recruit",
            "false",
        ]
        if docker_image_name is not None:
            args.extend(["-c", "docker_image_name", docker_image_name])
        if update:
            args.append("--update")
        return args

    def deploy_sandbox(self, app_id=None, *, docker_image_name=EXPERIMENT_IMAGE):
        requested_app_id = app_id or f"dlgr-{uuid.uuid4().hex[:8]}"
        try:
            result = self.run_dallinger(
                self._sandbox_args(
                    requested_app_id,
                    update=False,
                    docker_image_name=docker_image_name,
                ),
                timeout=1200,
            )
        except RuntimeError as exc:
            diagnostics = self._collect_remote_diagnostics()
            raise RuntimeError(f"{exc}\n\nRemote diagnostics:\n{diagnostics}") from exc
        output = f"{result.stdout}\n{result.stderr}"
        match = re.search(r"Experiment (dlgr-[0-9a-f]{8}) started\.", output)
        parsed_app_id = match.group(1) if match else None
        if parsed_app_id:
            return parsed_app_id
        return requested_app_id

    def update_sandbox(self, app_id, *, docker_image_name=EXPERIMENT_IMAGE):
        try:
            return self.run_dallinger(
                self._sandbox_args(
                    app_id, update=True, docker_image_name=docker_image_name
                ),
                timeout=1200,
            )
        except RuntimeError as exc:
            diagnostics = self._collect_remote_diagnostics()
            raise RuntimeError(f"{exc}\n\nRemote diagnostics:\n{diagnostics}") from exc

    def experiment_base_url(self, app_id):
        target_ip = socket.gethostbyname(self.ssh_host)
        return f"https://{app_id}.{target_ip}.nip.io"

    def fetch_experiment_page(self, app_id, path, *, query=None, timeout=30):
        query = query or {}
        return requests.get(
            f"{self.experiment_base_url(app_id)}{path}",
            params=query,
            timeout=timeout,
            verify=False,
        )

    def destroy_app(self, app_id):
        try:
            self.run_dallinger(
                ["docker-ssh", "destroy", "--server", self.server, "--app", app_id]
            )
        except RuntimeError as exc:
            diagnostics = self._collect_remote_diagnostics()
            raise RuntimeError(f"{exc}\n\nRemote diagnostics:\n{diagnostics}") from exc


@pytest.fixture(scope="session")
def docker_ssh_server(tmp_path_factory):
    if not os.environ.get("RUN_DOCKER"):
        pytest.skip("need RUN_DOCKER environment variable")
    if shutil.which("docker") is None:
        pytest.skip("docker executable not available")
    if not sys.executable:
        pytest.skip("python executable not available")
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
            python_executable=sys.executable,
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
