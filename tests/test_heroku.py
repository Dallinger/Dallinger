import datetime
import os
import signal
import sys
import threading
import time
from unittest import mock

import pytest
import redis

from dallinger.config import get_config
from dallinger.heroku.tools import HerokuTimeoutError


@pytest.fixture
def run_check(active_config):
    from dallinger.heroku.clock import run_check

    yield run_check


@pytest.fixture
def check_call():
    with mock.patch("dallinger.heroku.tools.check_call") as check_call:
        yield check_call


@pytest.fixture
def check_output():
    with mock.patch("dallinger.heroku.tools.check_output") as check_output:
        yield check_output


class TestClockScheduler:
    @pytest.fixture
    def setup(self):
        """Set up the environment by moving to the demos directory."""
        root_dir = os.path.dirname(__file__)
        os.chdir(f"{root_dir}/experiment")
        config = get_config()
        config.ready = False
        from dallinger.heroku import clock

        self.clock = clock

    @pytest.fixture
    def patched_scheduler(self, setup):
        from dallinger import heroku

        with mock.patch("apscheduler.schedulers.blocking.BlockingScheduler.start"):
            yield heroku.clock.scheduler

    @pytest.fixture
    def patched_wait_for_redis(self, setup):
        with mock.patch("dallinger.heroku.clock.wait_for_redis_ready") as patched:
            yield patched

    def teardown(self):
        os.chdir("../..")

    def test_scheduler_has_job(self, setup):
        assert len(self.clock.scheduler.get_jobs()) > 0

    def test_launch_loads_config(self, patched_scheduler, patched_wait_for_redis):
        self.clock.launch()
        patched_wait_for_redis.assert_called_once_with()
        patched_scheduler.start.assert_called_once()
        assert get_config().ready

    def test_launch_registers_additional_tasks(
        self, patched_scheduler, patched_wait_for_redis, tasks_with_cleanup
    ):
        tasks_with_cleanup.append(
            {
                "func_name": "test_task",
                "trigger": "interval",
                "kwargs": (("minutes", 5),),
            }
        )

        self.clock.launch()
        patched_wait_for_redis.assert_called_once_with()
        jobs = patched_scheduler.get_jobs()
        func_names = [job.func_ref for job in jobs]

        assert (
            "dallinger_experiment.dallinger_experiment:TestExperiment.test_task"
            in func_names
        )

    def test_wait_for_redis_ready_returns_when_ping_succeeds(self, setup):
        mock_redis = mock.Mock()

        with mock.patch.object(self.clock.db, "redis_conn", mock_redis):
            self.clock.wait_for_redis_ready(timeout=1, interval=0)

        mock_redis.ping.assert_called_once_with()

    def test_wait_for_redis_ready_retries_busy_loading(self, setup):
        mock_redis = mock.Mock()
        mock_redis.ping.side_effect = [
            redis.exceptions.BusyLoadingError("loading"),
            True,
        ]

        with (
            mock.patch.object(self.clock.db, "redis_conn", mock_redis),
            mock.patch("dallinger.heroku.clock.time.sleep") as sleep,
        ):
            self.clock.wait_for_redis_ready(timeout=1, interval=0.1)

        assert mock_redis.ping.call_count == 2
        sleep.assert_called_once_with(0.1)

    def test_wait_for_redis_ready_times_out(self, setup):
        mock_redis = mock.Mock()
        mock_redis.ping.side_effect = redis.exceptions.ConnectionError("down")

        with (
            mock.patch.object(self.clock.db, "redis_conn", mock_redis),
            mock.patch(
                "dallinger.heroku.clock.time.monotonic",
                side_effect=[0, 0, 2],
            ),
            mock.patch("dallinger.heroku.clock.time.sleep"),
        ):
            with pytest.raises(RuntimeError, match="Redis did not become ready"):
                self.clock.wait_for_redis_ready(timeout=1, interval=0.1)


