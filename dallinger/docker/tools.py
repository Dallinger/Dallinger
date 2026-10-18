import codecs
import os
import re
import sys
import tempfile
import time
import warnings
from hashlib import sha256
from pathlib import Path
from shutil import which
from subprocess import STDOUT, CalledProcessError, call, check_output, run

import click
import docker
from jinja2 import Template
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from dallinger.docker.wheel_filename import parse_wheel_filename
from dallinger.utils import (
    JSON_LOGFILE,
    abspath_from_egg,
    get_editable_dallinger_path,
)

LATEST_VERSION = ""  # use :latest image tag

# Worker containers get a low CPU weight so the web server wins when CPU is
# short: their combined weight is about 10% of the web container's default
# weight of 1024. Docker rejects weights below 2.
WORKERS_COMBINED_CPU_SHARES = 102
MIN_CPU_SHARES = 2


def worker_cpu_shares(worker_processes):
    """Return the Docker ``cpu_shares`` for each worker container.

    Parameters
    ----------
    worker_processes : int
        Number of worker containers sharing the combined worker weight.
    """
    return max(
        MIN_CPU_SHARES, round(WORKERS_COMBINED_CPU_SHARES / max(worker_processes, 1))
    )


def docker_worker_processes(config):
    """Return the number of worker containers for a Docker deployment.

    Uses ``worker_processes`` if it is set explicitly. Otherwise, an
    explicitly set ``num_dynos_worker`` (which used to size Docker workers
    too) is used with a ``FutureWarning``.

    Parameters
    ----------
    config : dallinger.config.Configuration
        The loaded configuration.
    """
    if not config.is_set_explicitly("worker_processes") and config.is_set_explicitly(
        "num_dynos_worker"
    ):
        count = config.get("num_dynos_worker")
        warnings.warn(
            "Docker deployments now use 'worker_processes' for the number of "
            f"worker containers; using num_dynos_worker = {count} instead. "
            "Set 'worker_processes' to silence this warning.",
            FutureWarning,
            stacklevel=2,
        )
        return count
    return config.get("worker_processes", 1)


docker_compose_template = Template(
    abspath_from_egg("dallinger", "dallinger/docker/docker-compose.yml.j2").read_text()
)

# Appended to custom Dockerfiles when a local Dallinger wheel is staged, so the
# image runs that tree even if the Dockerfile installed a pinned Dallinger.
LOCAL_DALLINGER_WHEEL_SNIPPET = """
# Added by Dallinger: install the local Dallinger wheel staged for this build.
COPY dallinger-*.whl /tmp/dallinger-wheel/
RUN python -m pip install --no-cache-dir --force-reinstall --no-deps /tmp/dallinger-wheel/dallinger-*.whl
"""


def _quote_dotenv_value(value):
    """Quote ``value`` so docker compose reads it back from ``.env`` unchanged.

    Unquoted ``.env`` values are interpolated (``$name``) and cut at `` #``.
    """
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$")
    return f'"{escaped}"'


def _private_opener(path, flags):
    """Open ``path`` readable and writable by the owner only."""
    return os.open(path, flags, 0o600)


