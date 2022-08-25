import click
import codecs
import netrc
import os
import re
import secrets
import subprocess
import tempfile
import time
import uuid

from datetime import datetime
from pathlib import Path
from shlex import quote
from heroku3.core import Heroku as Heroku3Client
import requests

from dallinger import heroku
from dallinger import registration
from dallinger.config import get_config
from dallinger.config import LOCAL_CONFIG
from dallinger.heroku.tools import HerokuApp
from dallinger.command_line.utils import Output
from dallinger.command_line.utils import header
from dallinger.command_line.utils import log
from dallinger.command_line.utils import require_exp_directory
from dallinger.command_line.utils import verify_id
from dallinger.deployment import _handle_launch_data
from dallinger.utils import abspath_from_egg
from dallinger.utils import GitClient
from dallinger.utils import setup_experiment


HEROKU_YML = abspath_from_egg("dallinger", "dallinger/docker/heroku.yml").read_text()


@click.group()
def docker():
    """Use docker for local debug and deployment."""
    import docker

    try:
        docker.client.from_env()
    except docker.errors.DockerException:
        print("Can't reach the docker damon. Is it running?")
        raise click.Abort


@docker.command()
@click.option("--verbose", is_flag=True, flag_value=True, help="Verbose mode")
@click.option(
    "--bot",
    is_flag=True,
    flag_value=True,
    help="Use bot to complete experiment",
)
@click.option(
    "--proxy",
    default=None,
    help="Alternate port when opening browser windows",
)
@click.option(
    "--no-browsers",
    is_flag=True,
    flag_value=True,
    default=False,
    help="Skip opening browsers",
)
@require_exp_directory
def debug(verbose, bot, proxy, no_browsers=False, exp_config=None):
    """Run the experiment locally using docker compose."""
    from dallinger.docker.deployment import DockerDebugDeployment

    debugger = DockerDebugDeployment(
        Output(), verbose, bot, proxy, exp_config, no_browsers
    )
    log(header, chevrons=False)
    debugger.run()


@docker.command()
def start_services():
    """Starts postgresql and redis services using docker"""
    os.system(
        "docker run --rm -d --name dallinger_redis -p 6379:6379 -v dallinger_redis:/data redis redis-server --appendonly yes"
    )
    os.system(
        "docker run --rm -d --name dallinger_postgres -p 5432:5432 -e POSTGRES_USER=dallinger -e POSTGRES_PASSWORD=dallinger -e POSTGRES_DB=dallinger -v dallinger_postgres:/var/lib/postgresql/data postgres:12"
    )


@docker.command()
def stop_services():
    """Stops docker based postgresql and redis services"""
    os.system("docker stop dallinger_redis")
    os.system("docker stop dallinger_postgres")


@docker.command()
def remove_services_data():
    """Remove redis and postgresql data - restores a pristine environment"""
    os.system("docker volume rm dallinger_redis dallinger_postgres")


@docker.command()
@click.option("--verbose", is_flag=True, flag_value=True, help="Verbose mode")
@click.option("--app", default=None, help="Experiment id")
@require_exp_directory
def sandbox(verbose, app):
    """Deploy app using Heroku to the MTurk Sandbox."""
    _deploy_in_mode(mode="sandbox", verbose=verbose, log=log, app=app)


@docker.command()
@click.option("--verbose", is_flag=True, flag_value=True, help="Verbose mode")
@click.option("--app", default=None, help="Experiment id")
@require_exp_directory
def deploy(verbose, app):
    """Deploy app using Heroku to MTurk."""
    _deploy_in_mode(mode="live", verbose=verbose, log=log, app=app)


@docker.command()
@require_exp_directory
def build():
    """Build a docker image for this experiment."""
    from dallinger.docker.tools import build_image

    config = get_config()
    config.load()
    _, tmp = setup_experiment(log=log, debug=True, local_checks=False)
    build_image(tmp, config.get("docker_image_base_name"), Output(), force_build=True)