@pytest.mark.usefixtures("experiment_dir", "active_config")
class TestHerokuClockTasks:
    @pytest.fixture
    def recruiters(self):
        with mock.patch("dallinger.heroku.clock.recruiters") as mock_recruiters:
            yield mock_recruiters

    def test_check_db_for_missing_notifications_assembles_resources(self, run_check):
        # Can't import until after config is loaded:
        from dallinger.heroku.clock import check_db_for_missing_notifications

        with mock.patch("dallinger.heroku.clock.run_check") as check:
            check_db_for_missing_notifications()

            check.assert_called()

    def test_does_nothing_if_assignment_still_current(
        self, a, active_config, run_check, recruiters
    ):
        participants = [a.participant()]
        reference_time = datetime.datetime.now()
        run_check(participants, active_config, reference_time)

        recruiters.by_name.assert_not_called()

    def test_reports_late_participants_to_their_recruiter(
        self, a, active_config, run_check, recruiters
    ):
        participants = [a.participant()]
        five_minutes_over = 60 * active_config.get("duration") + 5
        reference_time = datetime.datetime.now() + datetime.timedelta(
            minutes=five_minutes_over
        )

        run_check(participants, active_config, reference_time)

        recruiters.by_name.assert_called_once_with(participants[0].recruiter_id)


class TestHerokuUtilFunctions:
    @pytest.fixture
    def heroku(self):
        from dallinger.heroku import tools

        return tools

    def test_app_name(self, heroku):
        dallinger_uid = "8fbe62f5-2e33-4274-8aeb-40fc3dd621a0"
        assert heroku.app_name(dallinger_uid) == "dlgr-8fbe62f5-2e33-4274"

    def test_auth_token(self, heroku, check_output):
        check_output.return_value = b"some response "
        assert heroku.auth_token() == "some response"

    def test_log_in_ok(self, heroku, check_output):
        check_output.return_value = b"all good"
        heroku.log_in()

    def test_log_in_fails(self, heroku, check_output):
        check_output.side_effect = Exception("boom!")
        with pytest.raises(Exception) as excinfo:
            heroku.log_in()
        assert excinfo.match("You are not logged into Heroku.")

    def test_sanity_check_raises_on_invalid_config_combo(self, heroku, stub_config):
        assert heroku.sanity_check(stub_config) is None
        stub_config.set("heroku_team", "my_team")
        stub_config.set("dyno_type", "free")
        with pytest.raises(RuntimeError) as excinfo:
            heroku.sanity_check(stub_config)
        assert excinfo.match("dyno type not compatible")

    def test_sanity_check_raises_on_invalid_web_dyno_combo(self, heroku, stub_config):
        assert heroku.sanity_check(stub_config) is None
        stub_config.set("heroku_team", "my_team")
        stub_config.set("dyno_type_web", "free")
        with pytest.raises(RuntimeError) as excinfo:
            heroku.sanity_check(stub_config)
        assert excinfo.match("dyno type not compatible")

    def test_sanity_check_raises_on_invalid_worker_dyno_combo(
        self, heroku, stub_config
    ):
        assert heroku.sanity_check(stub_config) is None
        stub_config.set("heroku_team", "my_team")
        stub_config.set("dyno_type_worker", "free")
        with pytest.raises(RuntimeError) as excinfo:
            heroku.sanity_check(stub_config)
        assert excinfo.match("dyno type not compatible")

    def test_sanity_check_ok_when_optional_keys_absent(self, heroku, stub_config):
        del stub_config.data[0]["heroku_team"]
        assert heroku.sanity_check(stub_config) is None

    def test_request_headers(self, heroku):
        headers = heroku.request_headers("fake-token")
        assert headers["Authorization"] == "Bearer fake-token"


