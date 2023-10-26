"""Recruiters manage the flow of participants to the experiment."""
from __future__ import unicode_literals

# Used to be all in one file, but now we have a lot of recruiters, so we split them up.
from dallinger.recruiters.mturk import *  # noqa # pylint: disable=unused-import
from dallinger.recruiters.prolific import *  # noqa # pylint: disable=unused-import
from dallinger.recruiters.recruiter import *  # noqa # pylint: disable=unused-import
from dallinger.recruiters.redis import *  # noqa # pylint: disable=unused-import
from dallinger.recruiters.service import *  # noqa # pylint: disable=unused-import
