from __future__ import unicode_literals

import os
from tempfile import NamedTemporaryFile

import pytest
import six

from dallinger.config import LOCAL_CONFIG, Configuration, get_config


class TestConfigurationUnitTests(object):
    def test_register_new_variable(self):
        config = Configuration()
        config.register("num_participants", int)
        config.extend({"num_participants": 1})
        config.ready = True
        assert config.get("num_participants", 1)

    def test_register_duplicate_variable_raises(self):
        config = Configuration()
        config.register("num_participants", int)
        with pytest.raises(KeyError):
            config.register("num_participants", int)

    def test_register_unknown_type_raises(self):
        config = Configuration()
        with pytest.raises(TypeError):
            config.register("num_participants", object)

    def test_type_mismatch_on_assignment(self):
        config = get_config()
        with pytest.raises(TypeError):
            config["base_payment"] = 12

    def test_type_mismatch_on_extend(self):
        config = Configuration()
        config.register("num_participants", int)
        with pytest.raises(TypeError):
            config.extend({"num_participants": 1.0})

    def test_type_mismatch_with_cast_types(self):
        config = Configuration()
        config.register("num_participants", int)
        config.ready = True
        config.extend({"num_participants": 1.0}, cast_types=True)
        assert config.get("num_participants", 1) == 1

    def test_type_cast_types_failure_raises(self):
        config = Configuration()
        config.register("num_participants", int)
        config.ready = True
        with pytest.raises(TypeError):
            config.extend({"num_participants": "A NUMBER"}, cast_types=True)

    def test_type_casts_follow_file_pointers(self):
        config = Configuration()
        config.register("data", six.text_type)
        config.ready = True
        with NamedTemporaryFile() as data_file:
            data_file.write("hello".encode("utf-8"))
            data_file.flush()
            config.extend({"data": "file:" + data_file.name}, cast_types=True)
        assert config.get("data") == "hello"

    def test_get_before_ready_is_not_possible(self):
        config = Configuration()
        config.register("num_participants", int)
        config.extend({"num_participants": 1})
        with pytest.raises(RuntimeError):
            config.get("num_participants", 1)

    def test_layering_of_configs(self):
        config = Configuration()
        config.register("num_participants", int)
        config.extend({"num_participants": 1})
        config.ready = True
        assert config.get("num_participants", 1) == 1
        config.extend({"num_participants": 2})
        assert config.get("num_participants", 1) == 2

    def test_setting_unknown_key_is_ignored(self):
        config = Configuration()
        config.ready = True
        config.extend({"num_participants": 1})
        config.get("num_participants", None)

    def test_setting_value_that_doesnt_validate_fails(self):
        config = Configuration()

        def is_purple(val):
            if val != "purple":
                raise ValueError

        config.register("fave_colour", six.text_type, validators=[is_purple])
        config.ready = True
        config.set("fave_colour", "purple")
        with pytest.raises(ValueError):
            config.set("fave_colour", "red")

    def test_setting_by_set(self):
        config = Configuration()
        config.ready = True
        config.set("mode", "live")

    def test_setting_by_assignment(self):
        config = Configuration()
        config.ready = True
        config["mode"] = "live"

    def test_get_without_default_raises(self):
        config = Configuration()
        config.register("num_participants", int)
        config.ready = True
        with pytest.raises(KeyError):
            config.get("num_participants")

    def test_get_has_default_value(self):
        config = Configuration()
        config.register("num_participants", int)
        config.ready = True
        assert config.get("num_participants", 10) == 10

    def test_get_strips_strings(self):
        config = Configuration()
        config.register("test_string", six.text_type)
        config.ready = True
        config.extend({"test_string": " something "})
        assert config.get("test_string") == "something"

    def test_dict_access(self):
        config = Configuration()
        config.register("num_participants", int)
        config.ready = True
        config.extend({"num_participants": 1})
        assert config["num_participants"] == 1

    def test_attribute_access(self):
        config = Configuration()
        config.register("num_participants", int)
        config.ready = True
        config.extend({"num_participants": 1})
        assert config.num_participants == 1

    def test_attribute_setting(self):
        config = Configuration()
        config.register("num_participants", int)
        config.ready = True
        config.num_participants = 1
        assert config.num_participants == 1

    def test_strict_extending_blocks_unknown_keys(self):
        config = Configuration()
        config.register("num_participants", int)
        config.ready = True
        with pytest.raises(KeyError):
            config.extend({"unknown_key": 1}, strict=True)

    def test_setting_values_supports_synonyms(self):
        config = Configuration()
        config.register("num_participants", int, synonyms={"n"})
        config.ready = True
        config.extend({"n": 1})
        assert config.get("num_participants") == 1

    def test_loading_keys_from_config_file(self):
        config = Configuration()
        config.register("mode", six.text_type)
        config.register("num_participants", int, synonyms={"n"})
        config.register("deploy_worldwide", bool, synonyms={"worldwide"})
        mode_with_trailing_whitespace = "live    "
        contents = """
[Example Section]
mode = {}
num_participants = 10
worldwide = false
""".format(
            mode_with_trailing_whitespace
        )

        with NamedTemporaryFile() as configfile:
            configfile.write(contents.encode("utf-8"))
            configfile.flush()
            config.load_from_file(configfile.name)

        config.ready = True
        assert config.get("mode") == "live"  # whitespace stripped
        assert config.get("num_participants") == 10
        assert config.get("deploy_worldwide") is False

    def test_loading_keys_from_environment_variables(self):
        config = Configuration()
        config.register("num_participants", int, synonyms={"n"})
        os.environ["num_participants"] = "1"
        try:
            config.load_from_environment()
        finally:
            del os.environ["num_participants"]
        config.ready = True
        assert config.get("num_participants") == 1

    def test_loading_auto_recruit_from_redis(self, active_config, redis_conn):
        active_config.set("auto_recruit", False)
        from dallinger.db import redis_conn

        redis_conn.set("auto_recruit", 1)
        assert active_config.get("auto_recruit") is True