class DockerComposeWrapper:
    """Wrapper around a docker compose local daemon, modeled after HerokuLocalWrapper.

    Provides for verified startup and shutdown, and allows observers to register
    to recieve subprocess output via 'monitor()'.

    Implements a context manager pattern:

        with DockerComposeWrapper(config, output) as docker:
            docker.monitor(my_callback)

    Arg 'output' should implement log(), error() and blather() methods taking
    strings as arguments.
    """

    shell_command = "docker compose"
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
        self.env["FLASK_SECRET_KEY"] = self.env.get("FLASK_SECRET_KEY") or ""
        self.tmp_dir = tmp_dir
        self.original_dir = original_dir
        self.experiment_name = Path(self.original_dir).name
        self._record = []
        self.needs_chrome = needs_chrome

    def copy_docker_compose_files(self):
        """Prepare a docker-compose.yml file and place it in the experiment tmp dir.

        Dallinger's own compose calls pass the key via ``env=self.env``; the
        ``.env`` copy serves manual ``docker compose logs`` or ``down`` in the
        tmp dir, which fail without it because the template requires the key.
        """
        logger_filename = JSON_LOGFILE
        volumes = [
            f"{self.original_dir}:{self.original_dir}",
            f"{self.tmp_dir}:/experiment",
            f"./{logger_filename}:/experiment/{logger_filename}",
        ]
        with open(f"{self.tmp_dir}/{logger_filename}", "w") as f:  # noqa: F841
            pass

        editable_dallinger_path = get_editable_dallinger_path()
        if editable_dallinger_path:
            volumes.append(f"{editable_dallinger_path}/dallinger:/dallinger/dallinger")
            volumes.append(
                f"{editable_dallinger_path}/dallinger:/usr/local/lib/python3.14/dist-packages/dallinger/"
            )
            volumes.append(
                f"{editable_dallinger_path}/dallinger:/usr/local/lib/python3.13/dist-packages/dallinger/"
            )
            volumes.append(
                f"{editable_dallinger_path}/dallinger:/usr/local/lib/python3.12/dist-packages/dallinger/"
            )
            volumes.append(
                f"{editable_dallinger_path}/dallinger:/usr/local/lib/python3.11/dist-packages/dallinger/"
            )
        tag = get_experiment_image_tag(self.tmp_dir)
        worker_processes = docker_worker_processes(self.config)
        with open(os.path.join(self.tmp_dir, "docker-compose.yml"), "w") as fh:
            fh.write(
                docker_compose_template.render(
                    volumes=volumes,
                    experiment_name=self.experiment_name,
                    experiment_image=f"{self.experiment_name}:{tag}",
                    needs_chrome=self.needs_chrome,
                    config=self.config,
                    worker_processes=worker_processes,
                    worker_cpu_shares=worker_cpu_shares(worker_processes),
                )
            )
        dotenv_path = os.path.join(self.tmp_dir, ".env")
        with open(dotenv_path, "w", opener=_private_opener) as fh:
            os.fchmod(fh.fileno(), 0o600)
            fh.write(f"COMPOSE_PROJECT_NAME={self.experiment_name}\n")
            flask_secret_key = _quote_dotenv_value(self.env["FLASK_SECRET_KEY"])
            fh.write(f"FLASK_SECRET_KEY={flask_secret_key}\n")
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
        """Block until the postgresql server in the `docker compose` configuration
        is ready to accept connections.
        """
        needle = b"ready to accept connections"
        while needle not in self.run_compose(["logs", "postgresql"]):
            self.out.blather("Waiting for postgresql\n")
            time.sleep(1)
        self.out.blather("Postgresql ready\n")

    def start(self):
        """Build the image, then write the compose files and start the services.

        The image is built first because ``COPY . /experiment`` would
        otherwise bake ``.env``, and with it the Flask secret key, into it.
        """
        build_image(self.tmp_dir, self.experiment_name, self.out, self.needs_chrome)
        self.copy_docker_compose_files()
        self.run_compose(["up", "-d"])
        # Wait for postgres to complete initialization
        self.wait_postgres_ready()
        try:
            # ``web`` always exists; ``worker`` may have no replicas.
            self.run_compose(["exec", "web", "dallinger-housekeeper", "initdb"])
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
                self.out.error(f"{error['name']}: {error['message']}")
                self.out.error(
                    client.api.attach(error["name"], logs=True).decode("utf-8")
                )
            raise DockerStartupError
        return self

    def __exit__(self, exctype, excinst, exctb):
        self.stop()

    def stop(self):
        call(self._compose_command() + ["stop"], env=self.env)

    def get_container_name(self, service_name):
        """Return the name of the first container for the given service name
        as it is known to docker, as opposed to `docker compose`.
        """
        return f"{self.experiment_name}-{service_name}-1"

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
        `docker compose` command.
        Examples:
        # return the output of `docker compose ps`
        compose_commands = ["ps"]
        # Run `redis-cli ping` inside the `redis` container and return its output
        compose_commands = ["exec", "redis", "redis-cli", "ping"]

        Compose prefers process variables over ``.env``, so commands run with
        ``self.env``; otherwise a host ``FLASK_SECRET_KEY`` would replace the
        deployment's key.
        """
        return check_output(self._compose_command() + compose_commands, env=self.env)

    def _compose_command(self):
        """Return the ``docker compose`` invocation for this experiment's file."""
        return ["docker", "compose", "-f", f"{self.tmp_dir}/docker-compose.yml"]


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


