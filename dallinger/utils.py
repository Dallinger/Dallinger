from dallinger.config import get_config
from functools import update_wrapper
import os
import random
import string


def get_base_url():
    config = get_config()
    host = os.getenv('HOST', config.get('host'))
    if 'OPENSHIFT_SECRET_TOKEN' in os.environ:
        base_url = "http://{}".format(host)
    elif 'herokuapp.com' in host:
        base_url = "https://{}".format(host)
    else:
        # debug mode
        base_url = "http://{}:{}".format(
            host, config.get("port")
        )
    return base_url


def generate_random_id(size=6, chars=string.ascii_uppercase + string.digits):
    ''' Generate random id numbers '''
    return ''.join(random.choice(chars) for x in range(size))


class reify(object):
    """ Borrowed from Pyramid. See:
    http://docs.pylonsproject.org/projects/pyramid/en/latest/_modules/pyramid/decorator.html#reify

    Use as a class method decorator.  It operates almost exactly like the
    Python ``@property`` decorator, but it puts the result of the method it
    decorates into the instance dict after the first call, effectively
    replacing the function it decorates with an instance variable.  It is, in
    Python parlance, a non-data descriptor.  The following is an example and
    its usage:

    .. doctest::

        >>> from pyramid.decorator import reify

        >>> class Foo(object):
        ...     @reify
        ...     def jammy(self):
        ...         print('jammy called')
        ...         return 1

        >>> f = Foo()
        >>> v = f.jammy
        jammy called
        >>> print(v)
        1
        >>> f.jammy
        1
        >>> # jammy func not called the second time; it replaced itself with 1
        >>> # Note: reassignment is possible
        >>> f.jammy = 2
        >>> f.jammy
        2
    """
    def __init__(self, wrapped):
        self.wrapped = wrapped
        update_wrapper(self, wrapped)

    def __get__(self, inst, objtype=None):
        if inst is None:
            return self
        val = self.wrapped(inst)
        setattr(inst, self.wrapped.__name__, val)
        return val
