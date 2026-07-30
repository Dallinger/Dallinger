"""Experiment configuration loading and resolution.

Configuration values come from several sources with a fixed precedence,
lowest to highest:

1. Dallinger package defaults (``dallinger/default_configs/``)
2. Experiment class defaults (``Experiment.config_defaults()``)
3. The user's ``~/.dallingerconfig``
4. Experiment class settings (``Experiment.config_settings()``)
5. The experiment's ``config.txt``
6. Environment variables
7. Runtime writes (``config.set()``, ``config.extend()``, ``config.override()``)

After an experiment package has been initialized (see
:func:`initialize_experiment_package`), its directory is used when the
process changes into a non-experiment directory. A current working
directory containing ``experiment.py`` still takes precedence, so a process
should not move between different experiment roots.
"""

import configparser
import enum
import io
import json
import logging
import os
import sys
from collections import deque
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

marker = object()

LOCAL_CONFIG = "config.txt"
SENSITIVE_KEY_NAMES = ("access_id", "access_key", "password", "secret", "token")


def is_valid_json(value):
    json.loads(value)


def strtobool(val: str) -> int:
    """Convert a string representation of truth to true (1) or false (0).

    True values are 'y', 'yes', 't', 'true', 'on', and '1'; false values
    are 'n', 'no', 'f', 'false', 'off', and '0'.  Raises ValueError if
    'val' is anything else.

    Notes
    -----
    This implementation is derived from the `strtobool` function in setuptools,
    which itself is based on the original in Python's distutils.

    Source: https://github.com/pypa/setuptools/blob/main/setuptools/dist.py

    Copyright (c) 2016-2024 Python Packaging Authority (PyPA)
    Licensed under the MIT License.
    """
    val = val.lower()
    if val in ("y", "yes", "t", "true", "on", "1"):
        return 1
    if val in ("n", "no", "f", "false", "off", "0"):
        return 0
    raise ValueError(f"invalid truth value {val!r}")


default_keys = (
    # These are the keys allowed in a dallinger experiment config.txt file.
    ("ad_group", str, []),
    ("approve_requirement", int, []),
    ("assign_qualifications", bool, []),
    ("auto_recruit", bool, []),
    ("allow_repeat_worker_ids", bool, []),
    ("aws_access_key_id", str, ["AWS_ACCESS_KEY_ID"], True),
    (
        "aws_region",
        str,
        ["AWS_REGION", "AWS_DEFAULT_REGION", "aws_default_region"],
    ),
    ("aws_secret_access_key", str, ["AWS_SECRET_ACCESS_KEY"], True),
    ("base_payment", float, []),
    ("base_port", int, []),
    ("browser_exclude_rule", str, []),
    ("clock_on", bool, []),
    ("contact_email_on_error", str, []),
    ("chrome-path", str, []),
    ("dallinger_develop_directory", str, []),
    ("dallinger_email_address", str, []),
    ("dashboard_password", str, [], True),
    ("dashboard_user", str, [], True),
    ("database_size", str, []),
    ("database_url", str, [], True),
    ("debug_recruiter", str, []),
    ("description", str, []),
    ("disable_browser_autotranslate", bool, []),
    ("disable_when_duration_exceeded", bool, []),
    ("duration", float, []),
    ("dyno_type", str, []),
    ("dyno_type_web", str, []),
    ("dyno_type_worker", str, []),
    ("ec2_default_pem", str, []),
    ("ec2_default_security_group", str, []),
    ("enable_global_experiment_registry", bool, []),
    ("EXPERIMENT_CLASS_NAME", str, []),
    ("group_name", str, []),
    ("heroku_app_id_root", str, []),
    ("heroku_auth_token", str, [], True),
    ("heroku_python_version", str, []),
    ("heroku_team", str, ["team"]),
    ("heroku_region", str, []),
    ("host", str, []),
    ("id", str, []),
    ("infrastructure_debug_details", str, [], False),
    ("keywords", str, []),
    ("language", str, []),
    ("lifetime", int, []),
    ("lock_table_when_creating_participant", bool, []),
    ("logfile", str, []),
    ("loglevel", int, []),
    ("loglevel_worker", int, []),
    ("mode", str, []),
    ("mturk_qualification_blocklist", str, ["qualification_blacklist"]),
    ("mturk_qualification_requirements", str, [], False, [is_valid_json]),
    ("num_dynos_web", int, []),
    ("num_dynos_worker", int, []),
    ("organization_name", str, []),
    ("port", int, ["PORT"]),
    ("prolific_api_token", str, ["PROLIFIC_RESEARCHER_API_TOKEN"], True),
    ("prolific_api_version", str, []),
    ("prolific_completion_config", str, [], False, [is_valid_json]),
    ("prolific_completion_codes", str, [], False, [is_valid_json]),
    ("prolific_estimated_completion_minutes", int, []),
    ("prolific_is_custom_screening", bool, []),
    ("prolific_maximum_allowed_minutes", int, []),
    ("prolific_project", str, []),
    ("prolific_recruitment_config", str, [], False, [is_valid_json]),
    ("prolific_workspace", str, []),
    ("protected_routes", str, [], False, [is_valid_json]),
    ("publish_experiment", bool, []),
    ("recruiter", str, []),
    ("recruiters", str, []),
    ("redis_size", str, []),
    ("replay", bool, []),
    ("sentry", bool, []),
    ("smtp_host", str, []),
    ("smtp_username", str, []),
    ("smtp_password", str, ["dallinger_email_password"], True),
    ("threads", str, []),
    ("title", str, []),
    ("question_max_length", int, []),
    ("us_only", bool, []),
    ("webdriver_type", str, []),
    ("webdriver_url", str, []),
    ("whimsical", bool, []),
    ("worker_multiplier", float, []),
    ("docker_image_base_name", str, [], ""),
    ("docker_image_name", str, [], ""),
    ("docker_volumes", str, [], ""),
    ("docker_worker_cpu_shares", int, [], ""),
    ("server_pem", str, []),
)


