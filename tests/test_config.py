import os
from tempfile import NamedTemporaryFile

import pytest

from dallinger.config import LOCAL_CONFIG, Configuration, get_config


class TestConfigurationUnitTests:
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
        config.register("data", str)
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

    def test_source_priority_beats_load_order(self):
        from dallinger.config import ConfigSource

        config = Configuration()
        config.register("mode", str)
        config.extend({"mode": "live"}, source=ConfigSource.ENVIRONMENT)
        # Loaded later, but from a lower-priority source.
        config.extend({"mode": "sandbox"}, source=ConfigSource.USER_CONFIG)
        config.ready = True
        assert config.get("mode") == "live"

    def test_runtime_writes_beat_all_sources(self):
        from dallinger.config import ConfigSource

        config = Configuration()
        config.register("mode", str)
        config.extend({"mode": "live"}, source=ConfigSource.ENVIRONMENT)
        config.ready = True
        config.set("mode", "debug")
        assert config.get("mode") == "debug"

    def test_newest_layer_wins_within_a_source(self):
        from dallinger.config import ConfigSource

        config = Configuration()
        config.register("mode", str)
        config.extend({"mode": "sandbox"}, source=ConfigSource.USER_CONFIG)
        config.extend({"mode": "live"}, source=ConfigSource.USER_CONFIG)
        config.ready = True
        assert config.get("mode") == "live"

    def test_write_reflects_source_priority(self, in_tempdir):
        from dallinger.config import LOCAL_CONFIG, ConfigSource

        config = Configuration()
        config.register("mode", str)
        config.extend({"mode": "live"}, source=ConfigSource.ENVIRONMENT)
        config.extend({"mode": "sandbox"}, source=ConfigSource.USER_CONFIG)
        config.ready = True
        config.write()
        with open(LOCAL_CONFIG) as txt:
            assert "mode = live" in txt.read()

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

        config.register("fave_colour", str, validators=[is_purple])
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
        config.register("test_string", str)
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
        config.register("mode", str)
        config.register("num_participants", int, synonyms={"n"})
        config.register("deploy_worldwide", bool, synonyms={"worldwide"})
        mode_with_trailing_whitespace = "live    "
        contents = """
[Example Section]
mode = {}
num_participants = 10
worldwide = false
""".format(mode_with_trailing_whitespace)

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
class TestConfigurationIntegrationTests:
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

    def test_experiment_config_settings_priority(self, tmpdir, monkeypatch):
        # Experiment.config_settings() values are authoritative: they beat
        # ~/.dallingerconfig, but config.txt still wins because it has a
        # higher source priority (EXPERIMENT_CONFIG > EXPERIMENT_SETTINGS).
        import dallinger.config
        from dallinger.experiment import load as load_experiment

        exp_klass = load_experiment()
        monkeypatch.setattr(
            exp_klass,
            "config_settings",
            classmethod(
                lambda cls: {
                    # Not in config.txt: should win over ~/.dallingerconfig.
                    "group_name": "from_class_settings",
                    # Also in config.txt: config.txt should win.
                    "organization_name": "settings_should_lose",
                }
            ),
        )
        monkeypatch.setenv("HOME", str(tmpdir))
        with open(os.path.join(str(tmpdir), ".dallingerconfig"), "w") as f:
            f.write("[Parameters]\ngroup_name = from_user_config\n")

        saved_config = dallinger.config.config
        try:
            dallinger.config.config = None
            config = get_config(load=True)
            assert config.get("group_name") == "from_class_settings"
            assert config.get("organization_name") != "settings_should_lose"
        finally:
            dallinger.config.config = saved_config

    def test_load_resolves_same_config_after_cwd_change(self, tmpdir, monkeypatch):
        # Long-running processes (workers, CLI tools) may load config after
        # the current working directory has changed away from the experiment
        # directory. Once the experiment package has been initialized, such
        # processes must resolve the same config values (experiment defaults
        # and config.txt included) as processes loading from the experiment
        # directory (see https://gitlab.com/PsyNetDev/PsyNet/-/issues/1040).
        import sys

        import dallinger.config
        from dallinger.config import ConfigSource, initialize_experiment_package

        saved_experiment_module = sys.modules.get("dallinger_experiment")
        saved_config = dallinger.config.config
        initialize_experiment_package(os.getcwd())
        original_cwd = os.getcwd()
        # Isolate the test from any real ~/.dallingerconfig.
        monkeypatch.setenv("HOME", str(tmpdir))
        # An unrelated config.txt in the directory the process changes into
        # must not shadow the experiment's own config.txt.
        with open(os.path.join(str(tmpdir), "config.txt"), "w") as f:
            f.write("[Parameters]\norganization_name = stray_config\n")
        try:
            # Reference: a fresh config loaded from the experiment directory.
            dallinger.config.config = None
            reference = get_config(load=True)

            # A fresh config loaded after changing the working directory.
            os.chdir(str(tmpdir))
            dallinger.config.config = None
            config = get_config(load=True)

            assert config.get("duration") == reference.get("duration")
            assert config.get("title") == reference.get("title")
            assert config.get("organization_name") == reference.get("organization_name")
            # The experiment class defaults layer was applied, not skipped.
            defaults_layers = [
                layer
                for layer in config.data
                if layer.source == ConfigSource.EXPERIMENT_DEFAULTS
            ]
            assert defaults_layers and defaults_layers[0]["duration"] == 12345.0
        finally:
            os.chdir(original_cwd)
            dallinger.config.config = saved_config
            if saved_experiment_module is None:
                sys.modules.pop("dallinger_experiment", None)
            else:
                sys.modules["dallinger_experiment"] = saved_experiment_module

    def test_exp_class_working_dir_reload_keeps_env_priority(self, tmpdir, monkeypatch):
        # Regression test: the config.txt reload performed by the
        # exp_class_working_dir decorator must be tagged EXPERIMENT_CONFIG,
        # so environment variables keep their higher priority.
        import sys
        import types

        import dallinger.config
        from dallinger.experiment import exp_class_working_dir

        # Isolate the test from any real ~/.dallingerconfig.
        monkeypatch.setenv("HOME", str(tmpdir))
        module = types.ModuleType("fake_experiment_module")
        module.__file__ = os.path.join(os.getcwd(), "experiment.py")
        monkeypatch.setitem(sys.modules, "fake_experiment_module", module)
        monkeypatch.setenv("organization_name", "from_environment")

        captured = {}

        class Runner:
            __module__ = "fake_experiment_module"

            @exp_class_working_dir
            def run(self):
                captured["organization_name"] = get_config().get("organization_name")

        saved_config = dallinger.config.config
        try:
            dallinger.config.config = None
            config = get_config(load=True)
            # Sanity check: the environment beats config.txt in a full load.
            assert config.get("organization_name") == "from_environment"
            Runner().run()
        finally:
            dallinger.config.config = saved_config

        # The decorator's config.txt reload must not demote the environment.
        assert captured["organization_name"] == "from_environment"

    def test_get_config_without_load_does_not_load(self):
        # The experiment loader import inside get_config() used to shadow the
        # `load` parameter, forcing an eager config load whenever an
        # experiment was available.
        import dallinger.config

        saved_config = dallinger.config.config
        try:
            dallinger.config.config = None
            config = get_config()
            assert not config.ready
        finally:
            dallinger.config.config = saved_config

    def test_experiment_available_ignores_stale_experiment_module(
        self, tmpdir, monkeypatch
    ):
        # A `dallinger_experiment` entry in sys.modules that does not point at
        # a real experiment (e.g. a leftover namespace package) should not make
        # experiment_available() return True.
        import sys
        import types

        from dallinger.config import experiment_available

        stale = types.ModuleType("dallinger_experiment")
        stale.__path__ = [str(tmpdir)]  # No experiment module in there.
        monkeypatch.setitem(sys.modules, "dallinger_experiment", stale)
        original_cwd = os.getcwd()
        os.chdir(str(tmpdir))
        try:
            assert not experiment_available()
        finally:
            os.chdir(original_cwd)
