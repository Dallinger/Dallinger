from __future__ import unicode_literals

import io
import json
import logging
import os
import sys
from collections import deque
from contextlib import contextmanager
from pathlib import Path

import six
from setuptools.dist import strtobool
from six.moves import configparser

logger = logging.getLogger(__name__)

marker = object()

LOCAL_CONFIG = "config.txt"
SENSITIVE_KEY_NAMES = ("access_id", "access_key", "password", "secret", "token")


def is_valid_json(value):
    json.loads(value)


default_keys = (
    # These are the keys allowed in a dallinger experiment config.txt file.
    ("ad_group", six.text_type, []),
    ("approve_requirement", int, []),
    ("assign_qualifications", bool, []),
    ("auto_recruit", bool, []),
    ("aws_access_key_id", six.text_type, ["AWS_ACCESS_KEY_ID"], True),
    (
        "aws_region",
        six.text_type,
        ["AWS_REGION", "AWS_DEFAULT_REGION", "aws_default_region"],
    ),
    ("aws_secret_access_key", six.text_type, ["AWS_SECRET_ACCESS_KEY"], True),
    ("base_payment", float, []),
    ("base_port", int, []),
    ("browser_exclude_rule", six.text_type, []),
    ("clock_on", bool, []),
    ("contact_email_on_error", six.text_type, []),
    ("chrome-path", six.text_type, []),
    ("dallinger_develop_directory", six.text_type, []),
    ("dallinger_email_address", six.text_type, []),
    ("dashboard_password", six.text_type, [], True),
    ("dashboard_user", six.text_type, [], True),
    ("database_size", six.text_type, []),
    ("database_url", six.text_type, [], True),
    ("debug_recruiter", six.text_type, []),
    ("description", six.text_type, []),
    ("disable_browser_autotranslate", bool, []),
    ("disable_when_duration_exceeded", bool, []),
    ("duration", float, []),
    ("dyno_type", six.text_type, []),
    ("dyno_type_web", six.text_type, []),
    ("dyno_type_worker", six.text_type, []),
    ("ec2_default_pem", six.text_type, []),
    ("ec2_default_security_group", six.text_type, []),
    ("enable_global_experiment_registry", bool, []),
    ("EXPERIMENT_CLASS_NAME", six.text_type, []),
    ("group_name", six.text_type, []),
    ("heroku_app_id_root", six.text_type, []),
    ("heroku_auth_token", six.text_type, [], True),
    ("heroku_python_version", six.text_type, []),
    ("heroku_team", six.text_type, ["team"]),
    ("heroku_region", six.text_type, []),
    ("host", six.text_type, []),
    ("id", six.text_type, []),
    ("infrastructure_debug_details", six.text_type, [], False),
    ("keywords", six.text_type, []),
    ("language", six.text_type, []),
    ("lifetime", int, []),
    ("lock_table_when_creating_participant", bool, []),
    ("logfile", six.text_type, []),
    ("loglevel", int, []),
    ("loglevel_worker", int, []),
    ("mode", six.text_type, []),
    ("mturk_qualification_blocklist", six.text_type, ["qualification_blacklist"]),
    ("mturk_qualification_requirements", six.text_type, [], False, [is_valid_json]),
    ("num_dynos_web", int, []),
    ("num_dynos_worker", int, []),
    ("organization_name", six.text_type, []),
    ("port", int, ["PORT"]),
    ("prolific_api_token", six.text_type, ["PROLIFIC_RESEARCHER_API_TOKEN"], True),
    ("prolific_api_version", six.text_type, []),
    ("prolific_estimated_completion_minutes", int, []),
    ("prolific_is_custom_screening", bool, []),
    ("prolific_maximum_allowed_minutes", int, []),
    ("prolific_project", six.text_type, []),
    ("prolific_recruitment_config", six.text_type, [], False, [is_valid_json]),
    ("prolific_workspace", six.text_type, []),
    ("protected_routes", six.text_type, [], False, [is_valid_json]),
    ("publish_experiment", bool, []),
    ("recruiter", six.text_type, []),
    ("recruiters", six.text_type, []),
    ("redis_size", six.text_type, []),
    ("replay", bool, []),
    ("sentry", bool, []),
    ("smtp_host", six.text_type, []),
    ("smtp_username", six.text_type, []),
    ("smtp_password", six.text_type, ["dallinger_email_password"], True),
    ("threads", six.text_type, []),
    ("title", six.text_type, []),
    ("question_max_length", int, []),
    ("us_only", bool, []),
    ("webdriver_type", six.text_type, []),
    ("webdriver_url", six.text_type, []),
    ("whimsical", bool, []),
    ("worker_multiplier", float, []),
    ("docker_image_base_name", six.text_type, [], ""),
    ("docker_image_name", six.text_type, [], ""),
    ("docker_volumes", six.text_type, [], ""),
    ("docker_worker_cpu_shares", int, [], ""),
)