_COMMENT_RE = re.compile(r"(^|\s+)#.*$")
_INCLUDE_RE = re.compile(
    r"^(?:-[rc]\s*|--(?:requirement|constraint)(?:\s+|=))(?P<path>\S+)$"
)
_OPTION_RE = re.compile(r"\s+-")


def _read_requirement_lines(path: Path, _including=()) -> list[str]:
    """Return the requirement specifiers in a pip requirements file.

    Supports the subset of the pip requirements file format that Dallinger
    generates or experiments commonly use: comments, blank lines, backslash
    line continuations, ``-r``/``-c`` includes (resolved relative to the
    including file) and per-requirement options such as ``--hash``. Other
    option lines, including editable (``-e``) requirements, are skipped.
    Files are read as UTF-8, or as UTF-16 when they start with a UTF-16 byte
    order mark (as written by ``pip freeze >`` in Windows PowerShell 5). URL
    includes are not supported.

    Parameters
    ----------
    path : Path
        Path to a requirements or constraints file.

    Returns
    -------
    list of str
        Requirement specifiers, e.g. ``"dallinger==7.2.0"``, with trailing
        options removed.

    Raises
    ------
    ValueError
        If ``-r``/``-c`` includes form a cycle.
    """
    path = Path(path).resolve()
    if path in _including:
        chain = " -> ".join(str(p) for p in (*_including, path))
        raise ValueError(f"Requirements files include each other in a cycle: {chain}")
    data = path.read_bytes()
    is_utf16 = data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE))
    text = data.decode("utf-16" if is_utf16 else "utf-8-sig")

    logical_lines = []
    current = ""
    for raw_line in text.splitlines():
        line = _COMMENT_RE.sub("", raw_line)
        if line.endswith("\\"):
            current += line[:-1] + " "
            continue
        logical_lines.append((current + line).strip())
        current = ""
    logical_lines.append(current.strip())

    requirements = []
    for line in logical_lines:
        if not line:
            continue
        if line.startswith("-"):
            include = _INCLUDE_RE.match(line)
            if include:
                requirements.extend(
                    _read_requirement_lines(
                        path.parent / include["path"], (*_including, path)
                    )
                )
            continue
        requirements.append(_OPTION_RE.split(line, maxsplit=1)[0])
    return requirements


def _dallinger_pin(line: str):
    """Return the Dallinger version pinned by a requirement line, or ``None``."""
    # In case dallinger is installed in editable mode
    if line.startswith("file:dallinger-"):
        return str(parse_wheel_filename(line[len("file:") :]).version)
    try:
        requirement = Requirement(line)
    except InvalidRequirement:
        return None
    if canonicalize_name(requirement.name) != "dallinger":
        return None
    pins = [spec.version for spec in requirement.specifier if spec.operator == "=="]
    return pins[0] if pins else None


