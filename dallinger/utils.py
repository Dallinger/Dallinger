from dallinger.config import get_config
import os
import random
import string


def get_base_url(log=None):
    config = get_config()
    host = os.getenv('HOST', config.get('host'))
    if 'herokuapp.com' in host:
        base_url = "https://{}".format(host)
    else:
        # debug mode
        base_port = config.get('base_port')
        port_range = range(base_port, base_port + config.get('num_dynos_web', 1))
        if log is not None:
            log("ENV (PORT): {}".format(os.getenv('PORT', 'no port')))
            log("BY LAYER: {}".format(config.by_layer('base_port')))
            log("BASE PORT: {}".format(base_port))
            log("PORT RANGE: {}".format(port_range))
        base_url = "http://{}:{}".format(
            host, random.choice(port_range)
        )
    return base_url


def generate_random_id(size=6, chars=string.ascii_uppercase + string.digits):
    """Generate random id numbers."""
    return ''.join(random.choice(chars) for x in range(size))
