from __future__ import unicode_literals

import os
from tempfile import NamedTemporaryFile

from pytest import raises
import pexpect

from dallinger.config import Configuration


class TestConfiguration(object):

    def test_register_new_variable(self):
        config = Configuration()
        config.register('num_participants', int)
        config.extend({'num_participants': 1})
        config.ready = True
        assert config.get('num_participants', 1)

    def test_register_duplicate_variable_raises(self):
        config = Configuration()
        config.register('num_participants', int)
        with raises(KeyError):
            config.register('num_participants', int)

    def test_register_unknown_type_raises(self):
        config = Configuration()
        with raises(ValueError):
            config.register('num_participants', object)

    def test_type_mismatch(self):
        config = Configuration()
        config.register('num_participants', int)
        with raises(ValueError):
            config.extend({'num_participants': 1.0})

    def test_type_mismatch_with_cast_types(self):
        config = Configuration()
        config.register('num_participants', int)
        config.ready = True
        config.extend({'num_participants': 1.0}, cast_types=True)
        assert config.get('num_participants', 1) == 1

    def test_type_cast_types_failure_raises(self):
        config = Configuration()
        config.register('num_participants', int)
        config.ready = True
        with raises(ValueError):
            config.extend({'num_participants': 'A NUMBER'}, cast_types=True)

    def test_get_before_ready_is_not_possible(self):
        config = Configuration()
        config.register('num_participants', int)
        config.extend({'num_participants': 1})
        with raises(RuntimeError):
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

    def test_setting_by_set(self):
        config = Configuration()
        config.ready = True
        config.set("mode", u"live")

    def test_get_without_default_raises(self):
        config = Configuration()
        config.register('num_participants', int)
        config.ready = True
        with raises(KeyError):
            config.get('num_participants')

    def test_get_has_default_value(self):
        config = Configuration()
        config.register('num_participants', int)
        config.ready = True
        assert config.get('num_participants', 10) == 10

    def test_dict_access(self):
        config = Configuration()
        config.register('num_participants', int)
        config.ready = True
        config.extend({'num_participants': 1})
        assert config['num_participants'] == 1

    def test_attribute_access(self):
        config = Configuration()
        config.register('num_participants', int)
        config.ready = True
        config.extend({'num_participants': 1})
        assert config.num_participants == 1

    def test_attribute_setting(self):
        config = Configuration()
        config.register('num_participants', int)
        config.ready = True
        config.num_participants = 1
        assert config.num_participants == 1

    def test_strict_extending_blocks_unknown_keys(self):
        config = Configuration()
        config.register('num_participants', int)
        config.ready = True
        with raises(KeyError):
            config.extend({'unknown_key': 1}, strict=True)

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
        try:
            python = pexpect.spawn("python")
            python.read_nonblocking(10000)
            python.setecho(False)
            python.sendline('from dallinger.experiment_server import experiment_server')
            python.sendline('from dallinger.config import get_config')
            python.sendline('config = get_config()')
            python.sendline('print config.types')
            python.expect_exact("custom_parameter': <type 'int'>")
        finally:
            python.sendcontrol('d')
            python.read()
            os.chdir('../..')
