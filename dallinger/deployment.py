import os
import pkg_resources
import re
import redis
import requests
import shutil
import six
import tempfile
import threading
import time
import webbrowser
from six.moves import shlex_quote as quote

from dallinger import data
from dallinger import db
from dallinger import heroku
from dallinger import recruiters
from dallinger import registration
from dallinger.compat import is_command
from dallinger.config import get_config
from dallinger.heroku.tools import HerokuApp
from dallinger.heroku.tools import HerokuLocalWrapper
from dallinger.utils import ensure_directory
from dallinger.utils import get_base_url
from dallinger.utils import GitClient


def new_webbrowser_profile():
    if is_command('google-chrome'):
        new_chrome = webbrowser.Chrome()
        new_chrome.name = 'google-chrome'
        profile_directory = tempfile.mkdtemp()
        new_chrome.remote_args = webbrowser.Chrome.remote_args + [
            '--user-data-dir="{}"'.format(profile_directory)
        ]
        return new_chrome
    elif is_command('firefox'):
        new_firefox = webbrowser.Mozilla()
        new_firefox.name = 'firefox'
        profile_directory = tempfile.mkdtemp()
        new_firefox.remote_args = [
            '-profile', profile_directory, '-new-instance', '-no-remote', '-url', '%s',
        ]
        return new_firefox
    else:
        return webbrowser


def setup_experiment(log, debug=True, verbose=False, app=None, exp_config=None):
    """Check the app and, if compatible with Dallinger, freeze its state."""
    # Verify that the Postgres server is running.
    try:
        db.check_connection()
    except Exception:
        log("There was a problem connecting to the Postgres database!")
        raise

    # Load configuration.
    config = get_config()
    if not config.ready:
        config.load()

    # Check that the demo-specific requirements are satisfied.
    try:
        with open("requirements.txt", "r") as f:
            dependencies = [r for r in f.readlines() if r[:3] != "-e "]
    except (OSError, IOError):
        dependencies = []

    pkg_resources.require(dependencies)

    # Generate a unique id for this experiment.
    from dallinger.experiment import Experiment
    generated_uid = public_id = Experiment.make_uuid(app)

    # If the user provided an app name, use it everywhere that's user-facing.
    if app:
        public_id = str(app)

    log("Experiment id is " + public_id + "")

    # Copy this directory into a temporary folder, ignoring .git
    dst = os.path.join(tempfile.mkdtemp(), public_id)
    to_ignore = shutil.ignore_patterns(
        os.path.join(".git", "*"),
        "*.db",
        "snapshots",
        "data",
        "server.log",
    )
    shutil.copytree(os.getcwd(), dst, ignore=to_ignore)

    log(dst, chevrons=False)

    # Save the experiment id
    with open(os.path.join(dst, "experiment_id.txt"), "w") as file:
        file.write(generated_uid)

    # Change directory to the temporary folder.
    cwd = os.getcwd()
    os.chdir(dst)

    # Write the custom config
    if exp_config:
        config.extend(exp_config)

    config.extend({'id': six.text_type(generated_uid)})

    config.write(filter_sensitive=True)

    # Zip up the temporary directory and place it in the cwd.
    if not debug:
        log("Freezing the experiment package...")
        shutil.make_archive(
            os.path.join(cwd, "snapshots", public_id + "-code"), "zip", dst)

    # Check directories.
    ensure_directory(os.path.join("static", "scripts"))
    ensure_directory(os.path.join("templates", "default"))
    ensure_directory(os.path.join("static", "css"))

    # Get dallinger package location.
    from pkg_resources import get_distribution
    dist = get_distribution('dallinger')
    src_base = os.path.join(dist.location, dist.project_name)

    heroku_files = [
        "Procfile",
        "runtime.txt",
    ]

    for filename in heroku_files:
        src = os.path.join(src_base, "heroku", filename)
        shutil.copy(src, os.path.join(dst, filename))

    clock_on = config.get('clock_on', False)

    # If the clock process has been disabled, overwrite the Procfile.
    if not clock_on:
        src = os.path.join(src_base, "heroku", "Procfile_no_clock")
        shutil.copy(src, os.path.join(dst, "Procfile"))

    frontend_files = [
        os.path.join("static", "css", "dallinger.css"),
        os.path.join("static", "scripts", "dallinger2.js"),
        os.path.join("static", "scripts", "reqwest.min.js"),
        os.path.join("static", "scripts", "require.js"),
        os.path.join("static", "scripts", "reconnecting-websocket.js"),
        os.path.join("static", "scripts", "spin.min.js"),
        os.path.join("static", "scripts", "tracker.js"),
        os.path.join("static", "scripts", "store+json2.min.js"),
        os.path.join("templates", "error.html"),
        os.path.join("templates", "error-complete.html"),
        os.path.join("templates", "launch.html"),
        os.path.join("templates", "complete.html"),
        os.path.join("templates", "questionnaire.html"),
        os.path.join("templates", "thanks.html"),
        os.path.join("templates", "waiting.html"),
        os.path.join("static", "robots.txt")
    ]
    frontend_dirs = [
        os.path.join("templates", "base"),
    ]

    for filename in frontend_files:
        src = os.path.join(src_base, "frontend", filename)
        dst_filepath = os.path.join(dst, filename)
        if not os.path.exists(dst_filepath):
            shutil.copy(src, dst_filepath)
    for filename in frontend_dirs:
        src = os.path.join(src_base, "frontend", filename)
        dst_filepath = os.path.join(dst, filename)
        if not os.path.exists(dst_filepath):
            shutil.copytree(src, dst_filepath)

    time.sleep(0.25)

    os.chdir(cwd)

    return (public_id, dst)


