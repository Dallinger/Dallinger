from __future__ import unicode_literals

import os
from tempfile import NamedTemporaryFile

from nose.tools import assert_raises
import pexpect

from dallinger.config import Configuration


class TestConfiguration(object):

    def test_register_new_variable(self):
        config = Configuration()
        config.register('num_participants', int)
        config.extend({'num_participants': 1})
        config.ready = True
        assert config.get('num_participants', 1)

    def test_type_mismatch(self):
        config = Configuration()
        config.register('num_participants', int)
        with assert_raises(ValueError):
            config.extend({'num_participants': 1.0})

    def test_type_mismatch_with_cast_types(self):
        config = Configuration()
        config.register('num_participants', int)
        config.ready = True
        config.extend({'num_participants': 1.0}, cast_types=True)
        assert config.get('num_participants', 1) == 1

    def test_get_before_ready_is_not_possible(self):
        config = Configuration()
        config.register('num_participants', int)
        config.extend({'num_participants': 1})
        with assert_raises(RuntimeError):
            config.get('num_participants', 1)

    def test_layering_of_configs(self):
        config = Configuration()
        config.register('num_participants', int)
        config.extend({'num_participants': 1})
        config.ready = True
        assert config.get('num_participants', 1) == 1
        config.extend({'num_participants': 2})
        assert config.get('num_participants', 1) == 2

    def test_setting_unknown_key_is_ignored(self):
        config = Configuration()
        config.ready = True
        config.extend({'num_participants': 1})
        config.get('num_participants', None)

    def test_get_has_default_value(self):
        config = Configuration()
        config.register('num_participants', int)
        config.ready = True
        assert config.get('num_participants', 10) == 10

    def test_setting_values_supports_synonyms(self):
        config = Configuration()
        config.register('num_participants', int, synonyms={'n', })
        config.ready = True
        config.extend({'n': 1})
        assert config.get('num_participants') == 1

    def test_loading_keys_from_config_file(self):
        config = Configuration()
        config.register('num_participants', int, synonyms={'n', })
        config.register('deploy_worldwide', bool, synonyms={'worldwide', })
        with NamedTemporaryFile() as configfile:
            configfile.write("""
[Example Section]
num_participants = 10
worldwide = false
""")
            configfile.flush()
            config.load_from_config_file(configfile.name)
        config.ready = True
        assert config.get('num_participants') == 10
        assert config.get('deploy_worldwide') is False

    def test_loading_keys_from_environment_variables(self):
        config = Configuration()
        config.register('num_participants', int, synonyms={'n', })
        os.environ['num_participants'] = '1'
        try:
            config.load_from_environment()
        finally:
            del os.environ['num_participants']
        config.ready = True
        assert config.get('num_participants') == 1

    def test_experiment_defined_parameters(self):
        os.chdir('tests/experiment')
        python = pexpect.spawn("python")
        try:
            python.read_nonblocking(10000)
            python.setecho(False)
            python.sendline('from dallinger.experiment_server import experiment_server')
            python.sendline('from dallinger.config import get_config')
            python.sendline('config = get_config()')
            python.read_nonblocking(10000)
            python.sendline('print config.types')
            python.read_nonblocking(10000)
            types = python.read_nonblocking(10000)
            assert "'custom_parameter': <type 'int'>" in types
        finally:
            python.close()
            os.chdir('../..')
