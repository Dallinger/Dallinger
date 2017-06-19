from __future__ import unicode_literals

from collections import deque
from ConfigParser import SafeConfigParser
import distutils.util
import imp
import logging
import os
import sys
import threading

from .compat import unicode

logger = logging.getLogger(__file__)

marker = object()

LOCAL_CONFIG = 'config.txt'
SENSITIVE_KEY_NAMES = (
    'access_id',
    'access_key',
    'password',
    'secret',
    'token',
)

default_keys = (
    ('ad_group', unicode, []),
    ('approve_requirement', int, []),
    ('auto_recruit', bool, []),
    ('aws_access_key_id', unicode, [], True),
    ('aws_region', unicode, []),
    ('aws_secret_access_key', unicode, [], True),
    ('base_payment', float, []),
    ('browser_exclude_rule', unicode, []),
    ('clock_on', bool, []),
    ('contact_email_on_error', unicode, []),
    ('dallinger_email_address', unicode, []),
    ('dallinger_email_password', unicode, [], True),
    ('database_size', unicode, []),
    ('database_url', unicode, []),
    ('description', unicode, []),
    ('duration', float, []),
    ('dyno_type', unicode, []),
    ('group_name', unicode, []),
    ('heroku_auth_token', unicode, [], True),
    ('heroku_team', unicode, ['team']),
    ('host', unicode, []),
    ('id', unicode, []),
    ('keywords', unicode, []),
    ('lifetime', int, []),
    ('logfile', unicode, []),
    ('loglevel', int, []),
    ('mode', unicode, []),
    ('notification_url', unicode, []),
    ('num_dynos_web', int, []),
    ('num_dynos_worker', int, []),
    ('organization_name', unicode, []),
    ('port', int, ['PORT']),
    ('qualification_blacklist', unicode, []),
    ('qualification_blacklist_experience_limit', int, []),
    ('recruiter', unicode, []),
    ('threads', unicode, []),
    ('title', unicode, []),
    ('us_only', bool, []),
    ('webdriver_type', unicode, []),
    ('webdriver_url', unicode, []),
    ('whimsical', bool, []),
)


class Configuration(object):

    SUPPORTED_TYPES = {
        bytes,
        unicode,
        int,
        float,
        bool,
    }

    def __init__(self):
        self._reset()

    def set(self, key, value):
        return self.extend({key: value})

    def _reset(self):
        self.data = deque()
        self.types = {}
        self.synonyms = {}
        self.sensitive = set()
        self.ready = False

    def extend(self, mapping, cast_types=False, strict=False):
        normalized_mapping = {}
        for key, value in mapping.items():
            key = self.synonyms.get(key, key)
            if key not in self.types:
                # This key hasn't been registered, we ignore it
                if strict:
                    raise KeyError('{} is not a valid configuration key'.format(key))
                logger.debug('{} is not a valid configuration key'.format(key))
                continue
            expected_type = self.types.get(key)
            if cast_types:
                try:
                    if expected_type == bool:
                        value = distutils.util.strtobool(value)
                    value = expected_type(value)
                except ValueError:
                    pass
            if not isinstance(value, expected_type):
                raise TypeError(
                    'Got {value} for {key}, expected {expected_type}'
                    .format(
                        value=repr(value),
                        key=key,
                        expected_type=expected_type,
                    )
                )
            normalized_mapping[key] = value
        self.data.extendleft([normalized_mapping])

    def get(self, key, default=marker):
        if not self.ready:
            raise RuntimeError('Config not loaded')
        for layer in self.data:
            try:
                return layer[key]
            except KeyError:
                continue
        if default is marker:
            raise KeyError(key)
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

    def as_dict(self):
        d = {}
        for key in self.types:
            if key not in self.sensitive:
                try:
                    d[key] = self.get(key)
                except KeyError:
                    pass
        return d

    def register(self, key, type_, synonyms=None, sensitive=False):
        if synonyms is None:
            synonyms = set()
        if key in self.types:
            raise KeyError('Config key {} is already registered'.format(key))
        if type_ not in self.SUPPORTED_TYPES:
            raise TypeError(
                '{type} is not a supported type'.format(
                    type=type_
                )
            )
        self.types[key] = type_
        for synonym in synonyms:
            self.synonyms[synonym] = key

        if sensitive:
            self.sensitive.add(key)

    def load_from_file(self, filename):
        parser = SafeConfigParser()
        parser.read(filename)
        data = {}
        for section in parser.sections():
            data.update(dict(parser.items(section)))
        self.extend(data, cast_types=True, strict=True)

    def write(self, filter_sensitive=False):
        parser = SafeConfigParser()
        parser.add_section('Parameters')
        for layer in reversed(self.data):
            for k, v in layer.items():
                if (filter_sensitive and k in self.sensitive or
                        [s for s in SENSITIVE_KEY_NAMES if s in k]):
                    continue
                parser.set('Parameters', k, str(v))

        with open(LOCAL_CONFIG, 'w') as fp:
            parser.write(fp)

    def load_from_environment(self):
        self.extend(os.environ, cast_types=True)

    def load(self):
        # Apply extra parameters before loading the configs
        self.register_extra_parameters()

        globalConfigName = ".dallingerconfig"
        globalConfig = os.path.expanduser(os.path.join("~/", globalConfigName))
        localConfig = os.path.join(os.getcwd(), LOCAL_CONFIG)

        defaults_folder = os.path.join(os.path.dirname(__file__), "default_configs")
        local_defaults_file = os.path.join(defaults_folder, "local_config_defaults.txt")
        global_defaults_file = os.path.join(defaults_folder, "global_config_defaults.txt")

        # Load the configuration, with local parameters overriding global ones.
        for config_file in [
            global_defaults_file,
            local_defaults_file,
            globalConfig,
        ]:
            self.load_from_file(config_file)

        if os.path.exists(localConfig):
            self.load_from_file(localConfig)

        self.load_from_environment()
        self.ready = True

    def register_extra_parameters(self):
        extra_parameters = None
        cwd = os.getcwd()
        sys.path.append(cwd)
        path_index = len(sys.path) - 1
        try:
            from dallinger_experiment import extra_parameters
        except ImportError:
            try:
                exp = imp.load_source('dallinger_experiment', "dallinger_experiment.py")
                extra_parameters = getattr(exp, 'extra_parameters', None)
            except IOError:
                pass
            if extra_parameters is None:
                try:
                    # We may be in the original source directory, try experiment.py
                    exp = imp.load_source('dallinger_experiment', "experiment.py")
                    extra_parameters = getattr(exp, 'extra_parameters', None)
                except IOError:
                    pass
        if extra_parameters is not None and getattr(extra_parameters, 'loaded', None) is None:
            extra_parameters()
            extra_parameters.loaded = True
        # Remove path element we added
        sys.path.pop(path_index)


configurations = threading.local()


def get_config():
    if hasattr(configurations, 'config'):
        return configurations.config
    configurations.config = Configuration()

    for registration in default_keys:
        configurations.config.register(*registration)

    return configurations.config