@docker.command()
@click.option("--use-existing", is_flag=True, default=False)
def push(use_existing: bool, **kwargs) -> str:
    """Build and push the docker image for this experiment."""
    from dallinger.docker.tools import build_image
    from docker import client

    config = get_config()
    config.load()
    _, tmp = setup_experiment(log=log, debug=True, local_checks=False)
    image_name_with_tag = build_image(
        tmp,
        config.get("docker_image_base_name"),
        Output(),
        force_build=not use_existing,
    )
    docker_client = client.from_env()
    for line in docker_client.images.push(
        image_name_with_tag, stream=True, decode=True
    ):
        if "status" in line:
            print(line["status"], end="")
            print(line.get("progress", ""))
        if "error" in line:
            print(line.get("error", "") + "\n")
            if "unauthenticated" in line["error"]:
                registry_name = image_name_with_tag.split("/")[0]
                for help_line in REGISTRY_UNAUTHORIZED_HELP_TEXTS.get(
                    registry_name, REGISTRY_UNAUTHORIZED_HELP_TEXT
                ):
                    print(help_line.format(**locals()))
            if "denied" in line["error"]:
                print(
                    f"Your current account does not have permission to push to {image_name_with_tag}"
                )
            raise click.Abort
        if "aux" in line:
            print(f'Pushed image: {line["aux"]["Digest"]}\n')
    pushed_image = docker_client.images.get(image_name_with_tag).attrs["RepoDigests"][0]
    print(f"Image {pushed_image} built and pushed.\n")
    return pushed_image


REGISTRY_UNAUTHORIZED_HELP_TEXTS = {
    "ghcr.io": [
        "You need to login to the github docker registry {registry_name}.",
        "You need to create a PAT (Personal Access Token) here:",
        "https://github.com/settings/tokens/new?scopes=write:packages",
        "and use it to log in with the command",
        "docker login {registry_name}",
    ]
}
REGISTRY_UNAUTHORIZED_HELP_TEXT = [
    "You need to login to the {registry_name} registry with the command:",
    "docker login {registry_name}",
]


@docker.command()
@click.option(
    "--sandbox",
    "mode",
    flag_value="sandbox",
    help="Deploy to MTurk sandbox",
    default=True,
)
@click.option("--live", "mode", flag_value="live", help="Deploy to the real MTurk")
@click.option("--image", required=True, help="Name of the docker image to deploy")
@click.option("--config", "-c", "config_options", nargs=2, multiple=True)
def deploy_image(image, mode, config_options):
    """Deploy Heroku app using a docker image and MTurk."""
    config = get_config()
    config.load()
    dashboard_password = secrets.token_urlsafe(8)
    dallinger_uid = str(uuid.uuid4())
    config_dict = {
        "AWS_ACCESS_KEY_ID": config.get("aws_access_key_id"),
        "AWS_SECRET_ACCESS_KEY": config.get("aws_secret_access_key"),
        "AWS_DEFAULT_REGION": config.get("aws_region"),
        "auto_recruit": config.get("auto_recruit"),
        "smtp_username": config.get("smtp_username"),
        "smtp_password": config.get("smtp_password"),
        "whimsical": config.get("whimsical"),
        "FLASK_SECRET_KEY": secrets.token_urlsafe(16),
        "dashboard_password": dashboard_password,
        "mode": mode,
        "CREATOR": netrc.netrc().hosts["api.heroku.com"][0],
        "DALLINGER_UID": dallinger_uid,
    }
    config_dict.update(config_options)
    heroku_conn = Heroku3Client(session=requests.session())
    print(f"Creating Heroku app in {mode} mode")
    app_name = "dlgr-" + dallinger_uid.split("-")[0]
    app = heroku_conn.create_app(stack_id_or_name="container", name=app_name)
    app_hostname = app.domains()[0].hostname
    config_dict["HOST"] = app_hostname

    print(f"Heroku app {app.name} created. Installing add-ons")

    app.install_addon(f"heroku-postgresql:{config.get('database_size', 'hobby-dev')}")
    # redistogo is significantly faster to start than heroku-redis
    app.install_addon("redistogo:nano")
    app.install_addon("papertrail")
    print("Add-ons installed")

    # Prepare the git repo to push to Heroku
    tmp = tempfile.mkdtemp()
    os.chdir(tmp)
    Path("Dockerfile").write_text(f"FROM {image}")
    Path("heroku.yml").write_text(HEROKU_YML)
    git = GitClient()
    git.init()
    git.add("--all")
    git.commit(f"Deploying image {image}")

    # Launch the Heroku app.
    print("Pushing code to Heroku...")
    git.push(remote=app.git_url, branch="master:master")

    print("Waiting for all addons to be ready")
    expected_vars = {"DATABASE_URL", "REDISTOGO_URL", "PAPERTRAIL_API_TOKEN"}
    ready = False
    while not ready:
        time.sleep(2)
        if expected_vars - set(app.config().to_dict()) == set():
            ready = True

    config_dict["REDIS_URL"] = app.config()["REDISTOGO_URL"]
    app.update_config(config_dict)

    print("Initializing database")
    app.run_command("dallinger-housekeeper initdb")

    print("Scaling dynos")
    services = ["web", "worker"]
    if config.get("clock_on"):
        services.append("clock")
    payload = {
        "updates": [
            dict(
                type=type,
                quantity=config.get(f"num_dynos_{type}", 1),
                size=config.get("dyno_type", "hobby"),
            )
            for type in services
        ]
    }
    app._h._http_resource(
        method="PATCH",
        resource=("apps", app.id, "formation"),
        data=app._h._resource_serialize(payload),
    )

    print("Launching experiment")
    app_url = f"https://{app_hostname}"
    launch_data = _handle_launch_data(f"{app_url}/launch", print)
    print(launch_data.get("recruitment_msg"))

    print(
        f"You can login to {app_url}/dashboard using this password {dashboard_password} and the username 'admin'"
    )


