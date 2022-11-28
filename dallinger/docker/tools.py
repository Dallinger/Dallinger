import click
import docker
import os
import time

from hashlib import sha256

from jinja2 import Template
from pathlib import Path
from shutil import which
from subprocess import check_output
from subprocess import CalledProcessError
from pip._internal.network.session import PipSession
from pip._internal.req import parse_requirements

from dallinger.docker.wheel_filename import parse_wheel_filename
from dallinger.utils import abspath_from_egg
from dallinger.utils import get_editable_dallinger_path

docker_compose_template = Template(
    abspath_from_egg("dallinger", "dallinger/docker/docker-compose.yml.j2").read_text()
)


class DockerComposeWrapper(object):
    """Wrapper around a docker compose local daemon, modeled after HerokuLocalWrapper.

    Provides for verified startup and shutdown, and allows observers to register
    to recieve subprocess output via 'monitor()'.

    Implements a context manager pattern:

        with DockerComposeWrapper(config, output) as docker:
            docker.monitor(my_callback)

    Arg 'output' should implement log(), error() and blather() methods taking
    strings as arguments.
    """

    shell_command = "docker-compose"
    MONITOR_STOP = object()

    def __init__(
        self,
        config,
        output,
        original_dir,
        tmp_dir,
        verbose=True,
        env=None,
        needs_chrome=False,
    ):
        self.config = config
        self.out = output
        self.verbose = verbose
        self.env = env if env is not None else os.environ.copy()
        self.tmp_dir = tmp_dir
        self.original_dir = original_dir
        self.experiment_name = Path(self.original_dir).name
        self._record = []
        self.needs_chrome = needs_chrome

    def copy_docker_compse_files(self):
        """Prepare a docker-compose.yml file and place it in the experiment tmp dir"""
        volumes = [
            f"{self.original_dir}:{self.original_dir}",
            f"{self.tmp_dir}:/experiment",
        ]
        editable_dallinger_path = get_editable_dallinger_path()
        if editable_dallinger_path:
            volumes.append(f"{editable_dallinger_path}/dallinger:/dallinger/dallinger")
            volumes.append(
                f"{editable_dallinger_path}/dallinger:/usr/local/lib/python3.8/dist-packages/dallinger/"
            )
            volumes.append(
                f"{editable_dallinger_path}/dallinger:/usr/local/lib/python3.9/dist-packages/dallinger/"
            )
        tag = get_experiment_image_tag(self.tmp_dir)
        with open(os.path.join(self.tmp_dir, "docker-compose.yml"), "w") as fh:
            fh.write(
                docker_compose_template.render(
                    volumes=volumes,
                    experiment_name=self.experiment_name,
                    experiment_image=f"{self.experiment_name}:{tag}",
                    needs_chrome=self.needs_chrome,
                    config=self.config,
                )
            )
        with open(os.path.join(self.tmp_dir, ".env"), "w") as fh:
            fh.write(f"COMPOSE_PROJECT_NAME=${self.experiment_name}\n")
            fh.write(f"FLASK_SECRET_KEY=${self.env.get('FLASK_SECRET_KEY')}\n")
            fh.write(f"UID={os.getuid()}\n")
            fh.write(f"GID={os.getgid()}\n")

    def __enter__(self):
        return self.start()

    def wait_redis_ready(self):
        """Block until the redis server in the docker-compose configuration
        is ready to accept connections.
        """
        response = ""
        while response.strip() != b"PONG":
            if response:
                self.out.blather(f"Waiting for redis (got {response})\n")
            response = self.run_compose(["exec", "redis", "redis-cli", "ping"])
            time.sleep(1)
        self.out.blather("Redis ready\n")

    def wait_postgres_ready(self):
        """Block until the postgresql server in the docker-compose configuration
        is ready to accept connections.
        """
        needle = b"ready to accept connections"
        while needle not in self.run_compose(["logs", "postgresql"]):
            self.out.blather("Waiting for postgresql\n")
            time.sleep(1)
        self.out.blather("Postgresql ready\n")

    def start(self):
        self.copy_docker_compse_files()
        build_image(self.tmp_dir, self.experiment_name, self.out, self.needs_chrome)
        check_output("docker-compose up -d".split())
        # Wait for postgres to complete initialization
        self.wait_postgres_ready()
        try:
            self.run_compose(["exec", "worker", "dallinger-housekeeper", "initdb"])
        except CalledProcessError:
            self.out.error("There was a problem initializing the database")
            self.stop()
            raise
        self.wait_redis_ready()
        # Make sure the containers are all started
        errors = []
        client = docker.client.from_env()
        for container_id in self.run_compose(["ps", "-q"]).decode("utf-8").split():
            container = client.containers.get(container_id)
            try:
                health = container.attrs["State"]["Health"]["Status"]
            except KeyError:
                health = (
                    "healthy"  # Containers with no health check just need to be running
                )
            if container.status != "running" or health != "healthy":
                errors.append(
                    {
                        "name": container.name,
                        "message": f"{container.status} - {health}",
                    }
                )
        if errors:
            self.out.error("Some services did not start properly:")
            for error in errors:
                self.out.error(f'{error["name"]}: {error["message"]}')
                self.out.error(
                    client.api.attach(error["name"], logs=True).decode("utf-8")
                )
            raise DockerStartupError
        return self

    def __exit__(self, exctype, excinst, exctb):
        self.stop()

    def stop(self):
        os.system(f"docker-compose -f '{self.tmp_dir}/docker-compose.yml' stop")

    def get_container_name(self, service_name):
        """Return the name of the first container for the given service name
        as it is known to docker, as opposed to docker-compose.
        """
        return f"{self.experiment_name}_{service_name}_1"

    def monitor(self, listener):
        # How can we get a stream for two containers?
        # Or, as an alternative, how do we combine two of these (blocking?) iterators?
        # logs = client.api.events(filters={"ancestor": [f"{self.experiment_name}-web", f"{self.experiment_name}-worker"]})
        client = docker.client.from_env()
        logs = client.api.attach(self.get_container_name("web"), stream=True, logs=True)
        for raw_line in logs:
            line = raw_line.decode("utf-8", errors="ignore")
            self._record.append(line)
            if self.verbose:
                self.out.blather(line)
            if listener(line) is self.MONITOR_STOP:
                return

    def run_compose(self, compose_commands: str):
        """Run a command in the (already built) tmp directory of the current experiment
        `compose_commands` should be an array of strings to be appended to the
        docker-compose command.
        Examples:
        # return the output of `docker-compose ps`
        compose_commands = ["ps"]
        # Run `redis-cli ping` inside the `redis` container and return its output
        compose_commands = ["exec", "redis", "redis-cli", "ping"]
        """
        return check_output(
            ["docker-compose", "-f", f"{self.tmp_dir}/docker-compose.yml"]
            + compose_commands,
        )


