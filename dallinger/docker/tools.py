import docker
import os
import shutil
import time

from jinja2 import Template
from pathlib import Path
from subprocess import check_output
from subprocess import CalledProcessError

from dallinger.utils import abspath_from_egg


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
            fh.write(f"UID={os.getuid()}\n")
            fh.write(f"GID={os.getgid()}\n")

    def __enter__(self):
        return self.start()

    def start(self):
        self.copy_docker_compse_files()
        env = {"DOCKER_BUILDKIT": "1"}
        build_arg = ""
        if self.needs_chrome:
            build_arg = (
                "--build-arg DALLINGER_DOCKER_IMAGE=dallingerimages/dallinger-bot"
            )
        check_output(
            f"docker-compose build {build_arg}".split(),
            env={**os.environ.copy(), **env},
        )
        check_output("docker-compose up -d".split(), env={**os.environ.copy(), **env})
        # Wait for postgres to complete initialization
        while b"ready to accept connections" not in check_output(
            [
                "docker-compose",
                "-f",
                f"{self.tmp_dir}/docker-compose.yml",
                "logs",
                "postgresql",
            ]
        ):
            time.sleep(2)
        try:
            check_output(
                [
                    "docker-compose",
                    "-f",
                    f"{self.tmp_dir}/docker-compose.yml",
                    "exec",
                    "worker",
                    "dallinger-housekeeper",
                    "initdb",
                ]
            )
        except CalledProcessError:
            self.out.error("There was a problem initializing the database")
            self.stop()
            raise
        # Make sure the containers are all started
        status = check_output(
            [
                "docker-compose",
                "-f",
                f"{self.tmp_dir}/docker-compose.yml",
                "ps",
            ]
        )
        errors = []
        # docker-compose output looks like this:
        #             Name                           Command               State     Ports
        # -----------------------------------------------------------------------------------
        # function_learning_postgresql_1   docker-entrypoint.sh postgres    Up       5432/tcp
        # function_learning_redis_1        docker-entrypoint.sh redis ...   Up       6379/tcp
        # function_learning_web_1          /bin/sh -c dallinger_herok ...   Exit 1
        # function_learning_worker_1       /bin/sh -c dallinger_herok ...   Up
        # ^^^ a final newline
        for line in status.decode("utf-8").split("\n")[2:-1]:
            if "Up" not in line:
                errors.append(line)
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
        os.system(f"docker-compose -f '{self.tmp_dir}/docker-compose.yml' down")

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
