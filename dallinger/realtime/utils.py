"""Checks for the JSON values that game code hands to the engine."""

import json
import math
import numbers


def dump_json(value, what=None):
    """Return ``value`` as JSON text.

    :param what: names the value in the error if it isn't JSON
    :raises ValueError: if ``value`` isn't JSON, which includes NaN and
        infinity
    """
    try:
        return json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as error:
        if what is None:
            raise
        raise ValueError("{} isn't JSON: {}".format(what, error)) from error


def copy_json(value, what=None):
    """Return a copy of ``value`` made by a JSON round trip, so it shares
    nothing with the original, and dict keys and tuples come back as JSON
    has them.
    """
    return json.loads(dump_json(value, what))


def is_number(value):
    return (
        isinstance(value, numbers.Real)
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)