class DockerStartupError(click.Abort):
    """Some docker containers had problems starting"""


class BuildError(click.Abort):
    """There was a problem building the docker image"""


def get_base_image(experiment_tmp_path: str, needs_chrome: bool = False) -> str:
    """Inspects an experiment tmp directory and determines the version
    of dallinger required by the experiment.
    Returns a docker image name and tag. For example:
    `ghcr.io/dallinger/dallinger-bot:7.1.0`
    """
    dallinger_version = get_required_dallinger_version(experiment_tmp_path)
    base_image_name = "ghcr.io/dallinger/dallinger"
    if needs_chrome:
        base_image_name += "-bot"
    return f"{base_image_name}:{dallinger_version or 'latest'}"


def get_required_dallinger_version(experiment_tmp_path: str) -> str:
    """Examine the requirements.txt in an experiment tmp directory
    and return the dallinger version required by the experiment.
    """
    requirements_path = str(Path(experiment_tmp_path) / "requirements.txt")
    all_requirements = parse_requirements(requirements_path, session=PipSession())
    dallinger_requirements = [
        el.requirement
        for el in all_requirements
        if el.requirement.startswith("dallinger==")
        or el.requirement.startswith(
            "file:dallinger-"
        )  # In case dallinger is installed in editable mode
    ]
    if not dallinger_requirements:
        print("Could not determine Dallinger version. Using latest")
        return ""
    # pip-compile should have created a single spec in the form "dallinger==7.2.0"
    if "==" in dallinger_requirements[0]:
        return dallinger_requirements[0].split("==")[1]
    # Or we might have a requirement like `file:dallinger-7.2.0-py3-none-any.whl`
    return parse_wheel_filename(dallinger_requirements[0][len("file:") :]).version