INITIAL_DELAY = 5
RETRIES = 4


def _handle_launch_data(url, error, delay=INITIAL_DELAY, remaining=RETRIES):
    time.sleep(delay)
    remaining = remaining - 1
    launch_request = requests.post(url)
    try:
        launch_data = launch_request.json()
    except ValueError:
        error(
            "Error parsing response from /launch, check web dyno logs for details: "
            + launch_request.text
        )
        raise

    if not launch_request.ok:
        if remaining < 1:
            error('Experiment launch failed, check web dyno logs for details.')
            if launch_data.get('message'):
                error(launch_data['message'])
            launch_request.raise_for_status()
        delay = 2 * delay
        error('Experiment launch failed, retrying in {} seconds ...'.format(delay))
        return _handle_launch_data(url, error, delay, remaining)

    return launch_data


def deploy_sandbox_shared_setup(log, verbose=True, app=None, exp_config=None):
    """Set up Git, push to Heroku, and launch the app."""
    if verbose:
        out = None
    else:
        out = open(os.devnull, 'w')

    config = get_config()
    if not config.ready:
        config.load()
    heroku.sanity_check(config)

    (id, tmp) = setup_experiment(log, debug=False, app=app, exp_config=exp_config)

    # Register the experiment using all configured registration services.
    if config.get("mode") == "live":
        log("Registering the experiment on configured services...")
        registration.register(id, snapshot=None)

    # Log in to Heroku if we aren't already.
    log("Making sure that you are logged in to Heroku.")
    heroku.log_in()
    config.set("heroku_auth_token", heroku.auth_token())
    log("", chevrons=False)

    # Change to temporary directory.
    cwd = os.getcwd()
    os.chdir(tmp)

    # Commit Heroku-specific files to tmp folder's git repo.
    git = GitClient(output=out)
    git.init()
    git.add("--all")
    git.commit('"Experiment {}"'.format(id))

    # Initialize the app on Heroku.
    log("Initializing app on Heroku...")
    team = config.get("heroku_team", '').strip() or None
    heroku_app = HerokuApp(dallinger_uid=id, output=out, team=team)
    heroku_app.bootstrap()
    heroku_app.buildpack("https://github.com/stomita/heroku-buildpack-phantomjs")

    # Set up add-ons and AWS environment variables.
    database_size = config.get('database_size')
    redis_size = config.get('redis_size', 'premium-0')
    addons = [
        "heroku-postgresql:{}".format(quote(database_size)),
        "heroku-redis:{}".format(quote(redis_size)),
        "papertrail"
    ]
    if config.get("sentry", False):
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
    }

    heroku_app.set_multiple(**heroku_config)

    # Wait for Redis database to be ready.
    log("Waiting for Redis...")
    ready = False
    while not ready:
        r = redis.from_url(heroku_app.redis_url)
        try:
            r.set("foo", "bar")
            ready = True
        except redis.exceptions.ConnectionError:
            time.sleep(2)

    log("Saving the URL of the postgres database...")
    # Set the notification URL and database URL in the config file.
    config.extend({
        "notification_url": heroku_app.url + "/notifications",
        "database_url": heroku_app.db_url,
    })
    config.write()
    git.add("config.txt")
    time.sleep(0.25)
    git.commit("Save URLs for database and notifications")
    time.sleep(0.25)

    # Launch the Heroku app.
    log("Pushing code to Heroku...")
    git.push(remote="heroku", branch="HEAD:master")

    log("Scaling up the dynos...")
    size = config.get("dyno_type")
    for process in ["web", "worker"]:
        qty = config.get("num_dynos_" + process)
        heroku_app.scale_up_dyno(process, qty, size)
    if config.get("clock_on"):
        heroku_app.scale_up_dyno("clock", 1, size)

    time.sleep(8)

    # Launch the experiment.
    log("Launching the experiment on the remote server and starting recruitment...")
    launch_data = _handle_launch_data('{}/launch'.format(heroku_app.url), error=log)
    result = {
        'app_name': heroku_app.name,
        'app_home': heroku_app.url,
        'recruitment_msg': launch_data.get('recruitment_msg', None),
    }
    log("Experiment details:")
    log("App home: {}".format(result['app_home']), chevrons=False)
    log("Recruiter info:")
    log(result['recruitment_msg'], chevrons=False)

    # Return to the branch whence we came.
    os.chdir(cwd)

    log("Completed deployment of experiment " + id + ".")
    return result


