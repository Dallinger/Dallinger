import click
import codecs
import redis
import os
import time

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
from dallinger.docker.tools import build_image
from dallinger.utils import setup_experiment
from dallinger.redis_utils import connect_to_redis


@click.group()
def docker():
    """Use docker for local debug and deployment."""


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
    if verbose:
        out = None
    else:
        out = open(os.devnull, "w")
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

    team = config.get("heroku_team", None)
    heroku_app = HerokuApp(dallinger_uid=heroku_app_id, output=out, team=team)
    heroku_app.bootstrap(buildpack=None)
    heroku_app.push_containers()

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

    heroku_config = {
        "aws_access_key_id": config["aws_access_key_id"],
        "aws_secret_access_key": config["aws_secret_access_key"],
        "aws_region": config["aws_region"],
        "auto_recruit": config["auto_recruit"],
        "smtp_username": config["smtp_username"],
        "smtp_password": config["smtp_password"],
        "whimsical": config["whimsical"],
        "FLASK_SECRET_KEY": codecs.encode(os.urandom(16), "hex").decode("ascii"),
    }

    # Set up the preferred class as an environment variable, if one is set
    # This is needed before the config is parsed, but we also store it in the
    # config to make things easier for recording into bundles.
    preferred_class = config.get("EXPERIMENT_CLASS_NAME", None)
    if preferred_class:
        heroku_config["EXPERIMENT_CLASS_NAME"] = preferred_class

    heroku_app.set_multiple(**heroku_config)

    # Wait for Redis database to be ready.
    log("Waiting for Redis (this can take a couple minutes)...", nl=False)
    ready = False
    while not ready:
        try:
            r = connect_to_redis(url=heroku_app.redis_url)
            r.set("foo", "bar")
            ready = True
            log("\n✓ connected at {}".format(heroku_app.redis_url), chevrons=False)
        except (ValueError, redis.exceptions.ConnectionError):
            time.sleep(2)
            log(".", chevrons=False, nl=False)

    # WIP Incomplete

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

    # Return to the branch whence we came.
    os.chdir(cwd)

    log(
        "Completed Heroku deployment of experiment ID {} using app ID {}.".format(
            config.get("id"), heroku_app_id
        )
    )
    # launch_data = _handle_launch_data(launch_url, error=log)

    result = {
        "app_name": heroku_app.name,
        "app_home": heroku_app.url,
        "dashboard_url": "{}/dashboard/".format(heroku_app.url),
        # "recruitment_msg": launch_data.get("recruitment_msg", None),
    }
    return result