@pytest.mark.usefixtures("experiment_dir_merged")
class TestConfigurationIntegrationTests(object):
    def test_experiment_defined_parameters(self):
        config = get_config()
        config.register_extra_parameters()
        config.load_from_file(LOCAL_CONFIG)
        # From custom module function
        assert "custom_parameter" in config.types
        # From custom experiment instance method
        assert "custom_parameter2" in config.types

        assert config.types["custom_parameter"] is int
        assert config.types["custom_parameter2"] is bool

    def test_reload_config(self):
        # replicate the experiment API runner config loading
        config = get_config()
        config.register_extra_parameters()
        config.load_from_file(LOCAL_CONFIG)
        config._reset(register_defaults=True)
        config.register_extra_parameters()
        config.load_from_file(LOCAL_CONFIG)

    def test_write_omits_sensitive_keys_if_filter_sensitive(self, in_tempdir):
        config = get_config()
        config.set("aws_region", "some region")
        config.set("aws_secret_access_key", "foo")
        config.ready = True
        config.write(filter_sensitive=True)
        with open(LOCAL_CONFIG) as txt:
            contents = txt.read()
        assert "aws_region" in contents
        assert "aws_secret_access_key" not in contents

    def test_write_includes_all_keys_if_filter_sensitive_false(self, in_tempdir):
        config = get_config()
        config.set("aws_region", "some region")
        config.set("aws_secret_access_key", "foo")
        config.ready = True
        config.write(filter_sensitive=False)
        with open(LOCAL_CONFIG) as txt:
            contents = txt.read()
        assert "aws_region" in contents
        assert "aws_secret_access_key" in contents

    def test_write_accepts_alternate_directory(self):
        import tempfile

        target = os.path.join(tempfile.mkdtemp(), "custom")
        os.mkdir(target)
        config = get_config()
        config.set("aws_region", "some region")
        config.ready = True
        config.write(directory=target)
        with open(os.path.join(target, LOCAL_CONFIG)) as txt:
            contents = txt.read()
        assert "aws_region" in contents

    def test_experiment_config_defaults(self):
        config = get_config()
        config.load_experiment_config_defaults()

        assert config.get("duration") == 12345.0