def _deploy_in_mode(mode, app, verbose, log):
    # Load configuration.
    config = get_config()
    config.load()

    # Set the mode.
    config.extend({
        "mode": mode,
        "logfile": u"-",
    })

    # Do shared setup.
    deploy_sandbox_shared_setup(log, verbose=verbose, app=app)


class HerokuLocalDeployment(object):

    exp_id = None
    tmp_dir = None
    dispatch = {}  # Subclass may provide handlers for Heroku process output

    def configure(self):
        self.exp_config.update({
            "mode": u"debug",
            "loglevel": 0,
        })

    def setup(self):
        self.exp_id, self.tmp_dir = setup_experiment(
            self.out.log, exp_config=self.exp_config
        )

    def update_dir(self):
        os.chdir(self.tmp_dir)
        # Update the logfile to the new directory
        config = get_config()
        logfile = config.get('logfile')
        if logfile and logfile != '-':
            logfile = os.path.join(self.original_dir, logfile)
            config.extend({'logfile': logfile})
            config.write()

    def run(self):
        """Set up the environment, get a HerokuLocalWrapper instance, and pass
        it to the concrete class's execute() method.
        """
        self.configure()
        self.setup()
        self.update_dir()
        db.init_db(drop_all=True)
        self.out.log("Starting up the server...")
        config = get_config()
        with HerokuLocalWrapper(config, self.out, verbose=self.verbose) as wrapper:
            try:
                self.execute(wrapper)
            except KeyboardInterrupt:
                pass
            finally:
                os.chdir(self.original_dir)
                self.cleanup()

    def notify(self, message):
        """Callback function which checks lines of output, tries to match
        against regex defined in subclass's "dispatch" dict, and passes through
        to a handler on match.
        """
        for regex, handler in self.dispatch.items():
            match = re.search(regex, message)
            if match:
                handler = getattr(self, handler)
                return handler(match)

    def execute(self, heroku):
        raise NotImplementedError()


