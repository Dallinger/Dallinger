from __future__ import unicode_literals

from collections import deque
from ConfigParser import SafeConfigParser
import distutils.util
import os
import threading

from .compat import unicode

marker = object()

LOCAL_CONFIG = 'config.txt'


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
        self.ready = False

    def extend(self, mapping, cast_types=False):
        normalized_mapping = {}
        for key, value in mapping.items():
            key = self.synonyms.get(key, key)
            if key not in self.types:
                # This key hasn't been registered, we ignore it
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
            raise RuntimeError('Config loading not finished')
        for layer in self.data:
            try:
                return layer[key]
            except KeyError:
                continue
        if default is marker:
            raise KeyError(key)
        return default

    def register(self, key, type_, synonyms=set()):
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

    def load_from_config_file(self, filename):
        parser = SafeConfigParser()
        parser.read(filename)
        data = {}
        for section in parser.sections():
            data.update(dict(parser.items(section)))
        self.extend(data, cast_types=True)

    def write_config(self):
        parser = SafeConfigParser()
        parser.add_section('Parameters')
        for layer in reversed(self.data):
            for k, v in layer.items():
                parser.set('Parameters', k, str(v))
        with open(LOCAL_CONFIG, 'w') as fp:
            parser.write(fp)

    def load_from_environment(self):
        self.extend(os.environ, cast_types=True)

    def load_config(self):
        if self.ready:
            raise ValueError("Already loaded")
        globalConfigName = ".dallingerconfig"
        if 'OPENSHIFT_SECRET_TOKEN' in os.environ:
            globalConfig = os.path.join(os.environ['OPENSHIFT_DATA_DIR'], globalConfigName)
        else:
            globalConfig = os.path.expanduser(os.path.join("~/", globalConfigName))
        localConfig = os.path.join(os.getcwd(), LOCAL_CONFIG)

        defaults_folder = os.path.join(os.path.dirname(__file__), "default_configs")
        local_defaults_file = os.path.join(defaults_folder, "local_config_defaults.txt")
        global_defaults_file = os.path.join(defaults_folder, "global_config_defaults.txt")
        if not os.path.exists(localConfig):
            raise ValueError("No config.txt in the current directory")

        # read default global and local, then user's global and local. This way
        # any field not in the user's files will be set to the default value.
        for config_file in [global_defaults_file, local_defaults_file, globalConfig, localConfig]:
            self.load_from_config_file(config_file)
        self.ready = True


configurations = threading.local()


def get_config():
    if hasattr(configurations, 'config'):
        return configurations.config
    configurations.config = Configuration()

    for key, type_, synonyms in (
        ('ad_group', unicode, []),
        ('amt_keywords', unicode, []),
        ('anonymize_data', bool, []),
        ('approve_requirement', int, []),
        ('auto_recruit', bool, []),
        ('aws_access_key_id', unicode, []),
        ('aws_region', unicode, []),
        ('aws_secret_access_key', unicode, []),
        ('base_payment', float, []),
        ('browser_exclude_rule', unicode, []),
        ('clock_on', bool, []),
        ('contact_email_on_error', unicode, []),
        ('dallinger_email_address', unicode, []),
        ('dallinger_email_password', unicode, []),
        ('database_size', unicode, []),
        ('database_url', unicode, []),
        ('description', unicode, []),
        ('duration', float, []),
        ('dyno_type', unicode, []),
        ('heroku_email_address', unicode, []),
        ('heroku_password', unicode, []),
        ('heroku_team', unicode, []),
        ('host', unicode, ['HOST']),
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
        ('psiturk_access_key_id', unicode, []),
        ('psiturk_secret_access_id', unicode, []),
        ('psiturk_keywords', unicode, []),
        ('table_name', unicode, []),
        ('threads', unicode, []),
        ('title', unicode, []),
        ('us_only', bool, []),
        ('whimsical', bool, []),
    ):
        configurations.config.register(key, type_, synonyms)
    return configurations.config
