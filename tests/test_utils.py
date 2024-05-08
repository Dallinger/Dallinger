# -*- coding: utf-8 -*-
import io
import locale
from datetime import datetime, timedelta
from tempfile import NamedTemporaryFile
from unittest import mock

import pytest

from dallinger import config, utils
from dallinger.utils import check_experiment_dependencies


class TestSubprocessWrapper(object):
    @pytest.fixture
    def sys(self):
        with mock.patch("dallinger.utils.sys") as sys:
            yield sys

    def test_writing_to_stdout_unaffected_by_default(self):
        def sample(**kwargs):
            assert kwargs["stdin"] is None
            assert kwargs["stdout"] is None

        utils.wrap_subprocess_call(sample)(stdin=None, stdout=None)

    def test_writing_to_stdout_is_diverted_if_broken(self, sys):
        def sample(**kwargs):
            assert kwargs["stdin"] is None
            assert kwargs["stdout"] is not None
            assert kwargs["stdout"] is not sys.stdout

        sys.stdout.fileno.side_effect = io.UnsupportedOperation
        utils.wrap_subprocess_call(sample)(stdin=None, stdout=None)

    def test_writing_to_stdout_is_not_diverted_if_wrapstdout_is_false(self, sys):
        def sample(**kwargs):
            assert kwargs["stdin"] is None
            assert kwargs["stdout"] is None

        sys.stdout.fileno.side_effect = io.UnsupportedOperation
        utils.wrap_subprocess_call(sample, wrap_stdout=False)(stdin=None, stdout=None)

    def test_writing_to_stderr_is_diverted_if_broken(self, sys):
        def sample(**kwargs):
            assert kwargs["stderr"] is not None
            assert kwargs["stderr"] is not sys.stdout

        sys.stderr.fileno.side_effect = io.UnsupportedOperation
        utils.wrap_subprocess_call(sample)(stderr=None)

    def test_reading_from_stdin_is_not_diverted(self, sys):
        def sample(**kwargs):
            assert kwargs["stdin"] is None
            assert kwargs["stdout"] is None

        sys.stdin.fileno.side_effect = io.UnsupportedOperation
        utils.wrap_subprocess_call(sample)(stdin=None, stdout=None)

    def test_arbitrary_outputs_are_not_replaced_even_if_stdout_is_broken(self, sys):
        output = io.StringIO()

        def sample(**kwargs):
            assert kwargs["stdin"] is None
            assert kwargs["stdout"] is output

        sys.stdout.fileno.side_effect = io.UnsupportedOperation
        utils.wrap_subprocess_call(sample)(stdin=None, stdout=output)

    def test_writing_to_broken_stdout_is_output_after_returning(self, sys):
        def sample(**kwargs):
            kwargs["stdout"].write(b"Output")
            # The output isn't written until we return
            sys.stdout.write.assert_not_called()

        sys.stdout.fileno.side_effect = io.UnsupportedOperation
        utils.wrap_subprocess_call(sample)(stdin=None, stdout=None)
        sys.stdout.write.assert_called_once_with(b"Output")

    def test_writing_to_broken_stderr_is_output_after_returning(self, sys):
        def sample(**kwargs):
            kwargs["stderr"].write(b"Output")
            # The output isn't written until we return
            sys.stderr.write.assert_not_called()

        sys.stderr.fileno.side_effect = io.UnsupportedOperation
        utils.wrap_subprocess_call(sample)(stderr=None)
        sys.stderr.write.assert_called_once_with(b"Output")


@pytest.mark.usefixtures("in_tempdir")
class TestGitClient(object):
    @pytest.fixture
    def git(self):
        from dallinger.utils import GitClient

        git = GitClient()
        return git

    def test_client(self, git, stub_config):
        import subprocess

        stub_config.write()
        config = {"user.name": "Test User", "user.email": "test@example.com"}
        git.init(config=config)
        git.add("--all")
        git.commit("Test Repo")
        assert b"Test Repo" in subprocess.check_output(["git", "log"])

    def test_files_with_gitignore(self, git):
        config = {"user.name": "Test User", "user.email": "test@example.com"}
        with open("one.txt", "w") as one:
            one.write("one")
        with open("two.txt", "w") as two:
            two.write("two")
        with open(".gitignore", "w") as ignore:
            ignore.write("two.*")
        git.init(config=config)

        assert set(git.files()) == {".gitignore", "one.txt"}

    def test_both_commited_and_uncommitted_files_shown(self, git):
        config = {"user.name": "Test User", "user.email": "test@example.com"}
        git.init(config=config)

        with open("one.txt", "w") as one:
            one.write("one")
        git.add("--all")

        with open("two.txt", "w") as two:
            two.write("two")

        assert git.files() == {"one.txt", "two.txt"}

    def test_files_handles_nonascii_filenames(self, git):
        config = {"user.name": "Test User", "user.email": "test@example.com"}
        git.init(config=config)
        filename = b"J\xc3\xb8hn D\xc3\xb8\xc3\xa9's \xe2\x80\x93.txt"

        with open(filename, "w") as two:
            two.write("blah")

        assert git.files() == {filename.decode(locale.getpreferredencoding())}

    def test_files_on_non_git_repo(self, git):
        assert git.files() == set()

    def test_includes_details_in_exceptions(self, git):
        with pytest.raises(Exception) as ex_info:
            git.push("foo", "bar")
        assert ex_info.match("[nN]ot a git repository")

    def test_can_use_alternate_output(self, git):
        import tempfile

        git.out = tempfile.NamedTemporaryFile()
        git.encoding = "utf8"
        git.init()
        git.out.seek(0)
        assert b"git init" in git.out.read()

    def test_clone(self, git):
        with mock.patch("dallinger.utils.run_command") as runner:
            tempdir = git.clone("https://some-fake-repo")

        runner.assert_called_once_with(
            ["git", "clone", "https://some-fake-repo", tempdir], mock.ANY
        )