@pytest.mark.usefixtures("patch_netrc")
class TestHerokuApp:
    @pytest.fixture
    def temp_repo(self, in_tempdir, stub_config):
        from dallinger.utils import GitClient

        stub_config.write()
        config = {"user.name": "Test User", "user.email": "test@example.com"}
        git = GitClient()
        git.init(config=config)
        git.add("--all")
        git.commit("Test Repo")

    @pytest.fixture
    def full_app(self):
        from dallinger.heroku.tools import HerokuApp

        the_app = HerokuApp(dallinger_uid="fake-uid", output=None, team=None)
        yield the_app
        the_app.destroy()

    @pytest.fixture
    def app(self):
        from dallinger.heroku.tools import HerokuApp

        with mock.patch("dallinger.heroku.tools.subprocess"):
            the_app = HerokuApp(dallinger_uid="fake-uid", output=None, team="fake team")
            yield the_app

    def test_name(self, app):
        assert app.name == "dlgr-fake-uid"

    def test_url(self, app, check_call, check_output):
        check_output.return_value = (
            '{"app": {"web_url": "https://dlgr-fake-uid.herokuapp.com"}}'
        )
        assert app.url == "https://dlgr-fake-uid.herokuapp.com"
        check_output.assert_called_once_with(
            [
                "heroku",
                "apps:info",
                "--app",
                app.name,
                "--json",
            ]
        )

    def test_config_url(self, app):
        assert app.config_url == "https://api.heroku.com/apps/dlgr-fake-uid/config-vars"

    def test_dashboard_url(self, app):
        assert app.dashboard_url == "https://dashboard.heroku.com/apps/dlgr-fake-uid"

    def test_dashboard_metrics_url(self, app):
        assert (
            app.dashboard_metrics_url
            == "https://dashboard.heroku.com/apps/dlgr-fake-uid/metrics"
        )

    def test_bootstrap_creates_app_with_team(self, app, check_call, check_output):
        check_output.return_value = (
            '{"app": {"web_url": "https://dlgr-fake-uid.herokuapp.com"}}'
        )
        app.team = "some-team"
        app.bootstrap()
        check_call.assert_has_calls(
            [
                mock.call(
                    [
                        "heroku",
                        "apps:create",
                        "dlgr-fake-uid",
                        "--buildpack",
                        "heroku/python",
                        "--team",
                        "some-team",
                    ],
                    stdout=None,
                )
            ]
        )

    def test_bootstrap_sets_variables(self, app, check_call, check_output):
        check_output.return_value = (
            '{"app": {"web_url": "https://dlgr-fake-uid.herokuapp.com"}}'
        )
        app.team = "some-team"
        app.bootstrap()
        check_call.assert_called_with(
            [
                "heroku",
                "config:set",
                "CREATOR=test@example.com",
                "DALLINGER_UID=fake-uid",
                "HOST=https://dlgr-fake-uid.herokuapp.com",
                "--app",
                "dlgr-fake-uid",
            ],
            stdout=None,
        )

    def test_addon(self, app, check_call):
        app.addon("some-fake-addon")
        check_call.assert_called_once_with(
            ["heroku", "addons:create", "some-fake-addon", "--app", app.name],
            stdout=None,
        )

    def test_addon_destroy(self, app, check_call):
        app.addon_destroy("some-fake-addon")
        check_call.assert_called_once_with(
            [
                "heroku",
                "addons:destroy",
                "some-fake-addon",
                "--app",
                app.name,
                "--confirm",
                app.name,
            ],
            stdout=None,
        )

    def test_buildpack(self, app, check_call):
        app.buildpack("some-fake-buildpack")
        check_call.assert_called_once_with(
            ["heroku", "buildpacks:add", "some-fake-buildpack", "--app", app.name],
            stdout=None,
        )

    def test_clock_is_on_checks_psscale(self, app, check_output):
        app.clock_is_on
        check_output.assert_called_once_with(["heroku", "ps:scale", "--app", app.name])

    def test_clock_is_on_returns_true_if_clock_1(self, app, check_output):
        check_output.return_value = b"clock=1:Standard-2X console=0:Standard-1X"
        assert app.clock_is_on is True

    def test_clock_is_on_returns_false_if_clock_0(self, app, check_output):
        check_output.return_value = b"clock=0:Standard-2X console=0:Standard-1X"
        assert app.clock_is_on is False

    def test_clock_is_on_returns_false_if_no_clock(self, app, check_output):
        check_output.return_value = b"console=0:Standard-1X web=1:Standard-2X"
        assert app.clock_is_on is False

    def test_db_uri(self, app, check_output):
        check_output.return_value = b"blahblahpostgres://foobar"
        assert app.db_uri == "postgres://foobar"

    def test_db_uri_raises_if_no_match(self, app, check_output):
        check_output.return_value = "└─ as DATABASE on ⬢ dlgr-da089b8f app".encode(
            "utf8"
        )
        with pytest.raises(NameError) as excinfo:
            app.db_uri
            assert excinfo.match("Could not retrieve the DB URI")

    def test_db_url(self, app, check_output, check_call):
        check_output.return_value = b"some url    "
        assert app.db_url == "some url"
        check_call.assert_called_once_with(
            ["heroku", "pg:wait", "--app", app.name], stdout=None
        )

    def test_backup_capture(self, app, check_call):
        app.backup_capture()
        check_call.assert_called_once_with(
            ["heroku", "pg:backups:capture", "--app", app.name],
            stdout=None,
            stderr=None,
        )

    def test_backup_download(self, app, check_call):
        app.backup_download()
        check_call.assert_called_once_with(
            ["heroku", "pg:backups:download", "--app", app.name],
            stdout=None,
            stderr=None,
        )

    def test_destroy(self, app, check_output):
        check_output.return_value = b"some response message"
        assert app.destroy() == "some response message"
        check_output.assert_called_once_with(
            ["heroku", "apps:destroy", "--app", app.name, "--confirm", app.name]
        )

    def test_get(self, app, check_output):
        check_output.return_value = b"some value"
        assert app.get("some key") == "some value"
        check_output.assert_called_once_with(
            ["heroku", "config:get", "some key", "--app", app.name]
        )

    def test_open_logs(self, app, check_call):
        app.open_logs()
        check_call.assert_called_once_with(
            ["heroku", "addons:open", "papertrail", "--app", app.name], stdout=None
        )

    def test_pg_pull(self, app, check_call):
        app.pg_pull()
        check_call.assert_called_once_with(
            ["heroku", "pg:pull", "DATABASE_URL", app.name, "--app", app.name],
            stdout=None,
        )

    def test_pg_wait(self, app, check_call):
        app.pg_wait()
        check_call.assert_called_once_with(
            ["heroku", "pg:wait", "--app", app.name], stdout=None
        )

    def test_redis_url(self, app, check_output):
        check_output.return_value = b"some url"
        assert app.redis_url == "some url"
        check_output.assert_called_once_with(
            ["heroku", "config:get", "REDIS_URL", "--app", app.name]
        )

    def test_restore(self, app, check_call):
        app.restore("some url")
        check_call.assert_called_once_with(
            [
                "heroku",
                "pg:backups:restore",
                "some url",
                "DATABASE_URL",
                "--app",
                app.name,
                "--confirm",
                app.name,
            ],
            stdout=None,
        )

    def test_scale_up_dyno(self, app, check_call):
        app.scale_up_dyno("some process", quantity=1, size="free")
        check_call.assert_called_once_with(
            ["heroku", "ps:scale", "some process=1:free", "--app", app.name],
            stdout=None,
        )

    def test_scale_down_dyno(self, app, check_call):
        app.scale_down_dyno("some process")
        check_call.assert_called_once_with(
            ["heroku", "ps:scale", "some process=0", "--app", app.name], stdout=None
        )

    def test_scale_down_dynos_with_clock_off(self, app, check_call, check_output):
        check_output.return_value = b"[string indicating no clock process]"
        app.scale_down_dynos()
        check_call.assert_has_calls(
            [
                mock.call(
                    ["heroku", "ps:scale", "web=0", "--app", "dlgr-fake-uid"],
                    stdout=None,
                ),
                mock.call(
                    ["heroku", "ps:scale", "worker=0", "--app", "dlgr-fake-uid"],
                    stdout=None,
                ),
            ]
        )

    def test_scale_down_dynos_with_clock_on(self, app, check_call, check_output):
        check_output.return_value = b"clock=1 <= indicates clock is on"
        app.scale_down_dynos()
        check_call.assert_has_calls(
            [
                mock.call(
                    ["heroku", "ps:scale", "web=0", "--app", "dlgr-fake-uid"],
                    stdout=None,
                ),
                mock.call(
                    ["heroku", "ps:scale", "worker=0", "--app", "dlgr-fake-uid"],
                    stdout=None,
                ),
                mock.call(
                    ["heroku", "ps:scale", "clock=0", "--app", "dlgr-fake-uid"],
                    stdout=None,
                ),
            ]
        )

    def test_set(self, app, check_call):
        app.set("some key", "some value")
        check_call.assert_called_once_with(
            ["heroku", "config:set", "some key='some value'", "--app", app.name],
            stdout=None,
        )

    def test_set_multiple(self, app, check_call):
        app.set_multiple(key1="some value", key2="another value")
        check_call.assert_called_once_with(
            [
                "heroku",
                "config:set",
                "key1='some value'",
                "key2='another value'",
                "--app",
                app.name,
            ],
            stdout=None,
        )

    def test_set_called_with_nonsensitive_key_uses_stdoutput(self, app, check_call):
        app.set("some_nonsensitive_key", "some value")
        assert check_call.call_args_list[0][-1]["stdout"] is app.out

    def test_set_called_with_sensitive_key_suppresses_stdoutput(self, app, check_call):
        app.set("aws_secret_access_key", "some value")
        assert len(check_call.call_args_list) == 0

    @pytest.mark.usefixtures("check_heroku")
    def test_full_monty(self, full_app, temp_repo):
        app = full_app
        assert app.name == "dlgr-fake-uid"
        assert app.url == "https://dlgr-fake-uid.herokuapp.com"
        assert app.dashboard_url == "https://dashboard.heroku.com/apps/dlgr-fake-uid"
        app.bootstrap()
        app.buildpack("https://github.com/stomita/heroku-buildpack-phantomjs")
        app.set("auto_recruit", True)