class ConfigSource(enum.IntEnum):
    """Configuration sources, ordered by resolution priority (higher wins)."""

    PACKAGE_DEFAULTS = 10
    EXPERIMENT_DEFAULTS = 20
    USER_CONFIG = 30
    EXPERIMENT_SETTINGS = 35
    EXPERIMENT_CONFIG = 40
    ENVIRONMENT = 50
    RUNTIME = 60


class ConfigLayer(dict):
    """A mapping of config values tagged with the source that provided them.

    Subclassing dict preserves structural compatibility for callers that
    inspect ``Configuration.data``. Raw layer iteration still follows load
    order; callers needing resolved values should use
    :meth:`Configuration.get` or :meth:`Configuration.as_dict`.
    """

    __slots__ = ("source",)

    def __init__(self, mapping, source):
        super().__init__(mapping)
        self.source = source


class Configuration:
    SUPPORTED_TYPES = {bytes, str, int, float, bool}
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

    def extend(self, mapping, cast_types=False, strict=False, source=None):
        """Add a layer of config values, tagged with their source.

        ``source`` defaults to :attr:`ConfigSource.RUNTIME`, the highest
        priority, so ad-hoc writes always win over file-based sources.
        """
        if source is None:
            source = ConfigSource.RUNTIME
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
                if isinstance(value, str) and value.startswith("file:"):
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
        self.data.extendleft([ConfigLayer(normalized_mapping, source)])

    def _layers_by_priority(self):
        """Return layers ordered highest-priority first.

        ``self.data`` is newest-first; the stable sort preserves that order
        within a source, so the newest layer of a source wins.
        """
        return sorted(self.data, key=lambda layer: -layer.source)

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
        for layer in self._layers_by_priority():
            try:
                value = layer[key]
                if isinstance(value, str):
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

    def load_from_file(self, filename, strict=True, source=None):
        parser = configparser.ConfigParser()
        parser.read(filename)
        data = {}
        for section in parser.sections():
            data.update(dict(parser.items(section)))
        self.extend(data, cast_types=True, strict=strict, source=source)

    def write(self, filter_sensitive=False, directory=None):
        parser = configparser.ConfigParser()
        parser.add_section("Parameters")
        # Lowest priority first (oldest first within a source), so later
        # parser.set calls overwrite earlier ones and the written file
        # reflects the resolved configuration.
        for layer in sorted(reversed(self.data), key=lambda layer: layer.source):
            for k, v in layer.items():
                if filter_sensitive and self.is_sensitive(k):
                    continue
                parser.set("Parameters", k, str(v))

        directory = directory or os.getcwd()
        destination = os.path.join(directory, LOCAL_CONFIG)
        with open(destination, "w") as fp:
            parser.write(fp)

    def load_from_environment(self):
        self.extend(os.environ, cast_types=True, source=ConfigSource.ENVIRONMENT)

    def load_defaults(self, strict=True):
        """Load default configuration values"""
        # Apply extra parameters before loading the configs
        if experiment_available():
            # In practice this is False only in non-experiment contexts such
            # as tests: no experiment.py in the current directory and no
            # experiment package initialized in this process.
            self.register_extra_parameters()

        global_config_name = ".dallingerconfig"
        global_config = os.path.expanduser(os.path.join("~/", global_config_name))
        defaults_folder = os.path.join(os.path.dirname(__file__), "default_configs")
        local_defaults_file = os.path.join(defaults_folder, "local_config_defaults.txt")
        global_defaults_file = os.path.join(
            defaults_folder, "global_config_defaults.txt"
        )

        # Load the package defaults, with local parameters overriding global ones.
        for config_file in [global_defaults_file, local_defaults_file]:
            self.load_from_file(
                config_file, strict, source=ConfigSource.PACKAGE_DEFAULTS
            )

        if experiment_available():
            self.load_experiment_config_defaults()

        self.load_from_file(global_config, strict, source=ConfigSource.USER_CONFIG)

    def load(self, strict=True):
        self.load_defaults(strict)

        if experiment_available():
            self.load_experiment_config_settings()

        # Load config.txt from the experiment's directory, so processes
        # that changed their working directory still resolve the same
        # configuration (and unrelated config.txt files in the current
        # directory cannot shadow the experiment's). Outside an experiment,
        # fall back to the current directory.
        local_config = os.path.join(experiment_directory() or os.getcwd(), LOCAL_CONFIG)
        if os.path.exists(local_config):
            self.load_from_file(
                local_config, strict, source=ConfigSource.EXPERIMENT_CONFIG
            )

        self.load_from_environment()
        self.ready = True

    def register_extra_parameters(self):
        initialize_experiment_package(experiment_directory() or os.getcwd())
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

        if extra_parameters is None and exp_klass is not None:
            extra_parameters = getattr(
                sys.modules[exp_klass.__module__], "extra_parameters", None
            )

        if extra_parameters is not None and not self._module_params_loaded:
            extra_parameters()
            self._module_params_loaded = True

    def _load_experiment_mapping(self, method_name, source):
        """Load a config mapping returned by a classmethod on the experiment class."""
        from dallinger.experiment import load

        exp_klass = load()
        mapping = getattr(exp_klass, method_name)()
        if mapping:
            self.extend(mapping, strict=True, source=source)

    def load_experiment_config_defaults(self):
        """Load suggested defaults from ``Experiment.config_defaults()``."""
        self._load_experiment_mapping(
            "config_defaults", ConfigSource.EXPERIMENT_DEFAULTS
        )

    def load_experiment_config_settings(self):
        """Load authoritative settings from ``Experiment.config_settings()``."""
        self._load_experiment_mapping(
            "config_settings", ConfigSource.EXPERIMENT_SETTINGS
        )


