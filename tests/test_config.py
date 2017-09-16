from __future__ import unicode_literals

import os
import mock
from tempfile import NamedTemporaryFile

import pexpect
import pytest

from dallinger.config import Configuration
from dallinger.config import get_config, LOCAL_CONFIG


@pytest.mark.usefixtures('experiment_dir')
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
        with pytest.raises(KeyError):
            config.register('num_participants', int)

    def test_register_unknown_type_raises(self):
        config = Configuration()
        with pytest.raises(TypeError):
            config.register('num_participants', object)

    def test_type_mismatch(self):
        config = Configuration()
        config.register('num_participants', int)
        with pytest.raises(TypeError):
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
        with pytest.raises(TypeError):
            config.extend({'num_participants': 'A NUMBER'}, cast_types=True)

    def test_get_before_ready_is_not_possible(self):
        config = Configuration()
        config.register('num_participants', int)
        config.extend({'num_participants': 1})
        with pytest.raises(RuntimeError):
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

    def test_setting_by_assignment(self):
        config = Configuration()
        config.ready = True
        config["mode"] = u"live"

    def test_get_without_default_raises(self):
        config = Configuration()
        config.register('num_participants', int)
        config.ready = True
        with pytest.raises(KeyError):
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
        with pytest.raises(KeyError):
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
            config.load_from_file(configfile.name)
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

    def test_reload_config(self):
        # replicate the experiment API runner config loading
        config = get_config()
        config.register_extra_parameters()
        config.load_from_file(LOCAL_CONFIG)
        # Failse with _reset()
        config.clear()
        config.register_extra_parameters()
        config.load_from_file(LOCAL_CONFIG)

    def test_local_base_url(self):
        from dallinger.utils import get_base_url
        config = get_config()
        config.ready = True
        config.set(u'host', u'localhost')
        config.set(u'base_port', 5000)
        assert(get_base_url() == 'http://localhost:5000')

    @mock.patch.dict(os.environ, {'HOST': 'https://dlgr-bogus.herokuapp.com'})
    def test_remote_base_url(self):
        from dallinger.utils import get_base_url
        config = get_config()
        config.ready = True
        assert(get_base_url() == 'https://dlgr-bogus.herokuapp.com')

    @mock.patch.dict(os.environ, {'HOST': 'http://dlgr-bogus.herokuapp.com'})
    def test_remote_base_url_always_ssl(self):
        from dallinger.utils import get_base_url
        config = get_config()
        config.ready = True
        assert(get_base_url() == 'https://dlgr-bogus.herokuapp.com')