def _deploy_in_mode(mode, verbose, log, app=None):
    if app:
        verify_id(None, None, app)

    log(header, chevrons=False)
    config = get_config()
    config.load()
    config.extend({"mode": mode, "logfile": "-"})

    deploy_heroku_docker(log=log, verbose=verbose, app=app)


def deploy_heroku_docker(log, verbose=True, app=None, exp_config=None):
    from dallinger.docker.tools import build_image

    config = get_config()
    config.load()
    if not config.ready:
        config.load()
    (heroku_app_id, tmp) = setup_experiment(
        log, debug=False, app=app, exp_config=exp_config, local_checks=False
    )
    # Register the experiment using all configured registration services.
    if config.get("mode") == "live":
        log("Registering the experiment on configured services...")
        registration.register(heroku_app_id, snapshot=None)

    # Build experiment image
    build_image(tmp, Path(os.getcwd()).name, Output(), force_build=True)

    # Push the built image to get the registry sha256
    pushed_image = push.callback(use_existing=True)

    # Persist the built image sha256 into the experiment
    add_image_name(LOCAL_CONFIG, pushed_image)

    # Log in to Heroku if we aren't already.
    log("Making sure that you are logged in to Heroku.")
    heroku.log_in()
    log("Making sure that you are logged in to Heroku container registry.")
    heroku.container_log_in()
    config.set("heroku_auth_token", heroku.auth_token())
    log("", chevrons=False)
    services = ["web", "worker"]
    if config.get("clock_on"):
        services.append("clock")
    for service in services:
        text = f"""FROM {pushed_image}
        CMD dallinger_heroku_{service}
        """
        (Path(tmp) / f"Dockerfile.{service}").write_text(text)

    # Change to temporary directory.
    cwd = os.getcwd()
    os.chdir(tmp)

    out = None if verbose else open(os.devnull, "w")
    team = config.get("heroku_team", None)
    heroku_app = HerokuApp(dallinger_uid=heroku_app_id, output=out, team=team)
    heroku_app.bootstrap(buildpack=None)

    # Set up add-ons and AWS environment variables.
    database_size = config.get("database_size")
    redis_size = config.get("redis_size")
    addons = [
        "heroku-postgresql:{}".format(quote(database_size)),
        "heroku-redis:{}".format(quote(redis_size)),
        "papertrail",
    ]
    if config.get("sentry"):
        addons.append("sentry")

    for name in addons:
        heroku_app.addon(name)
    addons_t0 = datetime.now().astimezone().replace(microsecond=0)

    heroku_config = {
        "AWS_ACCESS_KEY_ID": config["aws_access_key_id"],
        "AWS_SECRET_ACCESS_KEY": config["aws_secret_access_key"],
        "AWS_DEFAULT_REGION": config["aws_region"],
        "auto_recruit": config["auto_recruit"],
        "smtp_username": config["smtp_username"],
        "smtp_password": config["smtp_password"],
        "whimsical": config["whimsical"],
        "dashboard_password": config["dashboard_password"],
        "FLASK_SECRET_KEY": codecs.encode(os.urandom(16), "hex").decode("ascii"),
    }

    # Set up the preferred class as an environment variable, if one is set
    # This is needed before the config is parsed, but we also store it in the
    # config to make things easier for recording into bundles.
    preferred_class = config.get("EXPERIMENT_CLASS_NAME", None)
    if preferred_class:
        heroku_config["EXPERIMENT_CLASS_NAME"] = preferred_class

    heroku_app.set_multiple(**heroku_config)

    # While the addons start up we push the containers
    heroku_app.push_containers()
    heroku_app.release_containers()

    log("Scaling up the dynos...")
    default_size = config.get("dyno_type")
    for service in services:
        size = config.get("dyno_type_" + service, default_size)
        qty = config.get("num_dynos_" + service, 1)
        heroku_app.scale_up_dyno(service, qty, size)

    log("Waiting for addons to be ready...")
    ready = False
    addons_text = previous_addons_text = ""
    while not ready:
        addons_text = heroku_app._result(heroku_addons_cmd(heroku_app.name)).strip()
        log("\033[F" * (len(previous_addons_text.split("\n")) + 2), chevrons=False)
        log(addons_text, chevrons=False)
        log(
            f"Total time waiting for addons to be ready: {datetime.now().astimezone().replace(microsecond=0) - addons_t0}",
            chevrons=False,
        )
        previous_addons_text = addons_text
        if "creating" not in addons_text:
            ready = True
        else:
            time.sleep(2)

    # Launch the experiment.
    log("Launching the experiment on the remote server and starting recruitment...")
    launch_url = "{}/launch".format(heroku_app.url)
    log("Calling {}".format(launch_url), chevrons=False)
    launch_data = _handle_launch_data(launch_url, error=log)
    result = {
        "app_name": heroku_app.name,
        "app_home": heroku_app.url,
        "dashboard_url": "{}/dashboard/".format(heroku_app.url),
        "recruitment_msg": launch_data.get("recruitment_msg", None),
    }

    log("Experiment details:")
    log("App home: {}".format(result["app_home"]), chevrons=False)
    log("Dashboard URL: {}".format(result["dashboard_url"]), chevrons=False)
    log("Dashboard user: {}".format(config.get("dashboard_user")), chevrons=False)
    log(
        "Dashboard password: {}".format(config.get("dashboard_password")),
        chevrons=False,
    )

    log("Recruiter info:")
    log(result["recruitment_msg"], chevrons=False)

    # Return to the branch whence we came.
    os.chdir(cwd)

    log(
        "Completed Heroku deployment of experiment ID {} using app ID {}.".format(
            config.get("id"), heroku_app_id
        )
    )

    result = {
        "app_name": heroku_app.name,
        "app_home": heroku_app.url,
        "dashboard_url": "{}/dashboard/".format(heroku_app.url),
        # "recruitment_msg": launch_data.get("recruitment_msg", None),
    }
    return result