class TestParticipationTime(object):
    @pytest.fixture
    def subject(self):
        from dallinger.utils import ParticipationTime

        return ParticipationTime

    def test_time_translations(self, subject, a, stub_config):
        timeline = subject(a.participant(), datetime.now(), stub_config)
        assert timeline.allowed_hours == stub_config.get("duration")
        assert timeline.allowed_minutes == 60.0
        assert timeline.allowed_seconds == 3600.0

    def test_excess_minutes(self, subject, a, stub_config):
        duration_mins = stub_config.get("duration") * 60
        participant = a.participant()
        five_minutes_over = participant.creation_time + timedelta(
            minutes=duration_mins + 5
        )

        timeline = subject(a.participant(), five_minutes_over, stub_config)

        assert int(round(timeline.excess_minutes)) == 5

    def test_is_overdue_true_if_exceeds_grace_period(self, subject, a, stub_config):
        duration_secs = round(stub_config.get("duration") * 60 * 60)
        participant = a.participant()
        just_over = timedelta(seconds=duration_secs + subject.grace_period_seconds + 1)
        reference_time = participant.creation_time + just_over

        timeline = subject(a.participant(), reference_time, stub_config)

        assert timeline.is_overdue

    def test_is_overdue_false_if_within_grace_period(self, subject, a, stub_config):
        duration_secs = round(stub_config.get("duration") * 60 * 60)
        participant = a.participant()
        just_under = timedelta(seconds=duration_secs + subject.grace_period_seconds - 1)
        reference_time = participant.creation_time + just_under
        timeline = subject(a.participant(), reference_time, stub_config)

        assert not timeline.is_overdue


class TestBaseURL(object):
    @pytest.fixture
    def subject(self):
        from dallinger.utils import get_base_url

        return get_base_url

    @pytest.fixture
    def config(self):
        instance = config.get_config()
        instance.ready = True
        yield instance
        config.config = None

    def test_base_url_uses_flask_if_available(self, subject):
        from dallinger.experiment_server.experiment_server import app

        with app.test_request_context(base_url="https://example.com", path="/launch"):
            assert subject() == "https://example.com"

    def test_base_url_uses_environment(self, subject, config):
        config.set("host", "127.0.0.1")
        config.set("base_port", 5000)
        config.set("num_dynos_web", 1)
        assert subject() == "http://127.0.0.1:5000"

    def test_local_base_url_converts(self, subject, config):
        config.set("host", "0.0.0.0")
        config.set("base_port", 5000)
        config.set("num_dynos_web", 1)
        assert subject() == "http://localhost:5000"

    def test_remote_base_url_always_ssl(self, subject, config):
        config.set("host", "http://dlgr-bogus.herokuapp.com")
        config.set("base_port", 80)
        config.set("num_dynos_web", 1)
        assert subject() == "https://dlgr-bogus.herokuapp.com"

    @pytest.mark.xfail(
        reason="HOST aliasing removed to fix https://github.com/Dallinger/Dallinger/issues/2130"
    )
    def test_os_HOST_environ_used_as_host(self, subject, config):
        with mock.patch("os.environ", {"HOST": "dlgr-bogus-2.herokuapp.com"}):
            config.load_from_environment()
        config.set("base_port", 80)
        config.set("num_dynos_web", 1)
        assert subject() == "https://dlgr-bogus-2.herokuapp.com"


class TestIsolatedWebbrowser(object):
    def test_chrome_isolation(self):
        import webbrowser

        with mock.patch("dallinger.utils.is_command") as is_command:
            is_command.side_effect = lambda s: s == "google-chrome"
            isolated = utils._new_webbrowser_profile()

        assert isinstance(isolated, webbrowser.Chrome)

    def test_firefox_isolation(self):
        import webbrowser

        with mock.patch("dallinger.utils.is_command") as is_command:
            is_command.side_effect = lambda s: s == "firefox"
            isolated = utils._new_webbrowser_profile()

        assert isinstance(isolated, webbrowser.Mozilla)

    def test_fallback_isolation(self):
        import webbrowser

        with mock.patch.multiple(
            "dallinger.utils", is_command=mock.DEFAULT, sys=mock.DEFAULT
        ) as patches:
            patches["is_command"].return_value = False
            patches["sys"].platform = 'anything but "darwin"'
            isolated = utils._new_webbrowser_profile()
        assert isolated == webbrowser


def test_check_experiment_dependencies_successful():
    with NamedTemporaryFile() as requirements_file:
        requirements = [
            "dallinger",
            "dallinger==9.7.0",
            "dallinger<=9.7.0",
            "dallinger>=9.7.0",
            "dallinger == 9.7.0",
            "dallinger@git+https://github.com/Dallinger/Dallinger",
            "dallinger @ git+https://github.com/Dallinger/Dallinger",
            "dallinger[demos]",
            "dallinger [demos]",
            "# dallinger",
            "",
            " # dallinger",
        ]
        lines = [f"{r}\n".encode("utf-8") for r in requirements]
        requirements_file.writelines(lines)
        requirements_file.flush()

        check_experiment_dependencies(requirements_file.name)


def test_check_experiment_dependencies_unsuccessful():
    with NamedTemporaryFile() as requirements_file:
        requirements_file.writelines(["NOTINSTALLED\n".encode("utf-8")])
        requirements_file.flush()

        with pytest.raises(ValueError) as e:
            check_experiment_dependencies(requirements_file.name)
        assert (
            str(e.value)
            == "Please install the 'NOTINSTALLED' package to run this experiment."
        )
