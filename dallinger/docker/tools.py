import docker
import os
import shutil
import time

from jinja2 import Template
from pathlib import Path
from subprocess import check_output
from subprocess import CalledProcessError

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
        self.client = docker.APIClient(base_url="unix://var/run/docker.sock")

    def copy_docker_compse_files(self):
        for filename in ["Dockerfile.web", "Dockerfile.worker"]:
            path = abspath_from_egg("dallinger", f"dallinger/docker/{filename}")
            shutil.copy2(path, self.tmp_dir)
        volumes = [f"{self.original_dir}:{self.original_dir}"]
        editable_dallinger_path = get_editable_dallinger_path()
        if editable_dallinger_path:
            volumes.append(f"{editable_dallinger_path}/dallinger:/dallinger/dallinger")
        with open(os.path.join(self.tmp_dir, "docker-compose.yml"), "w") as fh:
            fh.write(
                docker_compose_template.render(
                    volumes=volumes,
                    experiment_name=self.experiment_name,
                    needs_chrome=self.needs_chrome,
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
        env = {"DOCKER_BUILDKIT": "1"}
        build_args = ["--progress=plain"]
        if self.needs_chrome:
            build_args += [
                "--build-arg",
                "DALLINGER_DOCKER_IMAGE=dallingerimages/dallinger-bot",
            ]
        check_output(
            ["docker-compose", "build"] + build_args,
            env={**os.environ.copy(), **env},
        )
        check_output("docker-compose up -d".split(), env={**os.environ.copy(), **env})
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
        for container_id in self.run_compose(["ps", "-q"]).decode("utf-8").split():
            container = docker.client.from_env().containers.get(container_id)
            try:
                health = container.attrs["State"]["Health"]["Status"]
            except KeyError:
                health = (
                    "healthy"  # Containers with no health check just need to be running
                )
            if container.status != "running" or health != "healthy":
                errors.append(f"{container.name}: {container.status} - {health}")
        if errors:
            self.out.error("Some services did not start properly:")
            for error in errors:
                self.out.error(error)
                self.out.error(
                    self.client.attach(error.split(" ")[0], logs=True).decode("utf-8")
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
        # logs = self.client.events(filters={"ancestor": [f"{self.experiment_name}-web", f"{self.experiment_name}-worker"]})
        logs = self.client.attach(
            self.get_container_name("web"), stream=True, logs=True
        )
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

    # To build the docker images and upload them to heroku run the following
    # command in self.tmp_dir:
    # heroku container:push --recursive -a ${HEROKU_APP_NAME}
    # To make sure the app has the necessary addons:
    # heroku addons:create -a ${HEROKU_APP_NAME} heroku-postgresql:hobby-dev
    # heroku addons:create -a ${HEROKU_APP_NAME} heroku-redis:hobby-dev
    # To release containers:
    # heroku container:release web worker -a ${HEROKU_APP_NAME}
    # To initialize the database:
    # heroku run dallinger-housekeeper initdb -a $HEROKU_APP_NAME


class DockerStartupError(RuntimeError):
    """Some docker containers had problems starting"""