class Configuration(object):
    SUPPORTED_TYPES = {six.binary_type, six.text_type, int, float, bool}
    _experiment_params_loaded = False
    _module_params_loaded = False

    def __init__(self):
        self._reset()

    def set(self, key, value):
        return self.extend({key: value})

    def clear(self):
        self.data = deque()
        self.ready = False

    def _reset(self, register_defaults=False):
        self.clear()
        self.types = {}
        self.synonyms = {}
        self.validators = {}
        self.sensitive = set()
        self._experiment_params_loaded = False
        self._module_params_loaded = False
        if register_defaults:
            for registration in default_keys:
                self.register(*registration)

    def extend(self, mapping, cast_types=False, strict=False):
        normalized_mapping = {}
        for key, value in mapping.items():
            key = self.synonyms.get(key, key)
            test_deprecation(key)
            if key not in self.types:
                # This key hasn't been registered, we ignore it
                if strict:
                    raise_invalid_key_error(key)
                continue
            expected_type = self.types.get(key)
            if cast_types:
                if isinstance(value, six.text_type) and value.startswith("file:"):
                    # Load this value from a file
                    _, filename = value.split(":", 1)
                    with io.open(filename, "rt", encoding="utf-8") as source_file:
                        value = source_file.read()
                try:
                    if expected_type is bool:
                        value = strtobool(value)
                    value = expected_type(value)
                except ValueError:
                    pass
            if not isinstance(value, expected_type):
                raise TypeError(
                    "Got {value} for {key}, expected {expected_type}".format(
                        value=repr(value), key=key, expected_type=expected_type
                    )
                )
            for validator in self.validators.get(key, []):
                try:
                    validator(value)
                except ValueError as e:
                    # Annotate the exception with more info
                    e.dallinger_config_key = key
                    e.dallinger_config_value = value
                    raise e
            normalized_mapping[key] = value
        self.data.extendleft([normalized_mapping])

    @contextmanager
    def override(self, *args, **kwargs):
        self.extend(*args, **kwargs)
        yield self
        self.data.popleft()

    changeable_params = ["auto_recruit"]

    def get(self, key, default=marker):
        # For now this is limited to "auto_recruit", but in the future it can be extended
        # to other parameters as well
        if key == "auto_recruit":
            from dallinger.db import redis_conn

            auto_recruit = redis_conn.get("auto_recruit")
            if auto_recruit is not None:
                return bool(int(auto_recruit))
        if not self.ready:
            raise RuntimeError("Config not loaded")
        for layer in self.data:
            try:
                value = layer[key]
                if isinstance(value, six.text_type):
                    value = value.strip()
                return value
            except KeyError:
                continue
        if default is marker:
            error_text = f"The following config parameter was not set: {key}. Consider setting it in config.txt or in ~/.dallingerconfig."
            if key == "prolific_project":
                error_text += " Prolific projects will be created automatically if they don't exist already."
            raise KeyError(error_text)
        return default

    def __getitem__(self, key):
        return self.get(key)

    def __setitem__(self, key, value):
        return self.extend({key: value})

    def __getattr__(self, key):
        try:
            return self.get(key)
        except KeyError:
            raise AttributeError

    def as_dict(self, include_sensitive=False):
        d = {}
        for key in self.types:
            if key not in self.sensitive or include_sensitive:
                try:
                    d[key] = self.get(key)
                except KeyError:
                    pass
        return d

    def is_sensitive(self, key):
        if key in self.sensitive:
            return True
        # Also, does a sensitive string appear within the key?
        return any(s for s in SENSITIVE_KEY_NAMES if s in key)

    def register(self, key, type_, synonyms=None, sensitive=False, validators=None):
        if synonyms is None:
            synonyms = set()
        if key in self.types:
            raise KeyError("Config key {} is already registered".format(key))
        if type_ not in self.SUPPORTED_TYPES:
            raise TypeError("{type} is not a supported type".format(type=type_))
        self.types[key] = type_
        for synonym in synonyms:
            self.synonyms[synonym] = key

        if validators:
            self.validators[key] = validators

        if sensitive:
            self.sensitive.add(key)

    def load_from_file(self, filename, strict=True):
        parser = configparser.ConfigParser()
        parser.read(filename)
        data = {}
        for section in parser.sections():
            data.update(dict(parser.items(section)))
        self.extend(data, cast_types=True, strict=strict)

    def write(self, filter_sensitive=False, directory=None):
        parser = configparser.ConfigParser()
        parser.add_section("Parameters")
        for layer in reversed(self.data):
            for k, v in layer.items():
                if filter_sensitive and self.is_sensitive(k):
                    continue
                parser.set("Parameters", k, six.text_type(v))

        directory = directory or os.getcwd()
        destination = os.path.join(directory, LOCAL_CONFIG)
        with open(destination, "w") as fp:
            parser.write(fp)

    def load_from_environment(self):
        self.extend(os.environ, cast_types=True)

    def load_defaults(self, strict=True):
        """Load default configuration values"""
        # Apply extra parameters before loading the configs
        if experiment_available():
            # In practice, experiment_available should only return False in tests
            self.register_extra_parameters()

        global_config_name = ".dallingerconfig"
        global_config = os.path.expanduser(os.path.join("~/", global_config_name))
        defaults_folder = os.path.join(os.path.dirname(__file__), "default_configs")
        local_defaults_file = os.path.join(defaults_folder, "local_config_defaults.txt")
        global_defaults_file = os.path.join(
            defaults_folder, "global_config_defaults.txt"
        )

        # Load the configuration, with local parameters overriding global ones.
        for config_file in [global_defaults_file, local_defaults_file, global_config]:
            self.load_from_file(config_file, strict)

        if experiment_available():
            self.load_experiment_config_defaults()

    def load(self, strict=True):
        self.load_defaults(strict)

        localConfig = os.path.join(os.getcwd(), LOCAL_CONFIG)
        if os.path.exists(localConfig):
            self.load_from_file(localConfig, strict)

        self.load_from_environment()
        self.ready = True

    def register_extra_parameters(self):
        initialize_experiment_package(os.getcwd())
        extra_parameters = None

        # Import and instantiate the experiment class if available
        # This will run any experiment specific parameter registrations
        from dallinger.experiment import load

        exp_klass = load()
        exp_params = getattr(exp_klass, "extra_parameters", None)
        if exp_params is not None and not self._experiment_params_loaded:
            exp_params()
            self._experiment_params_loaded = True

        try:
            from dallinger_experiment.experiment import extra_parameters
        except ImportError:
            try:
                from dallinger_experiment.dallinger_experiment import extra_parameters
            except ImportError:
                try:
                    from dallinger_experiment import extra_parameters
                except ImportError:
                    pass
        if extra_parameters is not None and not self._module_params_loaded:
            extra_parameters()
            self._module_params_loaded = True

    def load_experiment_config_defaults(self):
        from dallinger.experiment import load

        exp_klass = load()
        self.extend(exp_klass.config_defaults(), strict=True)


