import click
import codecs
import os
import subprocess
import time

from datetime import datetime
from pathlib import Path
from shlex import quote

from dallinger import heroku
from dallinger import registration
from dallinger.config import get_config
from dallinger.heroku.tools import HerokuApp
from dallinger.command_line.utils import Output
from dallinger.command_line.utils import header
from dallinger.command_line.utils import log
from dallinger.command_line.utils import require_exp_directory
from dallinger.command_line.utils import verify_id
from dallinger.deployment import _handle_launch_data
from dallinger.utils import setup_experiment


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
def push():
    """Build a docker image for this experiment and push it."""
    from dallinger.docker.tools import build_image
    from docker import client

    config = get_config()
    config.load()
    _, tmp = setup_experiment(log=log, debug=True, local_checks=False)
    docker_client = client.from_env()
    image_base_name = config.get("image_base_name")
    image_name_with_tag = build_image(tmp, image_base_name, Output())
    for line in docker_client.images.push(image_base_name, stream=True, decode=True):
        if "status" in line:
            print(line["status"], end="")
            print(line.get("progress", ""))
        if "error" in line:
            print(line.get("error", "") + "\n")
            if "unauthenticated" in line["error"]:
                registry_name = image_base_name.split("/")[0]
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


def _deploy_in_mode(mode, verbose, log, app=None):
    if app:
        verify_id(None, None, app)

    log(header, chevrons=False)
    prelaunch = []
    config = get_config()
    config.load()
    config.extend({"mode": mode, "logfile": "-"})

    deploy_heroku_docker(log=log, verbose=verbose, app=app, prelaunch_actions=prelaunch)


def deploy_heroku_docker(
    log, verbose=True, app=None, exp_config=None, prelaunch_actions=None
):
    from dallinger.docker.tools import build_image

    config = get_config()
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
    base_image_name = build_image(tmp, Path(os.getcwd()).name, Output())

    # Log in to Heroku if we aren't already.
    log("Making sure that you are logged in to Heroku.")
    heroku.log_in()
    log("Making sure that you are logged in to Heroku container registry.")
    heroku.container_log_in()
    config.set("heroku_auth_token", heroku.auth_token())
    log("", chevrons=False)
    for service in ["web", "worker"]:
        text = f"""FROM {base_image_name}
        COPY . /experiment/
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
        "aws_access_key_id": config["aws_access_key_id"],
        "aws_secret_access_key": config["aws_secret_access_key"],
        "aws_region": config["aws_region"],
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
    for process in ["web", "worker"]:
        size = config.get("dyno_type_" + process, default_size)
        qty = config.get("num_dynos_" + process)
        heroku_app.scale_up_dyno(process, qty, size)

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
    return ["script", "-q", "--command", " ".join(cmd)]


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