@pytest.fixture
def wrapper():
    from dallinger.heroku.tools import HerokuLocalWrapper

    settings = {"base_port": 5000, "num_dynos_web": 1, "num_dynos_worker": 1}
    return HerokuLocalWrapper(
        mock.Mock(get=settings.get), mock.Mock(), env={"HOME": "/tmp"}
    )


def test_heroku_local_monitor_stops_when_output_ends(wrapper):
    import io

    wrapper._process = mock.Mock(stdout=io.BytesIO(b"web.1 | up\n"))
    wrapper._process.poll.return_value = 1
    listener = mock.Mock(return_value=None)

    stream = wrapper._stream()
    assert next(stream) == "web.1 | up\n"
    assert next(stream, None) is None

    wrapper._process.stdout = io.BytesIO(b"web.1 | up\n")
    wrapper.monitor(listener)

    listener.assert_called_once_with("web.1 | up\n")
    assert "exit code: 1" in wrapper.out.error.call_args.args[0]


def test_heroku_local_monitor_stops_iterating_when_told(wrapper):
    wrapper._stream = mock.Mock(return_value=["apple", "orange"])
    listener = mock.Mock(return_value=wrapper.MONITOR_STOP)
    wrapper.monitor(listener)
    listener.assert_called_once_with("apple")


