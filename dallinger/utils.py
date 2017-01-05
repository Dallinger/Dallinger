from dallinger.config import get_config
import os
import random
import string


def get_base_url():
    config = get_config()
    if 'OPENSHIFT_SECRET_TOKEN' in os.environ:
        base_url = "http://{}/ad".format(config.get('host'))
    else:
        base_url = "http://{}:{}/ad".format(
            config.get('host'), config.get("port")
        )
    return base_url


def generate_random_id(size=6, chars=string.ascii_uppercase + string.digits):
    ''' Generate random id numbers '''
    return ''.join(random.choice(chars) for x in range(size))