config = None


def get_config():
    global config

    if config is None:
        if experiment_available():
            from dallinger.experiment import load

            exp_klass = load()
            config_class = exp_klass.config_class()
        else:
            config_class = Configuration

        config = config_class()

        for registration in default_keys:
            config.register(*registration)

    return config


def initialize_experiment_package(path):
    """Make the specified directory importable as the `dallinger_experiment` package."""
    # Create __init__.py if it doesn't exist (needed for Python 2)
    init_py = os.path.join(path, "__init__.py")
    if not os.path.exists(init_py):
        open(init_py, "a").close()
    # Retain already set experiment module
    if sys.modules.get("dallinger_experiment") is not None:
        return
    dirname = os.path.dirname(path)
    basename = os.path.basename(path)
    sys.path.insert(0, dirname)
    package = __import__(basename)
    if Path(path) not in [Path(p) for p in package.__path__]:
        raise Exception(
            "Package was not imported from the requested path! ({} not in {})".format(
                path, package.__path__
            )
        )
    sys.modules["dallinger_experiment"] = package
    package.__package__ = "dallinger_experiment"
    package.__name__ = "dallinger_experiment"
    sys.path.pop(0)


def experiment_available():
    return Path("experiment.py").exists()


def raise_invalid_key_error(key):
    error_text = "{} is not a valid configuration key".format(key)
    if key == "prolific_reward_cents":
        error_text = (
            "The 'prolific_reward_cents' config variable has been removed. "
            + "Use 'base_payment' instead to set base compensation for participants. "
            + "Note that base_payment is written in terms of the base unit for the currency, "
            + "not in cents. So, if your prolific_reward_cents was originally set to 50, "
            + "then you should set your base_payment to 0.5."
        )
    raise KeyError(error_text)


def test_deprecation(key):
    if key == "prolific_maximum_allowed_minutes":
        import warnings

        warnings.simplefilter("always", DeprecationWarning)
        warnings.warn(
            "The 'prolific_maximum_allowed_minutes' config variable has no effect "
            + "as it is currently ignored by the Prolific API.",
            DeprecationWarning,
        )