def test_heroku_local_monitor_is_quiet_after_requested_stop(wrapper):
    import subprocess
    import threading

    wrapper._process = subprocess.Popen(
        [sys.executable, "-c", "import time; print('up', flush=True); time.sleep(30)"],
        stdout=subprocess.PIPE,
        start_new_session=True,
    )
    started = threading.Event()
    monitor = threading.Thread(
        target=wrapper.monitor, args=(lambda line: started.set(),)
    )
    monitor.start()
    assert started.wait(10)

    wrapper.stop()
    monitor.join(10)

    assert not monitor.is_alive()
    wrapper.out.error.assert_not_called()


def test_heroku_local_cancels_timeout_before_cleaning_up_a_failed_boot(wrapper):
    calls = []
    with (
        mock.patch("dallinger.heroku.tools.signal.signal"),
        mock.patch(
            "dallinger.heroku.tools.signal.alarm",
            side_effect=lambda secs: calls.append(("alarm", secs)),
        ),
        mock.patch.object(wrapper, "_boot", side_effect=OSError),
        mock.patch.object(wrapper, "stop", side_effect=lambda: calls.append("stop")),
        pytest.raises(OSError),
    ):
        wrapper.start(timeout_secs=12)

    assert calls[:3] == [("alarm", 12), ("alarm", 0), "stop"]