def add_image_name(config_path: str, image_name: str):
    """Alters the text file at `config_path` to set the contents
    of the variable `docker_image_name` to the passed `image_name`.
    If a line is already present it will be replaced.
    If it's not it will be added next to the line with the `docker_image_base_name` variable.
    """
    config = Path(config_path)
    new_line = f"docker_image_name = {image_name}"
    old_text = config.read_text()
    if re.search("^docker_image_name =", old_text, re.M):
        text = re.sub("docker_image_name = .*", new_line, old_text)
    elif re.search("^docker_image_base_name =", old_text, re.M):
        text = re.sub("(docker_image_base_name = .*)", r"\g<1>\n" + new_line, old_text)
    else:
        text = "".join((old_text, "\n" + new_line))

    config.write_text(text)


def heroku_addons_cmd(app_name):
    """Return a list suitable for invoking `heroku addons` that (if possible)
    has colorful output.

    If the `script` binary is available, use it to run the heroku CLI, so that
    it detects a terminal and emits colorful output.
    """
    return script_command(["heroku", "addons", "-a", app_name])


def script_command(cmd):
    return cmd


def script_command_linux(cmd):
    return ["script", "-q", "--command", " ".join(cmd), "/dev/null"]


def script_command_mac(cmd):
    return ["script", "-q", "/dev/null"] + cmd


for alternative in (script_command_linux, script_command_mac):
    try:
        if (
            subprocess.check_output(
                alternative(["echo", "success"]),
                stderr=subprocess.PIPE,
                stdin=None,
                timeout=0.1,
            ).strip()
            == b"success"
        ):
            script_command = alternative  # noqa
            break
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pass
