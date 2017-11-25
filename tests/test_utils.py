import io
import mock

import pytest

from dallinger import utils


class TestSubprocessWrapper(object):

    @pytest.fixture
    def sys(self):
        with mock.patch('dallinger.utils.sys') as sys:
            yield sys

    def test_writing_to_stdout_unaffected_by_default(self):
        def sample(**kwargs):
            assert kwargs['stdin'] is None
            assert kwargs['stdout'] is None
        utils.wrap_subprocess_call(sample)(stdin=None, stdout=None)

    def test_writing_to_stdout_is_diverted_if_broken(self, sys):
        def sample(**kwargs):
            assert kwargs['stdin'] is None
            assert kwargs['stdout'] is not None
            assert kwargs['stdout'] is not sys.stdout
        sys.stdout.fileno.side_effect = io.UnsupportedOperation
        utils.wrap_subprocess_call(sample)(stdin=None, stdout=None)

    def test_writing_to_stdout_is_not_diverted_if_wrapstdout_is_false(self, sys):
        def sample(**kwargs):
            assert kwargs['stdin'] is None
            assert kwargs['stdout'] is None
        sys.stdout.fileno.side_effect = io.UnsupportedOperation
        utils.wrap_subprocess_call(sample, wrap_stdout=False)(stdin=None, stdout=None)

    def test_writing_to_stderr_is_diverted_if_broken(self, sys):
        def sample(**kwargs):
            assert kwargs['stderr'] is not None
            assert kwargs['stderr'] is not sys.stdout
        sys.stderr.fileno.side_effect = io.UnsupportedOperation
        utils.wrap_subprocess_call(sample)(stderr=None)

    def test_reading_from_stdin_is_not_diverted(self, sys):
        def sample(**kwargs):
            assert kwargs['stdin'] is None
            assert kwargs['stdout'] is None
        sys.stdin.fileno.side_effect = io.UnsupportedOperation
        utils.wrap_subprocess_call(sample)(stdin=None, stdout=None)

    def test_arbitrary_outputs_are_not_replaced_even_if_stdout_is_broken(self, sys):
        output = io.StringIO()

        def sample(**kwargs):
            assert kwargs['stdin'] is None
            assert kwargs['stdout'] is output
        sys.stdout.fileno.side_effect = io.UnsupportedOperation
        utils.wrap_subprocess_call(sample)(stdin=None, stdout=output)

    def test_writing_to_broken_stdout_is_output_after_returning(self, sys):
        def sample(**kwargs):
            kwargs['stdout'].write('Output')
            # The output isn't written until we return
            sys.stdout.write.assert_not_called()
        sys.stdout.fileno.side_effect = io.UnsupportedOperation
        utils.wrap_subprocess_call(sample)(stdin=None, stdout=None)
        sys.stdout.write.assert_called_once_with('Output')

    def test_writing_to_broken_stderr_is_output_after_returning(self, sys):
        def sample(**kwargs):
            kwargs['stderr'].write('Output')
            # The output isn't written until we return
            sys.stderr.write.assert_not_called()
        sys.stderr.fileno.side_effect = io.UnsupportedOperation
        utils.wrap_subprocess_call(sample)(stderr=None)
        sys.stderr.write.assert_called_once_with('Output')
