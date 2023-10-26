"""
Each recruiter consists of two parts: a service (doing the API calls) and the actual recruiter (doing the logic).
"""
import flask  # noqa # pylint: disable=unused-import

from dallinger.recruiters.mturk.messages import *  # noqa # pylint: disable=unused-import
from dallinger.recruiters.mturk.qualifications import *  # noqa # pylint: disable=unused-import
from dallinger.recruiters.mturk.recruiter import *  # noqa # pylint: disable=unused-import
from dallinger.recruiters.mturk.service import *  # noqa # pylint: disable=unused-import

PERCENTAGE_APPROVED_REQUIREMENT_ID = "000000000000000000L0"
LOCALE_REQUIREMENT_ID = "00000000000000000071"
MAX_SUPPORTED_BATCH_SIZE = 100

mturk_routes = flask.Blueprint("mturk_recruiter", __name__)
