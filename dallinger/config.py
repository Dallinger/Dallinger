from __future__ import unicode_literals

from collections import deque
from ConfigParser import SafeConfigParser
import distutils.util
import imp
import logging
import os
import threading

from .compat import unicode

logger = logging.getLogger(__file__)

marker = object()

LOCAL_CONFIG = 'config.txt'
SENSITIVE_KEY_NAMES = ('secret', 'access_key', 'access_id', 'password', 'token')


class Configuration(object):

    SUPPORTED_TYPES = {
        bytes,
        unicode,
        int,
        float,
        bool,
    }

    def __init__(self):
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
                logger.warn('{} is not a valid configuration key'.format(key))
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
                raise ValueError(
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

    def register(self, key, type_, synonyms=set(), sensitive=False):
        if key in self.types:
            raise KeyError('Config key {} is already registered'.format(key))
        if type_ not in self.SUPPORTED_TYPES:
            raise ValueError(
                '{type} is not a supported type'.format(
                    type=type_
                )
            )
        self.types[key] = type_
        for synonym in synonyms:
            self.synonyms[synonym] = key

        if sensitive:
            self.sensitive.add(key)

    def load_from_config_file(self, filename):
        parser = SafeConfigParser()
        parser.read(filename)
        data = {}
        for section in parser.sections():
            data.update(dict(parser.items(section)))
        self.extend(data, cast_types=True)

    def write_config(self, filter_sensitive=False):
        parser = SafeConfigParser()
        parser.add_section('Parameters')
        for layer in reversed(self.data):
            for k, v in layer.items():
                if (filter_sensitive and k in self.sensitive or
                        [s for s in SENSITIVE_KEY_NAMES if s in k]):
                    continue
                parser.set('Parameters', k, str(v))

        # @@@ Temporary workaround until we remove use of psiturk recruiter
        parser.add_section('Database Parameters')
        for key in ('database_url', 'table_name', 'database_size'):
            parser.set('Database Parameters', key, str(self.get(key)))
        parser.add_section('Server Parameters')
        for key in ('host', 'port', 'notification_url'):
            parser.set('Server Parameters', key, str(self.get(key)))
        parser.add_section('HIT Configuration')
        for key in (
                'organization_name', 'title', 'contact_email_on_error', 'ad_group',
                'psiturk_keywords', 'browser_exclude_rule', 'approve_requirement',
                'us_only', 'lifetime', 'description', 'amt_keywords'):
            parser.set('HIT Configuration', key, str(self.get(key)))

        with open(LOCAL_CONFIG, 'w') as fp:
            parser.write(fp)

    def load_from_environment(self):
        self.extend(os.environ, cast_types=True)

    def load_config(self):
        if self.ready:
            raise ValueError("Already loaded")

        # Apply extra settings before loading the configs
        self.register_extra_settings()

        globalConfigName = ".dallingerconfig"
        if 'OPENSHIFT_SECRET_TOKEN' in os.environ:
            globalConfig = os.path.join(os.environ['OPENSHIFT_DATA_DIR'], globalConfigName)
        else:
            globalConfig = os.path.expanduser(os.path.join("~/", globalConfigName))
        localConfig = os.path.join(os.getcwd(), LOCAL_CONFIG)

        defaults_folder = os.path.join(os.path.dirname(__file__), "default_configs")
        local_defaults_file = os.path.join(defaults_folder, "local_config_defaults.txt")
        global_defaults_file = os.path.join(defaults_folder, "global_config_defaults.txt")

        # Load the configuration, with local settings overriding global ones.
        for config_file in [
            global_defaults_file,
            local_defaults_file,
            globalConfig,
        ]:
            self.load_from_config_file(config_file)

        if os.path.exists(localConfig):
            self.load_from_config_file(localConfig)

        self.load_from_environment()
        self.ready = True

    def register_extra_settings(self):
        extra_settings = None
        try:
            from dallinger_experiment import extra_settings
        except ImportError:
            try:
                exp = imp.load_source('dallinger_experiment', "dallinger_experiment.py")
                extra_settings = getattr(exp, 'extra_settings', None)
            except (ImportError, IOError):
                pass
            if extra_settings is None:
                try:
                    # We may be in the original source directory, try experiment.py
                    exp = imp.load_source('dallinger_experiment', "experiment.py")
                    extra_settings = getattr(exp, 'extra_settings', None)
                except (ImportError, IOError):
                    pass
        if extra_settings is not None and getattr(extra_settings, 'loaded', None) is None:
            extra_settings()
            extra_settings.loaded = True


configurations = threading.local()


def get_config():
    if hasattr(configurations, 'config'):
        return configurations.config
    configurations.config = Configuration()

    default_keys = (
        ('ad_group', unicode, []),
        ('amt_keywords', unicode, []),
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
        ('heroku_email_address', unicode, [], True),
        ('heroku_password', unicode, [], True),
        ('heroku_team', unicode, []),
        ('host', unicode, []),
        ('port', int, ['PORT']),
        ('launch_in_sandbox_mode', bool, []),
        ('lifetime', int, []),
        ('logfile', unicode, []),
        ('loglevel', int, []),
        ('mode', unicode, []),
        ('notification_url', unicode, []),
        ('num_dynos_web', int, []),
        ('num_dynos_worker', int, []),
        ('num_participants', int, []),
        ('organization_name', unicode, []),
        ('psiturk_access_key_id', unicode, [], True),
        ('psiturk_secret_access_id', unicode, [], True),
        ('table_name', unicode, []),
        ('threads', unicode, []),
        ('title', unicode, []),
        ('us_only', bool, []),
        ('whimsical', bool, []),
    )

    for registration in default_keys:
        configurations.config.register(*registration)

    return configurations.config
