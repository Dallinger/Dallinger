import docker
import os
import shutil
import time

from subprocess import check_output

from dallinger.utils import abspath_from_egg


client = docker.APIClient(base_url="unix://var/run/docker.sock")


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
        self, config, output, experiment_name, tmp_dir, verbose=True, env=None
    ):
        self.config = config
        self.out = output
        self.verbose = verbose
        self.env = env if env is not None else os.environ.copy()
        self.tmp_dir = tmp_dir
        self.experiment_name = experiment_name
        self._record = []

    def copy_docker_compse_files(self):
        for filename in ["docker-compose.yml", "Dockerfile.web", "Dockerfile.worker"]:
            path = abspath_from_egg(
                "dallinger", f"dallinger/command_line/docker/{filename}"
            )
            shutil.copy2(path, self.tmp_dir)
        with open(os.path.join(self.tmp_dir, ".env"), "w") as fh:
            fh.write(f"COMPOSE_PROJECT_NAME=${self.experiment_name}")

    def __enter__(self):
        return self.start()

    def start(self):
        self.copy_docker_compse_files()
        os.system("docker-compose up --build -d")
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
        os.system(
            f"docker-compose -f '{self.tmp_dir}/docker-compose.yml' exec worker dallinger-housekeeper initdb"
        )
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
            map(self.out.error, errors)
            raise DockerStartupError
        return self

    def __exit__(self, exctype, excinst, exctb):
        self.stop()

    def stop(self):
        os.system(f"docker-compose -f '{self.tmp_dir}/docker-compose.yml' down")

    def monitor(self, listener):
        web_container_name = f"{self.experiment_name}_web_1"
        logs = client.attach(web_container_name, stream=True, logs=True)
        for raw_line in logs:
            line = raw_line.decode("utf-8")
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