def get_required_dallinger_version(experiment_tmp_path: str) -> str:
    """Examine the requirements.txt in an experiment tmp directory
    and return the dallinger version required by the experiment.
    """
    requirements_path = Path(experiment_tmp_path) / "requirements.txt"
    pinned_versions = [
        version
        for version in map(_dallinger_pin, _read_requirement_lines(requirements_path))
        if version
    ]
    if not pinned_versions:
        print("Could not determine Dallinger version. Using latest")
        return LATEST_VERSION

    def _normalize_version(version_text: str) -> str:
        try:
            parsed_version = Version(version_text)
        except InvalidVersion:
            return version_text
        if parsed_version.is_prerelease:
            print(
                f"Dallinger version {parsed_version} is not guaranteed to have a published base image tag. "
                "Using latest"
            )
            return LATEST_VERSION
        return version_text

    return _normalize_version(pinned_versions[0])


def get_experiment_image_tag(experiment_tmp_path: str) -> str:
    """Return a docker image tag from the experiment's dependency inputs.

    Used for local ``docker debug`` (the experiment directory is bind-mounted,
    so the image is only a deps environment) and for ``dallinger docker build``
    / ``push --use-existing``. SSH and Heroku-docker deploys instead pass
    :func:`docker_tag_from_experiment_id` into :func:`build_image`, because
    those paths ``COPY`` the experiment into the image.
    """
    files = "requirements.txt", "prepare_docker_image.sh"
    hash = sha256()
    for filename in files:
        filepath = Path(experiment_tmp_path) / filename
        hash.update(filepath.read_bytes())
    return hash.hexdigest()[:8]


def docker_tag_from_experiment_id(experiment_id: str) -> str:
    """Return a Docker tag unique to this launch.

    On SSH and Heroku-docker deploy the experiment directory is copied into
    the image and compose pins that tag for the life of the app. A deps-only
    hash is then unsafe: two variants with the same ``requirements.txt`` and
    ``prepare_docker_image.sh`` share a tag, race each other's builds, and
    one app can run the other variant's code.

    ``experiment_id`` is the per-launch UID from ``setup_experiment``. Docker
    tags allow ``[A-Za-z0-9_.-]`` and must not start with ``.`` or ``-``.
    """
    tag = "".join(
        ch if ch.isalnum() or ch in "_.-" else "-" for ch in str(experiment_id)
    )
    tag = tag.lstrip(".-") or "latest"
    return tag[:128]


# Images built with a writable /experiment carry this label. docker-ssh runs
# only these as the SSH user; older images keep running as root.
RUNS_AS_SSH_USER_LABEL = "org.dallinger.runs-as-ssh-user"

# The SSH account is chosen when the container starts, after this image is built.
# Write permission on these directories lets that account create server.log and
# the static/assets link. Shipped source files stay owned by root.
_EXPERIMENT_WORKDIR_WRITABLE = """\
RUN mkdir -p /experiment/static \\
 && find /experiment -type d -exec chmod a+rwx {} +
"""


def ensure_experiment_workdir_writable(dockerfile_text):
    """Let the runtime user create files in every directory under /experiment.

    Docker-ssh runs the experiment as the SSH user. That uid is not known
    while the image is built, so the directories need to be writable by any
    user. Only directories change, which keeps the extra image layer small;
    shipped files stay owned by root.
    """
    marker = "find /experiment -type d -exec chmod a+rwx"
    if marker in dockerfile_text:
        return dockerfile_text
    return dockerfile_text.rstrip() + "\n\n" + _EXPERIMENT_WORKDIR_WRITABLE