def test_heroku_local_start_raises_without_home_dir_set(wrapper):
    from dallinger.heroku.tools import HerokuStartupError

    wrapper.env = {}
    with pytest.raises(HerokuStartupError, match='"HOME" environment not set'):
        wrapper.start()


def test_heroku_local_start_when_shell_command_fails(wrapper):
    wrapper.shell_command = ("nonsense",)
    with pytest.raises(OSError):
        wrapper.start()
    wrapper.out.error.assert_called_with("Couldn't start honcho for local debugging.")


def test_heroku_local_stop_before_start_is_noop(wrapper):
    wrapper.stop()
    wrapper.out.log.assert_called_with("No local server process was running.")


@pytest.mark.parametrize(
    "clock_on, processes",
    [(False, ["web", "worker"]), (True, ["web", "worker", "clock"])],
)
def test_heroku_local_boot_runs_procfile_processes_with_honcho(
    wrapper, clock_on, processes
):
    """honcho gets the Procfile processes and none of the parent's stdin."""
    import subprocess

    settings = {"base_port": 5000, "num_dynos_web": 2, "num_dynos_worker": 1}
    wrapper.config = mock.Mock(get={**settings, "clock_on": clock_on}.get)
    with (
        mock.patch("dallinger.heroku.tools.subprocess.Popen") as popen,
        mock.patch("dallinger.heroku.tools.psutil.Process"),
    ):
        wrapper._boot()

    command = popen.call_args.args[0]
    assert command[:4] == [sys.executable, "-m", "honcho", "start"]
    assert command[command.index("-c") + 1] == "web=2,worker=1"
    assert command[-len(processes) :] == processes
    assert popen.call_args.kwargs["stdin"] is subprocess.DEVNULL


def test_heroku_local_runner_env_puts_interpreter_bin_first(wrapper):
    bin_dir = os.path.dirname(sys.executable)
    wrapper.env = {"HOME": "/tmp", "PATH": os.pathsep.join(["/usr/bin", bin_dir])}
    env = wrapper._runner_env()
    assert env["PATH"].split(os.pathsep) == [bin_dir, "/usr/bin"]
    assert env["PYTHONUNBUFFERED"] == "1"


def test_heroku_local_failure_logs_until_process_end(wrapper):
    wrapper._stream = mock.Mock(return_value=["real", "stopped"])
    wrapper._process = mock.Mock(pid=12345)
    wrapper._process.poll = mock.Mock(return_value=1)
    wrapper._log_failure()
    wrapper._process.poll.assert_called_once()
    assert len(wrapper._record) == 0


def test_heroku_local_failure_logs_until_new_error(wrapper):
    wrapper._stream = mock.Mock(
        return_value=["real", "more", "[] web.1  |  [ERROR] Random", "remainder"]
    )
    wrapper._process = mock.Mock(pid=12345)
    wrapper._process.poll = mock.Mock(return_value=None)
    wrapper._log_failure()
    assert wrapper._record == ["real", "more"]


def test_heroku_local_failure_ends_after_timeout(wrapper):
    def timeout_stream():
        yield "first"
        yield "second"
        time.sleep(10)
        yield "after"

    wrapper._stream = mock.Mock(return_value=timeout_stream())
    wrapper._process = mock.Mock(pid=12345)
    wrapper._process.poll = mock.Mock(return_value=None)
    start_time = time.time()
    wrapper._log_failure()
    assert wrapper._record == ["first", "second"]
    assert (time.time() - start_time) < 5


LISTENING_WEB = """
import os, socket, time
server = socket.socket()
server.bind(("127.0.0.1", int(os.environ["PORT"])))
server.listen()
print("listening", flush=True)
time.sleep(60)
"""

STUBBORN_WEB = (
    "import signal\n"
    "for sig in (signal.SIGINT, signal.SIGTERM):\n"
    "    signal.signal(sig, signal.SIG_IGN)\n" + LISTENING_WEB
)


