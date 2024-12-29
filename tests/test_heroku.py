#!/usr/bin/python
# -*- coding: utf-8 -*-
import datetime
import os
import signal
import time
from unittest import mock

import pytest

from dallinger.config import get_config


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


class TestClockScheduler(object):
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

    def teardown(self):
        os.chdir("../..")

    def test_scheduler_has_job(self, setup):
        jobs = self.clock.scheduler.get_jobs()
        assert len(jobs) == 2
        assert (
            jobs[0].func_ref
            == "dallinger.heroku.clock:check_db_for_missing_notifications"
        )
        assert jobs[1].func_ref == "dallinger.heroku.clock:async_recruiter_status_check"

    def test_launch_loads_config(self, patched_scheduler):
        self.clock.launch()
        patched_scheduler.start.assert_called_once()
        assert get_config().ready

    def test_launch_registers_additional_tasks(
        self, patched_scheduler, tasks_with_cleanup
    ):
        jobs = patched_scheduler.get_jobs()
        assert len(jobs) == 2

        tasks_with_cleanup.append(
            {
                "func_name": "test_task",
                "trigger": "interval",
                "kwargs": (("minutes", 5),),
            }
        )

        self.clock.launch()
        jobs = patched_scheduler.get_jobs()
        assert len(jobs) == 3
        assert (
            jobs[2].func_ref
            == "dallinger_experiment.dallinger_experiment:TestExperiment.test_task"
        )


@pytest.mark.usefixtures("experiment_dir", "active_config")
class TestHerokuClockTasks(object):
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


class TestHerokuUtilFunctions(object):
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
class TestHerokuApp(object):
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


