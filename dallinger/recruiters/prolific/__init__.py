"""
Each recruiter consists of two parts: a service (doing the API calls) and the actual recruiter (doing the logic).
"""
import flask  # noqa # pylint: disable=unused-import

from dallinger.recruiters.prolific.recruiter import *  # noqa # pylint: disable=unused-import
from dallinger.recruiters.prolific.service import *  # noqa # pylint: disable=unused-import

prolific_routes = flask.Blueprint("prolific_recruiter", __name__)