def _toy_procfile_wrapper(tmp_path, monkeypatch, procfile, web=LISTENING_WEB):
    """A HerokuLocalWrapper that runs ``procfile`` with real honcho."""
    import socket

    from dallinger.heroku.tools import HerokuLocalWrapper

    (tmp_path / "web.py").write_text(web)
    (tmp_path / "Procfile").write_text(procfile)
    monkeypatch.chdir(tmp_path)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    settings = {"base_port": port, "num_dynos_web": 1, "num_dynos_worker": 1}
    return HerokuLocalWrapper(
        mock.Mock(get=settings.get), mock.Mock(), env=dict(os.environ)
    )


@pytest.mark.slow
def test_stop_kills_procfile_processes_that_ignore_signals(tmp_path, monkeypatch):
    import psutil

    wrapper = _toy_procfile_wrapper(
        tmp_path, monkeypatch, "web: python web.py\nworker: sleep 60\n", STUBBORN_WEB
    )
    wrapper.stop_grace_secs = 1
    wrapper.start(timeout_secs=20)
    runner = wrapper._process
    children = psutil.Process(runner.pid).children(recursive=True)
    # A repeated Ctrl-C while stop() waits must not cut the cleanup short.
    timer = threading.Timer(0.3, os.kill, (os.getpid(), signal.SIGINT))
    start_time = time.time()
    timer.start()
    try:
        wrapper.stop()
    finally:
        timer.cancel()

    assert time.time() - start_time > 0.3  # the SIGINT arrived during stop()
    assert runner.returncode != -signal.SIGKILL  # honcho exited by itself
    assert psutil.wait_procs(children, timeout=2)[1] == []
    wrapper.out.error.assert_not_called()


@pytest.mark.slow
def test_start_fails_fast_when_a_procfile_process_exits(tmp_path, monkeypatch):
    from dallinger.heroku.tools import HerokuStartupError

    wrapper = _toy_procfile_wrapper(
        tmp_path, monkeypatch, "web: sleep 60\nworker: exit 1\n"
    )
    start_time = time.time()
    with pytest.raises(HerokuStartupError):
        wrapper.start(timeout_secs=20)
    assert time.time() - start_time < 15
    assert not wrapper.is_running


@pytest.mark.slow
def test_monitor_ends_when_a_procfile_process_exits_after_startup(
    tmp_path, monkeypatch
):
    import psutil

    wrapper = _toy_procfile_wrapper(
        tmp_path, monkeypatch, "web: python web.py\nworker: sleep 3 && exit 1\n"
    )
    wrapper.start(timeout_secs=20)
    children = psutil.Process(wrapper._process.pid).children(recursive=True)

    wrapper.monitor(lambda line: None)

    assert psutil.wait_procs(children, timeout=5)[1] == []
    assert "stopped producing output" in wrapper.out.error.call_args[0][0]
    wrapper.stop()


@pytest.mark.parametrize("greenlets, max_connections", [(5, 50), (100, 110)])
def test_worker_greenlets_per_process_sizes_gevent_and_redis_pools(
    stub_config, greenlets, max_connections
):
    from dallinger_scripts.worker import worker_options

    stub_config.set("worker_greenlets_per_process", greenlets)
    worker_kwargs, pool_connections = worker_options(stub_config)
    assert worker_kwargs["pool_size"] == greenlets
    assert pool_connections == max_connections