@pytest.mark.usefixtures("bartlett_dir")
@pytest.mark.slow
class TestHerokuLocalWrapper(object):
    @pytest.fixture
    def config(self):
        from dallinger.deployment import setup_experiment

        cwd = os.getcwd()
        config = get_config()
        if not config.ready:
            config.load()

        (id, tmp) = setup_experiment(log=mock.Mock(), verbose=True, exp_config={})

        os.chdir(tmp)
        yield config
        os.chdir(cwd)

    @pytest.fixture
    def output(self):
        class Output(object):
            def __init__(self):
                self.log = mock.Mock()
                self.error = mock.Mock()
                self.blather = mock.Mock()

        return Output()

    @pytest.fixture
    def heroku(self, config, env, output, clear_workers):
        from dallinger.heroku.tools import HerokuLocalWrapper

        wrapper = HerokuLocalWrapper(config, output, env=env)
        yield wrapper
        try:
            print("Calling stop() on {}".format(wrapper))
            print(wrapper._record[-1])
            wrapper.stop(signal.SIGKILL)
        except (IndexError, TypeError):
            pass

    def test_start(self, heroku):
        assert heroku.start()
        assert heroku.is_running

    def test_start_raises_without_home_dir_set(self, heroku):
        from dallinger.heroku.tools import HerokuStartupError

        env = heroku.env.copy()
        del env["HOME"]
        heroku.env = env
        with pytest.raises(HerokuStartupError) as excinfo:
            heroku.start()
        assert excinfo.match('"HOME" environment not set... aborting.')

    def test_gives_up_after_timeout(self, heroku):
        from dallinger.heroku.tools import HerokuTimeoutError

        with pytest.raises(HerokuTimeoutError):
            heroku.start(timeout_secs=1)

    def test_quits_on_gunicorn_startup_error(self, heroku):
        from dallinger.heroku.tools import HerokuStartupError

        heroku.verbose = False  # more coverage
        heroku._stream = mock.Mock(return_value=["[DONE] Killing all processes"])
        with pytest.raises(HerokuStartupError):
            heroku.start()

    def test_start_fails_if_stream_ends_without_matching_success_regex(self, heroku):
        from dallinger.heroku.tools import HerokuStartupError

        heroku._stream = mock.Mock(
            return_value=["apple", "orange", heroku.STREAM_SENTINEL]
        )
        heroku.success_regex = "not going to match anything"
        with pytest.raises(HerokuStartupError):
            heroku.start()
        assert not heroku.is_running

    def test_error_flushes_logs(self, heroku):
        from dallinger.heroku.tools import HerokuStartupError

        heroku._stream = mock.Mock(
            return_value=["apple", "orange", heroku.STREAM_SENTINEL]
        )
        heroku.success_regex = "not going to match anything"
        heroku._log_failure = mock.Mock()
        with pytest.raises(HerokuStartupError):
            heroku.start()
        heroku._log_failure.assert_called_once()

    def test_failure_logs_until_process_end(self, heroku):
        heroku._stream = mock.Mock(
            return_value=["real", "stopped", heroku.STREAM_SENTINEL]
        )
        heroku._process = mock.Mock()
        heroku._process.poll = mock.Mock(return_value=1)
        heroku._log_failure()
        heroku._process.poll.assert_called_once()
        assert len(heroku._record) == 0

    def test_failure_logs_until_new_error(self, heroku):
        heroku._stream = mock.Mock(
            return_value=[
                "real",
                "more",
                "[] web.1  |  [ERROR] Random",
                "remainder",
                heroku.STREAM_SENTINEL,
            ]
        )
        heroku._process = mock.Mock()
        heroku._process.poll = mock.Mock(return_value=None)
        heroku._log_failure()
        assert heroku._record == ["real", "more"]

    def test_failure_ends_after_timeout(self, heroku):
        def timeout_stream():
            yield "first"
            yield "second"
            time.sleep(10)
            yield "after"
            yield heroku.STREAM_SENTINEL

        heroku._stream = mock.Mock(return_value=timeout_stream())
        heroku._process = mock.Mock()
        heroku._process.poll = mock.Mock(return_value=None)
        start_time = time.time()
        heroku._log_failure()
        assert heroku._record == ["first", "second"]
        assert (time.time() - start_time) < 5

    def test_stop(self, heroku):
        heroku.start()
        heroku.stop(signal.SIGKILL)
        heroku.out.log.assert_called_with("Local Heroku process terminated.")

    def test_stop_on_killed_process_no_error(self, heroku):
        heroku.start()
        heroku._process.terminate()
        heroku.stop()
        mock.call("Local Heroku was already terminated.") in heroku.out.log.mock_calls

    def test_start_when_shell_command_fails(self, heroku):
        heroku.shell_command = "nonsense"
        with pytest.raises(OSError):
            heroku.start()
            heroku.out.error.assert_called_with(
                "Couldn't start Heroku for local debugging."
            )

    def test_stop_before_start_is_noop(self, heroku):
        heroku.stop()
        heroku.out.log.assert_called_with("No local Heroku process was running.")

    def test_start_when_already_started_is_noop(self, heroku):
        heroku.start()
        heroku.start()
        heroku.out.log.assert_called_with("Local Heroku is already running.")

    def test_monitor(self, heroku):
        heroku._stream = mock.Mock(return_value=["apple", "orange"])
        listener = mock.Mock()
        heroku.monitor(listener)
        listener.assert_has_calls([mock.call("apple"), mock.call("orange")])

    def test_monitor_stops_iterating_when_told(self, heroku):
        heroku._stream = mock.Mock(return_value=["apple", "orange"])
        listener = mock.Mock()
        listener.return_value = heroku.MONITOR_STOP
        heroku.monitor(listener)
        listener.assert_has_calls([mock.call("apple")])

    def test_as_context_manager(self, config, env, output, clear_workers):
        from dallinger.heroku.tools import HerokuLocalWrapper

        with HerokuLocalWrapper(config, output, env=env) as heroku:
            assert heroku.is_running
        assert not heroku.is_running


class TestHerokuInfo(object):
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