def build_image(
    tmp_dir,
    base_image_name,
    out,
    needs_chrome=False,
    force_build=True,
    image_tag=None,
    quiet=False,
) -> str:
    """Build the docker image for the experiment and return its name.

    If ``image_tag`` is set, use it (deploy: per-launch UID). Otherwise hash
    ``requirements.txt`` and ``prepare_docker_image.sh``. If
    ``force_build`` is False, skip the build when that tag already exists.
    If ``quiet`` is True, the ``docker build`` output goes to a log file that
    is printed and kept only if the build fails, unless
    ``DALLINGER_VERBOSE_BUILD`` is ``1``, ``true`` or ``yes``.
    """
    tag = image_tag or get_experiment_image_tag(tmp_dir)
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
        **os.environ.copy(),
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

    docker_build_invocation += ["--label", f"{RUNS_AS_SSH_USER_LABEL}=1"]
    docker_build_invocation += ["-t", image_name]
    dockerfile_path = Path(tmp_dir) / "Dockerfile"
    if dockerfile_path.exists():
        out.blather(
            "Found a custom Dockerfile in the experiment directory, will use this for deployment.\n"
        )
        dockerfile_text = dockerfile_path.read_text(encoding="utf-8")
        if list(Path(tmp_dir).glob("dallinger-*.whl")):
            dockerfile_text += LOCAL_DALLINGER_WHEEL_SNIPPET
        dockerfile_path.write_text(
            ensure_experiment_workdir_writable(dockerfile_text), encoding="utf-8"
        )
    else:
        dockerfile_text = rf"""# syntax=docker/dockerfile:1
        FROM {base_image_name}
        #
        RUN mkdir /experiment
        WORKDIR /experiment
        #
        COPY requirements.txt requirements.txt
        COPY dallinger-*.whl .
        COPY *prepare_docker_image.sh prepare_docker_image.sh
        #
        # If a dallinger wheel is present, install it.
        # This will be true if Dallinger was installed with the editable `-e` flag
        # Note: We uninstall dallinger first to make sure the installation isn't skipped.
        RUN if [ -f dallinger-*.whl ]; then \
            echo "Dallinger wheel found, will install it"; \
            pip uninstall -y dallinger && pip install dallinger-*.whl; \
        else \
            echo "No Dallinger wheel found, using base image version"; \
        fi
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
        #
        # Some experiments might only list dallinger as dependency
        # If they do the grep command will exit non-0, the pip command will not run
        # but the whole `RUN` group will succeed thanks to the last `true` invocation
        RUN mkdir -p ~/.ssh && echo "Host *\n    StrictHostKeyChecking no" >> ~/.ssh/config
        RUN {ssh_mount} grep -v ^dallinger requirements.txt > /tmp/requirements_no_dallinger.txt && \
            python3 -m pip install -r /tmp/requirements_no_dallinger.txt || true
        COPY . /experiment
        # Reinstall a staged local wheel last, so it wins over a Dallinger pin
        # that another requirement (such as psynet) pulled in above.
        RUN set -- /experiment/dallinger-*.whl; \
            if [ -f "$1" ]; then pip install --force-reinstall --no-deps "$1"; fi
        ENV PORT=5000
        CMD dallinger_heroku_web
        """
        dockerfile_path.write_text(ensure_experiment_workdir_writable(dockerfile_text))
    # Our messages must reach the terminal before docker's own output does.
    sys.stdout.flush()
    verbose = os.environ.get("DALLINGER_VERBOSE_BUILD", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    if quiet and not verbose:
        _build_with_log_file(docker_build_invocation, env, image_name, out)
    else:
        try:
            check_output(docker_build_invocation, env=env)
        except CalledProcessError:
            raise BuildError
    out.blather(f"Built image: {image_name}" + "\n")
    return image_name


def _build_with_log_file(docker_build_invocation, env, image_name, out):
    """Run ``docker build`` into a log file, printing and keeping it only on failure."""
    with tempfile.NamedTemporaryFile(
        "w", prefix="dallinger-docker-build-", suffix=".log", delete=False
    ) as log_file:
        out.blather(
            f"Building image {image_name} (set DALLINGER_VERBOSE_BUILD=1 "
            "to show docker's output)...\n"
        )
        sys.stdout.flush()
        result = run(docker_build_invocation, env=env, stdout=log_file, stderr=STDOUT)
    log_path = Path(log_file.name)
    if result.returncode == 0:
        log_path.unlink()
        return
    out.blather(log_path.read_text(errors="replace"))
    out.blather(f"\nImage build failed; the log above is saved in {log_path}\n")
    sys.stdout.flush()
    raise BuildError