def get_experiment_image_tag(experiment_tmp_path: str) -> str:
    """Return a docker image tag to be used for the experiment.

    The tag needs to be a hash of all the files that, when changed,
    require the image to be rebuilt.

    When an experiment is changed an older image can still be used,
    as long as no dependencies or build script changed.
    The experiment directory can then be mounted to have the latest changes.
    This saves the need to rebuild the image too often.
    """
    files = "requirements.txt", "prepare_docker_image.sh"
    hash = sha256()
    for filename in files:
        filepath = Path(experiment_tmp_path) / filename
        hash.update(filepath.read_bytes())
    return hash.hexdigest()[:8]


def build_image(
    tmp_dir, base_image_name, out, needs_chrome=False, force_build=False
) -> str:
    """Build the docker image for the experiment and return its name."""
    tag = get_experiment_image_tag(tmp_dir)
    image_name = f"{base_image_name}:{tag}"
    base_image_name = get_base_image(tmp_dir, needs_chrome)
    client = docker.client.from_env()
    try:
        client.api.inspect_image(image_name)
        out.blather(f"Image {image_name} found\n")
        if not force_build:
            return image_name
        out.blather("Rebuilding\n")
    except docker.errors.ImageNotFound:
        out.blather(f"Image {image_name} not found - building\n")
    env = {
        "DOCKER_BUILDKIT": "1",
    }
    ssh_mount = ""
    docker_build_invocation = [which("docker"), "build", str(tmp_dir)]
    if os.environ.get("SSH_AUTH_SOCK"):
        env["SSH_AUTH_SOCK"] = os.environ.get("SSH_AUTH_SOCK")
        ssh_mount = "--mount=type=ssh"
        docker_build_invocation = [
            which("docker"),
            "build",
            "--ssh",
            "default",
            str(tmp_dir),
        ]

    docker_build_invocation += ["-t", image_name]
    dockerfile_text = rf"""# syntax=docker/dockerfile:1
    FROM {base_image_name}
    COPY . /experiment
    WORKDIR /experiment
    # If a dallinger wheel is present, install it.
    # This will be true if Dallinger was installed with the editable `-e` flag
    RUN if [ -f dallinger-*.whl ]; then pip install dallinger-*.whl; fi
    # If a dependency needs the ssh client and git, install them
    RUN grep git+ requirements.txt && \
        apt-get update && \
        apt-get install -y openssh-client git && \
        rm -rf /var/lib/apt/lists || true
    RUN {ssh_mount} echo 'Running script prepare_docker_image.sh' && \
        chmod 755 ./prepare_docker_image.sh && \
        ./prepare_docker_image.sh
    # We rely on the already installed dallinger: the docker image tag has been chosen
    # based on the contents of this file. This makes sure dallinger stays installed from
    # /dallinger, and that it doesn't waste space with two copies in two different layers.

    # Some experiments might only list dallinger as dependency
    # If they do the grep command will exit non-0, the pip command will not run
    # but the whole `RUN` group will succeed thanks to the last `true` invocation
    RUN mkdir -p ~/.ssh && echo "Host *\n    StrictHostKeyChecking no" >> ~/.ssh/config
    RUN {ssh_mount} grep -v ^dallinger requirements.txt > /tmp/requirements_no_dallinger.txt && \
        python3 -m pip install -r /tmp/requirements_no_dallinger.txt || true
    ENV PORT=5000
    CMD dallinger_heroku_web
    """
    (Path(tmp_dir) / "Dockerfile").write_text(dockerfile_text)
    try:
        check_output(docker_build_invocation, env=env)
    except CalledProcessError:
        raise BuildError
    out.blather(f"Built image: {image_name}" + "\n")
    return image_name