config = None


def get_config(load=False):
    global config

    if config is None:
        if experiment_available():
            # Import under a different name to avoid shadowing the `load`
            # parameter, which would otherwise force config loading below.
            from dallinger.experiment import load as load_experiment

            exp_klass = load_experiment()
            config_class = exp_klass.config_class()
        else:
            config_class = Configuration

        config = config_class()

        for registration in default_keys:
            config.register(*registration)

    if load and not config.ready:
        config.load()

    return config


def initialize_experiment_package(path):
    """Make the specified directory importable as the `dallinger_experiment` package."""
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


def experiment_directory():
    """Return the directory of the current experiment, or None.

    The current working directory counts if it contains an
    ``experiment.py`` file. Otherwise, fall back to the directory of the
    experiment package initialized in this process (via
    ``initialize_experiment_package``), provided that package contains
    ``experiment.py`` or ``dallinger_experiment.py``. This preserves the
    experiment's config layers after changing into a non-experiment
    directory. If the new directory contains another ``experiment.py``, the
    current working directory takes precedence.
    """
    if Path("experiment.py").exists():
        return os.getcwd()
    module = sys.modules.get("dallinger_experiment")
    if module is None:
        return None
    # Only count initialized packages that actually contain an experiment
    # module that ``dallinger.experiment.load`` could import; this guards
    # against stale or accidental `dallinger_experiment` entries (e.g.
    # namespace packages without any real location).
    module_paths = getattr(module, "__path__", None) or []
    for path in module_paths:
        for filename in ("experiment.py", "dallinger_experiment.py"):
            if Path(path, filename).exists():
                return path
    return None


def experiment_available():
    """Return True if an experiment is available in the current process."""
    return experiment_directory() is not None


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
