import io
import mock
import pytest
from datetime import datetime
from datetime import timedelta
from dallinger import utils


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