class DebugDeployment(HerokuLocalDeployment):

    dispatch = {
        r'[^\"]{} (.*)$'.format(recruiters.NEW_RECRUIT_LOG_PREFIX): 'new_recruit',
        r'{}'.format(recruiters.CLOSE_RECRUITMENT_LOG_PREFIX): 'recruitment_closed',
    }

    def __init__(self, output, verbose, bot, proxy_port, exp_config):
        self.out = output
        self.verbose = verbose
        self.bot = bot
        self.exp_config = exp_config or {}
        self.proxy_port = proxy_port
        self.original_dir = os.getcwd()
        self.complete = False
        self.status_thread = None

    def configure(self):
        super(DebugDeployment, self).configure()
        if self.bot:
            self.exp_config["recruiter"] = "bots"

    def execute(self, heroku):
        base_url = get_base_url()
        self.out.log("Server is running on {}. Press Ctrl+C to exit.".format(base_url))
        self.out.log("Launching the experiment...")
        time.sleep(4)
        try:
            result = _handle_launch_data('{}/launch'.format(base_url), error=self.out.error)
        except Exception:
            # Show output from server
            self.dispatch[r'POST /launch'] = 'launch_request_complete'
            heroku.monitor(listener=self.notify)
        else:
            if result['status'] == 'success':
                self.out.log(result['recruitment_msg'])
                self.heroku = heroku
                heroku.monitor(listener=self.notify)

    def launch_request_complete(self, match):
        return HerokuLocalWrapper.MONITOR_STOP

    def cleanup(self):
        self.out.log("Completed debugging of experiment with id " + self.exp_id)
        self.complete = True

    def new_recruit(self, match):
        """Dispatched to by notify(). If a recruitment request has been issued,
        open a browser window for the a new participant (in this case the
        person doing local debugging).
        """
        self.out.log("new recruitment request!")
        url = match.group(1)
        if self.proxy_port is not None:
            self.out.log("Using proxy port {}".format(self.proxy_port))
            url = url.replace(str(get_config().get('base_port')), self.proxy_port)
        new_webbrowser_profile().open(url, new=1, autoraise=True)

    def recruitment_closed(self, match):
        """Recruitment is closed.

        Start a thread to check the experiment summary.
        """
        if self.status_thread is None:
            self.status_thread = threading.Thread(target=self.check_status)
            self.status_thread.start()

    def check_status(self):
        """Check the output of the summary route until
        the experiment is complete, then we can stop monitoring Heroku
        subprocess output.
        """
        self.out.log("Recruitment is complete. Waiting for experiment completion...")
        base_url = get_base_url()
        status_url = base_url + '/summary'
        while not self.complete:
            time.sleep(10)
            try:
                resp = requests.get(status_url)
                exp_data = resp.json()
            except (ValueError, requests.exceptions.RequestException):
                self.out.error('Error fetching experiment status.')
            else:
                self.out.log('Experiment summary: {}'.format(exp_data))
                if exp_data.get('completed', False):
                    self.out.log('Experiment completed, all nodes filled.')
                    self.complete = True
                    self.heroku.stop()

    def notify(self, message):
        """Monitor output from heroku process.

        This overrides the base class's `notify`
        to make sure that we stop if the status-monitoring thread
        has determined that the experiment is complete.
        """
        if self.complete:
            return HerokuLocalWrapper.MONITOR_STOP
        return super(DebugDeployment, self).notify(message)


class LoaderDeployment(HerokuLocalDeployment):
    dispatch = {
        'Replay ready: (.*)$': 'start_replay',
    }

    def __init__(self, app_id, output, verbose, exp_config):
        self.app_id = app_id
        self.out = output
        self.verbose = verbose
        self.exp_config = exp_config or {}
        self.original_dir = os.getcwd()
        self.zip_path = None

    def configure(self):
        self.exp_config.update({
            "mode": u"debug",
            "loglevel": 0,
        })

        self.zip_path = data.find_experiment_export(self.app_id)
        if self.zip_path is None:
            msg = 'Dataset export for app id "{}" could not be found.'
            raise IOError(msg.format(self.app_id))

    def setup(self):
        self.exp_id, self.tmp_dir = setup_experiment(
            self.out.log, app=self.app_id, exp_config=self.exp_config
        )

    def execute(self, heroku):
        """Start the server, load the zip file into the database, then loop
        until terminated with <control>-c.
        """
        db.init_db(drop_all=True)
        self.out.log("Ingesting dataset from {}...".format(os.path.basename(self.zip_path)))
        data.ingest_zip(self.zip_path)
        base_url = get_base_url()
        self.out.log("Server is running on {}. Press Ctrl+C to exit.".format(base_url))

        if self.exp_config.get('replay', False):
            self.out.log("Launching the experiment...")
            time.sleep(4)
            _handle_launch_data('{}/launch'.format(base_url), error=self.out.error)
            heroku.monitor(listener=self.notify)

        # Just run until interrupted:
        while(self.keep_running()):
            time.sleep(1)

    def start_replay(self, match):
        """Dispatched to by notify(). If a recruitment request has been issued,
        open a browser window for the a new participant (in this case the
        person doing local debugging).
        """
        self.out.log("replay ready!")
        url = match.group(1)
        new_webbrowser_profile().open(url, new=1, autoraise=True)

    def cleanup(self):
        self.out.log("Terminating dataset load for experiment {}".format(self.exp_id))

    def keep_running(self):
        # This is a separate method so that it can be replaced in tests
        return True