@pytest.mark.usefixtures("bartlett_dir")
@pytest.mark.slow
class TestLocalProcfileWrapper:
    @pytest.fixture
    def config(self):
        from dallinger.deployment import setup_experiment

        cwd = os.getcwd()
        config = get_config(load=True)

        id, tmp = setup_experiment(log=mock.Mock(), verbose=True, exp_config={})

        os.chdir(tmp)
        yield config
        os.chdir(cwd)

    @pytest.fixture
    def heroku(self, config, env, clear_workers):
        from dallinger.heroku.tools import LocalProcfileWrapper

        wrapper = LocalProcfileWrapper(config, mock.Mock(), env=env)
        yield wrapper
        wrapper.stop()

    def test_start(self, heroku):
        assert heroku.start()
        assert heroku.is_running

    def test_gives_up_after_timeout(self, heroku):
        with mock.patch.object(heroku, "_up_and_running", return_value=False):
            with pytest.raises(HerokuTimeoutError):
                heroku.start(timeout_secs=1)

    def test_quits_on_gunicorn_startup_error(self, heroku):
        from dallinger.heroku.tools import HerokuStartupError

        heroku.verbose = False  # more coverage
        heroku._stream = mock.Mock(
            return_value=["12:00:00 system   | web.1 stopped (rc=1)"]
        )
        with mock.patch.object(heroku, "_up_and_running", return_value=False):
            with pytest.raises(HerokuStartupError):
                heroku.start()

    def test_start_fails_if_port_never_opens(self, heroku):
        from dallinger.heroku.tools import HerokuStartupError

        heroku._stream = mock.Mock(return_value=["apple", "orange"])
        heroku._log_failure = mock.Mock()
        with mock.patch.object(heroku, "_up_and_running", return_value=False):
            with pytest.raises(HerokuStartupError):
                heroku.start()
        heroku._log_failure.assert_called_once()
        assert not heroku.is_running

    @pytest.mark.parametrize(
        "kill_runner, stop_signal",
        [(False, None), (False, signal.SIGKILL), (True, None)],
    )
    def test_stop_leaves_no_processes(self, heroku, kill_runner, stop_signal):
        import psutil

        heroku.start()
        time.sleep(2)  # let gunicorn boot its worker processes
        children = psutil.Process(heroku._process.pid).children(recursive=True)
        if kill_runner:
            heroku._process.kill()
            heroku._process.wait()
        heroku.stop(stop_signal)
        _, alive = psutil.wait_procs(children, timeout=2)
        assert alive == []
        heroku.out.log.assert_called_with("Local server processes terminated.")

    @pytest.mark.parametrize("error", [HerokuTimeoutError, KeyboardInterrupt])
    def test_interrupted_start_leaves_no_processes(self, heroku, error):
        import psutil

        children = []

        def interrupt(port):
            children[:] = psutil.Process(heroku._process.pid).children(recursive=True)
            raise error()

        with mock.patch.object(heroku, "_up_and_running", side_effect=interrupt):
            with pytest.raises(error):
                heroku.start()
        _, alive = psutil.wait_procs(children, timeout=2)
        assert children and alive == []
        assert not heroku.is_running

    def test_start_when_already_started_is_noop(self, heroku):
        heroku.start()
        heroku.start()
        heroku.out.log.assert_called_with("Local server is already running.")

    def test_as_context_manager(self, config, env, clear_workers):
        from dallinger.heroku.tools import LocalProcfileWrapper

        with LocalProcfileWrapper(config, mock.Mock(), env=env) as heroku:
            assert heroku.is_running
        assert not heroku.is_running


class TestHerokuInfo:
    @pytest.fixture
    def info(self):
        from dallinger.heroku.tools import HerokuInfo

        yield HerokuInfo(team="fake team")

    def test_login_name(self, info, patch_netrc):
        login_name = info.login_name()
        patch_netrc.assert_has_calls([mock.call()])
        assert login_name == "test@example.com"

    def test_all_apps(self, info, custom_app_output):
        app_info = info.all_apps()
        custom_app_output.assert_has_calls(
            [mock.call(["heroku", "apps", "--json", "--team", "fake team"])]
        )
        assert app_info == [
            {
                "created_at": "2018-01-01T12:00Z",
                "name": "dlgr-my-uid",
                "web_url": "https://dlgr-my-uid.herokuapp.com",
            },
            {
                "created_at": "2018-01-02T00:00Z",
                "name": "dlgr-another-uid",
                "web_url": "https://dlgr-another-uid.herokuapp.com",
            },
        ]

    @pytest.mark.usefixtures("patch_netrc")
    def test_my_apps(self, info, custom_app_output):
        app_info = info.my_apps()
        custom_app_output.assert_has_calls(
            [
                mock.call(["heroku", "apps", "--json", "--team", "fake team"]),
                mock.call(["heroku", "config", "--json", "--app", "dlgr-my-uid"]),
                mock.call(["heroku", "config", "--json", "--app", "dlgr-another-uid"]),
            ]
        )
        assert app_info == [
            {
                "created_at": "2018-01-01T12:00Z",
                "dallinger_uid": "my-uid",
                "name": "dlgr-my-uid",
                "web_url": "https://dlgr-my-uid.herokuapp.com",
            }
        ]
